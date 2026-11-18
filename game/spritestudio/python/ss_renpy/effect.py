"""Effect-part slot lifecycle for one runtime.

Stateful companion to :mod:`ss_renpy.effectplan` (which is the pure decoder).
An :class:`EffectRig` owns one ``EffectSlot`` per Effect part of a runtime's
selected pack, steps each slot per frame against the part's active
``EventEffect``, and returns the decoded, world-space particle batches.

Engine-independent (no ``renpy`` import): the headless ``verify_effect`` tool
exercises the same path the Ren'Py displayable uses.
"""

from __future__ import annotations

from ss_renpy import effectplan


class EffectRig:
    """One Effect slot per Effect part of ``rt``'s current pack."""

    def __init__(self, rt, meta):
        self._rt = rt
        self._slots = {}   # part_index -> slot handle (or None on create failure)
        for p in meta.effect_parts():
            # One seed per part, or parts on one effect would throw the same
            # particles in the same places.
            self._slots[p.index] = rt.effect_slot_create(
                p.ref_effect_name_hash,
                seed=(p.index ^ p.ref_effect_name_hash) & 0xFFFFFFFF)

    def has(self) -> bool:
        return any(self._slots.values())

    def has_independent(self) -> bool:
        """Any slot running on its own clock — the only kind that still moves
        once the parent's head stops (liveness for the host's redraw gate).

        Only ever reached from :meth:`SSInternalPlayer.is_animating` after the
        head has stopped (playback short-circuits before it), so the per-slot
        query is off the normal render hot path. The runtime call is guarded so
        a failed query degrades to 'keep redrawing' rather than freezing a live
        effect."""
        try:
            return any(self._rt.effect_slot_is_independent(slot)
                       for slot in self._slots.values() if slot)
        except Exception:
            return self.has()   # conservative: keep redrawing

    def reset(self):
        """Re-arm every slot (call when the parent replays / heads out)."""
        for slot in self._slots.values():
            if slot:
                self._rt.effect_slot_reset(slot)

    def collect(self, part_index, matrix, alpha, parent_frame, dt, parent_looped):
        """Step one Effect part's slot and return its world-space batches.

        For a part in this frame's ``draw_order``: the step moves the effect's
        clock and builds its draw plan (``draw=True``), decoded here; returns
        ``[]`` when not visible. ``matrix`` is the effect part's world matrix,
        ``alpha`` its hierarchical alpha.
        """
        slot = self._slots.get(part_index)
        if not slot:
            return []
        ev = self._rt.active_effect_event(part_index)
        fps = float(self._rt.frame_rate or 30)
        # Zero-copy: the plan view is drained by build_effect_batches in one
        # pass (no retention), so we skip the per-frame copy on this hot path.
        visible, buf = self._rt.effect_slot_step_view(
            slot, ev, parent_frame, dt, fps, parent_looped,
            y_flip=True, vert_stride=2, draw=True)
        if not visible or not buf:
            return []
        return effectplan.build_effect_batches(
            buf, matrix=matrix, alpha=alpha, merge=True)

    def part_indices(self):
        """Part indices of every Effect slot this rig owns — the full set to step
        each frame, independent of ``draw_order`` (which omits Hide'd parts)."""
        return self._slots.keys()

    def step_idle(self, part_index, parent_frame, dt, parent_looped):
        """Advance one Effect slot's clock without drawing it.

        For a part the Brain dropped from ``draw_order`` while hidden, which
        :meth:`collect` therefore never reaches. Independent effects must keep
        simulating while off-screen, so the slot still steps every frame, with
        ``draw=False``: the Brain moves only the effect's clock and transitions
        and builds no plan, and the next :meth:`collect` gets the plan the
        effect would have had if it had drawn all along."""
        slot = self._slots.get(part_index)
        if not slot:
            return
        ev = self._rt.active_effect_event(part_index)
        fps = float(self._rt.frame_rate or 30)
        self._rt.effect_slot_step_view(
            slot, ev, parent_frame, dt, fps, parent_looped,
            y_flip=True, vert_stride=2, draw=False)

    def close(self):
        for slot in self._slots.values():
            if slot:
                self._rt.effect_slot_destroy(slot)
        self._slots.clear()
