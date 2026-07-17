#!/usr/bin/env python3
"""Software-render a .ssab frame WITH masks applied, to a PNG (verification).

A headless reference of the mask/clipping result: it drives the SAME engine-
independent core that the Ren'Py layer uses — ``mask.build_frame_mask`` for the
writers and ``mask.mask_passes`` for the per-pixel replay (the exact CPU twin of
the ``ss.partcolor_mask`` GLSL) — so the output proves the mask LOGIC produces
the right shape, independent of the GPU path and of any demo background.

It rasterizes the coverage on the CPU (each writer's quad/shape, with the same
``(255-mask)/255`` cutout), then for every masked target part runs
``mask_passes`` per pixel and clears alpha where it fails. Normal parts only
(the Jigsaw targets + textured masks); a Mesh writer is filled by triangles.

Requires Pillow (`pip install Pillow`).  Usage: python tools/render_mask_png.py [pack.ssab] [anim] [--frame N] [--out f.png] [--no-mask]
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_GAME = os.path.join(_ROOT, "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()
from ss_renpy import ssruntime, framedata, mask  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

# Reuse the proven Normal-quad warp + atlas loader from the no-mask renderer.
from render_png import load_atlases, warp_quad, _avg_color  # noqa: E402


class _Q:
    __slots__ = ("texture_hash", "blend_type", "alpha", "positions", "uvs")


def _quad_alpha(atlas, positions, uvs, canvas_size, off):
    """Warped alpha (0..255 'L' image) of a textured quad over the canvas."""
    q = _Q()
    q.positions, q.uvs = positions, uvs
    layer = warp_quad(atlas, q, canvas_size, off)
    return layer.split()[3] if layer is not None else None


def _fill_polygon_alpha(points, canvas_size, off):
    """Solid alpha mask of a polygon (for texture-less shape / mesh writers)."""
    m = Image.new("L", canvas_size, 0)
    d = ImageDraw.Draw(m)
    d.polygon([(off[0] + x, off[1] + y) for (x, y) in points], fill=255)
    return m


def build_coverage(fm, atlases, canvas_size, off):
    """CPU coverage: per-pixel 24-bit set, one bit per writer (== the shader)."""
    w, h = canvas_size
    cover = [[0] * w for _ in range(h)]
    for wr in fm.writers:
        thr = int(round((255.0 - wr.mask_value)))      # alpha cutout (0..255)
        if wr.has_texture and wr.texture_hash in atlases and len(wr.positions) == 4:
            a = _quad_alpha(atlases[wr.texture_hash], wr.positions, wr.uvs,
                            canvas_size, off)
            covered = (lambda px, py: a.getpixel((px, py)) > thr) if a else None
        elif len(wr.positions) == 4:                    # texture-less shape quad
            a = _fill_polygon_alpha(
                [wr.positions[0], wr.positions[1], wr.positions[3], wr.positions[2]],
                canvas_size, off)
            covered = lambda px, py: a.getpixel((px, py)) > 127
        else:                                           # mesh writer: fill tris
            a = Image.new("L", canvas_size, 0)
            d = ImageDraw.Draw(a)
            for (i, j, k) in wr.triangles:
                d.polygon([(off[0] + wr.positions[t][0], off[1] + wr.positions[t][1])
                           for t in (i, j, k)], fill=255)
            covered = lambda px, py: a.getpixel((px, py)) > 127
        if covered is None:
            continue
        bit = 1 << wr.bit
        # only scan the writer's bbox
        xs = [off[0] + p[0] for p in wr.positions]
        ys = [off[1] + p[1] for p in wr.positions]
        x0, x1 = max(0, int(min(xs))), min(w, int(max(xs)) + 1)
        y0, y1 = max(0, int(min(ys))), min(h, int(max(ys)) + 1)
        for py in range(y0, y1):
            row = cover[py]
            for px in range(x0, x1):
                if covered(px, py):
                    row[px] |= bit
    return cover


def apply_mask(layer, ap, fm, cover, off):
    """Zero ``layer`` alpha wherever ``mask_passes`` discards (the per-pixel replay of the mask shader)."""
    w, h = layer.size
    px = layer.load()
    bw, bh = fm.bsize
    bx, by = fm.bmin
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            wx, wy = x - off[0], y - off[1]
            cov_uv = ((wx - bx) / bw, (wy - by) / bh)
            bits = cover[y][x]
            keep = mask.mask_passes(fm, ap.rank, ap.visible_inside, cov_uv,
                                    lambda bit, _b=bits: (_b >> bit) & 1)
            if not keep:
                px[x, y] = (r, g, b, 0)
    return layer


def render(path, anim, frame, out, use_mask=True, bg="808080"):
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    base = os.path.dirname(os.path.abspath(path))
    atlases = load_atlases(meta, base)

    pl = SSInternalPlayer(data, lib=ssruntime.load_library(),
                          base_dir=os.path.relpath(base, _GAME).replace("\\", "/"))
    a0 = anim or meta.animation_names()[0]
    pl.set_animation(a0)
    pl.set_loop(-1)
    pl.play()
    plan = None
    fps = pl.fps or 30
    for fr in range(frame + 1):
        plan = pl.update(0.0 if fr == 0 else 1000.0 / fps)
    fm = plan.frame_mask
    pl.close()

    # canvas bbox over all drawable parts
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for tag, mp in plan.items:
        if tag != "mesh":
            continue
        for (x, y) in mp.positions[:4]:
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)
    margin = 12
    off = (-minx + margin, -miny + margin)
    cw = int(math.ceil(maxx - minx)) + 2 * margin
    ch = int(math.ceil(maxy - miny)) + 2 * margin
    size = (cw, ch)

    cover = build_coverage(fm, atlases, size, off) if (use_mask and fm) else None

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    n_masked = 0
    for tag, mp in plan.items:
        if tag != "mesh" or mp.texture_hash not in atlases:
            continue
        q = _Q()
        q.positions, q.uvs = list(mp.positions[:4]), list(mp.uvs[:4])
        layer = warp_quad(atlases[mp.texture_hash], q, size, off)
        if layer is None:
            continue
        avg = _avg_color(mp.colors)
        if avg[3] < 0.999:
            r, g, b, al = layer.split()
            layer = Image.merge("RGBA", (r, g, b, al.point(lambda v: int(v * avg[3]))))
        if use_mask and cover is not None and mp.mask is not None:
            layer = apply_mask(layer, mp.mask, fm, cover, off)
            n_masked += 1
        canvas = Image.alpha_composite(canvas, layer)

    bg_rgb = tuple(int(bg[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    framed = Image.alpha_composite(Image.new("RGBA", size, bg_rgb), canvas)
    framed.convert("RGB").save(out)
    print(f"wrote {out}  canvas={cw}x{ch}  writers={fm.count if fm else 0}  "
          f"masked_targets_drawn={n_masked}  mask={'ON' if use_mask else 'OFF'}")


def main(argv):
    ssab = next((a for a in argv[1:] if not a.startswith("--")
                 and a.endswith(".ssab")),
                os.path.join(_GAME, "ss_assets", "overall", "Mask.ssab"))
    rest = [a for a in argv[1:] if not a.startswith("--") and a != ssab]
    anim = rest[0] if rest else None
    frame = int(argv[argv.index("--frame") + 1]) if "--frame" in argv else 0
    out = argv[argv.index("--out") + 1] if "--out" in argv else \
        os.path.join(_ROOT, "out", "mask.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    render(ssab, anim, frame, out, use_mask="--no-mask" not in argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
