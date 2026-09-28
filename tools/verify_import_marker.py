#!/usr/bin/env python3
"""Headless check for the auto-importer's output plan (no Ren'Py).

Validates that projects sharing a name get one output folder between them
(``ss_renpy.import_marker``, driven by ``auto_importer.rpy``).

Usage:  python tools/verify_import_marker.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import import_marker  # noqa: E402

_ok = True


def check(label, cond):
    global _ok
    print(f"    {'PASS' if cond else 'FAIL'}  {label}")
    _ok = _ok and bool(cond)


def main() -> int:
    print("== import output plan verification ==\n")

    print("### plan_outputs: one folder, one project")
    src, out = os.path.join("S"), os.path.join("O")
    b1 = os.path.join(src, "Enemies", "Boss_1", "Enemy.sspj")
    b2 = os.path.join(src, "Enemies", "Boss_2", "Enemy.sspj")
    cat = os.path.join(src, "CatGuardian", "Enemy.sspj")
    low = os.path.join(src, "zz", "enemy.sspj")
    ringo = os.path.join(src, "Ringo", "Ringo.sspj")
    plan = import_marker.plan_outputs([b2, ringo, low, b1, cat], out)
    owners = {p: o for p, _, o in plan}
    dirs = {p: d for p, d, _ in plan}
    check("every project is planned once", sorted(owners) == sorted([b1, b2, cat, low, ringo]))
    check("the first in path order owns the folder", owners[cat] is None)
    check("the others name that owner", owners[b1] == cat and owners[b2] == cat)
    check("a name differing only in case collides", owners[low] == cat)
    check("a distinct name converts on its own", owners[ringo] is None)
    check("the folder is <out>/<name>", dirs[ringo] == os.path.join(out, "Ringo"))
    again = import_marker.plan_outputs([cat, b1, low, ringo, b2], out)
    check("the same owner whatever the input order", again == plan)


    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
