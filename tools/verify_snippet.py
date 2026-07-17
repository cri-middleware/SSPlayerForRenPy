#!/usr/bin/env python3
"""Headless check for the asset-browser snippet generator (no Ren'Py).

Validates the role heuristic and the three snippet shapes the dev browser
(``ss_browser.rpy``) offers.

Usage:  python tools/verify_snippet.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import snippet  # noqa: E402

_ok = True


def check(label, cond):
    global _ok
    print(f"    {'PASS' if cond else 'FAIL'}  {label}")
    _ok = _ok and bool(cond)


def main() -> int:
    print("== snippet generator verification ==\n")

    print("### default_role heuristic")
    check("oneshot: has_effects + single anim", snippet.default_role(1, True) == "oneshot")
    check("character: multi anim", snippet.default_role(5, False) == "character")
    check("ui: single anim, no effects", snippet.default_role(1, False) == "ui")
    check("character beats oneshot when multi-anim", snippet.default_role(3, True) == "character")

    print("### character snippet (path-based)")
    s = snippet.build_snippet("ss_assets/Ringo/Ringo.ssab", "character", ["wait1", "joy", "walk"])
    check("image + SSPlayer(path)", 'image ringo = SSPlayer(' in s and '"ss_assets/Ringo/Ringo.ssab"' in s)
    check("aliases for each anim", '"wait1": "wait1",' in s and '"joy": "joy",' in s)
    check("Character() uses stem", 'define ringo_chr = Character("Ringo", image="ringo")' in s)

    print("### one-shot snippet (path-based)")
    s = snippet.build_snippet("ss_assets/ParticleEffect/e038.ssab", "oneshot", ["hit"])
    check("one-shot loop=1 with path",
          'SSPlayer("ss_assets/ParticleEffect/e038.ssab", animation="hit", loop=1)' in s)

    print("### ui snippet (path-based)")
    s = snippet.build_snippet("ss_assets/ui/Logo.ssab", "ui", ["anime_1"])
    check("screen + add path", 'screen logo_screen():' in s
          and 'add SSPlayer("ss_assets/ui/Logo.ssab")' in s)

    print("### robustness")
    s = snippet.build_snippet("x/Foo.ssab", "character", [])
    check("empty anims still builds", 'image foo = SSPlayer(' in s)
    s = snippet.build_snippet("x/Bar.ssab", "weird-role", ["a", "b"])
    check("unknown role falls back to character", 'image bar = SSPlayer(' in s)

    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
