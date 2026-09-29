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


def display_frame(frame_no: float, sub_frame: bool):
    """Frame to *render*: raw float when sub-frame is on, else floored.

    The playback head stays a raw float regardless — only the
    value handed to ``get_frame_data`` is floored when sub-frame is off.
    """
    return frame_no if sub_frame else float(math.floor(frame_no))


def collect_ordered(rt, fd, instances, effects, parent_frame, dt,
                    parent_looped, sub_frame, part_infos=None, tree=None,
                    inherited=None, parts=None):
    """Z-ordered renderables for ``rt`` at the current frame.

    Returns a list of ``("mesh", MeshPart)`` / ``("fx", EffectBatch)`` in draw
    order, all in ``rt``'s world space. Normal parts come straight from the draw
    plan; Instance parts recurse and are composed by the instance part's matrix;
    Effect parts are stepped. Shared by the root player and Instance-child
    players (both ``SSInternalPlayer``, via :meth:`SSInternalPlayer.render_at`).

    Masking: the root passes ``tree`` (a :class:`mask.MaskTree`), a
    sub-animation gets ``inherited`` (a :class:`mask.MaskInherit` that carries
    the same tree). Every animation takes its numbers from the tree's running
    ``seq`` in draw order, and a sub-animation's are taken in its Instance
    part's place, so the numbers order the whole tree as it is drawn. Each
    Normal/Mesh target is stamped with its number and the flags its Instance
    part handed down (:func:`mask.target_mask`). This animation's own writers
    get their interval on that sequence and go up to the caller in
    ``inherited.writers`` — mapped into the caller's space at each level — or
    straight into the root's coverage.

    ``parts`` is an optional pre-decoded :func:`framedata.bulk_part_states` array
    the caller already holds for this frame.
    """
    # Materialize first: this fully drains the transient SoA buffers into copied
    # MeshParts / matrices, so the child/effect Brain calls below are safe.
    plan = list(framedata.iter_draw_plan(rt, fd, parts))
    if inherited is not None:
        tree = inherited.tree
    do_mask = part_infos is not None and tree is not None
    if do_mask:
        if inherited is not None:
            ctx = (inherited.influence, inherited.visible_inside)
            start_seq = inherited.start_seq
            writers_out = inherited.writers
        else:
            ctx, start_seq = mask.ROOT_CONTEXT, -1.0
            writers_out = tree.frame_mask.writers
        # Read from the same SoA as the plan, before any slot below steps.
        own_writers = mask.collect_writers(rt, fd, part_infos, parts, ctx[0])
        do = framedata._draw_order_array(fd)
        rank_of = {p: r for r, p in enumerate(do)}
        seq_of = [0.0] * len(do)
        numbered = 0          # ranks below this have their seq

        def number_to(rank):
            # Number every slot up to ``rank`` that has none yet, in order. A
            # slot the plan never yields (a pure mask, a skipped kind) still
            # takes its number, so a writer there has a position too.
            nonlocal numbered
            while numbered <= rank:
                seq_of[numbered] = tree.seq
                tree.seq += 1.0
                numbered += 1
    out = []
    # Part indices whose slot the draw-plan walk below steps this frame. The
    # Brain omits Hide'd Instance/Effect parts from draw_order,
    # so those never appear here — they are stepped
    # by the leftover pass at the end so independent children keep advancing
    # while off-screen.
    stepped_inst = set()
    stepped_fx = set()
    for item in plan:
        tag = item[0]
        if tag == "mesh":
            mp = item[1]
            if do_mask:
                p = mp.part_index
                rank = rank_of.get(p)
                pinfo = part_infos[p] if 0 <= p < len(part_infos) else None
                if rank is not None and pinfo is not None:
                    number_to(rank)
                    mp.mask = mask.target_mask(tree, pinfo, ctx, seq_of[rank])
            out.append(("mesh", mp))
        elif tag == "instance":
            _, p, mat, alpha, hidden = item
            stepped_inst.add(p)
            # Handed down BEFORE the child is built, so the child stamps its own
            # parts and the parent has nothing left to patch afterwards.
            child_ctx = None
            if do_mask:
                rank = rank_of.get(p)
                pinfo = part_infos[p] if 0 <= p < len(part_infos) else None
                if rank is not None and pinfo is not None:
                    number_to(rank)
                    child_ctx = mask.child_context(tree, pinfo, seq_of[rank])
            child_items = (instances.collect(
                p, parent_frame, dt, parent_looped, sub_frame, child_ctx)
                if instances is not None else [])
            if hidden:
                continue   # stepped for timing above; just not drawn
            for ctag, payload in child_items:
                if ctag == "mesh":
                    # transform_mesh_part carries ``mask`` over; the child's
                    # geometry lands in the root's world space here, which is the
                    # space the coverage UV is derived in.
                    out.append(("mesh",
                                framedata.transform_mesh_part(payload, mat, alpha)))
                else:  # "fx"
                    out.append(("fx",
                                transform_effect_batch(payload, mat, alpha)))
            # The visible child's writers — already on their intervals — go up
            # with this animation's, placed by the Instance part's matrix. A
            # hidden child's never get here: it masks nothing.
            if child_ctx is not None:
                for w in child_ctx.writers:
                    writers_out.append(mask.transform_writer(w, mat))
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
    if do_mask:
        number_to(len(seq_of) - 1)
        # A pure mask holds its bit from the start of its own animation up to
        # itself, so it never reaches what the caller draws next; a clipping
        # writer from itself to the end of the tree, so one written in a
        # sub-animation keeps clipping the caller's later parts, at any depth.
        for w in own_writers:
            s = seq_of[w.rank]
            if w.is_clipping:
                w.open, w.close = s, mask.SEQ_END
            else:
                w.open, w.close = start_seq, s
            writers_out.append(w)
    # Leftover pass: step every Instance/Effect slot the Brain dropped from
    # draw_order (Hide'd parts), so independent children keep their own clock
    # advancing instead of freezing. Stepping is driven from the full slot set,
    # not draw_order — matching the Unity/Web ports.
    # draw_order/visibility gate
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


def build_subplayer(owner, part):
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

    child = owner.make_child(child_data)
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
    own rigs, so nesting is fully recursive."""

    def __init__(self, owner):
        self._rt = owner._rt
        self._children = {}   # part_index -> _Child
        # part indices whose slot most recently stepped as independent. Fed from
        # each step's result (no extra FFI, and the flag only changes on an
        # EventInstance edge), so the per-frame redraw gate reads it for free.
        self._independent = set()
        for p in owner._meta.instance_parts():
            sub = build_subplayer(owner, p)
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

    def collect(self, part_index, parent_frame, dt, parent_looped, sub_frame,
                inherited=None):
        """Step one instance part and return the child's child-space renderables.

        Returns ``[]`` when the part has no resolvable child or the slot reports
        not-visible. Always steps the slot (independent children keep their own
        clock) — and, when not visible, still recurses into the child's own
        slots exactly as :meth:`step_idle` does, so a nested independent
        Effect/Instance does not freeze behind the runtime's visibility gate
        (the same freeze ``collect_ordered``'s leftover pass fixes for parts the
        Brain drops from ``draw_order``). On an ``EventInstance`` edge the child
        is (re)started so its own start events fire.

        ``inherited`` is the :class:`mask.MaskInherit` the Instance part hands
        the sub-animation, passed straight through to the child's ``render_at``
        so it can number and stamp its own parts and hand its writers back.
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
        return ch.sub.render_at(r.child_frame_no, r.child_looped, dt, sub_frame,
                                inherited)

    def mask_uses(self):
        """``(writes, draws_inside)`` over every sub-animation below, recursively
        — whether any of them holds a writer part, or a part that draws inside a
        mask. Pack-static; the owner folds it into its own once per build."""
        writes = inside = False
        for ch in self._children.values():
            w, i = ch.sub.mask_uses()
            writes = writes or w
            inside = inside or i
        return writes, inside

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
        advancing while off-screen),
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
