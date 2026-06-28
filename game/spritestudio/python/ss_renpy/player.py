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
    ``started`` / ``looped`` / ``finished`` are edge notifications for the host
    to map onto callbacks. ``world_matrices`` / ``hidden_parts`` snapshot the
    state the part-query API reads (taken before child/effect slots step, which
    invalidate the transient buffers).
    """
    items: list = field(default_factory=list)
    frame_no: float = 0.0
    disp: float = 0.0
    looped: bool = False
    started: bool = False
    finished: bool = False
    events: list = field(default_factory=list)
    world_matrices: list = field(default_factory=list)
    hidden_parts: Optional[set] = None


class SSInternalPlayer:
    """Imperative, engine-independent player for one ``.ssab`` pack."""

    def __init__(self, ssab_data: bytes, *, lib,
                 base_dir: str = "",
                 resource_manager: Optional[ResourceManager] = None,
                 pack_reader=None,
                 sub_frame: bool = True,
                 enable_events: bool = True,
                 coordinate_system: int = ssruntime.COORD_Y_DOWN,
                 origin: int = ssruntime.ORIGIN_CENTER):
        self._data = ssab_data
        self._lib = lib
        # ``base_dir`` is the host-relative dir used only to build texture
        # identifiers handed to the ResourceManager (textures are co-located
        # with the .ssab). Pack bytes are read via ``pack_reader`` instead.
        self.base_dir = base_dir.replace("\\", "/").rstrip("/")
        self._rm = resource_manager or RecordingResourceManager()
        self._pack_reader = pack_reader

        self._meta = SsabMeta(ssab_data)
        self._texmap = dict(self._meta.texture_hash_map())
        self._part_index = {p.name: p.index for p in self._meta.parts()}
        self._loader = self._make_loader()

        self._rt = ssruntime.SSRuntime(lib)
        self._rt.configure(coordinate_system=coordinate_system, origin=origin)
        self._rt.load_ssab_bytes(ssab_data)

        # playback state
        self.sub_frame = bool(sub_frame)
        self._enable_events = bool(enable_events)
        self.animation: Optional[str] = None
        self.loop = -1
        self.speed = 1.0
        self._base_loop = -1          # loop applied to the final queued animation
        self._anim_queue: List[str] = []

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
            self._instances = InstanceRig(self._rt, self._meta, self._loader,
                                          self._lib)
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
        # Textures for this pack (set_animation owns texture loading).
        self._acquire_textures(self._texmap.values())
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

    def play_sequence(self, names, loop: int = -1) -> None:
        """Play ``names`` in order; each but the last plays once, the last uses
        ``loop``. ``names`` may be a single name or a list."""
        if isinstance(names, str):
            names = [names]
        names = [n for n in names if n]
        if not names:
            return
        self._base_loop = loop
        self._anim_queue = list(names[1:])
        self.loop = 1 if self._anim_queue else loop
        self.set_animation(names[0])
        self.play()

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

        Mirrors the host displayable's per-frame core: advance the Brain, pump
        timeline events + finished/looped edges (auto-advancing a queued
        sequence), then materialise the z-ordered, world-space draw plan. Never
        raises; on a draw-plan failure it falls back to Normal/Mesh-only.
        """
        rt = self._rt
        dt_s = dt_ms / 1000.0
        frame_no = rt.update_ms(dt_ms)
        looped = rt.is_looped

        # --- events + play-state edges (engine-agnostic part of _pump_events)
        events_out: list = []
        started = False
        finished = False
        if self._enable_events and self._evt is not None and self._evt.available:
            try:
                for fe in self._evt.collect(rt):
                    self._event_queue.append(fe)
                    events_out.append(fe)
            except Exception:
                pass
        playing = rt.is_playing
        if self._was_playing and not playing:
            if self._anim_queue:
                nxt = self._anim_queue.pop(0)
                self.loop = 1 if self._anim_queue else self._base_loop
                self.set_animation(nxt)
                self.play()
                started = True
                playing = rt.is_playing
            else:
                finished = True
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
                         looped=looped, started=started, finished=finished,
                         events=events_out, world_matrices=self._last_world,
                         hidden_parts=hidden)

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
