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

Two more gates on the same "nothing silently freezes" invariant are pinned with
stubs rather than assets, because no demo pack reaches them (the branches are
inert for every shipped .ssab, so a pack-driven test would assert nothing):

  * the runtime's OWN visibility gate — a slot that steps but reports
    ``visible == False`` must still recurse into the child's slots;
  * the leftover pass must guard each slot separately — one wedged slot may not
    cancel its siblings' (nor the effect rig's) stepping for that frame.

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

from ss_renpy import framedata, instance, ssruntime  # noqa: E402
from ss_renpy.instance import InstanceRig, _Child, collect_ordered  # noqa: E402
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


# --------------------------------------------------------------------------
# Stub-driven gates (no pack reaches these branches; see the module docstring)
# --------------------------------------------------------------------------
class _StepResult:
    """What ``ss_instance_slot_step`` hands back."""
    def __init__(self, visible):
        self.visible = visible
        self.transitioned = False
        self.independent = True
        self.child_frame_no = 3.0
        self.child_looped = False


class _StubRT:
    def __init__(self, visible):
        self._visible = visible

    def active_event_instance(self, part_index):
        return object()

    def instance_slot_step(self, slot, ev, ctx, pf, dt, pl):
        return _StepResult(self._visible)


class _StubSub:
    """Stands in for the child SSInternalPlayer."""
    ctx = None

    def __init__(self):
        self.stepped = []
        self.rendered = []

    def play(self):
        pass

    def step_slots_only(self, frame_no, looped, dt, sub_frame=None):
        self.stepped.append(frame_no)

    def render_at(self, frame_no, looped, dt, sub_frame=None):
        self.rendered.append(frame_no)
        return []


def _rig(visible):
    """An InstanceRig around one stub child, bypassing the real constructor."""
    rig = object.__new__(InstanceRig)
    rig._rt = _StubRT(visible)
    rig._independent = set()
    sub = _StubSub()
    rig._children = {7: _Child(None, 1, sub)}
    return rig, sub


def check_invisible_recursion() -> bool:
    """A not-visible slot still recurses; a visible one renders instead."""
    print("### collect()  slot reports not-visible -> child slots still step")
    ok = True

    rig, sub = _rig(visible=False)
    out = rig.collect(7, 10.0, 0.033, False, True)
    if out != []:
        print(f"    FAIL: not-visible must draw nothing, got {out!r}"); ok = False
    if sub.stepped != [3.0]:
        print(f"    FAIL: child slots not stepped while invisible "
              f"(froze): stepped={sub.stepped!r}"); ok = False
    if sub.rendered:
        print(f"    FAIL: invisible child was rendered: {sub.rendered!r}"); ok = False

    rig, sub = _rig(visible=True)
    rig.collect(7, 10.0, 0.033, False, True)
    if sub.rendered != [3.0] or sub.stepped:
        print(f"    FAIL: visible path should render once and not step-only "
              f"(rendered={sub.rendered!r} stepped={sub.stepped!r})"); ok = False

    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


class _StubRig:
    """Instance/Effect rig whose ``boom`` slot raises when stepped."""
    def __init__(self, indices, boom=None):
        self._indices = list(indices)
        self._boom = boom
        self.stepped = []

    def part_indices(self):
        return list(self._indices)

    def step_idle(self, part_index, *args):
        if part_index == self._boom:
            raise RuntimeError("wedged slot")
        self.stepped.append(part_index)


def check_leftover_isolation() -> bool:
    """One raising slot must not cancel the rest of the leftover pass."""
    print("### collect_ordered()  leftover pass isolates a raising slot")
    instances = _StubRig([1, 2, 3], boom=2)
    effects = _StubRig([10, 11])
    orig = framedata.iter_draw_plan
    framedata.iter_draw_plan = lambda rt, fd: []      # empty plan: leftovers only
    try:
        out = collect_ordered(None, None, instances, effects,
                              0.0, 0.016, False, True)
    finally:
        framedata.iter_draw_plan = orig

    ok = True
    if out != []:
        print(f"    FAIL: empty draw plan should yield nothing, got {out!r}"); ok = False
    if instances.stepped != [1, 3]:
        print(f"    FAIL: sibling instance slots skipped after one raised: "
              f"{instances.stepped!r}, want [1, 3]"); ok = False
    if effects.stepped != [10, 11]:
        print(f"    FAIL: effect slots skipped after an instance slot raised: "
              f"{effects.stepped!r}, want [10, 11]"); ok = False
    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def main(argv) -> int:
    ok = check_invisible_recursion()
    ok = check_leftover_isolation() and ok
    print()

    target = argv[1] if len(argv) > 1 else os.path.join(
        _GAME, "ss_assets", "overall", "Instance.ssab")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found (run scripts/deploy-examples.* first)")
        return 0 if ok else 1
    lib = ssruntime.load_library()
    print("== Hidden independent-slot stepping verification ==\n")
    ok = check(lib, target) and ok
    print("\n== RESULT:", "ALL PASS" if ok else "FAILURES PRESENT", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
