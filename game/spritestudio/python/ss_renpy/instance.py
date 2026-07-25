"""Instance-part child playback, recursive.

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

from ss_renpy import framedata, mask
from ss_renpy.effectplan import transform_effect_batch

# Hard cap on instance nesting (defends against pathological / cyclic refs).
MAX_DEPTH = 8


def display_frame(frame_no: float, sub_frame: bool):
    """Frame to *render*: raw float when sub-frame is on, else floored.

    The playback head stays a raw float regardless — only the
    value handed to ``get_frame_data`` is floored when sub-frame is off.
    """
    return frame_no if sub_frame else float(math.floor(frame_no))


def collect_ordered(rt, fd, instances, effects, parent_frame, dt,
                    parent_looped, sub_frame, part_infos=None, frame_mask=None):
    """Z-ordered renderables for ``rt`` at the current frame.

    Returns a list of ``("mesh", MeshPart)`` / ``("fx", EffectBatch)`` in draw
    order, all in ``rt``'s world space. Normal parts come straight from the draw
    plan; Instance parts recurse and are composed by the instance part's matrix;
    Effect parts are stepped. Shared by the root player and Instance-child
    players (both ``SSInternalPlayer``, via :meth:`SSInternalPlayer.render_at`).

    Masking (SDK doc: 40_components/40_mask.md): when ``part_infos`` +
    ``frame_mask`` are supplied (the root's ``update``), each Normal/Mesh target
    is stamped via :func:`mask.attach_target`, and a masked **instance** part
    propagates its coverage to the *whole* sub-animation via
    :func:`mask.attach_inherited` (single-stage). Instance children are seeked
    through ``render_at``
    *without* these args, so they never build/attach their own coverage — they
    only inherit, exactly as the spec / Godot port require.
    """
    # Materialize first: this fully drains the transient SoA buffers into copied
    # MeshParts / matrices, so the child/effect Brain calls below are safe.
    plan = list(framedata.iter_draw_plan(rt, fd))
    do_mask = frame_mask is not None and part_infos is not None
    out = []
    # Part indices whose slot the draw-plan walk below steps this frame. The
    # Brain omits Hide'd Instance/Effect parts from draw_order (SDK doc:
    # 40_components/40_mask.ja.md), so those never appear here — they are stepped
    # by the leftover pass at the end so independent children keep advancing
    # while off-screen (40_components/10_instance.ja.md / 20_effect.ja.md).
    stepped_inst = set()
    stepped_fx = set()
    for item in plan:
        tag = item[0]
        if tag == "mesh":
            mp = item[1]
            if do_mask:
                mask.attach_target(mp, frame_mask, part_infos)
            out.append(("mesh", mp))
        elif tag == "instance":
            _, p, mat, alpha, hidden = item
            stepped_inst.add(p)
            child_items = (instances.collect(
                p, parent_frame, dt, parent_looped, sub_frame)
                if instances is not None else [])
            if hidden:
                continue   # stepped for timing above; just not drawn
            inst_info = (part_infos[p] if do_mask and 0 <= p < len(part_infos)
                         else None)
            inst_rank = frame_mask.rank_of.get(p) if do_mask else None
            for ctag, payload in child_items:
                if ctag == "mesh":
                    tmp = framedata.transform_mesh_part(payload, mat, alpha)
                    if do_mask and inst_rank is not None:
                        mask.attach_inherited(tmp, frame_mask, inst_info, inst_rank)
                    out.append(("mesh", tmp))
                else:  # "fx"
                    out.append(("fx",
                                transform_effect_batch(payload, mat, alpha)))
        elif tag == "effect":
            _, p, mat, alpha, hidden = item
            stepped_fx.add(p)
            batches = (effects.collect(p, mat, alpha, parent_frame, dt, parent_looped)
                       if effects is not None else [])
            if hidden:
                continue
            for eb in batches:
                out.append(("fx", eb))
        # "skip": unsupported kind (Text / Nines / Mask) — ignored
    # Leftover pass: step every Instance/Effect slot the Brain dropped from
    # draw_order (Hide'd parts), so independent children keep their own clock
    # advancing instead of freezing. Stepping is driven from the full slot set,
    # not draw_order — matching the Unity/Web ports and the SDK porting contract
    # (40_components/{10_instance,20_effect}.ja.md). draw_order/visibility gate
    # *drawing* only. Each slot is stepped exactly once per frame (the walk above
    # already stepped the parts present in the plan). Guarded PER SLOT so a
    # stepping failure never discards the frame already built in ``out`` — and
    # never cancels the remaining slots either: one wedged child (e.g. a torn-down
    # ctx) would otherwise freeze every other hidden clock, every frame, forever.
    if instances is not None:
        for pi in instances.part_indices():
            if pi not in stepped_inst:
                try:
                    instances.step_idle(pi, parent_frame, dt, parent_looped,
                                        sub_frame)
                except Exception:
                    pass
    if effects is not None:
        for pi in effects.part_indices():
            if pi not in stepped_fx:
                try:
                    effects.step_idle(pi, parent_frame, dt, parent_looped)
                except Exception:
                    pass
    return out


def build_subplayer(owner, part, depth):
    """Resolve one Instance ``part``'s pack + animation, then have ``owner`` build
    a parent-driven child player for it.

    The referenced pack is *internal* (same ``.ssab``, another animation) or
    *external* (``owner._loader(pack_name)`` per ``external_instances``, which also
    merges that pack's textures into the shared map). Construction of the child
    (shared lib / rm / loader / texmap / base_dir) is delegated to
    :meth:`SSInternalPlayer.make_child`, keeping the owner's construction
    details out of this module. Returns ``None`` (caller skips the slot)
    when the pack/animation can't resolve.
    """
    if depth > MAX_DEPTH:
        return None
    ref_pack = part.ref_anime_pack
    ref_anim = part.ref_anime_name
    if not ref_anim:
        return None

    if ref_pack and ref_pack != owner._meta.name and owner._loader is not None:
        child_data = owner._loader(ref_pack)     # external pack (merges textures)
    else:
        child_data = owner._meta.data            # internal (same pack, other anim)
    if not child_data:
        return None

    child = owner.make_child(child_data, depth)
    if child is None:
        return None
    if not child.set_animation(ref_anim):
        child.close()
        return None
    return child


class _Child:
    __slots__ = ("part", "slot", "sub")

    def __init__(self, part, slot, sub):
        self.part = part
        self.slot = slot
        self.sub = sub


class InstanceRig:
    """One InstanceSlot + a parent-driven child :class:`SSInternalPlayer` per
    Instance part of ``owner`` (the owning player). Recurses via the children's
    own rigs, so nesting is fully recursive (capped at ``MAX_DEPTH``)."""

    def __init__(self, owner, depth=0):
        self._rt = owner._rt
        self._children = {}   # part_index -> _Child
        # part indices whose slot most recently stepped as independent. Fed from
        # each step's result (no extra FFI, and the flag only changes on an
        # EventInstance edge), so the per-frame redraw gate reads it for free.
        self._independent = set()
        if depth > MAX_DEPTH:
            return
        for p in owner._meta.instance_parts():
            sub = build_subplayer(owner, p, depth + 1)
            if sub is None:
                continue
            slot = self._rt.instance_slot_create()
            if not slot:
                sub.close()
                continue
            self._children[p.index] = _Child(p, slot, sub)

    def has(self) -> bool:
        return bool(self._children)

    def has_independent(self) -> bool:
        """Whether anything here still moves once the parent's head stops: a
        slot running on its own clock, or a dependent child that itself hosts an
        independent effect/instance. Liveness for the host's redraw gate."""
        if self._independent:
            return True
        # A dependent (parent-synced) child can still contain an independent
        # descendant that must keep animating while this parent is stopped.
        return any(ch.sub._has_independent_rigs()
                   for ch in self._children.values())

    def reset(self):
        """Re-arm slots and recurse (call when the parent replays / heads out)."""
        self._independent.clear()
        for ch in self._children.values():
            self._rt.instance_slot_reset(ch.slot)
            ch.sub.reset_slots()

    def collect(self, part_index, parent_frame, dt, parent_looped, sub_frame):
        """Step one instance part and return the child's child-space renderables.

        Returns ``[]`` when the part has no resolvable child or the slot reports
        not-visible. Always steps the slot (independent children keep their own
        clock) — and, when not visible, still recurses into the child's own
        slots exactly as :meth:`step_idle` does, so a nested independent
        Effect/Instance does not freeze behind the runtime's visibility gate
        (the same freeze ``collect_ordered``'s leftover pass fixes for parts the
        Brain drops from ``draw_order``). On an ``EventInstance`` edge the child
        is (re)started so its own start events fire.
        """
        ch = self._children.get(part_index)
        if ch is None:
            return []
        ev = self._rt.active_event_instance(part_index)
        r = self._rt.instance_slot_step(
            ch.slot, ev, ch.sub.ctx, parent_frame, dt, parent_looped)
        # Cache independence off the step result (the gate then needs no FFI).
        if r.independent:
            self._independent.add(part_index)
        else:
            self._independent.discard(part_index)
        if r.transitioned:
            ch.sub.play()
        if not r.visible:
            # Not drawn this frame, but the child's own Instance/Effect slots
            # must still advance (see the docstring); render_at would build
            # renderables nobody uses, so step only.
            ch.sub.step_slots_only(r.child_frame_no, r.child_looped, dt,
                                   sub_frame)
            return []
        return ch.sub.render_at(r.child_frame_no, r.child_looped, dt, sub_frame)

    def part_indices(self):
        """Part indices of every Instance slot this rig owns — the full set to
        step each frame, independent of ``draw_order`` (which omits Hide'd parts).
        """
        return self._children.keys()

    def step_idle(self, part_index, parent_frame, dt, parent_looped, sub_frame):
        """Advance one Instance slot's clock without drawing it.

        For a part the Brain dropped from ``draw_order`` while hidden, which
        :func:`collect_ordered`'s draw-plan walk therefore never reaches. Steps
        the slot exactly as :meth:`collect` does (independent children must keep
        advancing while off-screen — SDK doc 40_components/10_instance.ja.md),
        caches independence for the redraw gate, then recurses into the child so
        its own Instance/Effect slots keep advancing too — but builds no
        renderables."""
        ch = self._children.get(part_index)
        if ch is None:
            return
        ev = self._rt.active_event_instance(part_index)
        r = self._rt.instance_slot_step(
            ch.slot, ev, ch.sub.ctx, parent_frame, dt, parent_looped)
        if r.independent:
            self._independent.add(part_index)
        else:
            self._independent.discard(part_index)
        if r.transitioned:
            ch.sub.play()
        ch.sub.step_slots_only(r.child_frame_no, r.child_looped, dt, sub_frame)

    def close(self):
        for ch in self._children.values():
            self._rt.instance_slot_destroy(ch.slot)
            ch.sub.close()
        self._children.clear()
