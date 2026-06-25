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

Other batch kinds (Mesh, Shape, Effect, Mask, Instance, Text, Nines) are
enumerated for diagnostics but not yet emitted — see :func:`classify_frame`.

SoA lifetime: the pointers returned by the runtime are valid only until the
next Brain call. Build geometry immediately after ``get_frame_data`` and do not
retain the raw buffers.
"""

from __future__ import annotations

from dataclasses import dataclass

from ss.runtime.FrameData import FrameData
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


def parse(fb: bytes) -> FrameData:
    return FrameData.GetRootAs(fb, 0)


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


def build_normal_quads(rt, fd: FrameData) -> list:
    """Resolve every visible Normal part of ``fd`` into world-space quads.

    ``rt`` is an :class:`ss_renpy.ssruntime.SSRuntime`. Must be called right
    after ``rt.get_frame_data`` for the same frame (SoA buffers are transient).
    """
    wm, _ = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    if not wm or not lv:
        return []

    quads = []
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
            ps = fd.Parts(p)
            if ps is None or ps.Hide():
                continue
            mo, vo, co = p * 16, p * 10, p * 6
            mat = wm[mo:mo + 16]
            positions, uvs = [], []
            for j in range(4):  # LT, RT, LB, RB (corner verts; center skipped)
                positions.append(_transform(mat, lv[vo + j * 2], lv[vo + j * 2 + 1]))
                uvs.append((uv[vo + j * 2], uv[vo + j * 2 + 1]))
            src_rect = (cm[co + 4], cm[co + 5], cm[co + 2], cm[co + 3])
            quads.append(NormalQuad(
                part_index=p, texture_hash=thash, blend_type=blend,
                positions=positions, uvs=uvs, src_rect=src_rect,
                alpha=ps.Alpha(), mask_influence=mask))
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
    import math
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
    import math
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
    import math
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


def _avg(seq):
    seq = list(seq)
    return sum(seq) / float(len(seq)) if seq else 0.0


def build_mesh_parts(rt, fd: FrameData) -> list:
    """Resolve every visible Normal part of ``fd`` into a coloured world mesh.

    The M2 equivalent of :func:`build_normal_quads`: instead of collapsing each
    part to a similarity transform it keeps the true 4-corner world quad (so
    shear and free deform are exact) and attaches per-vertex colour. Call right
    after ``rt.get_frame_data`` for the same frame — the SoA buffers are
    transient.
    """
    wm, _ = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    if not wm or not lv:
        return []

    out = []
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        if batch.Kind() != KIND_NORMAL:
            continue
        fb_blend = batch.BlendType()
        thash = batch.TextureHash()
        mask = bool(batch.Flags() & MASK_INFLUENCE)
        start, count = batch.StartRank(), batch.Count()
        for k in range(count):
            p = fd.DrawOrder(start + k)
            ps = fd.Parts(p)
            if ps is None or ps.Hide():
                continue
            mo, vo, co = p * 16, p * 10, p * 6
            mat = wm[mo:mo + 16]
            cblend, corners = part_colors(fd, ps)

            positions = [_transform(mat, lv[vo + j * 2], lv[vo + j * 2 + 1])
                         for j in range(4)]               # LT, RT, LB, RB
            uvs = [(uv[vo + j * 2], uv[vo + j * 2 + 1]) for j in range(4)]
            colors = [c.rgba for c in corners]
            rates = [c.rate for c in corners]
            has_pc = any(r > 0.0 for r in rates)

            use_center = bool(ps.UpdateFlag() & _CENTER_FLAGS)
            if use_center:
                # Centre vertex (index 4) — fan for smooth deform / gradient.
                positions.append(_transform(mat, lv[vo + 8], lv[vo + 9]))
                uvs.append((uv[vo + 8], uv[vo + 9]))
                colors.append(tuple(_avg(c[i] for c in colors) for i in range(4)))
                rates.append(_avg(rates))
                # Centre = 4; corners CCW LT(0) RT(1) RB(3) LB(2).
                tris = [(4, 0, 1), (4, 1, 3), (4, 3, 2), (4, 2, 0)]
            else:
                tris = [(0, 1, 2), (1, 3, 2)]   # LT,RT,LB and RT,RB,LB

            out.append(MeshPart(
                part_index=p, texture_hash=thash, blend_type=fb_blend,
                color_blend=cblend, positions=positions, uvs=uvs, colors=colors,
                rates=rates, triangles=tris, src_rect=(cm[co + 4], cm[co + 5],
                                                       cm[co + 2], cm[co + 3]),
                mask_influence=mask, use_center=use_center, has_partcolor=has_pc))
    return out


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
