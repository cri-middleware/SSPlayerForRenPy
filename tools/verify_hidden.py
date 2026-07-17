#!/usr/bin/env python3
"""Headless regression check: hidden independent Instance/Effect slots keep stepping.

The Brain omits ``Hide``'d Instance/Effect parts from ``draw_order`` (documented
SDK design — SpriteStudio-SDK docs 40_components/40_mask). A host that drives slot
stepping off ``draw_order`` therefore never steps a hidden part, freezing its clock;
for an *independent* part that must keep advancing while off-screen
(40_components/10_instance, 20_effect) this diverges from SS7. ``collect_ordered``
steps every slot the draw plan missed (leftover pass), so hidden independent slots
still advance.

This test drives ``overall/Instance.ssab`` (anime_1) headless and, using
``active_event_instance(part_index)`` (called once immediately before each
``ss_instance_slot_step``) as the step signal, asserts that a mid-timeline-hidden
independent part is stepped on *every* tick it is hidden — never frozen. A control
part that is never hidden pins the always-visible path.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_hidden.py
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
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402

TICKS = 130
DT_MS = 33.0
# Parts of interest in overall/Instance.ssab anime_1 (referenced by name so index
# drift in the pack doesn't break the test):
HIDDEN_INDEP = "INDEP_MID_INFINITE_HIDE"  # independent + hidden mid-timeline -> must step while hidden
HIDDEN_DEP = "MID_INFINITE_HIDE"          # dependent  + hidden mid-timeline -> our fix steps it too
CONTROL = "INDEP_ONLY"                     # independent, never hidden        -> steps every tick


def check(lib, path: str) -> bool:
    base = os.path.dirname(path)
    data = open(path, "rb").read()
    base_dir = os.path.relpath(base, _GAME).replace("\\", "/")
    p = SSInternalPlayer(data, lib=lib, base_dir=base_dir,
                         resource_manager=RecordingResourceManager(),
                         pack_reader=filesystem_pack_reader(base))
    if not p.set_animation("anime_1"):
        print("    FAIL: set_animation('anime_1')"); p.close(); return False
    if not (p._instances and p._instances.has()):
        print("    FAIL: no instance children built (loader/refs?)"); p.close(); return False

    by_name = {ip.name: ip.index for ip in p.meta.instance_parts()}
    watch = {}
    for nm in (HIDDEN_INDEP, HIDDEN_DEP, CONTROL):
        if nm not in by_name:
            print(f"    FAIL: expected instance part {nm!r} not in pack"); p.close(); return False
        watch[by_name[nm]] = nm

    p.set_loop(0)   # infinite: keep the head playing across the hide window
    p.play()

    # Instrument: record, per tick, which top-level instance slots got stepped.
    rt = p._rt
    _orig_aei = rt.active_event_instance
    state = {"tick": -1}
    stepped_at = {idx: set() for idx in watch}
    def _wrapped(part_index):
        t = state["tick"]
        if part_index in stepped_at and t >= 0:
            stepped_at[part_index].add(t)
        return _orig_aei(part_index)
    rt.active_event_instance = _wrapped

    hidden_at = {idx: set() for idx in watch}
    try:
        for t in range(TICKS):
            state["tick"] = t
            p.update(DT_MS)
            for idx, nm in watch.items():
                if p.is_part_hidden(nm):
                    hidden_at[idx].add(t)
    finally:
        rt.active_event_instance = _orig_aei
        p.close()

    ok = True
    for idx, nm in sorted(watch.items()):
        steps, hid = stepped_at[idx], hidden_at[idx]
        frozen = sorted(hid - steps)      # hidden but NOT stepped == the freeze
        indep = nm.startswith("INDEP_")
        tag = "indep" if indep else "dep "
        print(f"    [{tag}] {nm:<24} steps={len(steps):>3}/{TICKS}  "
              f"hidden={len(hid):>3}  frozen(hidden&unstepped)={len(frozen)}")
        if nm == CONTROL:
            # Never hidden and always live -> stepped every tick, exactly once.
            if len(steps) != TICKS:
                print(f"        FAIL: control expected {TICKS} steps, got {len(steps)}"); ok = False
        else:
            # Hidden mid-timeline -> must actually be hidden for a stretch, and
            # every hidden tick must still have stepped (never frozen).
            if not hid:
                print("        FAIL: expected a hidden window, part was never hidden"); ok = False
            if frozen:
                print(f"        FAIL: {len(frozen)} hidden ticks not stepped "
                      f"(clock frozen): {frozen[:8]}{'...' if len(frozen) > 8 else ''}"); ok = False
    return ok


def main(argv) -> int:
    target = argv[1] if len(argv) > 1 else os.path.join(
        _GAME, "ss_assets", "overall", "Instance.ssab")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found (run scripts/deploy-examples.* first)")
        return 0
    lib = ssruntime.load_library()
    print("== Hidden independent-slot stepping verification ==\n")
    ok = check(lib, target)
    print("\n== RESULT:", "ALL PASS" if ok else "FAILURES PRESENT", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
