"""Instance-part child playback, recursive (docs/08 §1).

A SpriteStudio **Instance part** embeds another animation, played in sync with
(or independently of) the parent. The Brain does the time/loop bookkeeping; the
host must:

1. keep one ``InstanceSlot`` + one *child* runtime context per instance part;
2. each frame resolve the part's active ``EventInstance`` and call
   ``ss_instance_slot_step`` (which advances the child and returns its exact
   float ``child_frame_no``);
3. render the child at that frame, composed by the instance part's world matrix
   and hierarchical alpha;
4. recurse — a child may itself contain Instance / Effect parts.

This module is engine-independent (no ``renpy`` import); the Ren'Py displayable
and the headless ``verify_instance`` tool both drive it through
:func:`collect_ordered`, which returns z-ordered, world-space renderables.

``collect_ordered`` materializes the draw plan (copying all SoA-derived data)
*before* stepping any child/effect slot, because those calls invalidate the
parent's transient SoA buffers — the same discipline the SDK warns about.
"""

from __future__ import annotations

import math

from ss_renpy import framedata, ssruntime
from ss_renpy.effect import EffectRig
from ss_renpy.effectplan import transform_effect_batch
from ss_renpy.ssab_meta import SsabMeta

# Hard cap on instance nesting (defends against pathological / cyclic refs).
MAX_DEPTH = 8


def display_frame(frame_no: float, sub_frame: bool):
    """Frame to *render*: raw float when sub-frame is on, else floored.

    The playback head stays a raw float regardless (docs/08 §3) — only the
    value handed to ``get_frame_data`` is floored when sub-frame is off.
    """
    return frame_no if sub_frame else float(math.floor(frame_no))


def collect_ordered(rt, fd, instances, effects, parent_frame, dt,
                    parent_looped, sub_frame):
    """Z-ordered renderables for ``rt`` at the current frame.

    Returns a list of ``("mesh", MeshPart)`` / ``("fx", EffectBatch)`` in draw
    order, all in ``rt``'s world space. Normal parts come straight from the draw
    plan; Instance parts recurse and are composed by the instance part's matrix;
    Effect parts are stepped. Shared by the root player and :class:`SubPlayer`.
    """
    # Materialize first: this fully drains the transient SoA buffers into copied
    # MeshParts / matrices, so the child/effect Brain calls below are safe.
    plan = list(framedata.iter_draw_plan(rt, fd))
    out = []
    for item in plan:
        tag = item[0]
        if tag == "mesh":
            out.append(("mesh", item[1]))
        elif tag == "instance":
            _, p, mat, alpha, hidden = item
            child_items = (instances.collect(
                p, parent_frame, dt, parent_looped, sub_frame)
                if instances is not None else [])
            if hidden:
                continue   # stepped for timing above; just not drawn
            for ctag, payload in child_items:
                if ctag == "mesh":
                    out.append(("mesh",
                                framedata.transform_mesh_part(payload, mat, alpha)))
                else:  # "fx"
                    out.append(("fx",
                                transform_effect_batch(payload, mat, alpha)))
        elif tag == "effect":
            _, p, mat, alpha, hidden = item
            batches = (effects.collect(p, mat, alpha, parent_frame, dt, parent_looped)
                       if effects is not None else [])
            if hidden:
                continue
            for eb in batches:
                out.append(("fx", eb))
        # "skip": unsupported kind (Shape / Mesh / Text / Nines / Mask) — ignored
    return out


def build_subplayer(parent_rt, part, parent_meta, loader, lib, depth):
    """Create a :class:`SubPlayer` for one instance ``part`` (or ``None``).

    Resolves the referenced pack: *internal* (same ``.ssab`` — re-binds the
    parent's bytes to a fresh context) or *external* (``loader(pack_name)`` per
    ``external_instances``). Returns ``None`` if the pack/animation can't be
    resolved, so the caller skips that instance gracefully.
    """
    if depth > MAX_DEPTH:
        return None
    ref_pack = part.ref_anime_pack
    ref_anim = part.ref_anime_name
    if not ref_anim:
        return None

    if ref_pack and ref_pack != parent_meta.name and loader is not None:
        child_data = loader(ref_pack)        # external pack
    else:
        child_data = parent_meta.data        # internal (same pack, other anim)
    if not child_data:
        return None

    try:
        child_meta = SsabMeta(child_data)
        child_rt = ssruntime.SSRuntime(lib)
        child_rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                           origin=ssruntime.ORIGIN_CENTER)
        child_rt.load_ssab_bytes(child_data)
        if not child_rt.setup_animation(ref_anim):
            child_rt.close()
            return None
    except Exception:
        return None
    return SubPlayer(child_rt, child_meta, loader, lib, depth)


class _Child:
    __slots__ = ("part", "slot", "sub")

    def __init__(self, part, slot, sub):
        self.part = part
        self.slot = slot
        self.sub = sub


class InstanceRig:
    """One InstanceSlot + child :class:`SubPlayer` per Instance part of ``rt``."""

    def __init__(self, rt, meta, loader, lib, depth=0):
        self._rt = rt
        self._children = {}   # part_index -> _Child
        if depth > MAX_DEPTH:
            return
        for p in meta.instance_parts():
            sub = build_subplayer(rt, p, meta, loader, lib, depth + 1)
            if sub is None:
                continue
            slot = rt.instance_slot_create()
            if not slot:
                sub.close()
                continue
            self._children[p.index] = _Child(p, slot, sub)

    def has(self) -> bool:
        return bool(self._children)

    def reset(self):
        """Re-arm slots and recurse (call when the parent replays / heads out)."""
        for ch in self._children.values():
            self._rt.instance_slot_reset(ch.slot)
            ch.sub.reset_slots()

    def collect(self, part_index, parent_frame, dt, parent_looped, sub_frame):
        """Step one instance part and return the child's child-space renderables.

        Returns ``[]`` when the part has no resolvable child or the slot reports
        not-visible. Always steps the slot (independent children keep their own
        clock — docs/08 §3). On an ``EventInstance`` edge the child is
        (re)started so its own start events fire.
        """
        ch = self._children.get(part_index)
        if ch is None:
            return []
        ev = self._rt.active_event_instance(part_index)
        prev = ch.sub.frame_no                       # raw float head (no round)
        r = self._rt.instance_slot_step(
            ch.slot, ev, ch.sub.ctx, prev, parent_frame, dt, parent_looped)
        if r.transitioned:
            ch.sub.play()
        if not r.visible:
            return []
        return ch.sub.collect(r.child_frame_no, r.child_looped, dt, sub_frame)

    def close(self):
        for ch in self._children.values():
            self._rt.instance_slot_destroy(ch.slot)
            ch.sub.close()
        self._children.clear()


class SubPlayer:
    """A child animation driven by a parent Instance slot (docs/08 §1).

    Owns a child runtime plus its *own* Instance/Effect rigs, so nesting is
    fully recursive. Its frame head is advanced by the parent's
    ``ss_instance_slot_step`` (not by an internal clock); :meth:`collect`
    renders it at a given (already-stepped) frame.
    """

    def __init__(self, rt, meta, loader, lib, depth):
        self._rt = rt
        self._meta = meta
        self.instances = InstanceRig(rt, meta, loader, lib, depth)
        self.effects = EffectRig(rt, meta)

    @property
    def ctx(self):
        return self._rt.ctx

    @property
    def frame_no(self) -> float:
        return self._rt.frame_no

    def play(self):
        self._rt.play()

    def reset_slots(self):
        self.instances.reset()
        self.effects.reset()

    def collect(self, frame_no, looped, dt, sub_frame):
        """Renderables (child world space) at ``frame_no`` for this child."""
        fb = self._rt.get_frame_data(display_frame(frame_no, sub_frame))
        if not fb:
            return []
        fd = framedata.parse(fb)
        return collect_ordered(self._rt, fd, self.instances, self.effects,
                               frame_no, dt, looped, sub_frame)

    def close(self):
        self.instances.close()
        self.effects.close()
        self._rt.close()
