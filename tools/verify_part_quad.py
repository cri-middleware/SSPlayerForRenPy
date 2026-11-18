#!/usr/bin/env python3
"""Headless check for part outlines (`part_quad`) and `hit_test_part`.

  * Ringo, every animation, every other frame: a part with a cell is outlined
    by exactly the corners it is drawn with, and every vertex of a Mesh part
    lies in its outline;
  * `Shape`: a Shape's outline is its size around its pivot -- the box of the
    vertices drawn on a frame without vertex deform, and not followed when the
    deform carries a corner outside it;
  * Null, Instance and Effect parts, a hidden part, an unknown part and a
    player with no frame drawn yet have no outline;
  * `hit_test_part` answers with the front-most outline in draw order, takes
    a set of targets, and skips a name the pack lacks;
  * the outlines are the last frame drawn's, still after `set_animation`.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_part_quad.py
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
from ss_renpy.outline import contains  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402
from ss_renpy.ssab_meta import PART_TYPE_MESH  # noqa: E402

_EPS = 1e-3
_ok = True


def check(label, good, detail=""):
    global _ok
    print(f"    {'PASS' if good else 'FAIL'}  {label}" + ("" if good else f": {detail}"))
    _ok = _ok and good


def load(lib, rel):
    path = os.path.join(_GAME, "ss_assets", rel)
    if not os.path.exists(path):
        print(f"SKIP: {path} not found (run scripts/deploy-examples.* first)")
        return None
    with open(path, "rb") as f:
        data = f.read()
    return SSInternalPlayer(data, lib=lib, base_dir=os.path.dirname(rel),
                            resource_manager=RecordingResourceManager(),
                            pack_reader=filesystem_pack_reader(os.path.dirname(path)))


def _near(a, b) -> bool:
    return abs(a[0] - b[0]) <= _EPS and abs(a[1] - b[1]) <= _EPS


def _box(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _frame(p, frame):
    p.set_frame_no(frame)
    return p.update(0.0)


def check_drawn(lib) -> None:
    print("### Ringo  outlines hold what is drawn")
    p = load(lib, "Ringo/Ringo.ssab")
    if p is None:
        return
    try:
        check("no outline before a frame is drawn", p.part_quad("body") is None)
        check("no hit before a frame is drawn", p.hit_test_part(0, -100) == -1)
        mesh = {i.index for i in p._part_infos if i.part_type == PART_TYPE_MESH}
        cells = meshes = 0
        bad = []
        for anim in p.animation_names():
            p.set_animation(anim)
            p.play()
            for frame in range(p.start_frame, p.end_frame + 1, 2):
                for kind, item in _frame(p, frame).items:
                    if kind != "mesh":
                        continue
                    q = p.part_quad(item.part_index)
                    where = f"{anim}@{frame} part {item.part_index}"
                    if q is None:
                        bad.append(f"{where}: no outline")
                    elif item.part_index in mesh:
                        meshes += 1
                        l, t, r, b = _box(q)
                        if any(not (l - _EPS <= x <= r + _EPS and t - _EPS <= y <= b + _EPS)
                               for x, y in item.positions):
                            bad.append(f"{where}: a vertex outside {q}")
                    else:
                        cells += 1
                        if not all(_near(a, b) for a, b in zip(q, item.positions[:4])):
                            bad.append(f"{where}: {q} != {item.positions[:4]}")
        check(f"{cells} cell parts outlined by their drawn corners, "
              f"{meshes} Mesh parts holding their vertices", not bad, bad[:3])
    finally:
        p.close()


def check_shape(lib) -> None:
    print("### Shape  the size around the pivot")
    p = load(lib, "overall/Shape.ssab")
    if p is None:
        return
    try:
        p.set_animation("anime_1")
        p.play()
        drawn = {it.part_index: it.positions for k, it in _frame(p, 0).items if k == "mesh"}
        shape = p.find_part_index("Shape")
        q = p.part_quad("Shape")
        check("no vertex deform: the box of the drawn vertices",
              q is not None and all(abs(a - b) <= _EPS
                                    for a, b in zip(_box(q), _box(drawn[shape]))),
              f"{q} vs {_box(drawn[shape])}")
        drawn = {it.part_index: it.positions for k, it in _frame(p, 4).items if k == "mesh"}
        moved = p.part_quad("Shape")
        l, t, r, b = _box(moved)
        check("a deformed corner is not followed",
              moved == q and any(x < l - _EPS or y < t - _EPS for x, y in drawn[shape]),
              f"{moved} vs {drawn[shape]}")
        check("the root (a Null part) has no outline", p.part_quad("root") is None)
    finally:
        p.close()


def check_none(lib) -> None:
    print("### no outline")
    for rel, part in (("overall/Instance.ssab", "NO_KEY"),
                      ("overall/Effect.ssab", "start=0_indep=off")):
        p = load(lib, rel)
        if p is None:
            return
        try:
            p.set_animation(None)
            p.play()
            _frame(p, 5)
            check(f"{rel}: {part}", p.find_part_index(part) >= 0
                  and p.part_quad(part) is None)
        finally:
            p.close()
    p = load(lib, "Ringo/Ringo.ssab")
    if p is None:
        return
    try:
        p.set_animation("wait1")
        p.play()
        _frame(p, 0)
        p.set_part_visibility_override("body", True)
        _frame(p, 0)
        check("a hidden part", p.part_quad("body") is None
              and p.part_quad(p.find_part_index("body")) is None)
        check("an unknown part", p.part_quad("no-such-part") is None
              and p.part_quad(10 ** 6) is None)
    finally:
        p.close()


def check_hit(lib) -> None:
    print("### hit_test_part  the front-most outline")
    p = load(lib, "Ringo/Ringo.ssab")
    if p is None:
        return
    try:
        p.set_animation("attack1")
        p.play()
        names = p.part_names()
        bad = []
        tried = 0
        for frame in range(p.start_frame, p.end_frame + 1, 3):
            order = [it.part_index for k, it in _frame(p, frame).items if k == "mesh"]
            quads = {i: p.part_quad(i) for i in order}
            for i in order:
                q = quads[i]
                cx = sum(x for x, _ in q) / 4.0
                cy = sum(y for _, y in q) / 4.0
                want = next(j for j in reversed(order) if contains(quads[j], cx, cy))
                tried += 1
                if p.hit_test_part(cx, cy) != want:
                    bad.append(f"@{frame} ({cx:.1f}, {cy:.1f}): "
                               f"{p.hit_test_part(cx, cy)} want {want}")
                if contains(q, cx, cy) and p.hit_test_part(cx, cy, [names[i]]) != i:
                    bad.append(f"@{frame} part {i} by name")
        check(f"{tried} points answered by the last outline drawn over them", not bad, bad[:3])
        body = p.find_part_index("body")
        q = p.part_quad(body)
        cx = sum(x for x, _ in q) / 4.0
        cy = sum(y for _, y in q) / 4.0
        check("targets by index, an unknown name skipped",
              p.hit_test_part(cx, cy, ["no-such-part", body]) == body)
        check("no target left: -1", p.hit_test_part(cx, cy, ["no-such-part"]) == -1)
        check("a point off every part: -1", p.hit_test_part(1e6, 1e6) == -1)
        before = p.part_quad(body)
        p.set_animation("wait1")
        check("set_animation keeps the last frame's outline", p.part_quad(body) == before)
    finally:
        p.close()


def main() -> int:
    print("== part outline / hit test verification ==\n")
    lib = ssruntime.load_library()
    check_drawn(lib)
    check_shape(lib)
    check_none(lib)
    check_hit(lib)
    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
