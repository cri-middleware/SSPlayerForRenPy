#!/usr/bin/env python3
"""Software-render a .ssab animation to PNG frames + an animated GIF.

This is NOT the Ren'Py renderer — it is a headless reference rasterizer that
drives the *same* render core (``framedata.build_mesh_parts``: world matrix x
local vertices, UVs and per-vertex ``parts_color`` straight from the runtime)
and composites the Normal parts with Pillow. It exists so we can visually verify
the data/geometry/colour path without a GUI, and so the output can be eyeballed
against the SS editor.

Only the ``Normal`` draw-batch kind is rendered. ``parts_color`` is applied as a
flat (averaged) tint per part via the ``eval_partcolor`` reference formula — the
exact per-vertex gradient is checked numerically by ``tools/verify_geometry.py``.
Requires Pillow (`pip install Pillow`).

Usage:
    python tools/render_png.py [anim.ssab] [animation] [--out DIR] [--bg hex]
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
from ss_renpy import ssruntime, framedata  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402

from PIL import Image  # noqa: E402

BLEND_ADD = framedata.BLEND_NAMES and 2  # BlendType.Add == 2


def load_atlases(meta: SsabMeta, base: str) -> dict:
    """``DrawBatch.texture_hash`` -> atlas image, keyed from BOTH texture tables.

    Cellmaps cover ordinary parts; ``external_textures`` covers parts whose
    drawing applies a texture change (``TCHG``), whose hash is of the FILE name.
    Skipping the second table leaves those quads without an atlas and this
    renderer drops them (see the ``atlases.get(th) is None`` guard below) — the
    silent-vanishing-part failure the shipped player also has to avoid.
    """
    tex = {}
    cache = {}

    def _load(rel):
        if rel not in cache:
            cache[rel] = Image.open(os.path.join(base, rel)).convert("RGBA")
        return cache[rel]

    for c in meta.cellmaps():
        if not c.image_path:
            continue
        img = _load(c.image_path)
        tex[c.name_hash] = img
        tex[c.image_path_hash] = img
    for t in meta.external_textures():
        if t.name:
            tex[t.name_hash] = _load(t.name)
    return tex


def _wrap_atlas(atlas: Image.Image, x0: int, y0: int, w: int, h: int) -> Image.Image:
    """Crop a ``w×h`` region from ``atlas`` at ``(x0, y0)`` with REPEAT wrap.

    Unlike ``Image.crop`` (which pads out-of-bounds with transparent), this tiles
    the atlas so UVs that exceed the texture wrap around — the software analogue
    of GL ``GL_REPEAT``. Needed for parts with ``UvScale``/``UvTranslation`` (the
    runtime bakes those into the UVs, so the sampled rect can run off the atlas;
    e.g. Basic.ssab part 20 has UvScale=2). For an in-bounds rect this is a plain
    single-tile copy, identical to ``crop``.
    """
    tw, th = atlas.size
    out = Image.new("RGBA", (w, h))
    x = 0
    while x < w:
        sx = (x0 + x) % tw
        cw = min(tw - sx, w - x)
        y = 0
        while y < h:
            sy = (y0 + y) % th
            ch = min(th - sy, h - y)
            out.paste(atlas.crop((sx, sy, sx + cw, sy + ch)), (x, y))
            y += ch
        x += cw
    return out


def warp_quad(atlas: Image.Image, quad, canvas_size, off) -> Image.Image | None:
    """Warp one Normal quad's cell crop onto its world parallelogram.

    Returns a canvas-sized RGBA layer (transparent outside the part), or None
    for degenerate geometry. Uses the UVs to crop (with REPEAT wrap, so UV-scaled
    parts sample correctly instead of running off the atlas) + flip-correct, then
    a single affine maps the rectangular cell onto the destination parallelogram
    (Normal parts are affine, so 4 corners form a parallelogram).
    """
    us = [u for (u, v) in quad.uvs]
    vs = [v for (u, v) in quad.uvs]
    u0, u1 = min(us), max(us)
    v0, v1 = min(vs), max(vs)
    w = int(round(u1 - u0))
    h = int(round(v1 - v0))
    if w <= 0 or h <= 0:
        return None
    crop = _wrap_atlas(atlas, int(round(u0)), int(round(v0)), w, h)

    # Flip so crop pixel (0,0) is the LT corner's texel.
    if quad.uvs[0][0] > quad.uvs[1][0]:   # LT.u > RT.u -> horizontally flipped
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if quad.uvs[0][1] > quad.uvs[2][1]:   # LT.v > LB.v -> vertically flipped
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)

    ox, oy = off
    d_lt = (quad.positions[0][0] + ox, quad.positions[0][1] + oy)
    d_rt = (quad.positions[1][0] + ox, quad.positions[1][1] + oy)
    d_lb = (quad.positions[2][0] + ox, quad.positions[2][1] + oy)

    # Forward affine: dest = M . local + t, local in [0,w]x[0,h].
    m00 = (d_rt[0] - d_lt[0]) / w
    m10 = (d_rt[1] - d_lt[1]) / w
    m01 = (d_lb[0] - d_lt[0]) / h
    m11 = (d_lb[1] - d_lt[1]) / h
    det = m00 * m11 - m01 * m10
    if abs(det) < 1e-9:
        return None
    # Inverse (dest->local) for PIL's AFFINE (which samples output->input).
    i00 = m11 / det
    i01 = -m01 / det
    i10 = -m10 / det
    i11 = m00 / det
    tx, ty = d_lt
    a, b = i00, i01
    c = -(i00 * tx + i01 * ty)
    d, e = i10, i11
    f = -(i10 * tx + i11 * ty)
    return crop.transform(canvas_size, Image.AFFINE, (a, b, c, d, e, f),
                          resample=Image.BILINEAR)


def scale_alpha(layer: Image.Image, factor: float) -> Image.Image:
    if factor >= 0.999:
        return layer
    r, g, bb, al = layer.split()
    al = al.point(lambda v: int(v * factor))
    return Image.merge("RGBA", (r, g, bb, al))


def _avg_color(colors) -> tuple:
    n = float(len(colors)) or 1.0
    return tuple(sum(c[i] for c in colors) / n for i in range(4))


def _avg_rate(rates) -> float:
    return sum(rates) / float(len(rates)) if rates else 0.0


def tint_layer(layer: Image.Image, blend: int, color, rate: float) -> Image.Image:
    """Apply a flat ``parts_color`` tint to an RGBA layer (per-channel LUT).

    Implements the PartColor formula (``eval_partcolor``)
    as a per-channel linear op out = pixel*S + O. Uniform-colour approximation
    of the per-vertex gradient; alpha is left untouched (handled separately).
    """
    vx, vy, vz = framedata.partcolor_varg(blend, rate)
    r, g, bb, al = layer.split()
    out = []
    for ci, ch in enumerate((r, g, bb)):
        cc = color[ci]
        if vz >= 0.5:   # Mul: per-channel multiply, no offset
            s, o = vx + cc * vy, 0.0
        else:           # Mix / Add / Sub: scalar scale + colour offset
            s, o = vx, cc * vy
        lut = [max(0, min(255, int(round((v / 255.0 * s + o) * 255.0))))
               for v in range(256)]
        out.append(ch.point(lut))
    return Image.merge("RGBA", (out[0], out[1], out[2], al))


def render_animation(ssab_path: str, anim: str | None, out_dir: str,
                     bg_hex: str = "404040"):
    data = open(ssab_path, "rb").read()
    meta = SsabMeta(data)
    base = os.path.dirname(os.path.abspath(ssab_path))
    atlases = load_atlases(meta, base)
    anims = meta.animations()
    if not anims:
        raise SystemExit("no animations in .ssab")
    a0 = next((a for a in anims if a.name == anim), anims[0])

    lib = ssruntime.load_library()
    rt = ssruntime.SSRuntime(lib)
    rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                 origin=ssruntime.ORIGIN_CENTER)
    rt.load_ssab_bytes(data)
    if not rt.setup_animation(a0.name):
        raise SystemExit(f"setup_animation({a0.name!r}) failed")
    fps = rt.frame_rate or a0.fps or 30
    total = max(1, a0.total_frame)
    dt = 1.0 / fps

    # Pass 1: capture per-frame quad lists + global bbox.
    rt.set_loop_count(-1)
    rt.play()
    frames_quads = []
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for fr in range(total):
        frame_no = rt.update(dt)
        fb = rt.get_frame_data(frame_no)
        fd = framedata.parse(fb)
        parts = framedata.build_mesh_parts(rt, fd)
        # copy values out before the next Brain call invalidates the SoA buffers
        snap = [(p.texture_hash, p.blend_type, p.color_blend,
                 _avg_color(p.colors), _avg_rate(p.rates), p.has_partcolor,
                 list(p.positions[:4]), list(p.uvs[:4])) for p in parts]
        frames_quads.append(snap)
        for rec in snap:
            for (x, y) in rec[6]:
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
    rt.close()

    if not math.isfinite(minx):
        raise SystemExit("no visible Normal geometry to render")
    margin = 12
    off = (-minx + margin, -miny + margin)
    cw = int(math.ceil(maxx - minx)) + 2 * margin
    ch = int(math.ceil(maxy - miny)) + 2 * margin
    canvas_size = (cw, ch)
    bg = tuple(int(bg_hex[i:i + 2], 16) for i in (0, 2, 4)) + (255,)

    os.makedirs(out_dir, exist_ok=True)
    gif_frames = []

    class _Q:  # tiny adapter so warp_quad can read .positions/.uvs
        __slots__ = ("texture_hash", "blend_type", "alpha", "positions", "uvs")

    for fr, snap in enumerate(frames_quads):
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        for (th, bl, cb, col, rate, has_pc, pos, uv) in snap:
            atlas = atlases.get(th)
            if atlas is None:
                continue
            q = _Q()
            q.texture_hash, q.blend_type, q.alpha = th, bl, col[3]
            q.positions, q.uvs = pos, uv
            layer = warp_quad(atlas, q, canvas_size, off)
            if layer is None:
                continue
            if has_pc:                      # parts_color tint (flat approx)
                layer = tint_layer(layer, cb, col, rate)
            layer = scale_alpha(layer, col[3])
            # Additive-blend parts are composited as normal alpha here; the
            # GPU path handles Add.
            canvas = Image.alpha_composite(canvas, layer)
        # composite over solid bg for viewing
        framed = Image.new("RGBA", canvas_size, bg)
        framed = Image.alpha_composite(framed, canvas)
        gif_frames.append(framed.convert("RGB"))
        if fr == total // 2:
            # transparent still for inspection
            canvas.save(os.path.join(out_dir, "still.png"))
            framed.convert("RGB").save(os.path.join(out_dir, "still_bg.png"))

    name = os.path.splitext(os.path.basename(ssab_path))[0]
    gif_path = os.path.join(out_dir, f"{name}_{a0.name}.gif")
    gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:],
                       duration=int(1000 / fps), loop=0, optimize=True)
    print(f"canvas={cw}x{ch}  frames={total}  fps={fps}  "
          f"parts/frame~{len(frames_quads[total // 2])}")
    print(f"wrote: {gif_path}")
    print(f"wrote: {os.path.join(out_dir, 'still.png')} (transparent)")
    print(f"wrote: {os.path.join(out_dir, 'still_bg.png')}")
    return gif_path


def main(argv):
    ssab = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else \
        os.path.join(_GAME, "ss_assets", "overall", "Basic.ssab")
    anim = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else None
    out_dir = os.path.join(_ROOT, "out")
    if "--out" in argv:
        out_dir = argv[argv.index("--out") + 1]
    bg = "404040"
    if "--bg" in argv:
        bg = argv[argv.index("--bg") + 1].lstrip("#")
    render_animation(ssab, anim, out_dir, bg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
