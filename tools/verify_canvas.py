#!/usr/bin/env python3
"""Headless check for `SsabMeta.canvas_rect` — the box `SSPlayer` lays out by.

Without a `size`, the displayable reports the authored canvas as its size and
puts the animation's origin where the pivot says, so a wrong sign here moves
every sprite by half its canvas. The fixtures pin each case the pivot can take:
centred, on the bottom edge (Ringo, standing on the ground) and on the left edge
(e003), plus an animation authored on a wider canvas than its siblings.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_canvas.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy.ssab_meta import SsabMeta  # noqa: E402

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    print(f"    {'PASS' if good else 'FAIL'}  {label}: {got!r}"
          + ("" if good else f" (want {want!r})"))
    _ok = _ok and good


def load(rel):
    path = os.path.join(_GAME, "ss_assets", rel)
    if not os.path.exists(path):
        print(f"SKIP: {path} not found (run scripts/deploy-examples.* first)")
        return None
    with open(path, "rb") as f:
        return SsabMeta(f.read())


def main() -> int:
    print("== canvas_rect verification ==\n")
    ringo = load("Ringo/Ringo.ssab")
    hit = load("ParticleEffect/e038.ssab")
    burner = load("ParticleEffect/e003.ssab")
    if ringo is None or hit is None or burner is None:
        return 0

    print("### pivot on the bottom edge (Ringo, 800x600, pivot (0, -0.5))")
    check("no name is the first animation", ringo.canvas_rect(),
          (-400.0, -600.0, 800.0, 600.0))
    check("the box lies entirely above the origin", ringo.canvas_rect("wait1"),
          (-400.0, -600.0, 800.0, 600.0))
    check("a wider canvas keeps the origin centred", ringo.canvas_rect("dead"),
          (-650.0, -600.0, 1300.0, 600.0))

    print("### pivot at the centre (e038, 640x640)")
    check("origin at the centre", hit.canvas_rect("hit"),
          (-320.0, -320.0, 640.0, 640.0))

    print("### pivot on the left edge (e003, 640x640, pivot (-0.5, 0))")
    check("the box lies entirely right of the origin", burner.canvas_rect(),
          (0.0, -320.0, 640.0, 640.0))

    print("### unknown name")
    check("None, not the first animation's box", ringo.canvas_rect("no-such-anim"),
          None)

    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
