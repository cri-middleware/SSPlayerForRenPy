"""Engine-independent SpriteStudio playback core (no ``renpy`` import).

``SSInternalPlayer`` owns one ``.ssab`` pack's playback: the ctypes runtime
(the "Brain"), its metadata, the Instance / Effect rigs, and timeline-event
resolution. It exposes an imperative API —

    p = SSInternalPlayer(ssab_bytes, lib=lib, base_dir="ss_assets/Ringo",
                         resource_manager=rm, pack_reader=reader)  # + textures
    p.set_animation("walk")     # Brain setup_animation (cheap switch)
    p.play()
    plan = p.update(dt_ms)      # advance -> engine-agnostic FramePlan

— and produces a :class:`FramePlan` of z-ordered, world-space renderables that a
host *render* layer turns into engine geometry. This is the middle tier of the
canonical SS Player stack (``ssruntime`` -> ``SSInternalPlayer`` -> host
``SSPlayer`` displayable); it carries no per-engine drawing or timing.

UV normalisation is intentionally NOT done here: it needs texture pixel sizes,
which only the host can supply, so the FramePlan carries raw geometry/UVs and
the render layer normalises (``framedata.normalize_uvs``).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from ss_renpy import framedata, mask, ssruntime
from ss_renpy.effect import EffectRig
from ss_renpy.events import EventResolver
from ss_renpy.instance import InstanceRig, collect_ordered
from ss_renpy.resource import RecordingResourceManager, ResourceManager
from ss_renpy.ssab_meta import SsabMeta

# Cap on the un-drained :meth:`SSInternalPlayer.poll_events` queue. Callback-only
# hosts never drain it, so it must be bounded; a poller that drains every
# interaction never comes close. Overflow is counted, not silent (events_dropped).
EVENT_QUEUE_MAX = 256


@dataclass
class FramePlan:
    """Result of one :meth:`SSInternalPlayer.update` — engine-agnostic.

    ``items`` are ``("mesh", MeshPart)`` / ``("fx", EffectBatch)`` in draw order,
    in world space (raw, un-normalised UVs). ``events`` are the FrameEvents that
    elapsed this update (also queued for :meth:`SSInternalPlayer.poll_events`).
    ``looped`` / ``finished`` are pure edge *observations* (``finished`` is the
    rising edge of the Brain's completion state — every configured loop played);
    the core takes no action on them — the host reads them and
    decides its policy (advance a sequence, fire a callback). ``world_matrices``
    / ``hidden_parts`` snapshot the state the part-query API reads (taken before
    child/effect slots step, which invalidate the transient buffers).
    """
    items: list = field(default_factory=list)
    frame_no: float = 0.0
    disp: float = 0.0
    looped: bool = False
    finished: bool = False
    events: list = field(default_factory=list)
    world_matrices: list = field(default_factory=list)
    hidden_parts: Optional[set] = None
    # The frame's mask coverage (a ``ss_renpy.mask.FrameMask``) or None when this
    # frame has no live mask writer. The render layer rasterizes its writers into
    # an offscreen coverage bitmap; individual masked items reference it (or, for
    # an instance child, the parent's) via ``MeshPart.mask`` (SDK doc:
    # 40_components/40_mask.md).
    frame_mask: object = None


def _pack_rgba(color) -> int:
    """A colour -> the packed ``0xRRGGBBAA`` the override C-API expects.

    Accepts an already-packed int, or an ``(r, g, b[, a])`` sequence of 0..255
    (alpha defaults to opaque). Components are clamped, never rescaled: an
    override colour lives in the same 8-bit sRGB space as the authored
    PartColor. Raises ValueError on anything else — a malformed colour is a
    coding error, and a clear traceback beats a silent no-op.
    """
    if isinstance(color, int):
        return color & 0xFFFFFFFF
    # Strings are iterable, so a colour string ("#f00", "#ff0000ff") would slip
    # past the length gates below and die on int(round("#")) with a TypeError —
    # breaking this function's ValueError contract. Colour *names* are a host
    # concern (the Ren'Py layer parses them via Color()); this core takes only
    # packed ints and 0..255 sequences.
    if isinstance(color, (str, bytes, bytearray)):
        raise ValueError(
            "colour must be a packed int or an (r, g, b[, a]) sequence, not a "
            "string — parse %r in the host layer first" % (color,))
    try:
        c = list(color)
    except TypeError:
        raise ValueError(
            "colour must be a packed int or an (r, g, b[, a]) sequence, "
            "got %r" % (color,)) from None
    if len(c) == 3:
        c.append(255)
    if len(c) != 4:
        raise ValueError(
            "colour must be a packed int or an (r, g, b[, a]) sequence, "
            "got %r" % (color,))
    r, g, b, a = (max(0, min(255, int(round(v)))) for v in c)
    return (r << 24) | (g << 16) | (b << 8) | a


class SSInternalPlayer:
    """Pure, engine-independent playback of ONE animation from a ``.ssab`` pack.

    Plays a single animation at a time (``set_animation`` / ``play`` / ``update``)
    and reports edges (``FramePlan.finished`` / ``looped``) as observations — it
    has no notion of animation *sequences* or what to play next; that policy
    belongs to the host (the ``SSPlayer`` displayable). Keeping it to one
    animation makes it the reusable building block for Instance-part children
    too (the canonical SS Player layering: ``ssruntime`` -> this -> host node)."""

    def __init__(self, ssab_data: bytes, *, lib,
                 base_dir: str = "",
                 resource_manager: Optional[ResourceManager] = None,
                 pack_reader=None,
                 sub_frame: bool = True,
                 enable_events: bool = True,
                 coordinate_system: int = ssruntime.COORD_Y_DOWN,
                 origin: int = ssruntime.ORIGIN_CENTER,
                 loader=None, texmap=None, parent_driven: bool = False,
                 depth: int = 0):
        self._data = ssab_data
        self._lib = lib
        # ``base_dir`` is the host-relative dir used only to build texture
        # identifiers handed to the ResourceManager (textures are co-located
        # with the .ssab). Pack bytes are read via ``pack_reader`` instead.
        self.base_dir = base_dir.replace("\\", "/").rstrip("/")
        self._rm = resource_manager or RecordingResourceManager()
        self._pack_reader = pack_reader

        # A corrupt/truncated pack fails deep inside the FlatBuffers walk
        # (struct.error and friends) — in the SsabMeta constructor or in any of
        # the metadata walks below — so gate them all into one diagnosable
        # error before any bytes reach the native runtime (which aborts on
        # invalid data rather than reporting it).
        try:
            self._meta = SsabMeta(ssab_data)
            # Texture hash -> image path. Shared across an Instance tree (the
            # root creates it; children receive the same dict) so the root
            # resolves every part's texture_hash, including those from
            # external instance packs.
            self._texmap = texmap if texmap is not None else {}
            own_map = self._meta.texture_hash_map()
            self._texmap.update(own_map)
            # Every image this pack draws from — cellmap atlases AND texture-
            # change (TCHG) targets, deduped, acquired once at the end of
            # construction. External packs' images are acquired by the loader as
            # they load.
            self._own_images = list(dict.fromkeys(
                p for p in own_map.values() if p))
            # Static per-part info indexed by part index (== draw-plan slot
            # index). Cached once: the mask layer reads the static mask flags
            # from it every frame, and it is also the name->index source.
            self._part_infos = self._meta.parts()
            # Second corruption gate: a zeroed/garbage buffer can PARSE as a
            # vacuous empty pack (the FlatBuffers walk only raises on
            # out-of-bounds access). A real pack always has parts.
            if not (self._part_infos or self._meta.animation_names()):
                raise ValueError(
                    "not a valid .ssab pack (no parts or animations found)")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(
                "not a valid .ssab pack (corrupt or truncated?): %r" % (e,)
            ) from e
        self._part_index = {p.name: p.index for p in self._part_infos}
        # External-instance pack loader (merges into the shared texmap and
        # acquires via the shared rm). The root builds one; children share it so
        # an external pack is read + registered once for the whole tree.
        self._loader = loader if loader is not None else self._make_loader()
        # Instance nesting depth (capped in InstanceRig) and parent-driven flag:
        # a child's own per-tick update() is a no-op — the parent seeks it.
        self._depth = depth
        self._parent_driven = bool(parent_driven)

        self._rt = ssruntime.SSRuntime(lib)
        self._rt.configure(coordinate_system=coordinate_system, origin=origin)
        self._rt.load_ssab_bytes(ssab_data)

        # playback state
        self.sub_frame = bool(sub_frame)
        self._enable_events = bool(enable_events)
        self.animation: Optional[str] = None
        self.loop = -1
        self.speed = 1.0
        # Playback direction / ping-pong persist across set_animation like
        # loop/speed: setup_animation resets them to forward/normal, so we track
        # them here and re-apply. 0 = forward, 1 = reverse;
        # style 0 = normal, 1 = ping-pong.
        self._direction = 0
        self._style = 0
        # Frame skipping (on = the runtime's own default): also reset by
        # setup_animation, so tracked and re-applied the same way.
        self._skip_frames = True

        # rigs (built at the end of construction) / events (per-animation, built
        # by set_animation)
        self._instances: Optional[InstanceRig] = None
        self._effects: Optional[EffectRig] = None
        self._evt: Optional[EventResolver] = None
        # Bounded: hosts that consume events via callbacks alone never call
        # poll_events(), so an unbounded queue would grow for the whole session
        # (a looping talking sprite emits UserData markers indefinitely). The
        # bound is lossy for a host that DOES poll but drains slower than the
        # animation emits, so overflow is counted (never silent) — see
        # :attr:`events_dropped`, which the Ren'Py layer surfaces as a warning.
        self._event_queue: deque = deque(maxlen=EVENT_QUEUE_MAX)
        self._events_dropped = 0
        self._was_finished = False

        # part-query snapshots (last rendered frame)
        self._last_world: list = []
        self._last_hidden: Optional[set] = None

        # Everything a *pack* implies is done here, at load: textures, and the
        # Instance/Effect rigs (parts, effect definitions and the external packs
        # a child references are all pack-static, so none of it depends on which
        # animation is selected). This keeps set_animation a cheap, synchronous
        # switch a game can call on the hot path — the same split the other ports
        # settled on (load -> setAnimation -> play). Runs last, so the recursive
        # child players the Instance rig builds see a fully constructed owner.
        self._acquire_textures(self._own_images)
        self._build_rigs()

    # -- texture / pack resolution -------------------------------------
    def texture_path(self, texture_hash: int) -> str:
        """Host-relative path for a ``DrawBatch.texture_hash`` (or "")."""
        img = self._texmap.get(texture_hash, "")
        if not img:
            return ""
        return (self.base_dir + "/" + img) if self.base_dir else img

    def _acquire_textures(self, images) -> None:
        for img in set(images):
            if not img:
                continue
            path = (self.base_dir + "/" + img) if self.base_dir else img
            try:
                self._rm.acquire(path)
            except Exception:
                pass

    def _make_loader(self):
        """``loader(pack_name)->bytes`` for external instance packs.

        Caches bytes, merges each loaded pack's cellmap -> image-path entries
        into ``self._texmap`` so child-part texture hashes resolve, and asks the
        ResourceManager to acquire those newly-discovered textures.
        """
        cache: dict = {}

        def load(pack_name):
            if pack_name in cache:
                return cache[pack_name]
            data = self._pack_reader(pack_name) if self._pack_reader else b""
            cache[pack_name] = data
            if data:
                try:
                    new_map = SsabMeta(data).texture_hash_map()
                    self._texmap.update(new_map)
                    self._acquire_textures(new_map.values())
                except Exception:
                    pass
            return data

        return load

    # -- rigs ----------------------------------------------------------
    def _build_rigs(self) -> None:
        """Build Instance/Effect rigs once for this pack (parts are pack-static;
        animation changes only reset slot state). Each is guarded so a failure
        disables only that feature."""
        try:
            # Children are parent-driven SSInternalPlayers, built by the rig
            # from this owner (it shares lib / rm / loader / texmap / base_dir).
            self._instances = InstanceRig(self, self._depth)
        except Exception:
            self._instances = None
        try:
            self._effects = EffectRig(self._rt, self._meta)
        except Exception:
            self._effects = None

    def _reset_slots(self) -> None:
        for rig in (self._instances, self._effects):
            if rig is not None:
                try:
                    rig.reset()
                except Exception:
                    pass

    # -- introspection -------------------------------------------------
    def animation_names(self) -> List[str]:
        return self._meta.animation_names() if self._meta else []

    @property
    def meta(self) -> SsabMeta:
        return self._meta

    def is_playing(self) -> bool:
        return bool(self._rt and self._rt.is_playing)

    def is_pausing(self) -> bool:
        return bool(self._rt and self._rt.is_pausing)

    def is_finished(self) -> bool:
        """The Brain's sticky completion STATE (every configured loop played).

        Distinct from ``FramePlan.finished``, which is its rising edge: this
        stays true until the next play/setup, never trips for an infinite loop,
        and is never raised by a commanded :meth:`stop` (SDK doc:
        30_core/20_playback_control.md). The host reads it to tell a naturally
        finished player from a merely stopped one — e.g. when snapshotting
        playback state for rollback."""
        return bool(self._rt and self._rt.is_finished)

    def is_playing_forward(self) -> bool:
        """Whether the head is advancing forward (direction + ping-pong leg;
        NOT the speed sign — see :attr:`ssruntime.SSRuntime.is_playing_forward`).

        The host uses this to gate audio: SS audio must only play while the
        timeline moves forward (SS does not support reverse audio playback —
        SDK doc: 10_introduction/20_limitations.md). Assumes forward when there
        is no runtime."""
        return bool(self._rt.is_playing_forward) if self._rt else True

    @property
    def playback_direction(self) -> int:
        """The configured direction (0 = forward, 1 = reverse).

        The *setting*, not the instantaneous heading — on a ping-pong return leg
        this still reads forward while :meth:`is_playing_forward` reads False."""
        return self._rt.playback_direction if self._rt else self._direction

    @property
    def playback_style(self) -> int:
        """The configured style (0 = normal, 1 = ping-pong)."""
        return self._rt.playback_style if self._rt else self._style

    @property
    def skip_frames(self) -> bool:
        """Whether frame skipping is on; see :meth:`set_skip_frames`."""
        return self._rt.skip_frames if self._rt else self._skip_frames

    @property
    def frame_no(self) -> float:
        return self._rt.frame_no if self._rt else 0.0

    @property
    def total_frames(self) -> int:
        return self._rt.total_frames if self._rt else 0

    @property
    def fps(self) -> int:
        return self._rt.fps if self._rt else 0

    @property
    def start_frame(self) -> int:
        return self._rt.start_frame if self._rt else 0

    @property
    def end_frame(self) -> int:
        return self._rt.end_frame if self._rt else 0

    def is_animating(self) -> bool:
        """True while something visibly moves: the head is advancing, or an
        Instance/Effect child runs on its own clock. Only *independent* slots
        justify motion once the head stops — dependent ones follow the parent
        frame, so a finished/stopped player with them must not keep demanding
        redraws (and emitting particles) forever."""
        if self._rt and self._rt.is_playing and not self._rt.is_pausing:
            return True
        return self._has_independent_rigs()

    def _has_independent_rigs(self) -> bool:
        """Whether any Instance/Effect slot — at this level or nested inside a
        dependent child — still runs on its own clock. The recursive liveness
        signal the redraw gate consults once the head has stopped."""
        if self._effects is not None and self._effects.has_independent():
            return True
        if self._instances is not None and self._instances.has_independent():
            return True
        return False

    # -- playback control ----------------------------------------------
    def set_animation(self, name: Optional[str] = None) -> bool:
        """Switch + pose an animation (does NOT start playback).

        Cheap and synchronous — a game may call it on the hot path: every
        resource the pack implies (textures, Instance/Effect rigs) was already
        acquired at construction. This runs the Brain's ``setup_animation``,
        rebuilds the per-animation timeline-event resolver, and re-arms the rig
        slots. ``name=None`` selects the first animation. Returns ``False`` if
        the animation is unknown.
        """
        if not name:
            names = self.animation_names()
            name = names[0] if names else None
        if not name:
            return False
        if not self._rt.setup_animation(name):
            return False
        self.animation = name
        # setup_animation resets loop/speed to defaults — re-apply ours.
        self._rt.set_loop(self.loop)
        if self.speed != 1.0:
            self._rt.set_animation_speed(self.speed)
        # ...and playback direction / ping-pong (also reset by setup_animation):
        # re-apply when non-default so a reverse / ping-pong mode survives an
        # animation switch — including host sequence chaining, which calls
        # set_animation for each queued clip — mirroring how loop/speed persist.
        # (Section is intentionally NOT carried: it is a per-animation frame
        # range, meaningless against a different clip.)
        if self._direction or self._style:
            self._rt.set_playback_direction(self._direction, self._style)
        # ...and frame skipping, which setup_animation turns back on.
        if not self._skip_frames:
            self._rt.set_skip_frames(False)
        # Timeline events are per-animation; rebuild the resolver.
        if self._enable_events:
            try:
                self._evt = EventResolver(self._data, name)
            except Exception:
                self._evt = None
        # The rigs themselves are pack-static (built at construction); a switch
        # only re-arms their slots so the new animation's Instance/Effect parts
        # fire from the top.
        self._reset_slots()
        return True

    def play(self, start_frame: float = -1.0) -> None:
        """Start playback. ``start_frame >= 0`` begins there; else resumes."""
        if self.animation is None:
            self.set_animation(None)
        self._reset_slots()
        if start_frame is not None and start_frame >= 0:
            self._rt.play_with_start_frame(start_frame)
        else:
            self._rt.play()
        # Re-arm the finished edge: is_finished stays latched until this point,
        # so replaying must drop our copy of it to report the next completion.
        self._was_finished = False

    # -- instance-child support (parent-driven mode) -------------------
    @property
    def ctx(self):
        """Native runtime context handle (the parent's instance slot steps it)."""
        return self._rt.ctx if self._rt else None

    def reset_slots(self) -> None:
        """Re-arm this player's Instance/Effect slots (parent calls on replay)."""
        self._reset_slots()

    def make_child(self, child_data: bytes, depth: int):
        """Build a parent-driven child player that shares this player's resources.

        The Instance rig (``ss_renpy.instance``) resolves *which* pack/animation a
        child part references; this factory owns *how* a child is built from the
        owner — inheriting lib, ResourceManager, external-pack loader, the shared
        texmap and base_dir, running parent-driven (the parent seeks it) with its
        own timeline events suppressed (root-only). Keeping construction here
        keeps the owner's construction details out of the instance module.
        Returns ``None`` on construction failure.
        """
        try:
            return SSInternalPlayer(
                child_data, lib=self._lib, base_dir=self.base_dir,
                resource_manager=self._rm, sub_frame=self.sub_frame,
                enable_events=False, parent_driven=True,
                loader=self._loader, texmap=self._texmap, depth=depth)
        except Exception:
            return None

    def render_at(self, frame_no, looped, dt_s, sub_frame=None):
        """Pose to an externally-stepped ``frame_no`` (no head advance) and return
        this player's z-ordered, world-space draw items.

        Used when this player is an Instance child: the parent's instance slot
        already computed ``frame_no``; we evaluate that frame and recurse into
        this child's own Instance/Effect parts. Never raises: a draw-plan failure
        returns Normal/Mesh-only, and a native/parse failure returns an empty
        list rather than propagating into the parent's frame build."""
        try:
            return self._render_at(frame_no, looped, dt_s, sub_frame)
        except Exception:
            return []

    def _render_at(self, frame_no, looped, dt_s, sub_frame=None):
        rt = self._rt
        sf = self.sub_frame if sub_frame is None else sub_frame
        disp = frame_no if sf else math.floor(frame_no)
        fb = rt.get_frame_data_view(disp)
        if not fb:
            return []
        fd = framedata.parse(fb)
        try:
            return collect_ordered(rt, fd, self._instances, self._effects,
                                   frame_no, dt_s, looped, sf)
        except Exception:
            fb2 = rt.get_frame_data_view(disp)
            return ([("mesh", mp)
                     for mp in framedata.build_mesh_parts(rt, framedata.parse(fb2))]
                    if fb2 else [])

    def step_slots_only(self, frame_no, looped, dt_s, sub_frame=None):
        """Advance every Instance/Effect slot of this player (recursively) without
        building renderables.

        Called by :meth:`ss_renpy.instance.InstanceRig.step_idle` when this player
        is a *hidden* Instance child: the Brain drops Hide'd parts from
        ``draw_order``, so the normal render walk (``render_at`` →
        ``collect_ordered``) never runs for it and its slots would freeze. Stepping
        here keeps independent descendants advancing while off-screen (SDK doc:
        40_components/10_instance.ja.md). Never raises — and guards each slot on
        its own, so one wedged child cannot freeze its siblings' clocks."""
        sf = self.sub_frame if sub_frame is None else sub_frame
        if self._instances is not None:
            for pi in list(self._instances.part_indices()):
                try:
                    self._instances.step_idle(pi, frame_no, dt_s, looped, sf)
                except Exception:
                    pass
        if self._effects is not None:
            for pi in list(self._effects.part_indices()):
                try:
                    self._effects.step_idle(pi, frame_no, dt_s, looped)
                except Exception:
                    pass

    def pause(self) -> None:
        if self._rt and not self._rt.is_pausing:
            self._rt.pause()

    def resume(self) -> None:
        if self._rt and self._rt.is_pausing:
            self._rt.pause()

    def stop(self) -> None:
        # A *commanded* stop is not a natural end: the Brain's is_finished stays
        # false for it (only a self-exhausted loop count trips it), so the host
        # never mistakes a commanded stop() for a completion.
        if self._rt:
            self._rt.stop()

    def set_loop(self, count: int) -> None:
        self.loop = count
        if self._rt:
            self._rt.set_loop(count)

    def set_speed(self, speed: float) -> None:
        self.speed = speed
        if self._rt:
            self._rt.set_animation_speed(speed)

    def set_frame(self, frame: float) -> None:
        if self._rt:
            self._rt.set_frame_no(frame)

    def set_section(self, start: int, end: int) -> None:
        if self._rt:
            self._rt.set_animation_section(start, end)

    def set_playback_direction(self, direction: int, style: int = 0) -> None:
        # Remember it so set_animation() can re-apply after setup_animation resets
        # it; works whether called before or after set_animation.
        self._direction = direction
        self._style = style
        if self._rt:
            self._rt.set_playback_direction(direction, style)

    def set_skip_frames(self, skip: bool) -> None:
        """Toggle frame skipping (on by default).

        On, ``update`` advances by the elapsed time and keeps real-time pace,
        skipping frames after a stall; off, it advances exactly one frame per
        update, so nothing is skipped and the animation stretches instead. See
        :meth:`ssruntime.SSRuntime.set_skip_frames`.

        Remembered like direction/style — ``setup_animation`` resets it to on —
        so it survives an animation switch, including host sequence chaining."""
        self._skip_frames = bool(skip)
        if self._rt:
            self._rt.set_skip_frames(self._skip_frames)

    def set_frame_rate(self, fps: int) -> None:
        if self._rt:
            self._rt.set_frame_rate(fps)

    def set_sub_frame(self, enabled: bool) -> None:
        self.sub_frame = bool(enabled)

    # -- per-frame advance ---------------------------------------------
    def update(self, dt_ms: float) -> FramePlan:
        """Advance by ``dt_ms`` milliseconds and return this frame's plan.

        Pure single-animation playback: advance the Brain, collect timeline
        events, observe the looped / finished edges, then materialise the
        z-ordered world-space draw plan. It does NOT decide what to play next —
        sequence chaining is the host's policy (it reads ``FramePlan.finished``
        and calls ``set_animation`` itself).

        Never raises: a draw-plan failure falls back to Normal/Mesh-only, and a
        native/parse failure (update_ms, world_matrices, get_frame_data_view,
        parse) degrades to an empty FramePlan instead of crashing the host's
        render() — the previous frame stays on screen and the next tick retries.
        """
        if self._parent_driven:
            # An Instance child is seeked by its parent via render_at(); its own
            # per-tick update is a no-op (mirrors Godot's setParentDriven).
            return FramePlan()
        try:
            return self._advance(dt_ms)
        except Exception:
            return FramePlan()

    def _advance(self, dt_ms: float) -> FramePlan:
        """Body of :meth:`update` (wrapped by it for the never-raises contract)."""
        rt = self._rt
        dt_s = dt_ms / 1000.0
        frame_no = rt.update_ms(dt_ms)
        looped = rt.is_looped

        events_out: list = []
        if self._enable_events and self._evt is not None and self._evt.available:
            try:
                for fe in self._evt.collect(rt):
                    if len(self._event_queue) == EVENT_QUEUE_MAX:
                        # deque(maxlen) evicts from the LEFT, i.e. the oldest —
                        # exactly the markers a poller most likely still needs.
                        # Count it so the loss is reportable instead of silent.
                        self._events_dropped += 1
                    self._event_queue.append(fe)
                    events_out.append(fe)
            except Exception:
                pass
        # `finished` is a pure observation the host maps to its policy. The Brain
        # reports it as a sticky state (true from the moment every configured loop
        # has played until the next play/setup, and never for a commanded stop),
        # so take its rising edge to keep FramePlan.finished a one-shot pulse.
        finished_state = rt.is_finished
        finished = finished_state and not self._was_finished
        self._was_finished = finished_state

        # --- draw plan (sub-frame off floors the *display* frame only)
        disp = frame_no if self.sub_frame else math.floor(frame_no)
        fb = rt.get_frame_data_view(disp)
        wm, wn = rt.world_matrices()
        self._last_world = list(wm[0:wn]) if (wm and wn) else []
        items: list = []
        hidden: Optional[set] = None
        frame_mask = None
        if fb:
            fd = framedata.parse(fb)
            hidden = framedata.hidden_parts(fd)
            # Build the coverage *before* collect_ordered steps any slot — both
            # read the transient SoA, which an instance/effect step invalidates.
            try:
                frame_mask = mask.build_frame_mask(rt, fd, self._part_infos)
            except Exception:
                frame_mask = None
            try:
                items = collect_ordered(rt, fd, self._instances, self._effects,
                                        frame_no, dt_s, looped, self.sub_frame,
                                        part_infos=self._part_infos,
                                        frame_mask=frame_mask)
            except Exception:
                # collect_ordered may have stepped slots and invalidated the
                # zero-copy view; re-evaluate for a clean Normal/Mesh-only frame.
                fb2 = rt.get_frame_data_view(disp)
                items = ([("mesh", mp)
                          for mp in framedata.build_mesh_parts(
                              rt, framedata.parse(fb2))]
                         if fb2 else [])
                frame_mask = None
        self._last_hidden = hidden

        return FramePlan(items=items, frame_no=frame_no, disp=disp,
                         looped=looped, finished=finished, events=events_out,
                         world_matrices=self._last_world, hidden_parts=hidden,
                         frame_mask=frame_mask)

    # -- timeline events -----------------------------------------------
    def poll_events(self) -> list:
        """Drain and return the FrameEvents collected since the last poll."""
        q = list(self._event_queue)
        self._event_queue.clear()
        return q

    @property
    def events_dropped(self) -> int:
        """How many queued FrameEvents the bounded queue has evicted, ever.

        Non-zero means a poller is draining slower than the animation emits, so
        :meth:`poll_events` returned only the tail of what happened — poll every
        interaction (or use the push callbacks) if it keeps climbing."""
        return self._events_dropped

    # -- part query ----------------------------------------------------
    def part_names(self) -> List[str]:
        return list(self._part_index.keys())

    def part_index(self, name: str) -> int:
        return self._part_index.get(name, -1)

    def part_transform(self, name: str):
        """Player-local transform of ``name`` on the last rendered frame, or
        ``None``: dict with x/y (px), rotation (deg), xscale/yscale."""
        i = self.part_index(name)
        base = i * 16
        if i < 0 or base + 16 > len(self._last_world):
            return None
        m = self._last_world[base:base + 16]
        return {
            "x": m[12], "y": m[13],
            "rotation": math.degrees(math.atan2(m[1], m[0])),
            "xscale": math.hypot(m[0], m[1]),
            "yscale": math.hypot(m[4], m[5]),
        }

    def is_part_hidden(self, name: str) -> bool:
        i = self.part_index(name)
        if i < 0 or self._last_hidden is None:
            return True
        return i in self._last_hidden

    # -- part overrides -------------------------------------------------
    # Per-part runtime overrides (color / cell / visibility): an imperative
    # "make this part this colour / cell / hidden NOW" that the Brain applies on
    # the resolved pose, so it wins over both the keyframe and any blend (SDK
    # doc: 40_components/65_override_layer.md).
    #
    # The Brain owns the table and its whole lifecycle — a new animation drops
    # visibility + non-Permanent color/cell overrides, a new pack drops
    # everything — so this core keeps no copy and never re-applies. (The host
    # displayable does keep a record, but only to restore overrides after Ren'Py
    # drops and rebuilds the native core on save/load; that is host policy, the
    # same tier that owns sequence chaining.)
    #
    # ``part`` is a part NAME or its integer index — the Pythonic form of the
    # ``*_by_index`` method pairs the Godot / Unity ports carry. Indices are
    # positional over the pack's parts and stable within one ``.ssab``, so
    # resolve a name once with :meth:`part_index` and reuse it if you set
    # overrides often. Every method returns False when the part is unknown or
    # the runtime rejects the call.
    def resolve_part(self, part) -> int:
        """A part name *or* index -> its index, or -1 when unknown/unusable.

        The single entry point every override method resolves through, so a
        host can normalise a caller's part reference the same way (the
        displayable keys its restore record by the resolved index).
        """
        if self._rt is None:
            return -1
        i = part if isinstance(part, int) else self.part_index(part)
        return i if 0 <= i < len(self._part_infos) else -1

    def set_part_visibility_override(self, part, hide: bool = True,
                                     cascade: bool = False) -> bool:
        """Force-hide ``part`` (``hide=True``) or revert it to the animation.

        ``cascade`` propagates the force-hide to the part's descendants — new,
        override-only behaviour (a keyframed hide never cascades in SS7).
        Visibility takes no priority mode: it always wins, and a new animation
        always clears it.
        """
        i = self.resolve_part(part)
        if i < 0:
            return False
        return self._rt.set_part_visibility_override(i, 1 if hide else 0,
                                                     cascade)

    def clear_part_visibility_override(self, part) -> bool:
        i = self.resolve_part(part)
        return i >= 0 and self._rt.clear_part_visibility_override(i)

    def set_part_color_override(
            self, part, color, blend_op: int = ssruntime.BLEND_MIX,
            priority: int = ssruntime.PRIORITY_HOLD_UNTIL_NEXT_ANIMATION) -> bool:
        """Tint ``part`` with one colour (all four corners).

        ``color`` is a packed ``0xRRGGBBAA`` int or an ``(r, g, b[, a])``
        sequence of 0..255. It is interpreted in the same 8-bit sRGB space as
        the authored PartColor and the Brain pre-multiplies alpha itself — pass
        the colour as authored, without converting it. ``blend_op`` is
        ``BLEND_MIX/MUL/ADD/SUB``. Normal parts only: other part types silently
        ignore it (the call still succeeds), matching SS6's PartsColorChange.
        """
        i = self.resolve_part(part)
        if i < 0:
            return False
        return self._rt.set_part_color_override(
            i, blend_op, _pack_rgba(color), priority)

    def set_part_color_override_corners(
            self, part, corners, blend_op: int = ssruntime.BLEND_MIX,
            priority: int = ssruntime.PRIORITY_HOLD_UNTIL_NEXT_ANIMATION) -> bool:
        """Like :meth:`set_part_color_override` with four distinct corners,
        given in the runtime's ``lt, rt, lb, rb`` order."""
        i = self.resolve_part(part)
        cols = list(corners) if corners is not None else []
        if i < 0 or len(cols) != 4:
            return False
        return self._rt.set_part_color_override_corners(
            i, blend_op, [_pack_rgba(c) for c in cols], priority)

    def clear_part_color_override(self, part) -> bool:
        i = self.resolve_part(part)
        return i >= 0 and self._rt.clear_part_color_override(i)

    def set_part_cell_override(
            self, part, cellmap_name: str, cell_name: str,
            priority: int = ssruntime.PRIORITY_HOLD_UNTIL_NEXT_ANIMATION) -> bool:
        """Make ``part`` draw a different cell.

        ``cellmap_name`` is written WITHOUT the ``.ssce`` extension; enumerate
        the valid targets with :meth:`cellmap_names` / :meth:`cell_names`. The
        cell is resolved immediately, so an unknown name returns False. Normal
        and Mask parts only. Empty names revert the part to the animation.
        """
        i = self.resolve_part(part)
        if i < 0:
            return False
        # (0, 0) is the Brain's "follow the animation" sentinel; "" hashes to 0
        # only if we short-circuit, since fnv1a of "" is the non-zero basis.
        cm = ssruntime.hash_string(cellmap_name) if cellmap_name else 0
        cn = ssruntime.hash_string(cell_name) if cell_name else 0
        return self._rt.set_part_cell_override(i, cm, cn, priority)

    def clear_part_cell_override(self, part) -> bool:
        i = self.resolve_part(part)
        return i >= 0 and self._rt.clear_part_cell_override(i)

    def clear_all_part_overrides(self) -> bool:
        return self._rt is not None and self._rt.clear_all_part_overrides()

    def cellmap_names(self) -> List[str]:
        """Names of this pack's cellmaps (cell-override targets)."""
        return [c.name for c in self._meta.cellmaps()]

    def cell_names(self, cellmap_name: str) -> List[str]:
        """Names of the cells in ``cellmap_name`` (cell-override targets)."""
        return self._meta.cell_names(cellmap_name)

    # -- teardown ------------------------------------------------------
    def close(self) -> None:
        for rig in (self._instances, self._effects):
            if rig is not None:
                try:
                    rig.close()
                except Exception:
                    pass
        self._instances = self._effects = None
        if self._rt is not None:
            try:
                self._rt.close()
            except Exception:
                pass
            self._rt = None

    def __del__(self):
        # The host displayable is GC-driven (it never calls close() itself, and
        # save/load drops cores wholesale), so release the Instance/Effect slot
        # handles and the runtime here — the runtime wrapper's own __del__ only
        # covers ctx/resource, not the rigs' slots. Guarded: interpreter
        # shutdown may have torn half of this down already.
        try:
            self.close()
        except Exception:
            pass
