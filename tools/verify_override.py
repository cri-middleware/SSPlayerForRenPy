#!/usr/bin/env python3
"""Headless check for the per-part Override Layer (colour / cell / visibility).

Exercises the engine-independent half of the feature with NO Ren'Py: the
``SSInternalPlayer.*_part_*_override`` API over the Brain's
``ss_runtime_*_override`` C-API. An override is applied by the Brain on the
*resolved* pose, so it wins over both the keyframe and any blend.

Validates:
  * ``_pack_rgba`` accepts the documented colour forms and clamps;
  * **visibility** force-hides a part, and ``cascade`` reaches its descendants
    while a plain force-hide does not;
  * **colour** repoints a Normal part's PartColor (blend mode + corner colours),
    and is ignored — without failing — on a non-Normal part;
  * **cell** repoints a Normal part's sampled cell (src_rect / UVs move);
  * **priority mode** lifecycle: ``Permanent`` survives a new animation,
    ``HoldUntilNextAnimation`` does not;
  * rejections return False (unknown part, blend_op >= 4, priority >= 3,
    unresolvable cell) rather than raising;
  * ``clear_*`` reverts to the animation and ``clear_all_part_overrides`` wipes
    the table;
  * the cell-override discovery helpers (``cellmap_names`` / ``cell_names``).

Usage:  python tools/verify_override.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime  # noqa: E402
from ss_renpy.player import SSInternalPlayer, _pack_rgba  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402

_RINGO = "ss_assets/Ringo/Ringo.ssab"

# Parts of the Ringo demo pack used below (index/type are stable within a pack):
#   apple_base (Null)  -> apple (Normal) -> heta (Normal)
# a three-deep chain of ONE Null and two Normal parts, which gives us both a
# colour/cell target and a clean cascade to observe.
_PARENT = "apple_base"
_NORMAL = "apple"
_CHILD = "heta"
_MESH = "head"          # a Mesh part: colour override must no-op on it


def _player():
    """A fresh core on the Ringo pack, or None when the demo assets are absent."""
    abs_ssab = os.path.join(_GAME, _RINGO)
    if not os.path.exists(abs_ssab):
        return None
    data = open(abs_ssab, "rb").read()
    return SSInternalPlayer(
        data, lib=_LIB, base_dir="ss_assets/Ringo",
        resource_manager=RecordingResourceManager(),
        pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))


def _step(p, n=1):
    """Advance ``n`` frames and return the last FramePlan."""
    dt_ms = 1000.0 / (p.frame_rate or 30)
    plan = None
    for _ in range(n):
        plan = p.update(dt_ms)
    return plan


def _mesh(plan, part_index):
    """The MeshPart drawn for ``part_index`` this frame, or None."""
    for kind, item in plan.items:
        if kind == "mesh" and getattr(item, "part_index", -1) == part_index:
            return item
    return None


def _hidden(plan, part_index) -> bool:
    """Whether the part did not draw this frame (hidden or simply absent)."""
    if plan.hidden_parts is not None and part_index in plan.hidden_parts:
        return True
    return _mesh(plan, part_index) is None


def check_pack_rgba() -> bool:
    print("### _pack_rgba  colour forms + clamping")
    cases = [
        (0xFF0000FF, 0xFF0000FF, "packed int passthrough"),
        ((255, 0, 0), 0xFF0000FF, "(r, g, b) -> opaque"),
        ((255, 0, 0, 128), 0xFF000080, "(r, g, b, a)"),
        ((300, -20, 0, 255), 0xFF0000FF, "clamped, not rescaled"),
    ]
    ok = True
    for value, want, why in cases:
        got = _pack_rgba(value)
        if got != want:
            print(f"    FAIL: {why}: {value!r} -> 0x{got:08X}, want 0x{want:08X}")
            ok = False
    # "#f00" / "#ff0000ff" are the trap: 4 and 9 chars, so the short forms slip
    # through a bare length gate and die on int(round("#")) with a TypeError,
    # breaking the documented ValueError contract. Colour STRINGS belong to the
    # host layer (Ren'Py's Color()), never to this core.
    for bad in ("#ff0000", "#f00", "#ff0000ff", "red", b"\xff\x00\x00",
                (1, 2), None):
        try:
            _pack_rgba(bad)
        except ValueError:
            continue
        except Exception as e:
            print(f"    FAIL: {bad!r} raised {e!r}, want ValueError"); ok = False
            continue
        print(f"    FAIL: {bad!r} was accepted, want ValueError"); ok = False
    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def check_visibility() -> bool:
    print("### visibility  force-hide / cascade / clear")
    p = _player()
    if p is None:
        print("    SKIP (Ringo not found)"); return True
    ok = True
    try:
        p.set_animation("wait1")
        p.play()
        i_parent = p.find_part_index(_PARENT)
        i_normal = p.find_part_index(_NORMAL)
        i_child = p.find_part_index(_CHILD)

        # Baseline: the chain draws.
        base = _step(p, 2)
        for name, idx in ((_NORMAL, i_normal), (_CHILD, i_child)):
            if _hidden(base, idx):
                print(f"    SKIP: {name!r} does not draw in 'wait1' — "
                      "cannot observe visibility here")
                return True

        # Force-hide the Normal part alone: its child keeps drawing.
        if not p.set_part_visibility_override(_NORMAL, True):
            print("    FAIL: set_part_visibility_override returned False"); ok = False
        plan = _step(p, 2)
        if not _hidden(plan, i_normal):
            print(f"    FAIL: {_NORMAL!r} still drew after force-hide"); ok = False
        if _hidden(plan, i_child):
            print(f"    FAIL: {_CHILD!r} was hidden without cascade"); ok = False

        # Clearing reverts to the animation.
        if not p.clear_part_visibility_override(_NORMAL):
            print("    FAIL: clear_part_visibility_override returned False"); ok = False
        plan = _step(p, 2)
        if _hidden(plan, i_normal):
            print(f"    FAIL: {_NORMAL!r} stayed hidden after clear"); ok = False

        # Cascade from the parent reaches both descendants.
        if not p.set_part_visibility_override(_PARENT, True, cascade=True):
            print("    FAIL: cascade set returned False"); ok = False
        plan = _step(p, 2)
        for name, idx in ((_NORMAL, i_normal), (_CHILD, i_child)):
            if not _hidden(plan, idx):
                print(f"    FAIL: {name!r} drew despite an ancestor cascade"); ok = False
        p.clear_all_part_overrides()
        plan = _step(p, 2)
        if _hidden(plan, i_normal):
            print("    FAIL: clear_all_part_overrides did not revert visibility"); ok = False

        # A part index the pack does not have is rejected, not raised.
        if p.set_part_visibility_override("no_such_part", True):
            print("    FAIL: unknown part name was accepted"); ok = False
        if p.set_part_visibility_override(9999, True):
            print("    FAIL: out-of-range part index was accepted"); ok = False
        print(f"    parent={i_parent} normal={i_normal} child={i_child}  "
              f"-> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def check_color() -> bool:
    print("### colour  blend mode + corners, Normal-only, clear")
    p = _player()
    if p is None:
        print("    SKIP (Ringo not found)"); return True
    ok = True
    try:
        p.set_animation("wait1")
        p.play()
        idx = p.find_part_index(_NORMAL)
        base = _step(p, 2)
        if _mesh(base, idx) is None:
            print(f"    SKIP: {_NORMAL!r} does not draw in 'wait1'"); return True

        # Opaque red, multiply. The Brain pre-multiplies alpha itself, so the
        # corner colours land in the plan as the shader's PartColor inputs.
        if not p.set_part_color_override(_NORMAL, (255, 0, 0),
                                         blend_op=ssruntime.BLEND_MUL):
            print("    FAIL: set_part_color_override returned False"); ok = False
        mp = _mesh(_step(p, 2), idx)
        if mp is None:
            print(f"    FAIL: {_NORMAL!r} stopped drawing after a colour override")
            return False
        if mp.color_blend != ssruntime.BLEND_MUL:
            print(f"    FAIL: color_blend is {mp.color_blend}, want "
                  f"{ssruntime.BLEND_MUL} (Mul)"); ok = False
        if not mp.has_partcolor:
            print("    FAIL: has_partcolor is False after a colour override"); ok = False
        # Red channel dominant, green/blue gone, on every corner.
        for n, (r, g, b, a) in enumerate(mp.colors):
            if not (r > 0.9 and g < 0.1 and b < 0.1):
                print(f"    FAIL: corner {n} is {(r, g, b, a)}, want red"); ok = False
                break

        # Four distinct corners, in lt, rt, lb, rb order.
        if not p.set_part_color_override_corners(
                _NORMAL, [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)],
                blend_op=ssruntime.BLEND_MIX):
            print("    FAIL: set_part_color_override_corners returned False"); ok = False
        mp = _mesh(_step(p, 2), idx)
        if mp is not None and len(mp.colors) >= 4:
            lt, rt, lb = mp.colors[0], mp.colors[1], mp.colors[2]
            if not (lt[0] > 0.9 and rt[1] > 0.9 and lb[2] > 0.9):
                print(f"    FAIL: corners not lt/rt/lb = R/G/B: "
                      f"{lt}, {rt}, {lb}"); ok = False
        if p.set_part_color_override_corners(_NORMAL, [(255, 0, 0)] * 3):
            print("    FAIL: a 3-corner list was accepted"); ok = False

        # Clearing reverts to the animation's own colour treatment.
        if not p.clear_part_color_override(_NORMAL):
            print("    FAIL: clear_part_color_override returned False"); ok = False
        mp = _mesh(_step(p, 2), idx)
        if mp is not None and mp.has_partcolor and mp.colors[0][1] < 0.1:
            print("    FAIL: colour override survived clear"); ok = False

        # Rejections: blend_op and priority are range-checked by the Brain.
        if p.set_part_color_override(_NORMAL, (255, 0, 0), blend_op=4):
            print("    FAIL: blend_op=4 was accepted"); ok = False
        if p.set_part_color_override(_NORMAL, (255, 0, 0), priority=3):
            print("    FAIL: priority=3 was accepted"); ok = False
        if p.set_part_color_override("no_such_part", (255, 0, 0)):
            print("    FAIL: unknown part name was accepted"); ok = False

        # A Mesh part is not Normal: SS6 restricts PartsColorChange to NORMAL,
        # so the call succeeds and the Brain simply does not apply it.
        i_mesh = p.find_part_index(_MESH)
        before = _mesh(_step(p, 2), i_mesh)
        if not p.set_part_color_override(_MESH, (255, 0, 0),
                                         blend_op=ssruntime.BLEND_MUL):
            print(f"    FAIL: colour override on {_MESH!r} (Mesh) returned False")
            ok = False
        after = _mesh(_step(p, 2), i_mesh)
        if before is not None and after is not None and \
                before.color_blend != after.color_blend:
            print(f"    FAIL: colour override applied to {_MESH!r} (not Normal)")
            ok = False
        print(f"    part={_NORMAL!r}({idx})  -> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def check_cell() -> bool:
    print("### cell  repoint a part's cell, discovery helpers, clear")
    p = _player()
    if p is None:
        print("    SKIP (Ringo not found)"); return True
    ok = True
    try:
        p.set_animation("wait1")
        p.play()
        idx = p.find_part_index(_NORMAL)

        maps = p.cellmap_names()
        if not maps:
            print("    FAIL: cellmap_names() is empty"); return False
        cells = p.cell_names(maps[0])
        if not cells:
            print(f"    FAIL: cell_names({maps[0]!r}) is empty"); return False
        if p.cell_names("no_such_cellmap"):
            print("    FAIL: cell_names() invented cells for an unknown map"); ok = False

        base = _mesh(_step(p, 2), idx)
        if base is None:
            print(f"    SKIP: {_NORMAL!r} does not draw in 'wait1'"); return True

        # Pick any cell whose atlas rect differs from the one being drawn, so
        # the swap is observable in the plan.
        target = next((c for c in cells if c != _NORMAL), None)
        if target is None:
            print("    SKIP: no alternative cell to swap to"); return True
        if not p.set_part_cell_override(_NORMAL, maps[0], target):
            print(f"    FAIL: set_part_cell_override(.., {maps[0]!r}, {target!r}) "
                  "returned False"); ok = False
        swapped = _mesh(_step(p, 2), idx)
        if swapped is None:
            print(f"    FAIL: {_NORMAL!r} stopped drawing after a cell override")
            return False
        if swapped.src_rect == base.src_rect:
            print(f"    FAIL: src_rect unchanged after swapping to {target!r} "
                  f"({base.src_rect})"); ok = False

        if not p.clear_part_cell_override(_NORMAL):
            print("    FAIL: clear_part_cell_override returned False"); ok = False
        reverted = _mesh(_step(p, 2), idx)
        if reverted is not None and reverted.src_rect != base.src_rect:
            print(f"    FAIL: cell override survived clear "
                  f"({reverted.src_rect} != {base.src_rect})"); ok = False

        # An unresolvable cell is rejected at set time (resolved eagerly).
        if p.set_part_cell_override(_NORMAL, maps[0], "no_such_cell"):
            print("    FAIL: unknown cell name was accepted"); ok = False
        if p.set_part_cell_override(_NORMAL, "no_such_cellmap", target):
            print("    FAIL: unknown cellmap name was accepted"); ok = False
        # Empty names are the "follow the animation" sentinel, i.e. a clear.
        if not p.set_part_cell_override(_NORMAL, "", ""):
            print("    FAIL: the empty-name sentinel was rejected"); ok = False
        print(f"    cellmap={maps[0]!r} cells={len(cells)} swap->{target!r}  "
              f"-> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def check_priority_lifecycle() -> bool:
    print("### priority  Permanent survives a new animation, Hold does not")
    p = _player()
    if p is None:
        print("    SKIP (Ringo not found)"); return True
    ok = True
    try:
        idx = p.find_part_index(_NORMAL)

        def tinted_after_switch(priority):
            """Set a red Mul override, switch animation, report if it survived."""
            p.set_animation("wait1")
            p.play()
            _step(p, 2)
            p.set_part_color_override(_NORMAL, (255, 0, 0),
                                      blend_op=ssruntime.BLEND_MUL,
                                      priority=priority)
            here = _mesh(_step(p, 2), idx)
            p.set_animation("wait2")
            p.play()
            there = _mesh(_step(p, 2), idx)
            p.clear_all_part_overrides()
            return here, there

        def is_red(mp):
            return (mp is not None and mp.has_partcolor
                    and mp.color_blend == ssruntime.BLEND_MUL
                    and mp.colors[0][0] > 0.9 and mp.colors[0][1] < 0.1)

        here, there = tinted_after_switch(ssruntime.PRIORITY_PERMANENT)
        if here is None or there is None:
            print("    SKIP: part does not draw in both animations"); return True
        if not is_red(here):
            print("    FAIL: Permanent override did not apply at all"); ok = False
        if not is_red(there):
            print("    FAIL: Permanent override was dropped by the new animation")
            ok = False

        here, there = tinted_after_switch(ssruntime.PRIORITY_HOLD_UNTIL_NEXT_ANIMATION)
        if not is_red(here):
            print("    FAIL: Hold override did not apply at all"); ok = False
        if is_red(there):
            print("    FAIL: Hold override survived the new animation"); ok = False

        # Visibility takes no priority mode and is always dropped on a switch.
        p.set_animation("wait1")
        p.play()
        _step(p, 2)
        p.set_part_visibility_override(_NORMAL, True)
        if not _hidden(_step(p, 2), idx):
            print("    FAIL: visibility override did not apply"); ok = False
        p.set_animation("wait2")
        p.play()
        if _hidden(_step(p, 2), idx):
            print("    FAIL: visibility override survived the new animation"); ok = False
        print(f"    -> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def main() -> int:
    global _LIB
    _LIB = ssruntime.load_library()
    print("== Override Layer (per-part colour / cell / visibility) verification ==\n")
    allok = True
    for fn in (check_pack_rgba, check_visibility, check_color, check_cell,
               check_priority_lifecycle):
        allok &= fn()
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
