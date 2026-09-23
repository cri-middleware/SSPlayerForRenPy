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
                    parent_looped, sub_frame, part_infos=None, frame_mask=None,
                    inherited=None, parts=None, clip_out=None):
    """Z-ordered renderables for ``rt`` at the current frame.

    Returns a list of ``("mesh", MeshPart)`` / ``("fx", EffectBatch)`` in draw
    order, all in ``rt``'s world space. Normal parts come straight from the draw
    plan; Instance parts recurse and are composed by the instance part's matrix;
    Effect parts are stepped. Shared by the root player and Instance-child
    players (both ``SSInternalPlayer``, via :meth:`SSInternalPlayer.render_at`).

    Masking: the root's ``update`` supplies
    ``part_infos`` + ``frame_mask`` and each Normal/Mesh target is stamped via
    :func:`mask.attach_target`. An Instance part hands its sub-animation the
    **composed** context from :func:`mask.inherit_for` (``mask_influence``
    by AND, ``visible_inside_mask`` by OR), which arrives here as ``inherited``
    when this player *is* that sub-animation; its parts then compose their own
    settings on top. The sub-animation is therefore not judged as one opaque
    blob by the Instance part alone — a caller cannot force "inside" onto a child
    that opted out, nor the reverse. Composing on the way down (rather than
    patching the child's output afterwards) is what makes nesting chain for
    free. Children never build coverage: ``frame_mask`` stays ``None`` for them
    and they sample the root's, exactly as the spec / Godot port require.

    ``parts`` is an optional pre-decoded :func:`framedata.bulk_part_states` array
    the caller already holds for this frame.
    """
    # Materialize first: this fully drains the transient SoA buffers into copied
    # MeshParts / matrices, so the child/effect Brain calls below are safe.
    plan = list(framedata.iter_draw_plan(rt, fd, parts))
    do_mask = part_infos is not None and (frame_mask is not None
                                          or inherited is not None)
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
                mask.attach_target(mp, frame_mask, part_infos, inherited)
            out.append(("mesh", mp))
            # When an owner asked for them (``clip_out`` — only ever passed to a
            # sub-animation, never the root), record this player's clipping
            # writers so the owner can bubble them into its coverage.
            # Collected regardless of the inherited influence: a
            # mask_influence==0 instance still carries its child's writers out,
            # onto the union plane (the owner composes the OP). A pure mask closes
            # within the child, so only clipping writers (which apply to *higher*
            # ranks) carry out.
            if clip_out is not None and part_infos is not None:
                cpi = (part_infos[mp.part_index]
                       if 0 <= mp.part_index < len(part_infos) else None)
                if cpi is not None and cpi.is_clipping:
                    cps = fd.Parts(mp.part_index)
                    cmv = cps.Mask() if cps is not None else 0.0
                    if cmv:                       # mask == 0 → writes nothing
                        clip_out.append(mask.clip_writer_desc(mp, cmv))
        elif tag == "instance":
            _, p, mat, alpha, hidden = item
            stepped_inst.add(p)
            # Composed BEFORE the child is built, so the child stamps its own
            # parts with the effective context and the parent has nothing left to
            # patch afterwards.
            child_ctx = (mask.inherit_for(p, part_infos, frame_mask, inherited)
                         if do_mask else None)
            # Only the coverage owner (the root, which holds ``frame_mask``)
            # gathers a child's clipping writers to carry out;
            # deeper players carry nothing (single-stage, matching the reference
            # ports — ForGodot bdfbf02 / ForWeb 7fd8275).
            child_clip = [] if frame_mask is not None else None
            child_items = (instances.collect(
                p, parent_frame, dt, parent_looped, sub_frame, child_ctx,
                clip_out=child_clip)
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
            # Bubble the visible child's clipping writers into this coverage,
            # ranked at the instance part and transformed by its slot matrix, with
            # the OP composed against the influence handed down.
            if child_clip and frame_mask is not None and part_infos is not None:
                rank = frame_mask.rank_of.get(p)
                pin = (part_infos[p] if 0 <= p < len(part_infos) else None)
                if rank is not None and pin is not None:
                    inh_infl = mask.compose(mask.ROOT_CONTEXT, pin)[0]
                    for desc in child_clip:
                        frame_mask.add_bubbled(desc, mat, rank, inh_infl)
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
                inherited=None, clip_out=None):
        """Step one instance part and return the child's child-space renderables.

        Returns ``[]`` when the part has no resolvable child or the slot reports
        not-visible. Always steps the slot (independent children keep their own
        clock) — and, when not visible, still recurses into the child's own
        slots exactly as :meth:`step_idle` does, so a nested independent
        Effect/Instance does not freeze behind the runtime's visibility gate
        (the same freeze ``collect_ordered``'s leftover pass fixes for parts the
        Brain drops from ``draw_order``). On an ``EventInstance`` edge the child
        is (re)started so its own start events fire.

        ``inherited`` is the composed mask context for the sub-animation,
        passed straight through to the
        child's ``render_at`` so it can stamp its own parts. ``clip_out``, when
        given, is the list the child appends its own clipping-writer descriptors
        to so the caller can carry them out into its coverage.
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
                                inherited, clip_out=clip_out)

    def has_clipping_children(self) -> bool:
        """True if any instance child's sub-animation statically holds a clipping
        writer part — so its masks can carry out into this owner.
        Lets the owner decide up front whether to build a coverage at all."""
        for ch in self._children.values():
            pinfos = getattr(ch.sub, "_part_infos", None) or ()
            if any(getattr(pi, "is_clipping", False) for pi in pinfos):
                return True
        return False

    def pending_clip_ranks(self, rank_of):
        """Owner-draw-order ranks of the instance parts whose sub-animation holds
        a clipping writer, so the owner can pre-count their carry-over in the
        mask scope (``FrameMask.note_pending_clip_ranks``) before the children are
        stepped and the writers actually gathered."""
        out = []
        for pidx, ch in self._children.items():
            r = rank_of.get(pidx)
            if r is None:
                continue
            pinfos = getattr(ch.sub, "_part_infos", None) or ()
            if any(getattr(pi, "is_clipping", False) for pi in pinfos):
                out.append(r)
        return out

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
