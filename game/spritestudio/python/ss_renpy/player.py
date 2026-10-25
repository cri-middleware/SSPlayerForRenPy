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
from typing import List, Optional, Sequence

from ss_renpy import framedata, mask, ssruntime
from ss_renpy.effect import EffectRig
from ss_renpy.events import EventResolver
from ss_renpy.instance import InstanceRig, collect_ordered
from ss_renpy.outline import FrameCopy
from ss_renpy.resource import RecordingResourceManager, ResourceManager
from ss_renpy.ssab_meta import PART_TYPE_MESH, SsabMeta

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
    world_matrices: Sequence[float] = field(default_factory=list)
    hidden_parts: Optional[set] = None
    # The frame's mask coverage (a ``ss_renpy.mask.FrameMask``) for the whole
    # instance tree, or None when nothing in it masks. It can hold no writer
    # while a part that draws inside a mask still references it. The render layer
    # rasterizes its writers into an offscreen coverage bitmap; masked items
    # reference it via ``MeshPart.mask``.
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


def _acquire_images(rm, base_dir: str, images) -> None:
    """Ask ``rm`` for each image path, resolved against ``base_dir``."""
    for img in set(images):
        if not img:
            continue
        path = (base_dir + "/" + img) if base_dir else img
        try:
            rm.acquire(path)
        except Exception:
            pass


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
                 problems=None):
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
            # Pack-static: collect_writers can only ever produce writers from
            # these parts (mask.py: the classification is by PartInfo).
            self._has_mask_writers = any(p.is_mask_writer
                                         for p in self._part_infos)
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
        # Why Instance parts could not be built, one message each, shared
        # across the tree like the texmap so the root holds its descendants'
        # too. A part without its child draws nothing while the rest plays on,
        # so this is the only trace of it the host can report.
        self._problems = problems if problems is not None else []
        # Parent-driven flag: a child's own per-tick update() is a no-op — the
        # parent seeks it.
        self._parent_driven = bool(parent_driven)

        self._rt = ssruntime.SSRuntime(lib)
        self._rt.configure(coordinate_system=coordinate_system, origin=origin)
        self._rt.load_ssab_bytes(ssab_data)

        # playback state
        self._sub_frame = bool(sub_frame)
        self._enable_events = bool(enable_events)
        self._current_animation: Optional[str] = None
        self._loop = -1
        self._speed = 1.0
        # Playback direction / ping-pong (0 = forward, 1 = reverse; style
        # 0 = normal, 1 = ping-pong) and frame skipping. The Brain keeps all
        # three across setup_animation on its own (SDK #369 / #370 / #375) --
        # they describe the playback, not the clip -- so nothing here re-applies
        # them. They are mirrored only so the getters below can answer before a
        # runtime exists, and so set_playback_direction works whether it is
        # called before or after the first set_animation.
        self._direction = 0
        self._style = 0
        self._skip_frames = True

        # rigs (built at the end of construction) / events (built below: one
        # resolver serves the whole pack, since an event is read from the table
        # of the animation that fired it, which a crossfade or an overlay makes
        # other than the one set up)
        self._instances: Optional[InstanceRig] = None
        self._effects: Optional[EffectRig] = None
        self._evt: Optional[EventResolver] = None
        if self._enable_events:
            try:
                self._evt = EventResolver(ssab_data)
            except Exception:
                self._evt = None
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
        self._last_world: Sequence[float] = []
        self._last_hidden: Optional[set] = None
        self._outline = FrameCopy()
        self._has_mesh = any(p.part_type == PART_TYPE_MESH
                             for p in self._part_infos)

        # Everything a *pack* implies is done here, at load: textures, and the
        # Instance/Effect rigs (parts, effect definitions and the external packs
        # a child references are all pack-static, so none of it depends on which
        # animation is selected). This keeps set_animation a cheap, synchronous
        # switch a game can call on the hot path — the same split the other ports
        # settled on (load -> setAnimation -> play). Runs last, so the recursive
        # child players the Instance rig builds see a fully constructed owner.
        self._acquire_textures(self._own_images)
        self._build_rigs()
        # Pack-static, over the whole tree below: whether anything can write a
        # mask, and whether anything draws inside one. A tree with neither skips
        # the mask walk; one with only the latter still runs it, because a part
        # that draws inside a mask is hidden where there is none.
        writes, inside = (self._instances.mask_uses()
                          if self._instances is not None else (False, False))
        self._tree_writes = self._has_mask_writers or writes
        self._tree_draws_inside = inside or any(
            p.visible_inside_mask for p in self._part_infos)

    def mask_uses(self):
        """``(writes, draws_inside)`` for this animation's tree — see the end of
        the constructor. Read by the owner's Instance rig."""
        return self._tree_writes, self._tree_draws_inside

    # -- texture / pack resolution -------------------------------------
    def texture_path(self, texture_hash: int) -> str:
        """Host-relative path for a ``DrawBatch.texture_hash`` (or "")."""
        img = self._texmap.get(texture_hash, "")
        if not img:
            return ""
        return (self.base_dir + "/" + img) if self.base_dir else img

    def _acquire_textures(self, images) -> None:
        _acquire_images(self._rm, self.base_dir, images)

    def _make_loader(self):
        """``loader(pack_name)->bytes`` for external instance packs.

        Caches bytes, merges each loaded pack's cellmap -> image-path entries
        into ``self._texmap`` so child-part texture hashes resolve, and asks the
        ResourceManager to acquire those newly-discovered textures.

        The closure holds what it uses, never ``self``: this player keeps it,
        so a reference back would make a cycle, and the native runtime and slot
        handles would then wait for the cyclic garbage collector instead of
        going when the host drops the player.
        """
        cache: dict = {}
        pack_reader = self._pack_reader
        texmap = self._texmap
        rm = self._rm
        base_dir = self.base_dir

        def load(pack_name):
            if pack_name in cache:
                return cache[pack_name]
            data = pack_reader(pack_name) if pack_reader else b""
            cache[pack_name] = data
            if data:
                try:
                    new_map = SsabMeta(data).texture_hash_map()
                    texmap.update(new_map)
                    _acquire_images(rm, base_dir, new_map.values())
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
            self._instances = InstanceRig(self)
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
        and is never raised by a commanded :meth:`stop`.
        The host reads it to tell a naturally
        finished player from a merely stopped one — e.g. when snapshotting
        playback state for rollback."""
        return bool(self._rt and self._rt.is_finished)

    def just_looped(self) -> bool:
        """Whether the last update crossed a loop boundary.

        A **pulse**, not a state: the runtime clears it at the top of every
        update, so it only reads true inside the tick that crossed — which is
        why it is not called ``is_looped``, here or in the Brain. Reading it a tick late reads False.
        """
        return bool(self._rt.just_looped) if self._rt else False

    def is_playing_forward(self) -> bool:
        """Whether the head is advancing forward (direction + ping-pong leg;
        NOT the speed sign — see :attr:`ssruntime.SSRuntime.is_playing_forward`).

        The host uses this to gate audio: SS audio must only play while the
        timeline moves forward (SS does not support reverse audio playback).
        Assumes forward when there
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
    def frame_skip_enabled(self) -> bool:
        """Whether frame skipping is on; see :meth:`set_skip_frames`."""
        return self._rt.skip_frames if self._rt else self._skip_frames

    @property
    def speed_scale(self) -> float:
        """The speed in effect, as a multiple of :attr:`frame_rate`.

        Read from the Brain, not from the value that was last *requested*:
        a zero or negative rate is clamped to ``0.0`` there -- a
        stop, since reverse playback is
        :meth:`set_playback_direction`'s business -- so the request and the
        effect part company the moment either is passed. The Player-facing
        getter reports the effect.
        """
        return self._rt.speed_scale if self._rt else self._speed

    @property
    def frame_no(self) -> float:
        return self._rt.frame_no if self._rt else 0.0

    @property
    def total_frames(self) -> int:
        return self._rt.total_frames if self._rt else 0

    @property
    def current_animation(self) -> Optional[str]:
        """The animation that is set up, or ``None`` before the first
        :meth:`set_animation`. Not to be confused with :meth:`animation_names`,
        which is the list to choose from."""
        return self._current_animation

    @property
    def instance_problems(self) -> List[str]:
        """Why Instance parts anywhere in this tree draw nothing: one message
        per part whose pack would not load (a stale or invalid pack) or lacks
        the animation the part plays. Empty when every part has its child. A
        pack the pack reader could not find is the reader's to report."""
        return list(self._problems)

    @property
    def frame_rate(self) -> int:
        """Frames per second in effect: the pack's authored rate unless
        :meth:`set_frame_rate` overrode it."""
        # `_rt` is the thin binding over the C ABI, whose name is
        # `ss_runtime_get_frame_rate`; the Player-facing stem is `frameRate`.
        return self._rt.frame_rate if self._rt else 0

    @property
    def loop_count(self) -> int:
        """Cycles to play; ``-1`` is infinite. Read back rather than kept by the
        caller, since :meth:`set_animation` resets the Brain's counter and this
        Player re-applies its own value afterwards."""
        return self._loop

    @property
    def sub_frame_enabled(self) -> bool:
        """Whether what is drawn may sit between two authored frames."""
        return self._sub_frame

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
        if self._stack_moves():
            return True
        return self._has_independent_rigs()

    def _stack_moves(self) -> bool:
        """Whether the clock runs and the track stack moves the pose on it,
        beyond track 0's own animation: a fade in flight, or another source
        still playing on a track that is heard. The clock is the Brain's, not
        track 0's: is_playing / is_pausing go false when track 0 finishes, and
        the stack runs on. Which tracks and sources count is the Brain's call;
        it releases sources itself, so a copy kept here would go stale."""
        rt = self._rt
        return (rt is not None and rt.is_clock_playing
                and not rt.is_clock_pausing and rt.is_stack_in_motion)

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
        self._current_animation = name
        # The loop count is per-transition, so re-apply ours. Speed and frame
        # skipping survive setup_animation on their own (SDK #369 / #370); they
        # are pushed anyway, because this is the one place a value set before the
        # first setup is guaranteed to reach the Brain.
        self._rt.set_loop_count(self._loop)
        if self._speed != 1.0:
            self._rt.set_speed_scale(self._speed)
        if not self._skip_frames:
            self._rt.set_skip_frames(False)
        # NOT carried: the section, and only the section. It is a range of frame
        # numbers and means nothing against a different clip. The playback
        # direction and ping-pong style are host policy and survive setup on
        # their own (SDK #375), so nothing here has to put them back.
        # The table an event is read from when the runtime cannot say which
        # animation fired it (a library that predates the track stack).
        if self._evt is not None:
            self._evt.select(name)
        # The rigs themselves are pack-static (built at construction); a switch
        # only re-arms their slots so the new animation's Instance/Effect parts
        # fire from the top.
        self._reset_slots()
        return True

    def play(self, start_frame: float = -1.0) -> None:
        """Start playback. ``start_frame >= 0`` begins there; otherwise heads
        out from the section start -- this is not a resume, which is
        :meth:`resume`."""
        if self._current_animation is None:
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

    def make_child(self, child_data: bytes, what: str = ""):
        """Build a parent-driven child player that shares this player's resources.

        The Instance rig (``ss_renpy.instance``) resolves *which* pack/animation a
        child part references; this factory owns *how* a child is built from the
        owner — inheriting lib, ResourceManager, external-pack loader, the shared
        texmap and base_dir, running parent-driven (the parent seeks it) with its
        own timeline events suppressed (root-only). Keeping construction here
        keeps the owner's construction details out of the instance module.
        Returns ``None`` on construction failure, recording why in
        :attr:`instance_problems`, after ``what`` (which part, playing what).
        """
        try:
            return SSInternalPlayer(
                child_data, lib=self._lib, base_dir=self.base_dir,
                resource_manager=self._rm, sub_frame=self._sub_frame,
                enable_events=False, parent_driven=True,
                loader=self._loader, texmap=self._texmap,
                problems=self._problems)
        except Exception as e:
            self._problems.append("%s: %s" % (what, e) if what else str(e))
            return None

    def render_at(self, frame_no, looped, dt_s, sub_frame=None, inherited=None):
        """Pose to an externally-stepped ``frame_no`` (no head advance) and return
        this player's z-ordered, world-space draw items.

        Used when this player is an Instance child: the parent's instance slot
        already computed ``frame_no``; we evaluate that frame and recurse into
        this child's own Instance/Effect parts. ``inherited`` is the
        :class:`mask.MaskInherit` the calling Instance part hands down: our parts
        take their numbers from the root's tree, sample the root's coverage,
        and our writers go back up in it. Never raises: a draw-plan failure
        returns Normal/Mesh-only, and a native/parse failure returns an empty
        list rather than propagating into the parent's frame build."""
        try:
            return self._render_at(frame_no, looped, dt_s, sub_frame, inherited)
        except Exception:
            return []

    def _render_at(self, frame_no, looped, dt_s, sub_frame=None, inherited=None):
        rt = self._rt
        sf = self._sub_frame if sub_frame is None else sub_frame
        disp = frame_no if sf else math.floor(frame_no)
        fb = rt.get_frame_data_view(disp)
        if not fb:
            return []
        fd = framedata.parse(fb)
        try:
            return collect_ordered(rt, fd, self._instances, self._effects,
                                   frame_no, dt_s, looped, sf,
                                   part_infos=self._part_infos,
                                   inherited=inherited)
        except Exception:
            return self._plain_items(
                disp, None if inherited is None
                else (inherited.influence, inherited.visible_inside))

    def _plain_items(self, disp, mask_ctx):
        """Normal-part-only renderables for ``disp``, without masks — the draw
        when the full walk failed. ``collect_ordered`` may have stepped slots
        and invalidated the zero-copy view, so the frame is fetched again.
        ``mask_ctx`` is the ``(influence, visible_inside)`` this animation was
        reached with, or None when nothing in the tree masks: a part that shows
        only inside a mask is then left out, as it would be with no mask."""
        fb = self._rt.get_frame_data_view(disp)
        if not fb:
            return []
        infos = self._part_infos
        out = []
        for mp in framedata.build_mesh_parts(self._rt, framedata.parse(fb)):
            p = mp.part_index
            if (mask_ctx is not None and 0 <= p < len(infos)
                    and mask.draws_only_inside(infos[p], mask_ctx)):
                continue
            out.append(("mesh", mp))
        return out

    def step_slots_only(self, frame_no, looped, dt_s, sub_frame=None):
        """Advance every Instance/Effect slot of this player (recursively) without
        building renderables.

        Called by :meth:`ss_renpy.instance.InstanceRig.step_idle` when this player
        is a *hidden* Instance child: the Brain drops Hide'd parts from
        ``draw_order``, so the normal render walk (``render_at`` →
        ``collect_ordered``) never runs for it and its slots would freeze. Stepping
        here keeps independent descendants advancing while off-screen.
        Never raises — and guards each slot on
        its own, so one wedged child cannot freeze its siblings' clocks."""
        sf = self._sub_frame if sub_frame is None else sub_frame
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
        # The Brain's pause is one-way and idempotent, and ignores a request
        # made while nothing is playing, so this needs no guard of its own.
        if self._rt:
            self._rt.pause()

    def resume(self) -> None:
        # Lifting the hold is `resume`, not a second `pause`: the Brain stopped
        # toggling. `play` would head out and lose the playhead.
        if self._rt:
            self._rt.resume()

    def stop(self) -> None:
        # Nothing rewinds: the playhead stays where it stands, so the host keeps
        # drawing the frame it stopped on. `play` is what heads out again.
        # A *commanded* stop is not a natural end: the Brain's is_finished stays
        # false for it (only a self-exhausted loop count trips it), so the host
        # never mistakes a commanded stop() for a completion.
        if self._rt:
            self._rt.stop()

    def set_loop_count(self, count: int) -> None:
        self._loop = count
        if self._rt:
            self._rt.set_loop_count(count)

    def set_speed_scale(self, speed: float) -> None:
        """Scale playback by ``speed``, a multiple of :attr:`frame_rate`.

        ``0.0`` and negatives are a **stop** in the Brain, not reverse playback
        (that is :meth:`set_playback_direction`); read :attr:`speed_scale`
        to see the value that took effect. :attr:`speed` keeps what was asked
        for, because the host layer replays it onto a rebuilt core.
        """
        self._speed = speed
        if self._rt:
            self._rt.set_speed_scale(speed)

    def set_frame_no(self, frame: float) -> None:
        if self._rt:
            self._rt.set_frame_no(frame)

    def set_animation_section(self, start: int, end: int) -> bool:
        """False, changing nothing, when the Brain refuses the section: both
        ends inside the animation and the end before the start."""
        return self._rt is not None and self._rt.set_animation_section(start, end)

    def set_playback_direction(self, direction: int, style: int = 0) -> None:
        # Remember it so set_animation() can re-apply after setup_animation resets
        # it; works whether called before or after set_animation.
        self._direction = direction
        self._style = style
        if self._rt:
            self._rt.set_playback_direction(direction, style)

    def set_frame_skip_enabled(self, enabled: bool) -> None:
        """Toggle frame skipping (on by default).

        On, ``update`` advances by the elapsed time and keeps real-time pace,
        skipping frames after a stall; off, it advances exactly one frame per
        update, so nothing is skipped and the animation stretches instead. See
        :meth:`ssruntime.SSRuntime.set_skip_frames`.

        Remembered like direction/style — ``setup_animation`` resets it to on —
        so it survives an animation switch, including host sequence chaining."""
        self._skip_frames = bool(enabled)
        if self._rt:
            self._rt.set_skip_frames(self._skip_frames)

    def set_frame_rate(self, fps: int) -> None:
        if self._rt:
            self._rt.set_frame_rate(fps)

    def set_sub_frame_enabled(self, enabled: bool) -> None:
        self._sub_frame = bool(enabled)

    # -- animation mixing: the Brain's track stack ---------------------
    # Layer and cross-fade animations of this pack on one character. Track 0
    # is the one set_animation sets up; tracks above it layer onto the pose
    # below, each with an alpha and a blend, and a track can carry several
    # weighted sources. Thin wrappers over the runtime: an animation is named
    # as set_animation names it, a track is an int >= 0, a source is the handle
    # track_main_source / add_track_source hand out. A setter returns False
    # when the runtime refuses the call; a read returns None where there is
    # nothing to read (no such track or source, no fade in flight, no
    # animation on the track). Fades take milliseconds, as update() does.
    #
    # set_animation folds the stack back to track 0 alone and resets what it
    # resets for track 0 (trackSync, alpha and blend of the other tracks
    # included), so a host lays its overlays again after it.
    @staticmethod
    def _track(track) -> int:
        """``track`` as a track number, or -1 for one the runtime cannot take
        (a negative int would wrap around to a huge u32 in ctypes)."""
        try:
            t = int(track)
        except (TypeError, ValueError):
            return -1
        return t if t >= 0 else -1

    def _track_zero_switched(self, name: str) -> None:
        """Track 0 plays ``name`` from this call on, as after set_animation.

        A crossfade (or a track animation) on track 0 hands the character to
        the incoming animation when it begins, not when it completes: from
        here is_playing / is_finished / just_looped, the frame and the events
        fired by default are the incoming animation's. Recording the switch
        now is what keeps set_animation from taking the animation a crossfade
        left for the one still selected, and current_animation from naming the
        outgoing one. Nothing is started -- the incoming animation carries on
        whatever play state track 0 had -- and the Instance/Effect slots are
        left running: they come from the pack's parts, which every animation
        of it shares."""
        self._current_animation = name
        if self._evt is not None:
            self._evt.select(name)
        # The loop count belongs to the animation, so the incoming one starts
        # looping forever; put this Player's count back on it, as set_animation
        # does. Speed, direction, frame-rate override and frame skip belong to
        # the track and carry over in the Brain.
        if self._rt:
            self._rt.set_loop_count(self._loop)
        # A finish of the outgoing animation is not this one's.
        self._was_finished = False

    def set_track_animation(self, track, name: str) -> bool:
        """Lay ``name`` on ``track``, replacing what it plays, without a fade.
        On track 0 it is what set_animation sets up from here on, but the stack
        and the play state stay as they are."""
        t = self._track(track)
        if t < 0 or not name or self._rt is None:
            return False
        if not self._rt.set_track_animation(t, name):
            return False
        if t == 0:
            self._track_zero_switched(name)
        return True

    def crossfade(self, track, name: str, duration_ms: float) -> bool:
        """Fade ``track`` over to ``name`` in ``duration_ms``. Everything the
        track carries fades out together; a crossfade started while one is in
        flight takes the pose as it stands. On track 0 the incoming animation
        is the current one from this call on (see `_track_zero_switched`)."""
        t = self._track(track)
        if t < 0 or not name or self._rt is None:
            return False
        if not self._rt.crossfade(t, name, float(duration_ms)):
            return False
        if t == 0:
            self._track_zero_switched(name)
        return True

    def track_count(self) -> int:
        return self._rt.track_count() if self._rt else 0

    def clear_track(self, track) -> bool:
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.clear_track(t))

    def set_track_alpha(self, track, alpha: float) -> bool:
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.set_track_alpha(t, float(alpha)))

    def track_alpha(self, track) -> Optional[float]:
        t = self._track(track)
        return self._rt.track_alpha(t) if t >= 0 and self._rt else None

    def set_track_blend(self, track, blend: int) -> bool:
        """``blend`` is ``ssruntime.TRACK_BLEND_MIX`` or ``_ADDITIVE``."""
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.set_track_blend(t, int(blend)))

    def track_blend(self, track) -> Optional[int]:
        t = self._track(track)
        return self._rt.track_blend(t) if t >= 0 and self._rt else None

    def set_track_sync(self, track, sync: int) -> bool:
        """``sync`` is ``ssruntime.TRACK_SYNC_FREE`` or ``_START``. It decides
        where the next animation laid on the track starts, so set it first."""
        t = self._track(track)
        return t >= 0 and self._rt is not None and self._rt.set_track_sync(
            t, int(sync))

    def track_sync(self, track) -> Optional[int]:
        t = self._track(track)
        return self._rt.track_sync(t) if t >= 0 and self._rt else None

    def set_track_frame(self, track, frame: float) -> bool:
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.set_track_frame(t, float(frame)))

    def track_frame(self, track) -> Optional[float]:
        t = self._track(track)
        return self._rt.track_frame(t) if t >= 0 and self._rt else None

    # A track's playback settings reach every animation on it, both sides of a
    # crossfade included, and outlast the animation. Track 0's are the ones the
    # older setters reach (set_speed_scale, set_frame_rate, ...); on track 0
    # these go through the copies this Player keeps for set_animation, so the
    # next switch does not put an older value back.
    def set_track_speed(self, track, speed: float) -> bool:
        t = self._track(track)
        if t < 0 or self._rt is None:
            return False
        if t == 0:
            self._speed = float(speed)
        return self._rt.set_track_speed(t, float(speed))

    def track_speed(self, track) -> Optional[float]:
        t = self._track(track)
        return self._rt.track_speed(t) if t >= 0 and self._rt else None

    def set_track_frame_rate(self, track, fps: int) -> bool:
        t = self._track(track)
        return t >= 0 and self._rt is not None and self._rt.set_track_frame_rate(
            t, int(fps))

    def track_frame_rate(self, track) -> Optional[int]:
        """The rate the track's animation plays at; 0 for a track with neither
        an animation nor an override."""
        t = self._track(track)
        return self._rt.track_frame_rate(t) if t >= 0 and self._rt else None

    def set_track_frame_skip_enabled(self, track, enabled: bool) -> bool:
        t = self._track(track)
        if t < 0 or self._rt is None:
            return False
        if t == 0:
            self._skip_frames = bool(enabled)
        return self._rt.set_track_skip_frames(t, bool(enabled))

    def track_frame_skip_enabled(self, track) -> Optional[bool]:
        t = self._track(track)
        if t < 0 or self._rt is None or t >= self._rt.track_count():
            return None
        return self._rt.track_skip_frames(t)

    def set_track_playback_direction(self, track, direction: int,
                                     style: int = 0) -> bool:
        t = self._track(track)
        if t < 0 or self._rt is None:
            return False
        if t == 0:
            self._direction, self._style = direction, style
        return self._rt.set_track_playback_direction(t, int(direction),
                                                     int(style))

    def track_playback_direction(self, track) -> Optional[int]:
        t = self._track(track)
        return (self._rt.track_playback_direction(t)
                if t >= 0 and self._rt else None)

    def track_playback_style(self, track) -> Optional[int]:
        t = self._track(track)
        return self._rt.track_playback_style(t) if t >= 0 and self._rt else None

    def set_track_loop_count(self, track, count: int) -> bool:
        """The loop count belongs to the animation on the track, so laying
        another one there starts it looping forever again; set it after. Track
        0's is :meth:`set_loop_count`, which this Player puts back on every
        animation track 0 is switched to."""
        t = self._track(track)
        if t < 0 or self._rt is None:
            return False
        if t == 0:
            self._loop = int(count)
        return self._rt.set_track_loop_count(t, int(count))

    def track_loop_count(self, track) -> Optional[int]:
        """``-1`` loops forever; None for a track with no animation."""
        t = self._track(track)
        return self._rt.track_loop_count(t) if t >= 0 and self._rt else None

    def is_track_finished(self, track) -> bool:
        """Whether the track's animation has played its loops: a state, as
        :meth:`is_finished` is for track 0. A finished track holds its last
        frame and is still mixed in -- fading or clearing it is the host's
        call -- and only track 0 finishing ends the character's playback."""
        t = self._track(track)
        return t >= 0 and self._rt is not None and self._rt.is_track_finished(t)

    def track_just_looped(self, track) -> bool:
        """Whether the last update wrapped the track's animation: a pulse, as
        :meth:`just_looped` is for track 0."""
        t = self._track(track)
        return t >= 0 and self._rt is not None and self._rt.track_just_looped(t)

    def set_track_outgoing_event_threshold(self, track,
                                           threshold: float) -> bool:
        """How long the outgoing side of a crossfade on ``track`` keeps firing
        events: while its share of the track, ``1 - t``, is at least
        ``threshold``. The default, ``inf``, silences it as the fade begins;
        ``0.5`` keeps it firing through the first half."""
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.set_track_outgoing_event_threshold(
                    t, float(threshold)))

    def track_outgoing_event_threshold(self, track) -> Optional[float]:
        t = self._track(track)
        return (self._rt.track_outgoing_event_threshold(t)
                if t >= 0 and self._rt else None)

    def fade_track(self, track, target_alpha: float,
                   duration_ms: float) -> bool:
        """Fade the track's alpha to ``target_alpha`` -- how much the track
        takes effect, not what it plays (that is :meth:`crossfade`)."""
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.fade_track(t, float(target_alpha),
                                        float(duration_ms)))

    def track_fade_progress(self, track) -> Optional[float]:
        """``0..1`` through the fade in flight on ``track``; None when it is
        not fading."""
        t = self._track(track)
        return self._rt.track_fade_progress(t) if t >= 0 and self._rt else None

    def cancel_track_fade(self, track) -> bool:
        t = self._track(track)
        return (t >= 0 and self._rt is not None
                and self._rt.cancel_track_fade(t))

    def track_main_source(self, track) -> Optional[int]:
        """Handle of the source carrying the track's animation. A source the
        Brain releases -- the outgoing side once a crossfade completes, say --
        may hand its number to a later one, so do not keep it across that."""
        t = self._track(track)
        return self._rt.track_main_source(t) if t >= 0 and self._rt else None

    def add_track_source(self, track, name: str,
                         weight: float = 1.0) -> Optional[int]:
        """Add ``name`` to ``track`` as another weighted source; its handle, or
        None when refused."""
        t = self._track(track)
        if t < 0 or not name or self._rt is None:
            return None
        return self._rt.add_track_source(t, name, float(weight))

    def set_source_weight(self, source, weight: float) -> bool:
        s = self._track(source)
        return (s >= 0 and self._rt is not None
                and self._rt.set_source_weight(s, float(weight)))

    def source_weight(self, source) -> Optional[float]:
        s = self._track(source)
        return self._rt.source_weight(s) if s >= 0 and self._rt else None

    def set_source_frame(self, source, frame: float) -> bool:
        s = self._track(source)
        return (s >= 0 and self._rt is not None
                and self._rt.set_source_frame(s, float(frame)))

    def source_frame(self, source) -> Optional[float]:
        s = self._track(source)
        return self._rt.source_frame(s) if s >= 0 and self._rt else None

    def set_source_event_threshold(self, source, threshold: float) -> bool:
        """The weight at which the source starts firing events. Only track 0's
        main source fires by default (``inf`` elsewhere)."""
        s = self._track(source)
        # Decides which events are reported, not what is drawn.
        return s >= 0 and self._rt is not None and \
            self._rt.set_source_event_threshold(s, float(threshold))

    def source_event_threshold(self, source) -> Optional[float]:
        s = self._track(source)
        return (self._rt.source_event_threshold(s)
                if s >= 0 and self._rt else None)

    # -- per-frame advance ---------------------------------------------
    def update(self, dt_ms: float) -> FramePlan:
        """Advance by ``dt_ms`` milliseconds and return this frame's plan.

        Pure single-animation playback: advance the Brain, collect timeline
        events, observe the looped / finished edges, then materialise the
        z-ordered world-space draw plan. It does NOT decide what to play next —
        sequence chaining is the host's policy (it reads ``FramePlan.finished``
        and calls ``set_animation`` itself).

        Never raises: a draw-plan failure falls back to Normal/Mesh-only, and a
        native/parse failure (update_ms, get_frame_data_view,
        world_matrices_snapshot, parse) degrades to an empty FramePlan instead
        of crashing the host's render() — the previous frame stays on screen and
        the next tick retries.
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
        looped = rt.just_looped

        events_out: list = []
        if self._enable_events and self._evt is not None:
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
        disp = frame_no if self._sub_frame else math.floor(frame_no)
        fb = rt.get_frame_data_view(disp)
        self._last_world = rt.world_matrices_snapshot()
        self._outline.capture(rt, fb, self._last_world, self._has_mesh)
        items: list = []
        hidden: Optional[set] = None
        frame_mask = None
        if fb:
            fd = framedata.parse(fb)
            # ONE bulk PartState decode for the whole frame: the hidden-part
            # snapshot, the mask walk and the renderable walk all read the same
            # values, and each used to decode the vector again.
            bulk_parts = framedata.bulk_part_states(fd)
            hidden = framedata.hidden_parts(fd, bulk_parts)
            # One coverage for the whole instance tree, filled while
            # collect_ordered walks it: each animation reads its own writers
            # there, before it steps any slot of its own.
            tree = (mask.MaskTree(self._tree_writes)
                    if self._tree_writes or self._tree_draws_inside else None)
            try:
                items = collect_ordered(rt, fd, self._instances, self._effects,
                                        frame_no, dt_s, looped, self._sub_frame,
                                        part_infos=self._part_infos,
                                        tree=tree, parts=bulk_parts)
                if tree is not None:
                    frame_mask = tree.frame_mask
                    frame_mask.finalize(tree.seq)
                    mask.settle(items, frame_mask)
            except Exception:
                items = self._plain_items(
                    disp, None if tree is None else mask.ROOT_CONTEXT)
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

    def find_part_index(self, name: str) -> int:
        return self._part_index.get(name, -1)

    def part_transform(self, name: str):
        """Player-local transform of ``name`` on the last rendered frame, or
        ``None``: dict with x/y (px), rotation (deg), xscale/yscale.

        A position, a rotation and a scale — a part's skew (shear) is not part
        of it. SpriteStudio applies skew as a per-part vertex deform that does
        not propagate to child parts, so a follower (which behaves like a child)
        rides the pose without the shear even under a sheared part or parent;
        the art itself still draws sheared.
        """
        i = self.find_part_index(name)
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
        """Whether ``name`` was hidden on the last rendered frame.

        ``False`` for a part this pack does not have, and ``False`` before the
        first :meth:`update` has produced a frame — "not hidden", the same
        answer the sibling Players give (ForFlutter's ``isPartHidden``,
        ForGodot's ``is_part_hidden``). Answering ``True`` there reads as "this
        part is hidden" and sends a caller down the branch for a part that does
        not exist; use :meth:`part_index` (``-1``) to ask whether it does.
        """
        i = self.find_part_index(name)
        if i < 0 or self._last_hidden is None:
            return False
        return i in self._last_hidden

    def part_quad(self, part):
        """The outline ``part`` (a name or index) is drawn with on the last
        rendered frame, as four ``(x, y)`` corners -- ``lt, rt, lb, rb`` -- in
        the space :meth:`part_transform` reports; ``None`` for an unknown or
        hidden part, one that draws nothing of its own (Null, bone, Instance,
        Effect), or before the first frame. See ``ss_renpy.outline``."""
        i = self.resolve_part(part)
        return self._outline.quad(i) if i >= 0 else None

    def hit_test_part(self, x: float, y: float, parts=None) -> int:
        """The index of the front-most part whose :meth:`part_quad` outline
        holds ``(x, y)`` on the last rendered frame, among ``parts`` (names or
        indices; every part when ``None``), or -1. A part this pack lacks is
        skipped."""
        targets = None
        if parts is not None:
            targets = {i for i in map(self.resolve_part, parts) if i >= 0}
        return self._outline.hit_test(x, y, targets)

    def is_part_skinned_mesh(self, name: str) -> bool:
        """Whether ``name`` is a bone-skinned mesh part (``False`` if unknown).

        Static ``.ssab`` metadata (a mesh binding with influencing bones), so —
        unlike :meth:`is_part_hidden` — this holds before the first frame and
        never changes. A skinned mesh draws from its bones while its own node
        transform stays at the setup pose, so it is a poor *part-tracking*
        (``ss_attach``) target: a follower snaps to the node, not the deformed
        art. Mirrors the sibling Players' ``is_part_skinned_mesh``; deform-only
        (rigid) meshes and non-mesh parts answer ``False``. Read once, from the
        per-part info the pack was parsed into at construction.
        """
        i = self.find_part_index(name)
        if i < 0:
            return False
        return self._part_infos[i].skinned_mesh

    # -- part overrides -------------------------------------------------
    # Per-part runtime overrides (color / cell / visibility): an imperative
    # "make this part this colour / cell / hidden NOW" that the Brain applies on
    # the resolved pose, so it wins over both the keyframe and any blend.
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
        i = part if isinstance(part, int) else self.find_part_index(part)
        return i if 0 <= i < len(self._part_infos) else -1

    def set_part_visibility_override(self, part, hide: bool = True,
                                     cascade: bool = False) -> bool:
        """Force-hide ``part`` (``hide=True``) or revert it to the animation.

        ``cascade`` propagates the force-hide to the part's descendants — new,
        override-only behaviour (a keyframed hide never cascades in SpriteStudio).
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

    def replaceable_texture_names(self) -> List[str]:
        """Names accepted by :meth:`resolve_texture_name` — every cellmap plus
        every texture a ``TCHG`` can select.
        The host surfaces these as the
        runtime texture-replacement targets."""
        return self._meta.replaceable_texture_names()

    def resolve_texture_name(self, name: str) -> str:
        """Host-relative image path for a replaceable-texture ``name`` (or "").

        The SAME string :meth:`texture_path` returns for that image, so the host
        can key a texture-replacement override by it and every
        ``DrawBatch.texture_hash`` that binds this image will resolve to the
        override. The two hash spaces (cellmap name and TCHG file name) collapse
        to one path here, so keying by path covers both."""
        img = self._meta.resolve_texture_image(name)
        if not img:
            return ""
        return (self.base_dir + "/" + img) if self.base_dir else img

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
