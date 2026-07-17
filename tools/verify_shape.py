#!/usr/bin/env python3
"""Headless check for Shape part rendering (textureless procedural polygons).

Drives a pack with Shape parts (default overall/Shape.ssab) through its frames
and validates two layers:

* **Raw shape SoA** (the C-API contract): per-part valid vertex counts are one
  of {5, 6, 7, 12} (Triangle / Rectangle / Arrow / Star), the paired bbox coords
  stay in [0, 1], and every local vertex is finite.
* **Draw plan** (via :func:`ss_renpy.instance.collect_ordered`): Shape parts
  surface as textureless ``("mesh", MeshPart)`` items (``texture_hash == 0``),
  positions are finite, the triangle fan indices stay within each part's vertex
  range and all share vertex 0, per-vertex colours are finite/in-range, and the
  PartColor ``rate`` is forced to 1.0 (a shape has no texel to blend).

Plain CPython — no Ren'Py. GL2 rendering (premultiplied-alpha fill, blend) still
needs a GUI run (scene_viewer.rpy lists Shape.ssab; Shift+B previews it).

Usage:  python tools/verify_shape.py [pack.ssab ...]
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime, framedata  # noqa: E402
from ss_renpy.instance import collect_ordered, display_frame  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402

PART_TYPE_SHAPE = 3          # ss.format.PartType.PartTypeShape
VALID_COUNTS = {5, 6, 7, 12}  # Triangle / Rectangle / Arrow / Star (fan verts)


def check_pack(lib, path: str, anim=None) -> bool:
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    name = os.path.basename(path)
    from collections import Counter
    types = Counter(p.part_type for p in meta.parts())
    n_shape = types.get(PART_TYPE_SHAPE, 0)
    print(f"### {name}  shape_parts(static)={n_shape}  "
          f"anims={len(meta.animations())}")
    if not meta.animations():
        print("    FAIL: no animations")
        return False

    rt = ssruntime.SSRuntime(lib)
    ok = True
    try:
        rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                     origin=ssruntime.ORIGIN_CENTER)
        rt.load_ssab_bytes(data)
        a0 = anim or meta.animation_names()[0]
        if not rt.setup_animation(a0):
            print(f"    FAIL: setup_animation({a0!r})")
            return False
        rt.set_loop(-1)
        rt.play()
        fps = rt.fps or 30
        dt = 1.0 / fps
        total = max(1, meta.animations()[0].total_frame)

        shape_renderables = 0
        counts_seen: set[int] = set()
        bad_count = 0        # raw SoA count not in VALID_COUNTS
        bad_box = 0          # raw bbox coord outside [0, 1]
        bad_soa_vert = 0     # raw local vertex not finite
        bad_pos = 0          # draw-plan position not finite
        bad_idx = 0          # fan index out of range
        bad_fan = 0          # triangle not anchored on vertex 0
        bad_color = 0        # colour channel not finite / outside [0, 1]
        bad_rate = 0         # rate != 1.0
        first_sig = None
        moved = False

        for fr in range(total + 1):
            f = rt.update(dt)
            fb = rt.get_frame_data(display_frame(f, False))
            if not fb:
                continue
            fd = framedata.parse(fb)

            # -- raw shape SoA (pointers valid until the next Brain call, so read
            #    BEFORE collect_ordered, which steps child slots) --------------
            sv, nsv = rt.shape_vertices()
            sb, nsb = rt.shape_vertex_box_coords()
            sc, nsc = rt.shape_vertex_counts()
            if sc:
                for p in range(nsc):
                    c = int(sc[p])
                    if c <= 0:
                        continue
                    counts_seen.add(c)
                    if c not in VALID_COUNTS:
                        bad_count += 1
                    so = p * framedata.SHAPE_STRIDE
                    if so + c * 2 > nsv or so + c * 2 > nsb:
                        continue
                    for j in range(c):
                        x, y = sv[so + j * 2], sv[so + j * 2 + 1]
                        if not (math.isfinite(x) and math.isfinite(y)):
                            bad_soa_vert += 1
                        fx, fy = sb[so + j * 2], sb[so + j * 2 + 1]
                        if not (-1e-4 <= fx <= 1.0001 and -1e-4 <= fy <= 1.0001):
                            bad_box += 1

            # -- draw plan: shapes surface as textureless "mesh" items ---------
            items = collect_ordered(rt, fd, None, None, f, dt, rt.is_looped, False)
            sig = 0.0
            for tag, mp in items:
                if tag != "mesh" or mp.texture_hash != 0:
                    continue
                shape_renderables += 1
                nv = len(mp.positions)
                for (x, y) in mp.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        bad_pos += 1
                    else:
                        sig += x * 0.13 + y * 0.07
                for tri in mp.triangles:
                    if any(idx < 0 or idx >= nv for idx in tri):
                        bad_idx += 1
                    if tri[0] != 0:
                        bad_fan += 1
                for col in mp.colors:
                    if any(not math.isfinite(ch) or ch < -1e-4 or ch > 1.0001
                           for ch in col):
                        bad_color += 1
                if any(abs(rt_ - 1.0) > 1e-6 for rt_ in mp.rates):
                    bad_rate += 1
            if first_sig is None:
                first_sig = sig
            elif abs(sig - first_sig) > 1e-3:
                moved = True

        print(f"    shape renderables (anim {a0!r}): {shape_renderables}   "
              f"vertex-counts seen: {sorted(counts_seen)}   "
              f"moves over time: {moved}")
        print(f"    raw SoA: bad_count={bad_count} bad_box={bad_box} "
              f"bad_vert={bad_soa_vert}")
        print(f"    draw plan: bad_pos={bad_pos} bad_idx={bad_idx} "
              f"bad_fan={bad_fan} bad_color={bad_color} bad_rate={bad_rate}")

        if shape_renderables == 0:
            print("    FAIL: no shape parts rendered")
            ok = False
        if bad_count or bad_box or bad_soa_vert:
            print("    FAIL: raw shape SoA violates the C-API contract")
            ok = False
        if bad_pos or bad_idx or bad_fan or bad_color or bad_rate:
            print("    FAIL: invalid shape draw-plan geometry/colour")
            ok = False
        if not moved:
            print("    WARN: shape geometry did not change across frames")
        return ok
    finally:
        rt.close()


def main(argv) -> int:
    if len(argv) > 1:
        targets = [(t, None) for t in argv[1:]]
    else:
        targets = [
            (os.path.join(_GAME, "ss_assets", "overall", "Shape.ssab"), None),
        ]
    lib = ssruntime.load_library()
    print("== Shape verification ==\n")
    allok = True
    for path, anim in targets:
        allok &= check_pack(lib, path, anim)
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
