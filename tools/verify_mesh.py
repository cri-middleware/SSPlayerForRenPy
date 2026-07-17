#!/usr/bin/env python3
"""Headless check for Mesh(deform) part rendering (SDK doc: 40_components/30_mesh.md).

Drives a pack with Mesh parts (default Ringo.ssab + overall/Mesh.ssab) through
its frames, walks the draw plan via :func:`ss_renpy.instance.collect_ordered`,
and validates the deform geometry the mesh SoA produces: that deform meshes
(>4 verts) actually appear, positions are finite, triangle indices stay within
each part's vertex range, the mesh deforms over time (vertices move), and every
mesh texture resolves. Plain CPython — no Ren'Py.

Usage:  python tools/verify_mesh.py [pack.ssab ...]
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


def check_pack(lib, path: str, anim=None) -> bool:
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    texmap = meta.texture_hash_map()
    name = os.path.basename(path)
    from collections import Counter
    types = Counter(p.part_type for p in meta.parts())
    n_mesh = types.get(9, 0)  # PartType.PartTypeMesh
    print(f"### {name}  mesh_parts(static)={n_mesh}  anims={len(meta.animations())}")
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

        deform_meshes = 0
        bad_pos = 0
        bad_idx = 0
        unresolved = set()
        first_sig = None
        moved = False
        for fr in range(total + 1):
            f = rt.update(dt)
            fb = rt.get_frame_data(display_frame(f, False))
            if not fb:
                continue
            fd = framedata.parse(fb)
            items = collect_ordered(rt, fd, None, None, f, dt, rt.is_looped, False)
            sig = 0.0
            for tag, mp in items:
                if tag != "mesh" or len(mp.positions) <= 5:
                    continue   # count only true deform meshes
                deform_meshes += 1
                if mp.texture_hash not in texmap:
                    unresolved.add(mp.texture_hash)
                nv = len(mp.positions)
                for (x, y) in mp.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        bad_pos += 1
                    else:
                        sig += x * 0.13 + y * 0.07
                for tri in mp.triangles:
                    if any(idx < 0 or idx >= nv for idx in tri):
                        bad_idx += 1
            if first_sig is None:
                first_sig = sig
            elif abs(sig - first_sig) > 1e-3:
                moved = True

        print(f"    deform-mesh renderables (anim {a0!r}): {deform_meshes}   "
              f"deforms over time: {moved}")
        print(f"    bad positions={bad_pos}  out-of-range indices={bad_idx}"
              + (f"  UNRESOLVED textures={sorted(unresolved)}" if unresolved
                 else "  all textures resolved"))
        if deform_meshes == 0:
            print("    FAIL: no deform meshes rendered")
            ok = False
        if bad_pos or bad_idx:
            print("    FAIL: invalid mesh geometry/indices")
            ok = False
        if unresolved:
            ok = False
        if not moved:
            print("    WARN: mesh vertices did not change across frames")
        return ok
    finally:
        rt.close()


def main(argv) -> int:
    if len(argv) > 1:
        targets = [(t, None) for t in argv[1:]]
    else:
        targets = [
            (os.path.join(_GAME, "ss_assets", "Ringo", "Ringo.ssab"), "dance"),
            (os.path.join(_GAME, "ss_assets", "overall", "Mesh.ssab"), None),
        ]
    lib = ssruntime.load_library()
    print("== Mesh(deform) verification ==\n")
    allok = True
    for path, anim in targets:
        allok &= check_pack(lib, path, anim)
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
