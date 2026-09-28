#!/usr/bin/env python3
"""Headless check for the auto-importer's output plan and freshness marker (no Ren'Py).

Validates that projects sharing a name get one output folder between them, and
that the marker skips reconversion only when the .sspj, its sources and the
converter are all what they were at the last successful conversion
(``ss_renpy.import_marker``, driven by ``auto_importer.rpy``).

Usage:  python tools/verify_import_marker.py
"""

from __future__ import annotations

import os
import sys
import tempfile

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


def _touch(path, mtime):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("x")
    os.utime(path, (mtime, mtime))


def main() -> int:
    print("== import marker verification ==\n")

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

    with tempfile.TemporaryDirectory() as tmp:
        proj = os.path.join(tmp, "Ringo")
        sspj = os.path.join(proj, "Ringo.sspj")
        cell = os.path.join(proj, "Ringo.png")
        _touch(sspj, 1_000_000.25)
        _touch(cell, 1_000_100.5)
        outdir = os.path.join(tmp, "out")
        os.makedirs(outdir)

        print("### read_marker: anything but a snapshot reconverts")
        check("missing marker -> None", import_marker.read_marker(outdir) is None)
        with open(os.path.join(outdir, import_marker.MARKER_NAME), "w") as fh:
            fh.write(repr(1_000_100.5))
        check("an older plain-mtime marker -> None", import_marker.read_marker(outdir) is None)
        with open(os.path.join(outdir, import_marker.MARKER_NAME), "w") as fh:
            fh.write("{not json")
        check("a corrupt marker -> None", import_marker.read_marker(outdir) is None)

        print("### snapshot / stamp round trip")
        snap = import_marker.snapshot(sspj, "7.0.0+aaaaaaa")
        check("sources = newest mtime in the folder", snap["sources"] == 1_000_100.5)
        import_marker.stamp(outdir, snap)
        check("a stamped snapshot reads back equal", import_marker.read_marker(outdir) == snap)
        check("unchanged sources and converter -> current",
              import_marker.read_marker(outdir) == import_marker.snapshot(sspj, "7.0.0+aaaaaaa"))

        print("### what makes the output stale")
        check("another converter build",
              import_marker.read_marker(outdir) != import_marker.snapshot(sspj, "7.0.0+bbbbbbb"))
        other = os.path.join(tmp, "Other", "Ringo.sspj")
        _touch(other, 1_000_100.5)
        check("another .sspj converting into the folder",
              import_marker.read_marker(outdir) != import_marker.snapshot(other, "7.0.0+aaaaaaa"))
        os.utime(cell, (1_000_200.0, 1_000_200.0))
        check("a source saved again",
              import_marker.read_marker(outdir) != import_marker.snapshot(sspj, "7.0.0+aaaaaaa"))
        os.utime(cell, (1_000_050.0, 1_000_050.0))
        check("a source put back to an older copy",
              import_marker.read_marker(outdir) != import_marker.snapshot(sspj, "7.0.0+aaaaaaa"))

    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
