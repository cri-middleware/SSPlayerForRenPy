"""Walk the per-frame FrameData draw plan and build render geometry.

This is the engine-independent render-data core (the equivalent of the Web
player's ``GeometryBuilder``). It turns the Brain's FlatBuffers draw plan +
SoA buffers into concrete quads the Ren'Py layer can blit / mesh.

Two render paths are provided, both for the ``Normal`` draw-batch kind:

* **M1 — :func:`build_normal_quads` + :func:`decompose_quad`**: resolves each
  part to a *similarity* transform (center/rotate/scale/flip) for the blit +
  ``Transform`` renderer. Drops shear (tracked as ``skew_err``).
* **M2 — :func:`build_mesh_parts`**: resolves each part to a full triangulated
  mesh (4 corners, or a 5-vertex centre fan when the part has free deform /
  per-vertex colour) with per-vertex colour from ``parts_color`` and the
  framebuffer + PartColor blend modes. This is what a model-based mesh renderer
  consumes and is shear/free-deform exact.

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

from ss.runtime.FrameData import FrameData
from ss.runtime.PartState import PartState
from ss.runtime.SsAttributePartColorKeyValueColor import (
    SsAttributePartColorKeyValueColor,
)
from ss.runtime.U8Rect import U8Rect
from ss.runtime.UpdateAttributeFlags import UpdateAttributeFlags

# DrawBatchKind (framedata.fbs)
KIND_NORMAL, KIND_SHAPE, KIND_INSTANCE, KIND_EFFECT = 0, 1, 2, 3
KIND_MESH, KIND_TEXT, KIND_NINES, KIND_MASK = 4, 5, 6, 7
KIND_NAMES = {0: "Normal", 1: "Shape", 2: "Instance", 3: "Effect",
              4: "Mesh", 5: "Text", 6: "Nines", 7: "Mask"}

BLEND_NAMES = {0: "Mix", 1: "Mul", 2: "Add", 3: "Sub", 4: "Mulalpha",
               5: "Screen", 6: "Exclusion", 7: "Invert", 8: "Mul2",
               9: "Div2", 10: "Screen2", 11: "Overlay2"}

# Kinds the Normal render path (M1 blit + M2 mesh) can emit.
M1_RENDERABLE_KINDS = frozenset({KIND_NORMAL})

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

# -- PartColor blend (texel<->vertex-colour, shader-side; 10_parts_color) -----
# This is a DIFFERENT axis from the framebuffer blend on DrawBatch.blend_type:
# PartColor blend mixes texel and vertex colour *inside the shader* and only the
# first four modes are valid; values >= 4 clamp to Mix (10_parts_color §1-1).
PC_BLEND_MIX, PC_BLEND_MUL, PC_BLEND_ADD, PC_BLEND_SUB = 0, 1, 2, 3
PC_BLEND_NAMES = {0: "Mix", 1: "Mul", 2: "Add", 3: "Sub"}

# Coefficient table from 10_parts_color §1-4-1 — (pixel_weight_adj, color_weight,
# mul_flag). The generic formula evaluated per fragment (§1-4-3) is
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
# wants a triangle fan from the centre (SCHEMA.md "PartState Identity").
_CENTER_FLAGS = (UpdateAttributeFlags.AttributeVertex
                 | UpdateAttributeFlags.AttributePartColor)


def parse(fb) -> FrameData:
    return FrameData.GetRootAs(fb, 0)


# --- Bulk struct reads (mirror SSPlayerForUnity's RawPartState* / command casts)
# PartState and EffectDrawCommand are fixed-layout FlatBuffers *structs* stored in
# contiguous vectors, so the whole array decodes in ONE struct call instead of
# N × the per-element FlatBuffers accessor chain (Offset→Get→unpack→enforce), which
# the profiler showed was ~31% of frame CPU. The field offsets below MIRROR the
# generated PartState.py (regenerate via scripts/generate-runtime-code if the
# schema changes); the vector *base* is taken from the generated accessor so only
# the intra-struct layout is duplicated, and a one-time self-check vs the accessor
# disables the fast path automatically if it ever drifts.
_PS_SIZE = 144
# UpdateFlag u64@0, Alpha f32@48, Priority f32@56, Mask f32@108,
# PartColor i16@128, Shader i16@130, Hide bool@138 (little-endian). Priority/Mask
# are the per-frame mask attributes (09_mask): Priority feeds draw order (the
# runtime already sorts draw_order, but we keep it for diagnostics) and Mask is
# the cutout value (0..255, a float despite the range). Shader indexes
# FrameData.shaders (the per-part user-shader effect; -1 = none).
_PS_REC = struct.Struct('<Q40xf4xf48xf16xhh6x?5x')
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
    n = fd.PartsLength()
    if n == 0 or PartState.SizeOf() != _PS_SIZE:
        return None
    p0 = fd.Parts(0)
    if p0 is None:
        return None
    base = p0._tab.Pos
    blob = p0._tab.Bytes[base:base + n * _PS_SIZE]
    lite = [_PartLite(uf, a, prio, mask, pc, shader, hide)
            for (uf, a, prio, mask, pc, shader, hide) in _PS_REC.iter_unpack(blob)]
    if _ps_fastpath is None:
        l0 = lite[0]
        if (l0._hide != p0.Hide() or l0._uf != p0.UpdateFlag()
                or l0._pc != p0.PartColor() or l0._shader != p0.Shader()
                or abs(l0._a - p0.Alpha()) > 1e-6
                or abs(l0._prio - p0.Priority()) > 1e-6
                or abs(l0._mask - p0.Mask()) > 1e-6):
            _ps_fastpath = False
            return None
        _ps_fastpath = True
    return lite


def hidden_parts(fd: FrameData) -> set:
    """Owned set of part indices hidden on ``fd`` (for the part-query API).

    A tiny snapshot so callers can answer "is part N hidden?" *after* the
    FrameData buffer is gone — the analogue of the ``_last_wm`` matrix snapshot.
    Must run while ``fd``'s buffer is still valid (right after :func:`parse`,
    before any slot step), since a zero-copy ``get_frame_data_view`` buffer is
    invalidated by the instance/effect steps that follow.
    """
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


def partcolor_varg(blend_idx: int, rate: float) -> tuple:
    """Build the ``varg`` coefficient triple for one vertex (10_parts_color §1-4-2)."""
    cx, cy, cz = _PC_COEF[clamp_pc_blend(blend_idx)]
    return (1.0 + cx * rate, cy * rate, cz)


def eval_partcolor(pixel_rgb, color_rgb, blend_idx: int, rate: float) -> tuple:
    """CPU reference of the PartColor fragment formula (10_parts_color §1-4-3).

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

    Pure math, engine-independent — the equivalent of the reference players'
    ``uv * inv_tex_size`` UV normalize. Results may
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
    """Per-part data shared by the M1 (quad) and M2 (mesh) builders.

    The common walk of the FrameData draw plan resolves this once per visible
    Normal part; both builders then project it onto their own output shape.
    ``positions`` / ``uvs`` carry all 5 verts (LT,RT,LB,RB,CENTER) — the M1 path
    uses the first 4, the M2 path appends the centre only when it fans.
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

    Per docs/08 §4: vertices are pre-computed WORLD coords (``x``/``y`` SoA),
    UVs are interleaved texture-pixel at ``vertex_offset*2``, indices are
    part-local 0-based, and the offset arrays are CSR (length ``num_parts+1``).
    Returns ``None`` for an empty/degenerate range (non-Mesh part, bad offsets).
    Colour is the part's hierarchical alpha on white (Mesh ``parts_color`` is
    Whole-only; per-part tint is a later refinement).
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
    # Bulk-slice the ctypes SoA pointers once (one C-level copy each) rather than
    # indexing per element — per-element ctypes access dominated this function.
    xs = mvx[v0:v1]
    ys = mvy[v0:v1]
    us = muv[v0 * 2:v1 * 2]                       # interleaved u, v
    idx = midx[i0:i1]
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


def _read_shape_part(shape_soa, wm, wn, fd, ps, p, blend, mask):
    """Build a :class:`MeshPart` for a Shape part from the shape SoA.

    Shape parts are textureless procedural polygons (Rectangle / Triangle /
    Star / Arrow). The runtime emits, per part, up to 12 LOCAL vertices
    (post-pivot, post-coord-system) laid out as a TRIANGLE_FAN from vertex 0,
    plus matching normalized bbox coords ((0, 0) = LT .. (1, 1) = RB). Positions
    are sent through the part's world matrix (exactly like a Normal part's local
    vertices); the fill is the PartColor with ``rate`` forced to 1.0 — a shape
    has no texel to blend against (SCHEMA.md / 10_parts_color: Shape is rate-1.0),
    so the (white) texture supplied by the render layer is fully replaced by the
    interpolated corner colour. Returns ``None`` for a non-shape part or a
    degenerate range (<3 valid verts, e.g. a size-collapsed shape).
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
    # Bulk-slice the ctypes SoA pointers once (mirrors _read_mesh_part) rather
    # than indexing per element — per-element ctypes access is the hot cost.
    lv = sv[so:so + count * 2]
    bc = sb[so:so + count * 2]
    positions = [_transform(mat, lv[j * 2], lv[j * 2 + 1]) for j in range(count)]

    # Per-vertex colour: bilinear-interpolate the four PartColor corners across
    # the shape's bbox (fx, fy). ``part_colors`` returns [LT, RT, LB, RB]; a part
    # with no ``parts_color`` entry gets white × hierarchical alpha (so a shape
    # still fills solid).
    #
    # A Shape **bypasses the PartColor blend formula** (SSPlayerForWeb
    # GeometryBuilder.buildShape, 10_parts_color): a textureless shape has no
    # texel to blend against, so the blend mode is FORCED to Mix and the rate to
    # 1.0 — the fill is the interpolated corner colour itself, regardless of the
    # part's authored PartColor blend (Add/Sub against the white texel would
    # otherwise blow out / invert). The authored ``blend`` from ``part_colors``
    # is intentionally discarded.
    _authored_blend, corners = part_colors(fd, ps)
    lt, rt, lb, rb = corners
    colors = []
    for j in range(count):
        fx, fy = bc[j * 2], bc[j * 2 + 1]
        w = ((1.0 - fx) * (1.0 - fy), fx * (1.0 - fy),
             (1.0 - fx) * fy, fx * fy)          # LT, RT, LB, RB weights
        colors.append(tuple(
            lt.rgba[c] * w[0] + rt.rgba[c] * w[1]
            + lb.rgba[c] * w[2] + rb.rgba[c] * w[3] for c in range(4)))
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
    buffers (the engine-independent analogue of the reference players'
    ``get_local_vertices`` / ``get_local_uvs`` accessors). Must be iterated right
    after ``rt.get_frame_data`` for the same frame — the SoA pointers are valid
    only until the next Brain call.
    """
    wm, _ = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    if not wm or not lv:
        return

    parts = bulk_part_states(fd)
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        if batch.Kind() != KIND_NORMAL:
            continue
        blend = batch.BlendType()
        thash = batch.TextureHash()
        mask = bool(batch.Flags() & MASK_INFLUENCE)
        start, count = batch.StartRank(), batch.Count()
        for k in range(count):
            p = fd.DrawOrder(start + k)
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

    This is what the M1 Ren'Py renderer (blit + ``Transform``) needs: it cannot
    express a free 2x4 quad, only translate/rotate/scale/flip about a center. SS
    Normal parts are affine, so the only thing this *drops* is shear — captured
    as ``skew_err`` (max corner reprojection error in px). For typical VN parts
    ``skew_err`` is ~0; large values flag a part M1 will render slightly wrong
    (fix in M2 via model-based mesh).

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
    the original quad, the gap is the shear M1 cannot represent.
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

    Pure geometry shared by :func:`decompose_quad` (M1 ``NormalQuad``) and the
    Ren'Py Transform backend (M2 ``MeshPart`` corners). Returns
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
    Records ``skew_err`` so callers know how faithful the M1 approximation is.
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
# M2 — full-fidelity mesh path (shear / free-deform exact + vertex colour)
# ---------------------------------------------------------------------------

@dataclass
class VertexColor:
    """One vertex's PartColor: RGBA (0..1) plus the texel blend ``rate``.

    ``rgba.a`` already has the part's hierarchical alpha pre-multiplied
    (SCHEMA.md / 10_parts_color §1-3) — never re-multiply by ``PartState.alpha``.
    ``rate`` is the texel<->colour blend strength; ``0`` = texel pass-through.
    """
    rgba: tuple   # (r, g, b, a) floats 0..1
    rate: float


# Default for a part with no ``parts_color`` entry (10_parts_color §1-2-4):
# white, hierarchical alpha, rate 0 → the generic formula returns the raw texel,
# so the renderer needs no separate "has part colour?" branch.
def _default_vertex_color(alpha: float) -> VertexColor:
    return VertexColor((1.0, 1.0, 1.0, max(0.0, min(1.0, alpha))), 0.0)


def _read_corner(kv) -> VertexColor:
    rect = kv.Rgba(U8Rect())
    return VertexColor(
        (rect.R() / 255.0, rect.G() / 255.0, rect.B() / 255.0, rect.A() / 255.0),
        kv.Rate())


def part_colors(fd: FrameData, ps) -> tuple:
    """Resolve a part's per-corner colour: ``(blend_idx, [lt, rt, lb, rb])``.

    ``blend_idx`` is clamped to the 4 valid PartColor modes. Parts without a
    ``parts_color`` entry (``PartState.part_color() < 0``) get the white /
    rate-0 default on all four corners (10_parts_color §1-2/§1-2-4). Only the
    Normal-part rule (four corners individual) is applied here; Mesh (Whole-only)
    and Shape (rate forced 1.0) are M3+/Shape-kind concerns.
    """
    cidx = ps.PartColor()
    if cidx is None or cidx < 0:
        vc = _default_vertex_color(ps.Alpha())
        return (PC_BLEND_MIX, [vc, vc, vc, vc])
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
    triangles: list          # [(i, j, k)] into the vertex arrays
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
    # Masking (09_mask): a ``ss_renpy.mask.MaskApply`` when this part is a masked
    # target this frame, else None. Set by the mask layer after the draw plan is
    # built (the render layer reads it to bind coverage + replay the stencil); it
    # is intentionally NOT part of the equality/identity of the geometry.
    mask: object = None


def _avg(seq):
    seq = list(seq)
    return sum(seq) / float(len(seq)) if seq else 0.0


def read_shader(fd: FrameData, ps) -> tuple:
    """Resolve a part's user-shader effect → ``(id_hash, params)``.

    Mirrors SSPlayerForGodot's ``_resolve_part_shader_info``: the shader applies
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


def _mesh_part_from(fd: FrameData, part: _NormalPart) -> MeshPart:
    """Project one resolved :class:`_NormalPart` to a coloured triangulated mesh.

    The per-part half of :func:`build_mesh_parts`, factored out so the z-ordered
    :func:`iter_draw_plan` walk can reuse it.
    """
    ps = part.ps
    cblend, corners = part_colors(fd, ps)
    shader_id, shader_params = read_shader(fd, ps)

    positions = list(part.positions[:4])             # LT, RT, LB, RB
    uvs = list(part.uvs[:4])
    colors = [c.rgba for c in corners]
    rates = [c.rate for c in corners]
    has_pc = any(r > 0.0 for r in rates)

    use_center = bool(ps.UpdateFlag() & _CENTER_FLAGS)
    if use_center:
        # Centre vertex (index 4) — fan for smooth deform / gradient.
        positions.append(part.positions[CENTER])
        uvs.append(part.uvs[CENTER])
        colors.append(tuple(_avg(c[i] for c in colors) for i in range(4)))
        rates.append(_avg(rates))
        # Centre = 4; corners CCW LT(0) RT(1) RB(3) LB(2).
        tris = [(CENTER, LT, RT), (CENTER, RT, RB),
                (CENTER, RB, LB), (CENTER, LB, LT)]
    else:
        tris = [(LT, RT, LB), (RT, RB, LB)]

    return MeshPart(
        part_index=part.part_index, texture_hash=part.texture_hash,
        blend_type=part.blend_type, color_blend=cblend, positions=positions,
        uvs=uvs, colors=colors, rates=rates, triangles=tris,
        src_rect=part.src_rect, mask_influence=part.mask_influence,
        use_center=use_center, has_partcolor=has_pc,
        shader_id_hash=shader_id, shader_params=shader_params)


def build_mesh_parts(rt, fd: FrameData) -> list:
    """Resolve every visible Normal part of ``fd`` into a coloured world mesh.

    The M2 equivalent of :func:`build_normal_quads`: instead of collapsing each
    part to a similarity transform it keeps the true 4-corner world quad (so
    shear and free deform are exact) and attaches per-vertex colour. Call right
    after ``rt.get_frame_data`` for the same frame — the SoA buffers are
    transient. ``uvs`` are texture-pixel; normalize with :func:`normalize_uvs`
    and sample with REPEAT wrap (the runtime bakes UV scale/rotation in).
    """
    return [_mesh_part_from(fd, part)
            for part in _iter_visible_normal_parts(rt, fd)]


def iter_draw_plan(rt, fd: FrameData):
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
    still be stepped (independent playback must keep advancing while off-screen,
    docs/08 §3); the consumer suppresses *drawing* on ``hidden``.
    """
    wm, wn = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    have_soa = bool(wm and lv)
    # Mesh(deform) SoA (docs/08 §4) — separate CSR buffers; cheap pointer fetch
    # even when the pack has no Mesh parts (then ranges are empty / skipped).
    mesh_soa = (rt.mesh_vertices_x(), rt.mesh_vertices_y(), rt.mesh_uvs(),
                rt.mesh_indices(), rt.mesh_vertex_offsets(),
                rt.mesh_index_offsets())
    # Shape SoA — fixed 12-vert/part local positions + bbox coords + valid
    # counts. Cheap pointer fetch even when the pack has no Shape parts (counts
    # are then all zero / skipped).
    shape_soa = (rt.shape_vertices(), rt.shape_vertex_box_coords(),
                 rt.shape_vertex_counts())
    parts = bulk_part_states(fd)
    # Parts emitted as a Mask batch write coverage only — no colour output. A pure
    # Mask-type part has ONLY a Mask batch (already yielded as "skip"), but a
    # ``draw_as_mask`` Shape/Normal/Mesh part ALSO emits its own colour batch at
    # the same draw-order slot; that colour batch must be suppressed (the part is
    # the mask, not a drawn sprite — 09_mask). Clipping writers (``mask_write``)
    # emit no Mask batch, so they are absent here and draw normally.
    mask_only_parts = set()
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        if batch.Kind() == KIND_MASK:
            s, c = batch.StartRank(), batch.Count()
            for k in range(c):
                mask_only_parts.add(fd.DrawOrder(s + k))
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        kind = batch.Kind()
        blend = batch.BlendType()
        thash = batch.TextureHash()
        mask = bool(batch.Flags() & MASK_INFLUENCE)
        start, count = batch.StartRank(), batch.Count()
        for k in range(count):
            p = fd.DrawOrder(start + k)
            if kind != KIND_MASK and p in mask_only_parts:
                continue   # draw_as_mask: contributes coverage, not colour
            ps = parts[p] if parts is not None else fd.Parts(p)
            hidden = ps is None or ps.Hide()
            if kind == KIND_NORMAL:
                if not have_soa or hidden:
                    continue
                part = _read_normal_part(wm, lv, uv, cm, ps, p, blend, thash, mask)
                yield ("mesh", _mesh_part_from(fd, part))
            elif kind == KIND_MESH:
                if hidden:
                    continue
                mp = _read_mesh_part(mesh_soa, ps, p, blend, thash, mask)
                if mp is not None:
                    yield ("mesh", mp)
            elif kind == KIND_SHAPE:
                if not have_soa or hidden:
                    continue
                sp = _read_shape_part(shape_soa, wm, wn, fd, ps, p, blend, mask)
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
    (and folds the instance part's hierarchical alpha in), per docs/08 §1. ``m``
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
    ``"renderable_parts"`` / ``"unsupported_parts"`` for the M1 verdict.
    """
    by_kind: dict[int, dict] = {}
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        k = batch.Kind()
        slot = by_kind.setdefault(k, {"batches": 0, "parts": 0})
        slot["batches"] += 1
        slot["parts"] += batch.Count()
    renderable = sum(v["parts"] for k, v in by_kind.items()
                     if k in M1_RENDERABLE_KINDS)
    unsupported = sum(v["parts"] for k, v in by_kind.items()
                      if k not in M1_RENDERABLE_KINDS)
    by_kind["renderable_parts"] = renderable
    by_kind["unsupported_parts"] = unsupported
    return by_kind
