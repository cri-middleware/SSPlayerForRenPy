"""Walk the per-frame FrameData draw plan and build render geometry.

This is the engine-independent render-data core. It turns the Brain's FlatBuffers
draw plan + SoA buffers into concrete quads the Ren'Py layer can blit / mesh.

Two render paths are provided, both for the ``Normal`` draw-batch kind:

* :func:`build_mesh_parts` resolves each part to a full triangulated mesh (4
  corners, or a 5-vertex centre fan when the part has free deform / per-vertex
  colour) with per-vertex colour from ``parts_color`` and the framebuffer +
  PartColor blend modes. This is what the mesh renderer consumes and is
  shear/free-deform exact.
* :func:`build_normal_quads` + :func:`decompose_quad` resolve each part to a
  *similarity* transform (center/rotate/scale/flip). Drops shear (tracked as
  ``skew_err``).

The z-ordered walk :func:`iter_draw_plan` additionally emits Mesh(deform) and
Shape parts (both as ``("mesh", MeshPart)`` — a Shape is a textureless
procedural polygon) plus Instance / Effect slots. The remaining kinds (Text,
Nines, Mask) are enumerated for diagnostics only — see :func:`classify_frame`.

SoA lifetime: the pointers returned by the runtime are valid only until the
next Brain call. Build geometry immediately after ``get_frame_data`` and do not
retain the raw buffers.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from ss.runtime.DrawBatch import DrawBatch
from ss.runtime.FrameData import FrameData
from ss.runtime.PartAttributePartColor import PartAttributePartColor
from ss.runtime.PartState import PartState
from ss.runtime.SsAttributePartColorKeyValueColor import (
    SsAttributePartColorKeyValueColor,
)
from ss.runtime.U8Color import U8Color
from ss.runtime.UpdateAttributeFlags import UpdateAttributeFlags

# DrawBatchKind (framedata.fbs)
KIND_NORMAL, KIND_SHAPE, KIND_INSTANCE, KIND_EFFECT = 0, 1, 2, 3
KIND_MESH, KIND_TEXT, KIND_NINES, KIND_MASK = 4, 5, 6, 7
KIND_NAMES = {0: "Normal", 1: "Shape", 2: "Instance", 3: "Effect",
              4: "Mesh", 5: "Text", 6: "Nines", 7: "Mask"}

BLEND_NAMES = {0: "Mix", 1: "Mul", 2: "Add", 3: "Sub", 4: "Mulalpha",
               5: "Screen", 6: "Exclusion", 7: "Invert", 8: "Mul2",
               9: "Div2", 10: "Screen2", 11: "Overlay2"}

# Kinds the Normal render path can emit.
RENDERABLE_KINDS = frozenset({KIND_NORMAL})

MASK_INFLUENCE = 0x01  # DrawBatch.flags bit

# SoA buffer strides (floats per part), mirroring the runtime's layout. The
# local-vertex and local-UV buffers share the same 10-float stride: 5 verts ×
# 2 coords (LT, RT, LB, RB, CENTER).
MATRIX_STRIDE = 16   # 4×4 world matrix, column-major
VERT_STRIDE = 10     # local vertices: LT,RT,LB,RB,CENTER × (x, y)
UV_STRIDE = 10       # local UVs: same layout, in texture-pixel space
CELL_STRIDE = 6      # cell meta: [pivot_x, pivot_y, size_w, size_h, rect_left, rect_top]
# Shape SoA: fixed 12 verts/part × (x, y) for local positions, and × (fx, fy)
# for the matching normalized bbox coords. Only the first shape_vertex_counts[p]
# slots are valid; the runtime caps a shape at 12 verts (star = 12).
SHAPE_STRIDE = 24

# Vertex order within a part (indices into the 5-vertex local position/UV arrays).
LT, RT, LB, RB, CENTER = 0, 1, 2, 3, 4

# -- PartColor blend (texel<->vertex-colour, shader-side) ---------------------
# This is a DIFFERENT axis from the framebuffer blend on DrawBatch.blend_type:
# PartColor blend mixes texel and vertex colour *inside the shader* and only the
# first four modes are valid; values >= 4 clamp to Mix.
PC_BLEND_MIX, PC_BLEND_MUL, PC_BLEND_ADD, PC_BLEND_SUB = 0, 1, 2, 3
PC_BLEND_NAMES = {0: "Mix", 1: "Mul", 2: "Add", 3: "Sub"}

# Coefficient table — (pixel_weight_adj, color_weight, mul_flag). The generic
# formula evaluated per fragment is
#   out_rgb = pixel*varg.x + mix(white, pixel, varg.z) * color * varg.y
# with varg = (1 + c.x*rate, c.y*rate, c.z). rate == 0 makes it a texel pass-
# through for every mode, which is exactly the part-colour-less default.
_PC_COEF = (
    (-1.0,  1.0, 0.0),   # Mix: lerp(pixel, color, rate)
    (-1.0,  1.0, 1.0),   # Mul: pixel * lerp(1, color, rate)
    ( 0.0,  1.0, 0.0),   # Add: pixel + color*rate
    ( 0.0, -1.0, 0.0),   # Sub: pixel - color*rate
)

# update_flag bits that mean "this part has explicit free deform / per-vertex
# colour" → the runtime then populates the 5th (centre) vertex and the part
# wants a triangle fan from the centre.
_CENTER_FLAGS = (UpdateAttributeFlags.AttributeVertex
                 | UpdateAttributeFlags.AttributePartColor)


def parse(fb) -> FrameData:
    return FrameData.GetRootAs(fb, 0)


# FrameData's vtable slots, from the generated FrameData.py. Each reader below
# checks its slot against the generated accessor before trusting it.
_FD_PARTS, _FD_PARTS_COLOR, _FD_DRAW_ORDER, _FD_DRAW_BATCHES = 4, 8, 16, 18
_U8 = struct.Struct('<B').unpack_from
_U16 = struct.Struct('<H').unpack_from
_U32 = struct.Struct('<I').unpack_from
_I32 = struct.Struct('<i').unpack_from


def _vector(tab, slot):
    """``(start, length)`` of the vector field at vtable ``slot`` of the
    FlatBuffers table ``tab``, or ``(0, 0)`` when it is absent: the generated
    accessors' Offset / Vector / VectorLen, in a few struct reads. A field that
    does not lead to a vector inside the buffer reads ``(0, -1)``, a length no
    accessor returns."""
    buf, pos = tab.Bytes, tab.Pos
    vt = pos - _I32(buf, pos)[0]
    if slot >= _U16(buf, vt)[0]:
        return 0, 0
    o = _U16(buf, vt + slot)[0]
    if not o:
        return 0, 0
    a = pos + o
    a += _U32(buf, a)[0]
    if a + 4 > len(buf):
        return 0, -1
    return a + 4, _U32(buf, a)[0]


# --- Bulk struct reads
# PartState and EffectDrawCommand are fixed-layout FlatBuffers *structs* stored in
# contiguous vectors, so the whole array decodes in ONE struct call instead of
# N × the per-element FlatBuffers accessor chain (Offset→Get→unpack→enforce),
# which profiling showed dominated frame CPU. The field offsets below MIRROR the
# generated PartState.py (regenerate via scripts/generate-fbs-code if the
# schema changes); the vector *base* is taken from the generated accessor so only
# the intra-struct layout is duplicated, and a one-time self-check vs the accessor
# disables the fast path automatically if it ever drifts.
_PS_SIZE = 144
# UpdateFlag u64@0, Alpha f32@48, Priority i32@56, Mask f32@108,
# PartColor i16@128, Shader i16@130, Hide bool@138 (little-endian). Priority/Mask
# are the per-frame mask attributes:
# Priority feeds draw order (the runtime already sorts draw_order, but we keep
# it for diagnostics) and Mask is the cutout value (0..255, a float despite the
# range). Shader indexes FrameData.shaders (the per-part user-shader effect;
# -1 = none).
_PS_REC = struct.Struct('<Q40xf4xi48xf16xhh6x?5x')
_ps_fastpath = None   # None = unvalidated, True = validated OK, False = disabled


class _PartLite:
    """Pre-decoded PartState fields for the render hot path.

    Exposes the same method names the draw-plan walk calls on a ``PartState`` so
    callers are unchanged, but the values come from one bulk ``struct`` decode
    rather than four-to-six per-part FlatBuffers accessor calls.
    """
    __slots__ = ('_uf', '_a', '_prio', '_mask', '_pc', '_shader', '_hide')

    def __init__(self, uf, a, prio, mask, pc, shader, hide):
        self._uf = uf
        self._a = a
        self._prio = prio
        self._mask = mask
        self._pc = pc
        self._shader = shader
        self._hide = hide

    def UpdateFlag(self): return self._uf
    def Alpha(self): return self._a
    def Priority(self): return self._prio
    def Mask(self): return self._mask
    def PartColor(self): return self._pc
    def Shader(self): return self._shader
    def Hide(self): return self._hide


def bulk_part_states(fd: FrameData):
    """All PartStates decoded in one pass → ``list[_PartLite]``, or ``None``.

    ``None`` means "use ``fd.Parts(p)``": no parts, the struct size changed, or
    the one-time layout self-check failed (schema drift → safe fallback).
    """
    global _ps_fastpath
    if _ps_fastpath is False:
        return None
    base, n = _vector(fd._tab, _FD_PARTS)
    if _ps_fastpath is None and n != fd.PartsLength():
        _ps_fastpath = False
        return None
    if n == 0 or PartState.SizeOf() != _PS_SIZE:
        return None
    blob = fd._tab.Bytes[base:base + n * _PS_SIZE]
    lite = [_PartLite(uf, a, prio, mask, pc, shader, hide)
            for (uf, a, prio, mask, pc, shader, hide) in _PS_REC.iter_unpack(blob)]
    if _ps_fastpath is None:
        p0 = fd.Parts(0)
        l0 = lite[0]
        if (p0 is None or base != p0._tab.Pos
                or l0._hide != p0.Hide() or l0._uf != p0.UpdateFlag()
                or l0._pc != p0.PartColor() or l0._shader != p0.Shader()
                or l0._prio != p0.Priority()
                or abs(l0._a - p0.Alpha()) > 1e-6
                or abs(l0._mask - p0.Mask()) > 1e-6):
            _ps_fastpath = False
            return None
        _ps_fastpath = True
    return lite


def hidden_parts(fd: FrameData, parts=None) -> set:
    """Owned set of part indices hidden on ``fd`` (for the part-query API).

    A tiny snapshot so callers can answer "is part N hidden?" *after* the
    FrameData buffer is gone — the analogue of the ``_last_wm`` matrix snapshot.
    Must run while ``fd``'s buffer is still valid (right after :func:`parse`,
    before any slot step), since a zero-copy ``get_frame_data_view`` buffer is
    invalidated by the instance/effect steps that follow.

    ``parts`` is an optional pre-decoded :func:`bulk_part_states` array — pass the
    frame's if you already have one, since the decode is per-frame work.
    """
    if parts is None:
        parts = bulk_part_states(fd)
    if parts is not None:
        return {i for i, ps in enumerate(parts) if ps.Hide()}
    hidden = set()
    for i in range(fd.PartsLength()):
        ps = fd.Parts(i)
        if ps is None or ps.Hide():
            hidden.add(i)
    return hidden


def clamp_pc_blend(blend_type: int) -> int:
    """Clamp a raw ``parts_color.blend_type`` to the 4 valid PartColor modes."""
    return blend_type if 0 <= blend_type <= 3 else PC_BLEND_MIX


def partcolor_coef(blend_idx: int) -> tuple:
    """The ``(cx, cy, cz)`` coefficient row for one PartColor mode.

    The rate-independent half of :func:`partcolor_varg`, so a renderer that packs
    ``varg`` per *vertex* can resolve the mode once per *part* without
    reimplementing the clamp — the mode table and its clamp stay owned here.
    """
    return _PC_COEF[clamp_pc_blend(blend_idx)]


def partcolor_varg(blend_idx: int, rate: float) -> tuple:
    """Build the ``varg`` coefficient triple for one vertex."""
    cx, cy, cz = partcolor_coef(blend_idx)
    return (1.0 + cx * rate, cy * rate, cz)


def pack_pc_mesh(parts, ox, oy, tw, th):
    """Pack a run of Normal / Shape parts into flat (geometry, attributes,
    indices) arrays for the render layer's PartColor mesh (a_tex_coord +
    a_ss_color + a_ss_varg) — the per-vertex build shared by the batched, masked
    and user-shader mesh draws.

    Per vertex: world position offset to screen px by (ox, oy); UV normalized
    by the atlas size (tw, th); per-corner PartColor RGBA + the shader ``varg``
    triple. Triangles are rebased by the running vertex count, so ``parts`` may
    be a single part (masked / user-shader draw) or a whole same-texture run
    (batched draw). Returns ``(geometry, attributes, indices, nverts)``.

    The hottest loop in the render layer (every vertex of every part, every
    frame), so the per-vertex work is kept to arithmetic on locals: the UV
    divisor and the PartColor coefficients are loop-invariant and resolved
    once per run / per part, and each vertex extends the flat arrays once. It
    lives here, not in ``spritestudio.rpy``, because a list built in a ``.rpy``
    is a ``RevertableList``: every extend is recorded for rollback and ``Mesh2``
    reads every item back through a Python method, which costs more than the
    packing itself.
    """
    geometry = []
    attributes = []
    indices = []
    base = 0
    inv_tw = (1.0 / tw) if tw > 0 else 1.0
    inv_th = (1.0 / th) if th > 0 else 1.0
    g_ext = geometry.extend
    a_ext = attributes.extend
    i_ext = indices.extend
    for mp in parts:
        cx, cy, cz = partcolor_coef(mp.color_blend)
        if mp.has_partcolor:
            for (x, y), (u, v), c, rate in zip(mp.positions, mp.uvs,
                                               mp.colors, mp.rates):
                g_ext((ox + x, oy + y))
                a_ext((u * inv_tw, v * inv_th, c[0], c[1], c[2], c[3],
                       1.0 + cx * rate, cy * rate, cz))
        else:
            # No PartColor on this part, i.e. every rate is 0, which collapses
            # varg to the constant (1, 0, cz) for EVERY mode — the texel
            # pass-through. Hoisting it drops the rate read and two multiplies
            # per vertex on what is the common case for most packs.
            for (x, y), (u, v), c in zip(mp.positions, mp.uvs, mp.colors):
                g_ext((ox + x, oy + y))
                a_ext((u * inv_tw, v * inv_th, c[0], c[1], c[2], c[3],
                       1.0, 0.0, cz))
        for (i, j, k) in mp.triangles:
            i_ext((base + i, base + j, base + k))
        base += len(mp.positions)
    return geometry, attributes, indices, base


def eval_partcolor(pixel_rgb, color_rgb, blend_idx: int, rate: float) -> tuple:
    """CPU reference of the PartColor fragment formula.

    ``pixel_rgb`` / ``color_rgb`` are 0..1 RGB triples. Returns the composited
    RGB. This is the authority the headless rasterizer and tests check against;
    the Ren'Py shader must reproduce it. ``rate == 0`` returns ``pixel_rgb``
    unchanged for every mode (the part-colour-less pass-through).
    """
    vx, vy, vz = partcolor_varg(blend_idx, rate)
    out = []
    for i in range(3):
        white_or_pixel = (1.0 - vz) + pixel_rgb[i] * vz   # mix(1, pixel, vz)
        out.append(pixel_rgb[i] * vx + white_or_pixel * color_rgb[i] * vy)
    return tuple(out)


@dataclass
class NormalQuad:
    """One Normal part resolved to world space for the current frame.

    ``positions`` / ``uvs`` are the 4 corners in LT, RT, LB, RB order.
    ``positions`` are world pixels (coordinate-system flip already applied by
    the runtime). ``uvs`` are in *texture pixel* space (divide by texture size
    to normalize). ``src_rect`` is the atlas crop ``(left, top, w, h)`` from
    ``cell_meta`` — enough to blit without parsing the cell table.
    """
    part_index: int
    texture_hash: int
    blend_type: int
    positions: list  # [(x, y)] * 4
    uvs: list        # [(u, v)] * 4  (texture pixels)
    src_rect: tuple  # (left, top, w, h)
    alpha: float
    mask_influence: bool


def _transform(m, vx, vy):
    # 4x4 column-major; 2D affine subset.
    # m00=m[0] m10=m[1] m01=m[4] m11=m[5] tx=m[12] ty=m[13]
    return (m[0] * vx + m[4] * vy + m[12],
            m[1] * vx + m[5] * vy + m[13])


def normalize_uvs(uvs, tex_w, tex_h) -> list:
    """Convert texture-*pixel* UVs to texture-*normalized* UVs (``uv / texsize``).

    The reference form of the rule, kept for ports and headless tools: the render
    hot path multiplies by a hoisted ``1 / texsize`` per run instead of calling
    this per part. Pure math, engine-independent — the equivalent of the reference
    players' ``uv * inv_tex_size`` UV normalize. Results may
    fall outside ``[0, 1]`` for UV-scaled / -translated / -rotated parts; the
    consumer must sample with **REPEAT** wrap (not clamp) to reproduce them — the
    runtime has already baked ``UvScale``/``UvTranslation``/``UvRotation`` into
    these UVs. Degenerate texture sizes pass the UVs through unchanged.
    """
    if tex_w <= 0 or tex_h <= 0:
        return [(u, v) for (u, v) in uvs]
    return [(u / tex_w, v / tex_h) for (u, v) in uvs]


@dataclass
class _NormalPart:
    """Per-part data shared by the quad and mesh builders.

    The common walk of the FrameData draw plan resolves this once per visible
    Normal part; both builders then project it onto their own output shape.
    ``positions`` / ``uvs`` carry all 5 verts (LT,RT,LB,RB,CENTER) — the quad path
    uses the first 4, the mesh path appends the centre only when it fans.
    """
    part_index: int
    ps: object               # PartState (kept for Alpha/UpdateFlag/PartColor)
    blend_type: int
    texture_hash: int
    mask_influence: bool
    positions: list          # [(x, y)] * 5 world  (LT,RT,LB,RB,CENTER)
    uvs: list                # [(u, v)] * 5 texture px
    src_rect: tuple          # (left, top, w, h)


def _read_normal_part(wm, lv, uv, cm, ps, p, blend, thash, mask):
    """Build a :class:`_NormalPart` for part ``p`` from the SoA buffers.

    The per-part SoA read shared by :func:`_iter_visible_normal_parts` and
    :func:`iter_draw_plan`. Must run while the SoA pointers are still valid
    (i.e. before the next Brain call).
    """
    mo = p * MATRIX_STRIDE
    vo = p * VERT_STRIDE
    uo = p * UV_STRIDE
    co = p * CELL_STRIDE
    mat = wm[mo:mo + MATRIX_STRIDE]
    positions = [_transform(mat, lv[vo + j * 2], lv[vo + j * 2 + 1])
                 for j in range(5)]   # LT, RT, LB, RB, CENTER
    uvs = [(uv[uo + j * 2], uv[uo + j * 2 + 1]) for j in range(5)]
    src_rect = (cm[co + 4], cm[co + 5], cm[co + 2], cm[co + 3])
    return _NormalPart(
        part_index=p, ps=ps, blend_type=blend, texture_hash=thash,
        mask_influence=mask, positions=positions, uvs=uvs, src_rect=src_rect)


def _read_mesh_part(mesh_soa, ps, p, blend, thash, mask):
    """Build a :class:`MeshPart` for a Mesh(deform) part from the mesh SoA.

    Vertices are pre-computed WORLD coords (``x``/``y`` SoA), UVs are
    interleaved texture-pixel at ``vertex_offset*2``, indices are part-local
    0-based, and the offset arrays are CSR (length ``num_parts+1``). Returns
    ``None`` for an empty/degenerate range (non-Mesh part, bad offsets). Colour
    is the part's hierarchical alpha on white (Mesh ``parts_color``
    (Whole-only) tint is not applied).
    """
    (mvx, nvx), (mvy, _nvy), (muv, nuv), (midx, ni), (voff, nvo), (ioff, nio) = mesh_soa
    if not mvx or not voff or not ioff:
        return None
    if p + 1 >= nvo or p + 1 >= nio:
        return None
    v0, v1 = voff[p], voff[p + 1]
    if v1 <= v0 or v1 > nvx or v1 * 2 > nuv:
        return None
    i0, i1 = ioff[p], ioff[p + 1]
    if i1 <= i0 or (i1 - i0) % 3 != 0 or i1 > ni:
        return None
    n = v1 - v0
    # One list per buffer: the loops below index each element, and indexing a
    # list is cheaper than indexing the SoA view.
    xs = mvx[v0:v1].tolist()
    ys = mvy[v0:v1].tolist()
    us = muv[v0 * 2:v1 * 2].tolist()              # interleaved u, v
    idx = midx[i0:i1].tolist()
    positions = [(xs[k], ys[k]) for k in range(n)]                  # world
    uvs = [(us[k * 2], us[k * 2 + 1]) for k in range(n)]            # tex px
    alpha = max(0.0, min(1.0, ps.Alpha()))
    colors = [(1.0, 1.0, 1.0, alpha)] * n
    rates = [0.0] * n
    tris = [(idx[t], idx[t + 1], idx[t + 2]) for t in range(0, i1 - i0, 3)]
    return MeshPart(
        part_index=p, texture_hash=thash, blend_type=blend,
        color_blend=PC_BLEND_MIX, positions=positions, uvs=uvs, colors=colors,
        rates=rates, triangles=tris, src_rect=(0, 0, 0, 0),
        mask_influence=mask, use_center=False, has_partcolor=False)


def _read_shape_part(shape_soa, wm, wn, fd, ps, p, blend, mask, pcs=None):
    """Build a :class:`MeshPart` for a Shape part from the shape SoA.

    Shape parts are textureless procedural polygons (Rectangle / Triangle /
    Star / Arrow). The runtime emits, per part, up to 12 LOCAL vertices
    (post-pivot, post-coord-system) laid out as a TRIANGLE_FAN from vertex 0,
    plus matching normalized bbox coords ((0, 0) = LT .. (1, 1) = RB). Positions
    are sent through the part's world matrix (exactly like a Normal part's local
    vertices); the fill is the PartColor with ``rate`` forced to 1.0 — a shape
    has no texel to blend against, so the (white) texture
    supplied by the render layer is fully replaced by the interpolated corner
    colour. Returns ``None`` for a non-shape part or a degenerate range
    (<3 valid verts, e.g. a size-collapsed shape).
    """
    (sv, nsv), (sb, nsb), (sc, nsc) = shape_soa
    if not sv or not sc or p >= nsc:
        return None
    count = int(sc[p])
    if count < 3:
        return None
    mo = p * MATRIX_STRIDE
    so = p * SHAPE_STRIDE
    if mo + MATRIX_STRIDE > wn or so + count * 2 > nsv or so + count * 2 > nsb:
        return None
    mat = wm[mo:mo + MATRIX_STRIDE]
    # One list per buffer, as in _read_mesh_part.
    lv = sv[so:so + count * 2].tolist()
    bc = sb[so:so + count * 2].tolist()
    positions = [_transform(mat, lv[j * 2], lv[j * 2 + 1]) for j in range(count)]

    # Per-vertex colour: bilinear-interpolate the four PartColor corners across
    # the shape's bbox (fx, fy). ``part_colors`` returns [LT, RT, LB, RB]; a part
    # with no ``parts_color`` entry gets white × hierarchical alpha (so a shape
    # still fills solid).
    #
    # A Shape **bypasses the PartColor blend formula**: a
    # textureless shape has no texel to blend against, so the blend mode is
    # FORCED to Mix and the rate to 1.0 — the fill is the interpolated corner
    # colour itself, regardless of the part's authored PartColor blend (Add/Sub
    # against the white texel would otherwise blow out / invert). The authored
    # ``blend`` from ``part_colors`` is intentionally discarded.
    _authored_blend, corners = part_colors(fd, ps, pcs)
    lt, rt, lb, rb = corners
    # Corner colours are loop-invariant — hoist the four .rgba reads out of the
    # per-vertex loop; only the bbox weights (fx, fy) vary per vertex.
    c0, c1, c2, c3 = lt.rgba, rt.rgba, lb.rgba, rb.rgba
    colors = []
    for j in range(count):
        fx, fy = bc[j * 2], bc[j * 2 + 1]
        w0 = (1.0 - fx) * (1.0 - fy)            # LT, RT, LB, RB weights
        w1 = fx * (1.0 - fy)
        w2 = (1.0 - fx) * fy
        w3 = fx * fy
        colors.append((
            c0[0] * w0 + c1[0] * w1 + c2[0] * w2 + c3[0] * w3,
            c0[1] * w0 + c1[1] * w1 + c2[1] * w2 + c3[1] * w3,
            c0[2] * w0 + c1[2] * w1 + c2[2] * w2 + c3[2] * w3,
            c0[3] * w0 + c1[3] * w1 + c2[3] * w2 + c3[3] * w3,
        ))
    rates = [1.0] * count
    # TRIANGLE_FAN from vertex 0 (centre for rect/tri/star; leading corner for
    # arrow). count-2 triangles; the closing vertex makes the fan wrap.
    tris = [(0, i, i + 1) for i in range(1, count - 1)]
    return MeshPart(
        part_index=p, texture_hash=0, blend_type=blend, color_blend=PC_BLEND_MIX,
        positions=positions, uvs=[(0.0, 0.0)] * count, colors=colors,
        rates=rates, triangles=tris, src_rect=(0, 0, 0, 0),
        mask_influence=mask, use_center=False, has_partcolor=True)


def _iter_visible_normal_parts(rt, fd: FrameData):
    """Yield a :class:`_NormalPart` for each visible Normal part of ``fd``.

    The single source of truth for walking the draw plan + reading the SoA
    buffers. Must be iterated right after ``rt.get_frame_data`` for the same frame
    — the SoA pointers are valid only until the next Brain call.
    """
    wm, _ = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    if not wm or not lv:
        return

    parts = bulk_part_states(fd)
    do = _draw_order_array(fd)
    for (start, count, thash, _vc, _ic, blend, kind, flags) in _draw_batch_list(fd):
        if kind != KIND_NORMAL:
            continue
        mask = bool(flags & MASK_INFLUENCE)
        for k in range(count):
            p = do[start + k]
            ps = parts[p] if parts is not None else fd.Parts(p)
            if ps is None or ps.Hide():
                continue
            yield _read_normal_part(wm, lv, uv, cm, ps, p, blend, thash, mask)


def build_normal_quads(rt, fd: FrameData) -> list:
    """Resolve every visible Normal part of ``fd`` into world-space quads.

    ``rt`` is an :class:`ss_renpy.ssruntime.SSRuntime`. Must be called right
    after ``rt.get_frame_data`` for the same frame (SoA buffers are transient).
    """
    quads = []
    for part in _iter_visible_normal_parts(rt, fd):
        quads.append(NormalQuad(
            part_index=part.part_index, texture_hash=part.texture_hash,
            blend_type=part.blend_type, positions=part.positions[:4],
            uvs=part.uvs[:4], src_rect=part.src_rect,
            alpha=part.ps.Alpha(), mask_influence=part.mask_influence))
    return quads


@dataclass
class Placement:
    """A Normal quad decomposed into a center + similarity transform.

    A blit + ``Transform`` cannot express a free 2x4 quad, only
    translate/rotate/scale/flip about a center. SS Normal parts are affine, so the
    only thing this *drops* is shear — captured as ``skew_err`` (max corner
    reprojection error in px). For typical VN parts ``skew_err`` is ~0; large
    values flag a part this form renders slightly wrong.

    Angles are degrees; ``rotation_deg`` is measured so that rotating the +x
    axis by it lands on the top edge (atan2 convention, in the Y-down screen
    space the runtime already produced). ``mirror`` means a horizontal flip.
    """
    center: tuple        # world (x, y)
    rotation_deg: float
    xscale: float
    yscale: float
    mirror: bool
    skew_err: float
    src_rect: tuple      # (left, top, w, h) in atlas px
    alpha: float
    texture_hash: int
    blend_type: int


def reconstruct_corners(p: Placement) -> list:
    """Inverse of :func:`decompose_quad` for verification.

    Rebuilds LT, RT, LB, RB world corners from the placement. Compared against
    the original quad, the gap is the shear this form cannot represent.
    """
    _, _, w, h = p.src_rect
    cx, cy = p.center
    a = math.radians(p.rotation_deg)
    ca, sa = math.cos(a), math.sin(a)
    u = (ca, sa)            # top-edge (local +x) direction, unit
    v = (-sa, ca)           # perpendicular (local +y), right-handed in Y-down
    # Rotation is locked to the top edge, so x is never flipped; a negative
    # determinant ("mirror") shows up as the y-basis flipping — i.e. negative
    # yzoom in Ren'Py terms.
    ex = (p.xscale * u[0], p.xscale * u[1])     # world delta per source x px
    sy = -p.yscale if p.mirror else p.yscale
    ey = (sy * v[0], sy * v[1])                 # world delta per source y px
    corners = []
    for (lx, ly) in ((-w / 2, -h / 2), (w / 2, -h / 2),
                     (-w / 2, h / 2), (w / 2, h / 2)):
        corners.append((cx + lx * ex[0] + ly * ey[0],
                        cy + lx * ex[1] + ly * ey[1]))
    return corners


def placement_from_corners(positions, src_rect) -> tuple:
    """Similarity fit of 4 world corners (LT, RT, LB, RB) + ``src_rect``.

    Pure geometry shared by :func:`decompose_quad` (``NormalQuad``) and the
    Ren'Py Transform backend (``MeshPart`` corners). Returns
    ``(center, rotation_deg, xscale, yscale, mirror)``; shear is dropped (the
    caller measures the residual). Degenerate cells return a zero placement.
    """
    lt, rt, lb, rb = positions[0], positions[1], positions[2], positions[3]
    _, _, w, h = src_rect
    if w <= 0 or h <= 0:
        return ((0.0, 0.0), 0.0, 0.0, 0.0, False)
    ex = (rt[0] - lt[0], rt[1] - lt[1])   # spans w source px
    ey = (lb[0] - lt[0], lb[1] - lt[1])   # spans h source px
    xscale = math.hypot(*ex) / w
    yscale = math.hypot(*ey) / h
    rotation = math.degrees(math.atan2(ex[1], ex[0]))
    mirror = (ex[0] * ey[1] - ex[1] * ey[0]) < 0
    center = ((lt[0] + rb[0]) / 2.0, (lt[1] + rb[1]) / 2.0)
    return (center, rotation, xscale, yscale, mirror)


def decompose_quad(q: NormalQuad) -> Placement:
    """Decompose a Normal quad into center / rotation / scale / mirror.

    Uses the top edge (RT-LT) and left edge (LB-LT) of the world parallelogram.
    Records ``skew_err`` so callers know how faithful the approximation is.
    """
    center, rotation, xscale, yscale, mirror = placement_from_corners(
        q.positions, q.src_rect)
    p = Placement(center, rotation, xscale, yscale, mirror, 0.0,
                  q.src_rect, q.alpha, q.texture_hash, q.blend_type)
    if q.src_rect[2] <= 0 or q.src_rect[3] <= 0:
        return p
    # skew residual: how far the rebuilt corners drift from the real ones.
    rec = reconstruct_corners(p)
    p.skew_err = max(math.hypot(rc[0] - oc[0], rc[1] - oc[1])
                     for rc, oc in zip(rec, q.positions))
    return p


# ---------------------------------------------------------------------------
# Full-fidelity mesh path (shear / free-deform exact + vertex colour)
# ---------------------------------------------------------------------------

@dataclass
class VertexColor:
    """One vertex's PartColor: RGBA (0..1) plus the texel blend ``rate``.

    ``rgba.a`` already has the part's hierarchical alpha pre-multiplied
    (SCHEMA.md) — never re-multiply
    by ``PartState.alpha``. ``rate`` is the texel<->colour blend strength;
    ``0`` = texel pass-through.
    """
    rgba: tuple   # (r, g, b, a) floats 0..1
    rate: float


_WHITE_OPAQUE = VertexColor((1.0, 1.0, 1.0, 1.0), 0.0)


# Default for a part with no ``parts_color`` entry:
# white, hierarchical alpha, rate 0 → the
# generic formula returns the raw texel, so the renderer needs no separate
# "has part colour?" branch.
def _default_vertex_color(alpha: float) -> VertexColor:
    # Opaque is by far the common case, so it returns a shared instance (callers
    # only ever read a VertexColor) and skips the clamp. Spelled ``not <`` rather
    # than ``>=`` so a NaN alpha still lands here, exactly as the
    # ``max(0, min(1, alpha))`` clamp below it used to.
    if not (alpha < 1.0):
        return _WHITE_OPAQUE
    return VertexColor((1.0, 1.0, 1.0, max(0.0, alpha)), 0.0)


def _read_corner(kv) -> VertexColor:
    rect = kv.Rgba(U8Color())
    return VertexColor(
        (rect.R() / 255.0, rect.G() / 255.0, rect.B() / 255.0, rect.A() / 255.0),
        kv.Rate())


# --- Bulk PartColor decode (same idea as bulk_part_states) ------------------
# PartAttributePartColor is a fixed 36-byte FlatBuffers *struct* in a contiguous
# vector, so the whole PartsColor array decodes in ONE struct pass instead of
# N parts x 4 corners x ~5 accessor chains (profiling showed part_colors
# dominating FramePlan CPU on colour-heavy packs). Layout MIRRORS the generated
# PartAttributePartColor.py (regenerate via scripts/generate-fbs-code if the
# schema changes): BlendType u8@0 (+3 pad), then Lt/Rt/Lb/Rb key-values at 4/12/
# 20/28, each an RGBA byte quad (A,R,G,B) + f32 rate. A one-time self-check vs the
# accessor path disables the fast path automatically if the layout ever drifts.
_PC_SIZE = 36
_PC_REC = struct.Struct('<B3x' + 'BBBBf' * 4)   # blend, (A,R,G,B,rate) x4
_pc_fastpath = None   # None = unvalidated, True = validated OK, False = disabled


def _decode_pc_record(rec) -> tuple:
    """One ``_PC_REC`` tuple -> ``(blend, [lt, rt, lb, rb])`` VertexColors.

    ``rec`` is ``(blend, a,r,g,b,rate, a,r,g,b,rate, ...)`` — the RGBA bytes are
    stored A,R,G,B (see U8Color), so re-order to the (R,G,B,A) VertexColor tuple.
    """
    corners = []
    o = 1
    for _ in range(4):
        a, r, g, b, rate = rec[o], rec[o + 1], rec[o + 2], rec[o + 3], rec[o + 4]
        corners.append(VertexColor(
            (r / 255.0, g / 255.0, b / 255.0, a / 255.0), rate))
        o += 5
    return (clamp_pc_blend(rec[0]), corners)


def bulk_part_colors(fd: FrameData):
    """All PartColor entries decoded in one pass → ``list`` indexed by
    ``PartState.part_color()``, or ``None`` (empty / size drift / self-check
    failed → callers fall back to :func:`part_colors`' accessor path)."""
    global _pc_fastpath
    if _pc_fastpath is False:
        return None
    base, n = _vector(fd._tab, _FD_PARTS_COLOR)
    if _pc_fastpath is None and n != fd.PartsColorLength():
        _pc_fastpath = False
        return None
    if n == 0 or PartAttributePartColor.SizeOf() != _PC_SIZE:
        return None
    blob = fd._tab.Bytes[base:base + n * _PC_SIZE]
    out = [_decode_pc_record(rec) for rec in _PC_REC.iter_unpack(blob)]
    if _pc_fastpath is None:
        p0 = fd.PartsColor(0)
        if p0 is None or base != p0._tab.Pos:
            _pc_fastpath = False
            return None
        # Validate the WHOLE record against the accessor path, not just the LT
        # corner: SizeOf() cannot catch a same-size field reorder, so a partial
        # check could let RT/LB/RB decode wrong while the fast path still
        # reports "validated OK". The four corners live at struct offsets
        # 4/12/20/28 (see _PC_REC).
        ref_b = clamp_pc_blend(p0.BlendType())
        ref_corners = (
            _read_corner(p0.Lt(SsAttributePartColorKeyValueColor())),
            _read_corner(p0.Rt(SsAttributePartColorKeyValueColor())),
            _read_corner(p0.Lb(SsAttributePartColorKeyValueColor())),
            _read_corner(p0.Rb(SsAttributePartColorKeyValueColor())),
        )
        got_b, got_corners = out[0]
        ok = (got_b == ref_b)
        if ok:
            for gc, rc in zip(got_corners, ref_corners):
                if (gc.rate != rc.rate
                        or any(abs(gc.rgba[i] - rc.rgba[i]) > 1e-6
                               for i in range(4))):
                    ok = False
                    break
        if not ok:
            _pc_fastpath = False
            return None
        _pc_fastpath = True
    return out


def part_colors(fd: FrameData, ps, pcs=None) -> tuple:
    """Resolve a part's per-corner colour: ``(blend_idx, [lt, rt, lb, rb])``.

    ``blend_idx`` is clamped to the 4 valid PartColor modes. Parts without a
    ``parts_color`` entry (``PartState.part_color() < 0``) get the white /
    rate-0 default on all four corners.
    Only the Normal-part rule (four corners individual) is applied here; Mesh
    (Whole-only) and Shape (rate forced 1.0) are handled by their own builders.

    ``pcs`` is an optional pre-decoded :func:`bulk_part_colors` array; when given
    (the render hot path) the entry is read from it instead of the per-corner
    FlatBuffers accessor chain.
    """
    cidx = ps.PartColor()
    if cidx is None or cidx < 0:
        vc = _default_vertex_color(ps.Alpha())
        return (PC_BLEND_MIX, [vc, vc, vc, vc])
    if pcs is not None and 0 <= cidx < len(pcs):
        return pcs[cidx]
    pc = fd.PartsColor(cidx)
    if pc is None:
        vc = _default_vertex_color(ps.Alpha())
        return (PC_BLEND_MIX, [vc, vc, vc, vc])
    blend = clamp_pc_blend(pc.BlendType())
    corners = [
        _read_corner(pc.Lt(SsAttributePartColorKeyValueColor())),
        _read_corner(pc.Rt(SsAttributePartColorKeyValueColor())),
        _read_corner(pc.Lb(SsAttributePartColorKeyValueColor())),
        _read_corner(pc.Rb(SsAttributePartColorKeyValueColor())),
    ]
    return (blend, corners)


@dataclass
class MeshPart:
    """One Normal part resolved to a triangulated, coloured world-space mesh.

    Vertex order is LT, RT, LB, RB (+ centre as vertex 4 when ``use_center``).
    ``positions`` are world pixels (coordinate flip already applied by the
    runtime). ``uvs`` are texture-*pixel* coordinates — divide by the atlas
    size to normalize. ``colors`` / ``rates`` feed the PartColor shader formula
    (:func:`eval_partcolor`); ``color_blend`` selects the mode. ``blend_type``
    is the separate *framebuffer* blend (DrawBatch.blend_type, 12 modes).
    ``triangles`` indexes into the vertex arrays.
    """
    part_index: int
    texture_hash: int
    blend_type: int          # framebuffer blend (DrawBatch.blend_type)
    color_blend: int         # PartColor blend 0..3 (shader-side)
    positions: list          # [(x, y)] world
    uvs: list                # [(u, v)] texture px
    colors: list             # [(r, g, b, a)] 0..1
    rates: list              # [float]
    # [(i, j, k)] into the vertex arrays. A fixed-topology part (the quad / centre
    # fan of a Normal part) shares one of the module-level tuples, so treat this
    # as read-only — copy before mutating (as transform_mesh_part / mask do).
    triangles: tuple | list
    src_rect: tuple          # (left, top, w, h) atlas px
    mask_influence: bool
    use_center: bool         # 5-vertex fan (free deform / per-vertex colour)
    has_partcolor: bool      # any corner rate > 0 (i.e. colour actually applied)
    # User-shader effect (SS6 ss-* family). ``shader_id_hash`` is the runtime's
    # fnv1a(name) of the assigned shader (0 = none / Default); ``shader_params``
    # is the (param0..param7) tuple driving it (empty when no shader). The render
    # layer maps the hash to a registered GLSL variant and binds the params; the
    # shader is orthogonal to the geometry, so it is NOT part of equality.
    shader_id_hash: int = 0
    shader_params: tuple = ()
    # Masking: a ``ss_renpy.mask.MaskApply``
    # when this part is a masked target this frame, else None. Set by the mask
    # layer after the draw plan is built (the render layer reads it to bind
    # coverage + replay the stencil); it is intentionally NOT part of the
    # equality/identity of the geometry.
    mask: object = None


def _avg(seq):
    seq = list(seq)
    return sum(seq) / float(len(seq)) if seq else 0.0


def read_shader(fd: FrameData, ps) -> tuple:
    """Resolve a part's user-shader effect → ``(id_hash, params)``.

    The shader applies
    only when the ``AttributeShader`` flag is set and ``PartState.shader`` indexes
    a valid ``FrameData.shaders`` entry. ``id_hash`` is the runtime's fnv1a of the
    shader name (e.g. ``fnv1a("ss-sepia")``); ``params`` is the 8-float
    ``(param0..param7)`` tuple. Returns ``(0, ())`` when no shader is present.
    """
    idx = ps.Shader()
    if (idx is not None and idx >= 0
            and (ps.UpdateFlag() & UpdateAttributeFlags.AttributeShader)
            and idx < fd.ShadersLength()):
        sh = fd.Shaders(idx)
        if sh is not None:
            return (sh.IdHash(), (sh.Param0(), sh.Param1(), sh.Param2(),
                                  sh.Param3(), sh.Param4(), sh.Param5(),
                                  sh.Param6(), sh.Param7()))
    return (0, ())


_TRIS_QUAD = ((LT, RT, LB), (RT, RB, LB))
_TRIS_FAN = ((CENTER, LT, RT), (CENTER, RT, RB),
             (CENTER, RB, LB), (CENTER, LB, LT))


def _read_normal_mesh_part(wm, lv, uv, cm, fd: FrameData, ps, p: int,
                           blend: int, thash: int, mask: bool, pcs=None) -> MeshPart:
    """Build a MeshPart directly from the SoA buffers, bypassing intermediate _NormalPart."""
    cblend, corners = part_colors(fd, ps, pcs)
    shader_id, shader_params = read_shader(fd, ps)

    mo = p * MATRIX_STRIDE
    vo = p * VERT_STRIDE
    uo = p * UV_STRIDE
    co = p * CELL_STRIDE
    m0, m1, _, _, m4, m5, _, _, _, _, _, _, tx, ty, _, _ = wm[mo:mo + MATRIX_STRIDE]

    use_center = bool(ps.UpdateFlag() & _CENTER_FLAGS)
    colors = [c.rgba for c in corners]
    rates = [c.rate for c in corners]
    has_pc = any(r > 0.0 for r in rates)

    if use_center:
        x0, y0, x1, y1, x2, y2, x3, y3, x4, y4 = lv[vo:vo + 10]
        u0, v0, u1, v1, u2, v2, u3, v3, u4, v4 = uv[uo:uo + 10]
        positions = [(m0 * x0 + m4 * y0 + tx, m1 * x0 + m5 * y0 + ty),
                     (m0 * x1 + m4 * y1 + tx, m1 * x1 + m5 * y1 + ty),
                     (m0 * x2 + m4 * y2 + tx, m1 * x2 + m5 * y2 + ty),
                     (m0 * x3 + m4 * y3 + tx, m1 * x3 + m5 * y3 + ty),
                     (m0 * x4 + m4 * y4 + tx, m1 * x4 + m5 * y4 + ty)]
        uvs = [(u0, v0), (u1, v1), (u2, v2), (u3, v3), (u4, v4)]
        c0, c1, c2, c3 = colors
        colors.append(((c0[0] + c1[0] + c2[0] + c3[0]) * 0.25,
                       (c0[1] + c1[1] + c2[1] + c3[1]) * 0.25,
                       (c0[2] + c1[2] + c2[2] + c3[2]) * 0.25,
                       (c0[3] + c1[3] + c2[3] + c3[3]) * 0.25))
        r0, r1, r2, r3 = rates
        rates.append((r0 + r1 + r2 + r3) * 0.25)
        tris = _TRIS_FAN
    else:
        x0, y0, x1, y1, x2, y2, x3, y3 = lv[vo:vo + 8]
        u0, v0, u1, v1, u2, v2, u3, v3 = uv[uo:uo + 8]
        positions = [(m0 * x0 + m4 * y0 + tx, m1 * x0 + m5 * y0 + ty),
                     (m0 * x1 + m4 * y1 + tx, m1 * x1 + m5 * y1 + ty),
                     (m0 * x2 + m4 * y2 + tx, m1 * x2 + m5 * y2 + ty),
                     (m0 * x3 + m4 * y3 + tx, m1 * x3 + m5 * y3 + ty)]
        uvs = [(u0, v0), (u1, v1), (u2, v2), (u3, v3)]
        tris = _TRIS_QUAD

    _, _, cw, ch, cl, ct = cm[co:co + CELL_STRIDE]
    return MeshPart(
        part_index=p, texture_hash=thash, blend_type=blend, color_blend=cblend,
        positions=positions, uvs=uvs, colors=colors, rates=rates, triangles=tris,
        src_rect=(cl, ct, cw, ch), mask_influence=mask, use_center=use_center,
        has_partcolor=has_pc, shader_id_hash=shader_id, shader_params=shader_params)


def _mesh_part_from(fd: FrameData, part: _NormalPart, pcs=None) -> MeshPart:
    """Project one resolved :class:`_NormalPart` to a coloured triangulated mesh.

    The per-part half of :func:`build_mesh_parts`, factored out so the z-ordered
    :func:`iter_draw_plan` walk can reuse it. ``pcs`` is an optional pre-decoded
    :func:`bulk_part_colors` array (see :func:`part_colors`).
    """
    ps = part.ps
    cblend, corners = part_colors(fd, ps, pcs)
    shader_id, shader_params = read_shader(fd, ps)

    positions = list(part.positions[:4])             # LT, RT, LB, RB
    uvs = list(part.uvs[:4])
    colors = [c.rgba for c in corners]
    rates = [c.rate for c in corners]
    has_pc = any(r > 0.0 for r in rates)

    use_center = bool(ps.UpdateFlag() & _CENTER_FLAGS)
    if use_center:
        # Centre vertex (index 4) — fan for smooth deform / gradient. The centre
        # colour/rate is the mean of the four corners; inlined over the fixed 4
        # (== _avg but without the per-channel generator+call — this executes
        # for nearly every part on deform-heavy packs). ``a*0.25 == a/4.0``
        # exactly.
        positions.append(part.positions[CENTER])
        uvs.append(part.uvs[CENTER])
        c0, c1, c2, c3 = colors
        colors.append(((c0[0] + c1[0] + c2[0] + c3[0]) * 0.25,
                       (c0[1] + c1[1] + c2[1] + c3[1]) * 0.25,
                       (c0[2] + c1[2] + c2[2] + c3[2]) * 0.25,
                       (c0[3] + c1[3] + c2[3] + c3[3]) * 0.25))
        r0, r1, r2, r3 = rates
        rates.append((r0 + r1 + r2 + r3) * 0.25)
        # Centre = 4; corners CCW LT(0) RT(1) RB(3) LB(2).
        tris = _TRIS_FAN
    else:
        tris = _TRIS_QUAD

    return MeshPart(
        part_index=part.part_index, texture_hash=part.texture_hash,
        blend_type=part.blend_type, color_blend=cblend, positions=positions,
        uvs=uvs, colors=colors, rates=rates, triangles=tris,
        src_rect=part.src_rect, mask_influence=part.mask_influence,
        use_center=use_center, has_partcolor=has_pc,
        shader_id_hash=shader_id, shader_params=shader_params)


class _ZeroSeq:
    """``x[i] == 0`` for any ``i`` — mirrors ``FrameData.DrawOrder``'s 0-on-absent
    when the frame has no draw-order vector (so the walk never IndexErrors)."""
    __slots__ = ()

    def __getitem__(self, i):
        return 0


_ZERO_SEQ = _ZeroSeq()


_do_fastpath = None


def _draw_order_array(fd: FrameData):
    """The whole DrawOrder Uint16 vector as a tuple (one struct read), or a
    zero sequence when absent. Hoists the per-call offset/base recompute out of
    the hot draw walk (``fd.DrawOrder(j)`` is read once per part per batch)."""
    global _do_fastpath
    if _do_fastpath is not False:
        a, n = _vector(fd._tab, _FD_DRAW_ORDER)
        if _do_fastpath is None:
            if n != fd.DrawOrderLength():
                _do_fastpath = False
            elif n:
                _do_fastpath = _U16(fd._tab.Bytes, a)[0] == fd.DrawOrder(0)
        if _do_fastpath is not False:
            if n == 0:
                return _ZERO_SEQ
            return struct.unpack_from('<%dH' % n, fd._tab.Bytes, a)
    n = fd.DrawOrderLength()
    return tuple(fd.DrawOrder(j) for j in range(n)) if n else _ZERO_SEQ


# --- Bulk DrawBatch decode (same idea as bulk_part_states) ------------------
# DrawBatch is a fixed 16-byte FlatBuffers *struct*; iter_draw_plan walks the
# batch vector TWICE (mask pre-scan + draw), reading up to 6 fields per batch, so
# decode the whole vector once. Layout MIRRORS the generated DrawBatch.py
# (regenerate via scripts/generate-fbs-code if the schema changes):
# StartRank u16@0, Count u16@2, TextureHash u32@4, VertexCount u16@8,
# IndexCount u16@10, BlendType u8@12, Kind u8@13, Flags u8@14 (+1 pad). A
# one-time self-check vs the accessor disables the fast path if it ever drifts.
_DB_SIZE = 16
_DB_REC = struct.Struct('<HHIHHBBBx')  # start,count,thash,vcount,icount,blend,kind,flags
_db_fastpath = None


def _draw_batch_list(fd: FrameData):
    """All DrawBatches as ``(start, count, thash, vcount, icount, blend, kind,
    flags)`` tuples — one struct pass (or the accessor path on drift). Never
    ``None`` so the two draw-walk loops can iterate it directly."""
    global _db_fastpath
    if _db_fastpath is not False and DrawBatch.SizeOf() == _DB_SIZE:
        base, n = _vector(fd._tab, _FD_DRAW_BATCHES)
        if _db_fastpath is None and n != fd.DrawBatchesLength():
            _db_fastpath = False
        elif n == 0:
            return []
        else:
            out = list(_DB_REC.iter_unpack(
                fd._tab.Bytes[base:base + n * _DB_SIZE]))
            if _db_fastpath is None:
                # Validate all 8 fields (incl. VertexCount@8 / IndexCount@10)
                # against the accessor: SizeOf() cannot catch a same-size field
                # reorder, so every decoded field is checked even though the
                # walk itself ignores vcount/icount.
                b0 = fd.DrawBatches(0)
                r = out[0]
                _db_fastpath = bool(
                    base == b0._tab.Pos
                    and r[0] == b0.StartRank() and r[1] == b0.Count()
                    and r[2] == b0.TextureHash() and r[3] == b0.VertexCount()
                    and r[4] == b0.IndexCount() and r[5] == b0.BlendType()
                    and r[6] == b0.Kind() and r[7] == b0.Flags())
            if _db_fastpath:
                return out
    # Fallback: accessor path, same tuple shape.
    n = fd.DrawBatchesLength()
    out = []
    for b in range(n):
        db = fd.DrawBatches(b)
        out.append((db.StartRank(), db.Count(), db.TextureHash(),
                    db.VertexCount(), db.IndexCount(), db.BlendType(),
                    db.Kind(), db.Flags()))
    return out


def build_mesh_parts(rt, fd: FrameData) -> list:
    """Resolve every visible Normal part of ``fd`` into a coloured world mesh.

    Unlike :func:`build_normal_quads`, instead of collapsing each
    part to a similarity transform it keeps the true 4-corner world quad (so
    shear and free deform are exact) and attaches per-vertex colour. Call right
    after ``rt.get_frame_data`` for the same frame — the SoA buffers are
    transient. ``uvs`` are texture-pixel; normalize with :func:`normalize_uvs`
    and sample with REPEAT wrap (the runtime bakes UV scale/rotation in).
    """
    pcs = bulk_part_colors(fd)
    return [_mesh_part_from(fd, part, pcs)
            for part in _iter_visible_normal_parts(rt, fd)]


def _mesh_soa(rt):
    """The Mesh(deform) SoA: world x / y, interleaved UVs, part-local indices
    and the two CSR offset arrays, as :func:`_read_mesh_part` takes them."""
    return (rt.mesh_vertices_x(), rt.mesh_vertices_y(), rt.mesh_uvs(),
            rt.mesh_indices(), rt.mesh_vertex_offsets(),
            rt.mesh_index_offsets())


def _shape_soa(rt):
    """The Shape SoA: 12 local vertices per part, their bbox coords and the
    valid counts, as :func:`_read_shape_part` takes them."""
    return (rt.shape_vertices(), rt.shape_vertex_box_coords(),
            rt.shape_vertex_counts())


def iter_draw_plan(rt, fd: FrameData, parts=None):
    """Walk the draw plan in z-order, yielding tagged, SoA-resolved items.

    Yields, in draw order, one of:

    * ``("mesh", MeshPart)`` — a visible Normal, Mesh(deform) *or* Shape part
      (Shape is a textureless procedural polygon; ``texture_hash == 0``);
    * ``("instance", part_index, matrix, alpha, hidden)`` — an Instance slot;
    * ``("effect", part_index, matrix, alpha, hidden)`` — an Effect slot;
    * ``("skip", kind, part_index)`` — an unsupported kind (Text/Nines/Mask).

    ``matrix`` is the part's 16-float column-major world matrix (a *copy*) and
    ``alpha`` its hierarchical ``PartState.alpha``. Every payload is copied out
    of the transient SoA buffers, so the caller may fully materialize this
    generator (``list(...)``) and only *then* make further Brain calls (e.g.
    stepping a child/effect slot, which invalidates the SoA pointers).

    Instance/Effect items are yielded even when ``hidden`` so their slots can
    still be stepped (independent playback must keep advancing while
    off-screen); the consumer suppresses *drawing* on ``hidden``.

    ``parts`` is an optional pre-decoded :func:`bulk_part_states` array (see
    :func:`hidden_parts`).
    """
    wm, wn = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    have_soa = bool(wm and lv)
    mesh_soa = shape_soa = None
    if parts is None:
        parts = bulk_part_states(fd)
    pcs = bulk_part_colors(fd)   # pre-decoded per-corner colours (hot path)
    do = _draw_order_array(fd)
    # Parts emitted as a Mask batch write coverage only — no colour output. A pure
    # Mask-type part has ONLY a Mask batch (already yielded as "skip"), but a
    # ``draw_as_mask`` Shape/Normal/Mesh part ALSO emits its own colour batch at
    # the same draw-order slot; that colour batch must be suppressed (the part is
    # the mask, not a drawn sprite). Clipping
    # writers (``mask_write``) emit no Mask batch, so they are absent here and
    # draw normally.
    batches = _draw_batch_list(fd)
    mask_only_parts = None
    for (s, c, _th, _vc, _ic, _bl, kind, _fl) in batches:
        if kind == KIND_MASK:
            if mask_only_parts is None:
                mask_only_parts = set()
            for k in range(c):
                mask_only_parts.add(do[s + k])
    for (start, count, thash, _vc, _ic, blend, kind, flags) in batches:
        mask = bool(flags & MASK_INFLUENCE)
        if kind == KIND_MESH and mesh_soa is None:
            mesh_soa = _mesh_soa(rt)
        elif kind == KIND_SHAPE and shape_soa is None:
            shape_soa = _shape_soa(rt)
        for k in range(count):
            p = do[start + k]
            if mask_only_parts is not None and kind != KIND_MASK and p in mask_only_parts:
                continue   # draw_as_mask: contributes coverage, not colour
            ps = parts[p] if parts is not None else fd.Parts(p)
            hidden = ps is None or ps.Hide()
            if kind == KIND_NORMAL:
                if not have_soa or hidden:
                    continue
                yield ("mesh", _read_normal_mesh_part(wm, lv, uv, cm, fd, ps, p, blend, thash, mask, pcs))
            elif kind == KIND_MESH:
                if hidden:
                    continue
                mp = _read_mesh_part(mesh_soa, ps, p, blend, thash, mask)
                if mp is not None:
                    yield ("mesh", mp)
            elif kind == KIND_SHAPE:
                if not have_soa or hidden:
                    continue
                sp = _read_shape_part(shape_soa, wm, wn, fd, ps, p, blend, mask, pcs)
                if sp is not None:
                    yield ("mesh", sp)
            elif kind == KIND_INSTANCE or kind == KIND_EFFECT:
                mo = p * MATRIX_STRIDE
                mat = (list(wm[mo:mo + MATRIX_STRIDE])
                       if have_soa and mo + MATRIX_STRIDE <= wn else None)
                alpha = ps.Alpha() if ps is not None else 1.0
                tag = "instance" if kind == KIND_INSTANCE else "effect"
                yield (tag, p, mat, alpha, hidden)
            else:
                yield ("skip", kind, p)


def transform_mesh_part(mp: MeshPart, m, alpha_mul: float = 1.0) -> MeshPart:
    """Copy ``mp`` with its positions sent through 4x4 ``m`` and alpha scaled.

    Composes an Instance part's world matrix onto a child animation's geometry
    (and folds the instance part's hierarchical alpha in). ``m``
    is a 16-float column-major matrix (``None`` = identity); ``alpha_mul``
    multiplies every vertex colour's alpha.
    """
    if m is None and alpha_mul == 1.0:
        return mp
    positions = ([_transform(m, x, y) for (x, y) in mp.positions]
                 if m is not None else list(mp.positions))
    colors = ([(r, g, b, a * alpha_mul) for (r, g, b, a) in mp.colors]
              if alpha_mul != 1.0 else list(mp.colors))
    return MeshPart(
        part_index=mp.part_index, texture_hash=mp.texture_hash,
        blend_type=mp.blend_type, color_blend=mp.color_blend,
        positions=positions, uvs=list(mp.uvs), colors=colors,
        rates=list(mp.rates), triangles=list(mp.triangles),
        src_rect=mp.src_rect, mask_influence=mp.mask_influence,
        use_center=mp.use_center, has_partcolor=mp.has_partcolor,
        shader_id_hash=mp.shader_id_hash, shader_params=mp.shader_params,
        mask=mp.mask)


def classify_frame(fd: FrameData) -> dict:
    """Summarize one frame's draw batches by kind (for diagnostics/audit).

    Returns ``{kind_id: {"batches": n, "parts": m}}`` plus convenience keys
    ``"renderable_parts"`` / ``"unsupported_parts"`` for the audit.
    """
    by_kind: dict[int, dict] = {}
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        k = batch.Kind()
        slot = by_kind.setdefault(k, {"batches": 0, "parts": 0})
        slot["batches"] += 1
        slot["parts"] += batch.Count()
    renderable = sum(v["parts"] for k, v in by_kind.items()
                     if k in RENDERABLE_KINDS)
    unsupported = sum(v["parts"] for k, v in by_kind.items()
                      if k not in RENDERABLE_KINDS)
    by_kind["renderable_parts"] = renderable
    by_kind["unsupported_parts"] = unsupported
    return by_kind
