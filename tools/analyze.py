#!/usr/bin/env python3
"""Displayability audit (plain CPython, no Ren'Py).

For each ``.ssab`` it: parses metadata, plays the first animation through every
frame, collects which DrawBatchKinds appear, runs the M1 Normal-quad geometry
pipeline on a sample frame, and validates the quads against the real atlas
size. Prints a per-pack verdict: what M1 can render now vs. what needs a later
milestone.

Usage:
    python tools/analyze.py [dir_or_ssab ...]
Default target: game/sprites/overall (the converted "overall" test project).
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


def png_size(path: str):
    """(w, h) from a PNG IHDR without PIL; None if unreadable."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", head[16:24])
        return (w, h)
    except OSError:
        return None


def audit_pack(lib, path: str) -> dict:
    name = os.path.basename(path)
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    anims = meta.animations()
    cellmaps = meta.cellmaps()
    base = os.path.dirname(path)

    # texture_hash -> (image_path, (w,h) or None)
    tex = {}
    matched_key_kind = set()
    for c in cellmaps:
        dims = png_size(os.path.join(base, c.image_path)) if c.image_path else None
        tex[c.name_hash] = (c.image_path, dims, "name_hash")
        tex[c.image_path_hash] = (c.image_path, dims, "image_path_hash")

    result = {"name": name, "anims": [a.name for a in anims],
              "cellmaps": [(c.name, c.image_path) for c in cellmaps],
              "kinds": {}, "verdict": "", "geom": "", "notes": []}
    if not anims:
        result["verdict"] = "no animations"
        return result

    rt = ssruntime.SSRuntime(lib)
    try:
        rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN)
        rt.load_ssab_bytes(data)
        a0 = anims[0]
        if not rt.setup_animation(a0.name):
            result["verdict"] = f"setup_animation({a0.name!r}) failed"
            return result
        rt.set_loop(-1)
        rt.play()

        total = max(1, a0.total_frame)
        fps = rt.fps or a0.fps or 30
        dt = 1.0 / fps
        kinds_seen: dict[int, int] = {}
        sample_quads = []
        sample_frame = total // 2
        for fr in range(total):
            frame_no = rt.update(dt)
            fb = rt.get_frame_data(frame_no)
            if not fb:
                continue
            fd = framedata.parse(fb)
            cls = framedata.classify_frame(fd)
            for k, v in cls.items():
                if isinstance(k, int):
                    kinds_seen[k] = max(kinds_seen.get(k, 0), v["parts"])
            if fr == sample_frame:
                sample_quads = framedata.build_normal_quads(rt, fd)

        result["kinds"] = {framedata.KIND_NAMES.get(k, str(k)): n
                           for k, n in sorted(kinds_seen.items())}

        # --- verdict ---
        seen = set(kinds_seen)
        supported = seen & framedata.M1_RENDERABLE_KINDS
        unsupported = seen - framedata.M1_RENDERABLE_KINDS
        if not seen:
            result["verdict"] = "no draw batches"
        elif not unsupported:
            result["verdict"] = "FULL — M1 renders everything"
        elif supported:
            need = ", ".join(sorted(framedata.KIND_NAMES.get(k, str(k))
                                    for k in unsupported))
            result["verdict"] = f"PARTIAL — Normal renders; needs later: {need}"
        else:
            need = ", ".join(sorted(framedata.KIND_NAMES.get(k, str(k))
                                    for k in unsupported))
            result["verdict"] = f"NOT YET — needs: {need}"

        # --- geometry sanity on the sample frame's Normal quads ---
        if sample_quads:
            bad_pos = bad_uv = bad_rect = 0
            hashes = set()
            for q in sample_quads:
                hashes.add(q.texture_hash)
                for (x, y) in q.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        bad_pos += 1
                entry = tex.get(q.texture_hash)
                if entry and entry[1]:
                    tw, th = entry[1]
                    matched_key_kind.add(entry[2])
                    l, t, w, h = q.src_rect
                    if l < -0.5 or t < -0.5 or l + w > tw + 0.5 or t + h > th + 0.5:
                        bad_rect += 1
                    for (u, v) in q.uvs:
                        if u < -0.5 or v < -0.5 or u > tw + 0.5 or v > th + 0.5:
                            bad_uv += 1
            unresolved = [h for h in hashes if h not in tex]
            g = (f"{len(sample_quads)} Normal quads @frame{sample_frame}: "
                 f"pos_bad={bad_pos} uv_oob={bad_uv} rect_oob={bad_rect}")
            if unresolved:
                g += f" UNRESOLVED_TEX={len(unresolved)}"
            result["geom"] = g
            if matched_key_kind:
                result["notes"].append(
                    "texture_hash matches cellmap " + "/".join(sorted(matched_key_kind)))
        else:
            result["geom"] = "no Normal quads on sample frame"
        return result
    finally:
        rt.close()


def main(argv: list[str]) -> int:
    targets = argv[1:] or [os.path.join(_GAME, "sprites", "overall")]
    paths: list[str] = []
    for t in targets:
        if os.path.isdir(t):
            paths += sorted(glob.glob(os.path.join(t, "*.ssab")))
        elif t.endswith(".ssab"):
            paths.append(t)
    if not paths:
        print("no .ssab found")
        return 2

    lib = ssruntime.load_library()
    print(f"== Displayability audit: {len(paths)} packs "
          f"(M1 renders kinds={sorted(framedata.M1_RENDERABLE_KINDS)} = Normal)\n")
    full = partial = none = 0
    for p in paths:
        r = audit_pack(lib, p)
        kinds = ", ".join(f"{k}:{v}" for k, v in r["kinds"].items()) or "-"
        v = r["verdict"]
        full += v.startswith("FULL")
        partial += v.startswith("PARTIAL")
        none += v.startswith("NOT")
        print(f"### {r['name']:<22} {v}")
        print(f"      anims={len(r['anims'])}  cellmaps={r['cellmaps']}")
        print(f"      kinds(maxparts)= {kinds}")
        if r["geom"]:
            print(f"      geom: {r['geom']}")
        for n in r["notes"]:
            print(f"      note: {n}")
        print()
    print(f"== Summary: {full} FULL, {partial} PARTIAL, {none} NOT-YET "
          f"(of {len(paths)} packs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
