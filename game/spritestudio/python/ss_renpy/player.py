"""Engine-independent SpriteStudio playback core (no ``renpy`` import).

``SSInternalPlayer`` owns one ``.ssab`` pack's playback: the ctypes runtime
(the "Brain"), its metadata, the Instance / Effect rigs, and timeline-event
resolution. It exposes an imperative API —

    p = SSInternalPlayer(ssab_bytes, lib=lib, base_dir="ss_assets/Ringo",
                         resource_manager=rm, pack_reader=reader)
    p.set_animation("walk")     # Brain setup_animation + rm.acquire(textures)
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
from dataclasses import dataclass, field
from typing import List, Optional

from ss_renpy import framedata, ssruntime
from ss_renpy.effect import EffectRig
from ss_renpy.events import EventResolver
from ss_renpy.instance import InstanceRig, collect_ordered
from ss_renpy.resource import RecordingResourceManager, ResourceManager
from ss_renpy.ssab_meta import SsabMeta


@dataclass
class FramePlan:
    """Result of one :meth:`SSInternalPlayer.update` — engine-agnostic.

    ``items`` are ``("mesh", MeshPart)`` / ``("fx", EffectBatch)`` in draw order,
    in world space (raw, un-normalised UVs). ``events`` are the FrameEvents that
    elapsed this update (also queued for :meth:`SSInternalPlayer.poll_events`).
    ``looped`` / ``finished`` are pure edge *observations* (``finished`` is the
    play->stop edge); the core takes no action on them — the host reads them and
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

        self._meta = SsabMeta(ssab_data)
        # Texture hash -> image path. Shared across an Instance tree (the root
        # creates it; children receive the same dict) so the root resolves every
        # part's texture_hash, including those from external instance packs.
        self._texmap = texmap if texmap is not None else {}
        self._texmap.update(self._meta.texture_hash_map())
        # This pack's own cellmap images, acquired on set_animation. External
        # packs' images are acquired by the loader as they are loaded.
        self._own_images = [c.image_path for c in self._meta.cellmaps()
                            if c.image_path]
        self._part_index = {p.name: p.index for p in self._meta.parts()}
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

        # rigs / events (built lazily on first set_animation)
        self._instances: Optional[InstanceRig] = None
        self._effects: Optional[EffectRig] = None
        self._evt: Optional[EventResolver] = None
        self._event_queue: list = []
        self._was_playing = False

        # part-query snapshots (last rendered frame)
        self._last_world: list = []
        self._last_hidden: Optional[set] = None

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
        """True while something visibly moves (playing, or live rigs)."""
        if self._rt and self._rt.is_playing and not self._rt.is_pausing:
            return True
        if self._effects is not None and self._effects.has():
            return True
        if self._instances is not None and self._instances.has():
            return True
        return False

    # -- playback control ----------------------------------------------
    def set_animation(self, name: Optional[str] = None) -> bool:
        """Load + pose an animation (does NOT start playback).

        Runs the Brain's ``setup_animation`` and asks the ResourceManager to
        acquire this pack's textures, rebuilds the timeline-event resolver, and
        (re)arms the Instance/Effect rigs. ``name=None`` selects the first
        animation. Returns ``False`` if the animation is unknown.
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
        # Textures for this pack (set_animation owns texture loading). External
        # instance packs' textures are acquired by the loader as they load.
        self._acquire_textures(self._own_images)
        # Timeline events are per-animation; rebuild the resolver.
        if self._enable_events:
            try:
                self._evt = EventResolver(self._data, name)
            except Exception:
                self._evt = None
        # Build rigs once, then just re-arm on subsequent switches.
        if self._instances is None and self._effects is None:
            self._build_rigs()
        else:
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
        self._was_playing = True

    # -- instance-child support (parent-driven mode) -------------------
    @property
    def ctx(self):
        """Native runtime context handle (the parent's instance slot steps it)."""
        return self._rt.ctx if self._rt else None

    def reset_slots(self) -> None:
        """Re-arm this player's Instance/Effect slots (parent calls on replay)."""
        self._reset_slots()

    def render_at(self, frame_no, looped, dt_s, sub_frame=None):
        """Pose to an externally-stepped ``frame_no`` (no head advance) and return
        this player's z-ordered, world-space draw items.

        Used when this player is an Instance child: the parent's instance slot
        already computed ``frame_no``; we evaluate that frame and recurse into
        this child's own Instance/Effect parts. Never raises; on a draw-plan
        failure it returns Normal/Mesh-only."""
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

    def pause(self) -> None:
        if self._rt and not self._rt.is_pausing:
            self._rt.pause()

    def resume(self) -> None:
        if self._rt and self._rt.is_pausing:
            self._rt.pause()
            self._was_playing = True

    def stop(self) -> None:
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
        if self._rt:
            self._rt.set_playback_direction(direction, style)

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
        and calls ``set_animation`` itself). Never raises; on a draw-plan failure
        it falls back to Normal/Mesh-only.
        """
        if self._parent_driven:
            # An Instance child is seeked by its parent via render_at(); its own
            # per-tick update is a no-op (mirrors Godot's setParentDriven).
            return FramePlan()
        rt = self._rt
        dt_s = dt_ms / 1000.0
        frame_no = rt.update_ms(dt_ms)
        looped = rt.is_looped

        events_out: list = []
        if self._enable_events and self._evt is not None and self._evt.available:
            try:
                for fe in self._evt.collect(rt):
                    self._event_queue.append(fe)
                    events_out.append(fe)
            except Exception:
                pass
        # The play->stop edge — a pure observation the host maps to its policy.
        playing = rt.is_playing
        finished = self._was_playing and not playing
        self._was_playing = playing

        # --- draw plan (sub-frame off floors the *display* frame only)
        disp = frame_no if self.sub_frame else math.floor(frame_no)
        fb = rt.get_frame_data_view(disp)
        wm, wn = rt.world_matrices()
        self._last_world = list(wm[0:wn]) if (wm and wn) else []
        items: list = []
        hidden: Optional[set] = None
        if fb:
            fd = framedata.parse(fb)
            hidden = framedata.hidden_parts(fd)
            try:
                items = collect_ordered(rt, fd, self._instances, self._effects,
                                        frame_no, dt_s, looped, self.sub_frame)
            except Exception:
                # collect_ordered may have stepped slots and invalidated the
                # zero-copy view; re-evaluate for a clean Normal/Mesh-only frame.
                fb2 = rt.get_frame_data_view(disp)
                items = ([("mesh", mp)
                          for mp in framedata.build_mesh_parts(
                              rt, framedata.parse(fb2))]
                         if fb2 else [])
        self._last_hidden = hidden

        return FramePlan(items=items, frame_no=frame_no, disp=disp,
                         looped=looped, finished=finished, events=events_out,
                         world_matrices=self._last_world, hidden_parts=hidden)

    # -- timeline events -----------------------------------------------
    def poll_events(self) -> list:
        """Drain and return the FrameEvents collected since the last poll."""
        q = self._event_queue
        self._event_queue = []
        return q

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
