"""Effect-part slot lifecycle for one runtime (docs/08 §2).

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
            self._slots[p.index] = rt.effect_slot_create(
                p.ref_effect_name_hash, seed=0)

    def has(self) -> bool:
        return any(self._slots.values())

    def reset(self):
        """Re-arm every slot (call when the parent replays / heads out)."""
        for slot in self._slots.values():
            if slot:
                self._rt.effect_slot_reset(slot)

    def collect(self, part_index, matrix, alpha, parent_frame, dt, parent_looped):
        """Step one Effect part's slot and return its world-space batches.

        Always steps (so independent effects keep advancing even when the
        consumer suppresses drawing); returns ``[]`` when not visible. ``matrix``
        is the effect part's world matrix, ``alpha`` its hierarchical alpha.
        """
        slot = self._slots.get(part_index)
        if not slot:
            return []
        ev = self._rt.active_effect_event(part_index)
        fps = float(self._rt.fps or 30)
        visible, buf = self._rt.effect_slot_step(
            slot, ev, parent_frame, dt, fps, parent_looped,
            y_flip=True, vert_stride=2)
        if not visible or not buf:
            return []
        return effectplan.build_effect_batches(
            buf, matrix=matrix, alpha=alpha, merge=True)

    def close(self):
        for slot in self._slots.values():
            if slot:
                self._rt.effect_slot_destroy(slot)
        self._slots.clear()
