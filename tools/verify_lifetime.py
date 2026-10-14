#!/usr/bin/env python3
"""Headless check that a dropped ``SSInternalPlayer`` goes at once.

The host never calls ``close()``: Ren'Py drops the core on pickling and when
the displayable goes, and ``__del__`` releases the native runtime and the
Instance / Effect slot handles. That only happens promptly if nothing in the
player refers back to it. A reference cycle leaves every handle waiting for the
cyclic garbage collector -- on a rollback-heavy scene, a runtime per dropped
core. So each pack kind is played and dropped with the collector off, and the
player and its runtime must both be gone.

Usage:  python tools/verify_lifetime.py
"""

from __future__ import annotations

import gc
import os
import sys
import weakref

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402


def check(lib, rel_ssab: str, anim, kind: str) -> bool:
    abs_ssab = os.path.join(_GAME, rel_ssab)
    if not os.path.exists(abs_ssab):
        print(f"### {rel_ssab}  SKIP (not found)")
        return True
    p = SSInternalPlayer(open(abs_ssab, "rb").read(), lib=lib,
                         base_dir=os.path.dirname(rel_ssab),
                         resource_manager=RecordingResourceManager(),
                         pack_reader=filesystem_pack_reader(
                             os.path.dirname(abs_ssab)))
    name = anim or p.animation_names()[0]
    p.set_animation(name)
    p.play()
    for _ in range(10):
        p.update(1000.0 / (p.frame_rate or 30))
    player, runtime = weakref.ref(p), weakref.ref(p._rt)
    del p
    ok = player() is None and runtime() is None
    print(f"### {rel_ssab}  [{kind}]  play={name!r}  "
          f"player freed={player() is None}  runtime freed={runtime() is None}")
    if not ok:
        print("    FAIL: something in the player refers back to it, so dropping "
              "it leaves the native handles to the cyclic collector")
    print("    ->", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    lib = ssruntime.load_library()
    targets = [
        ("ss_assets/Ringo/Ringo.ssab",         "wait1",    "character"),
        ("ss_assets/overall/Instance.ssab",    None,       "instance"),
        ("ss_assets/ParticleEffect/e001.ssab", "emission", "effect"),
    ]
    print("== SSInternalPlayer lifetime verification (cyclic gc off) ==\n")
    allok = True
    gc.disable()
    try:
        for rel, anim, kind in targets:
            allok &= check(lib, rel, anim, kind)
            print()
    finally:
        gc.enable()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
