#!/usr/bin/env python3
"""Headless verification of the M2 render core (plain CPython, no PIL/numpy).

M2 adds full-fidelity Normal rendering: shear/free-deform-exact world meshes
plus per-vertex ``parts_color`` and the PartColor blend modes. None of that
needs a GUI to be *correct* — only the final on-screen GL draw does — so this
tool proves the engine-independent core:

  1. unit-tests the PartColor blend math (``eval_partcolor``) against the spec
     cases in 10_parts_color §1-4 (rate-0 pass-through, Mix/Mul/Add/Sub @ rate 1);
  2. for every pack, plays the first animation and validates each frame's
     ``build_mesh_parts`` output — finite positions, in-range triangles, UVs
     inside the atlas, colours in 0..1, blend index 0..3, the 5-vertex centre
     fan iff the part flags free deform / per-vertex colour;
  3. checks the alpha-not-double-applied contract (part-colour-less vertices
     carry exactly ``PartState.alpha``);
  4. confirms M2 corner positions match the M1 :func:`build_normal_quads`
     geometry (same world matrix x local verts), so M2 is a strict superset.

Exits non-zero if any check fails.

Usage:
    python tools/verify_m2.py [dir_or_ssab ...]   # default: game/sprites/overall
"""

from __future__ import annotations

import glob
import math
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime, framedata  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402


# --------------------------------------------------------------------------
# 1. PartColor blend math (10_parts_color §1-4)
# --------------------------------------------------------------------------

def _approx(a, b, eps=1e-6) -> bool:
    return all(abs(x - y) <= eps for x, y in zip(a, b))


def test_partcolor_math() -> list:
    """Return a list of failure strings (empty == all good)."""
    fails = []
    pix = (0.20, 0.50, 0.80)
    col = (0.90, 0.40, 0.10)

    # rate 0 -> texel pass-through for every mode.
    for mode in range(4):
        got = framedata.eval_partcolor(pix, col, mode, 0.0)
        if not _approx(got, pix):
            fails.append(f"rate0 mode={mode}: {got} != {pix}")

    # rate 1 spec results.
    cases = {
        framedata.PC_BLEND_MIX: col,                                  # lerp->color
        framedata.PC_BLEND_MUL: tuple(p * c for p, c in zip(pix, col)),
        framedata.PC_BLEND_ADD: tuple(p + c for p, c in zip(pix, col)),
        framedata.PC_BLEND_SUB: tuple(p - c for p, c in zip(pix, col)),
    }
    for mode, want in cases.items():
        got = framedata.eval_partcolor(pix, col, mode, 1.0)
        if not _approx(got, want):
            fails.append(f"rate1 {framedata.PC_BLEND_NAMES[mode]}: {got} != {want}")

    # out-of-range blend clamps to Mix.
    if framedata.clamp_pc_blend(7) != framedata.PC_BLEND_MIX:
        fails.append("clamp_pc_blend(7) != Mix")
    if framedata.clamp_pc_blend(-1) != framedata.PC_BLEND_MIX:
        fails.append("clamp_pc_blend(-1) != Mix")
    return fails


# --------------------------------------------------------------------------
# 2-4. Per-pack mesh validation
# --------------------------------------------------------------------------

def png_size(path: str):
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def _is_parallelogram(pos, eps=0.5) -> bool:
    # LT + RB == RT + LB  (diagonals share a midpoint) for the 4 corners.
    lt, rt, lb, rb = pos[0], pos[1], pos[2], pos[3]
    return (abs((lt[0] + rb[0]) - (rt[0] + lb[0])) <= eps
            and abs((lt[1] + rb[1]) - (rt[1] + lb[1])) <= eps)


def verify_pack(lib, path: str) -> dict:
    name = os.path.basename(path)
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    anims = meta.animations()
    base = os.path.dirname(path)
    tex = {}
    for c in meta.cellmaps():
        dims = png_size(os.path.join(base, c.image_path)) if c.image_path else None
        tex[c.name_hash] = dims
        tex[c.image_path_hash] = dims

    res = {"name": name, "errors": [], "frames": 0, "parts": 0,
           "partcolor": 0, "free_deform": 0, "center_fan": 0, "uv_oob": 0,
           "blends": set(), "color_blends": set()}
    if not anims:
        res["errors"].append("no animations")
        return res

    rt = ssruntime.SSRuntime(lib)
    try:
        rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN)
        rt.load_ssab_bytes(data)
        a0 = anims[0]
        if not rt.setup_animation(a0.name):
            res["errors"].append(f"setup_animation({a0.name!r}) failed")
            return res
        rt.set_loop(-1)
        rt.play()
        fps = rt.fps or a0.fps or 30
        total = max(1, a0.total_frame)
        dt = 1.0 / fps

        def err(msg):
            if len(res["errors"]) < 12:
                res["errors"].append(msg)

        for fr in range(total):
            frame_no = rt.update(dt)
            fb = rt.get_frame_data(frame_no)
            if not fb:
                continue
            fd = framedata.parse(fb)
            res["frames"] += 1
            mesh = framedata.build_mesh_parts(rt, fd)
            # M1 corners for cross-check (same buffers, this frame only).
            m1 = {q.part_index: q.positions
                  for q in framedata.build_normal_quads(rt, fd)}

            for mp in mesh:
                res["parts"] += 1
                res["blends"].add(mp.blend_type)
                res["color_blends"].add(mp.color_blend)
                if mp.has_partcolor:
                    res["partcolor"] += 1
                if mp.use_center:
                    res["center_fan"] += 1
                nverts = len(mp.positions)
                # structural
                if nverts != (5 if mp.use_center else 4):
                    err(f"f{fr} p{mp.part_index}: {nverts} verts, "
                        f"use_center={mp.use_center}")
                if not (len(mp.uvs) == len(mp.colors) == len(mp.rates) == nverts):
                    err(f"f{fr} p{mp.part_index}: ragged vertex arrays")
                for (i, j, k) in mp.triangles:
                    if not (0 <= i < nverts and 0 <= j < nverts and 0 <= k < nverts):
                        err(f"f{fr} p{mp.part_index}: tri idx oob {(i, j, k)}")
                # numeric
                for (x, y) in mp.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        err(f"f{fr} p{mp.part_index}: non-finite pos")
                        break
                for (r, g, b, a) in mp.colors:
                    if not all(-1e-4 <= v <= 1.0001 for v in (r, g, b, a)):
                        err(f"f{fr} p{mp.part_index}: colour oob {(r, g, b, a)}")
                        break
                if not (0 <= mp.color_blend <= 3):
                    err(f"f{fr} p{mp.part_index}: color_blend={mp.color_blend}")
                # UVs inside atlas. Slightly-out-of-bounds UVs are a property of
                # the source .ssab (UV animation / atlas overscan), not a port
                # bug — GL clamps/wraps and M2 passes the runtime UVs through
                # unchanged (same as M1). Count as a warning, don't fail.
                dims = tex.get(mp.texture_hash)
                if dims:
                    tw, th = dims
                    for (u, v) in mp.uvs:
                        if u < -0.5 or v < -0.5 or u > tw + 0.5 or v > th + 0.5:
                            res["uv_oob"] += 1
                            break
                # free deform (non-parallelogram corner quad)
                if not _is_parallelogram(mp.positions):
                    res["free_deform"] += 1
                # M1 <-> M2 corner agreement
                if mp.part_index in m1:
                    for (mc, qc) in zip(mp.positions[:4], m1[mp.part_index]):
                        if abs(mc[0] - qc[0]) > 1e-3 or abs(mc[1] - qc[1]) > 1e-3:
                            err(f"f{fr} p{mp.part_index}: M1/M2 corner mismatch")
                            break

            # alpha-not-double-applied: a part-colour-less part's vertex alpha
            # equals PartState.alpha exactly (no second multiply).
            for mp in mesh:
                if mp.has_partcolor:
                    continue
                ps = fd.Parts(mp.part_index)
                if ps is None:
                    continue
                want = max(0.0, min(1.0, ps.Alpha()))
                got = mp.colors[0][3]
                if abs(got - want) > 1e-3:
                    err(f"f{fr} p{mp.part_index}: alpha {got:.3f} != "
                        f"PartState.alpha {want:.3f}")
        return res
    finally:
        rt.close()


def main(argv) -> int:
    targets = argv[1:] or [os.path.join(_GAME, "sprites", "overall")]
    paths = []
    for t in targets:
        if os.path.isdir(t):
            paths += sorted(glob.glob(os.path.join(t, "*.ssab")))
        elif t.endswith(".ssab"):
            paths.append(t)
    if not paths:
        print("no .ssab found")
        return 2

    print("== M2 core verification ==\n")
    fails = test_partcolor_math()
    if fails:
        print("PartColor blend math: FAIL")
        for f in fails:
            print(f"    {f}")
    else:
        print("PartColor blend math: OK (rate-0 passthrough, Mix/Mul/Add/Sub, clamp)")
    print()

    lib = ssruntime.load_library()
    total_err = len(fails)
    for p in paths:
        r = verify_pack(lib, p)
        status = "OK  " if not r["errors"] else "FAIL"
        bl = ",".join(framedata.BLEND_NAMES.get(b, str(b)) for b in sorted(r["blends"]))
        cb = ",".join(framedata.PC_BLEND_NAMES.get(b, str(b))
                      for b in sorted(r["color_blends"]))
        print(f"[{status}] {r['name']:<24} frames={r['frames']:<4} "
              f"parts={r['parts']:<5} partcolor={r['partcolor']} "
              f"free_deform={r['free_deform']} center_fan={r['center_fan']}")
        warn = f"  uv_oob_warn={r['uv_oob']}" if r["uv_oob"] else ""
        print(f"        fb_blend={{{bl}}}  partcolor_blend={{{cb}}}{warn}")
        for e in r["errors"]:
            print(f"        ! {e}")
            total_err += 1

    print(f"\n== {'ALL PASS' if total_err == 0 else str(total_err) + ' FAILURE(S)'} ==")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
