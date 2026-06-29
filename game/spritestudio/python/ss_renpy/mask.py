"""Engine-independent mask / clipping-mask core (docs/09_mask).

SpriteStudio 7 "mask" and "clipping" are two features over one stencil. Ren'Py's
GL2 model layer does not expose a stencil buffer, so — exactly like the Godot
port — we use the **coverage-bitmap hybrid** (09_mask §3-2):

  1. Per frame, rasterize every mask *writer* into an offscreen RGBA8 bitmap,
     one bit per writer (max 24, packed into the RGB channels).
  2. Each masked *target* part, in its fragment shader, samples that coverage and
     *replays* the writers in draw order to reconstruct the stencil, then
     ``discard``\\ s by the inside/outside test.

This module owns the **engine-independent half**: reading the mask fields from
the draw plan, classifying writers (pure mask / clipping), assigning coverage
bits, building each writer's coverage geometry, the bbox + ``local -> uv`` data
the render layer needs, the per-writer ``mask_meta`` the replay shader consumes,
and a CPU reference of the replay (:func:`mask_passes`) so the whole thing is
testable headless. The actual offscreen render + GLSL live in the Ren'Py layer
(``spritestudio.rpy``), the same split as UV normalization.

Field provenance is split across two tables (09_mask §1):
  * **static** (``PartInfo`` from ``ssab_meta``): ``mask_influence`` /
    ``mask_write`` / ``visible_inside_mask`` / ``draw_as_mask`` / part type.
  * **per-frame** (``PartState``): ``Mask`` (cutout 0..255) / ``Priority`` /
    ``Hide``. Hidden parts are already absent from ``draw_order``, so a writer's
    only per-frame gate here is ``mask != 0`` (§2-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ss_renpy import framedata

# Coverage encodes one writer per bit across the RGB channels of an RGBA8
# bitmap (8 bits x 3). The alpha channel is reserved (premultiplied accumulator
# in the GPU path), so the hard cap is 24 (09_mask §3-2).
MAX_WRITERS = 24

# Two triangles for a 4-corner quad (LT, RT, LB, RB) — matches the non-fan
# layout in framedata._mesh_part_from so winding is consistent with the
# drawable path.
_QUAD_TRIS = [(framedata.LT, framedata.RT, framedata.LB),
              (framedata.RT, framedata.RB, framedata.LB)]


@dataclass
class MaskWriter:
    """One coverage writer for the current frame (09_mask §3-2-1 ``MaskWriter``).

    ``positions`` / ``uvs`` / ``triangles`` are the geometry to rasterize into
    the coverage bitmap (world space, texture-pixel UVs — the render layer
    normalizes by the atlas size, as everywhere else). ``op_invert`` is the OP
    (``mask_influence``: False = increment, True = invert). ``is_clipping``
    distinguishes a clipping writer (also drawn in colour, applies to *higher*
    ranks) from a pure mask (applies to *lower* ranks). ``mask_value`` is the
    per-frame cutout (0..255) → threshold ``(255 - mask) / 255``; ``has_texture``
    is False for a texture-less shape mask (whole geometry is the mask, §2-5).
    """
    part_index: int
    rank: int
    bit: int
    op_invert: bool
    is_clipping: bool
    mask_value: float
    texture_hash: int
    has_texture: bool
    positions: list           # [(x, y)] world
    uvs: list                 # [(u, v)] texture px
    triangles: list           # [(i, j, k)] into positions


@dataclass
class MaskApply:
    """Per-target replay parameters stamped onto a drawable (09_mask §2).

    A drawable part that is masked carries one of these. ``frame_mask`` is the
    coverage it samples (the *parent's* coverage for an inherited instance
    child); ``rank`` and ``visible_inside`` are this target's draw-order rank and
    polarity (§2-1 / §2-4). The render layer uses ``frame_mask`` for the coverage
    texture + ``mask_meta`` and ``rank`` / ``visible_inside`` for the replay
    uniforms; ``mask_passes`` below is the CPU reference of that replay.
    """
    frame_mask: "FrameMask"
    rank: int
    visible_inside: bool


@dataclass
class FrameMask:
    """All masking state for one frame of one animation (one coverage bitmap).

    Built by :func:`build_frame_mask`. ``meta`` is parallel to ``writers``:
    ``(rank, bit, op_invert, is_clipping)`` per writer — exactly the replay
    shader's ``mask_meta`` (09_mask §3-2-1). ``bmin`` / ``bsize`` are the world
    bbox of all writer geometry; a target's coverage UV is
    ``(world - bmin) / bsize``. ``max_mask_rank`` / ``min_clip_rank`` are the
    scope bounds (§2-1) used to skip targets no writer can reach.
    """
    writers: List[MaskWriter] = field(default_factory=list)
    meta: list = field(default_factory=list)       # [(rank, bit, op_invert, is_clipping)]
    bmin: tuple = (0.0, 0.0)
    bsize: tuple = (1.0, 1.0)
    max_mask_rank: int = -1                         # max rank of pure-mask writers
    min_clip_rank: Optional[int] = None             # min rank of clipping writers
    rank_of: dict = field(default_factory=dict)     # part_index -> draw-order rank

    @property
    def count(self) -> int:
        return len(self.writers)

    def in_scope(self, rank: int) -> bool:
        """True if any writer can affect a target at ``rank`` (09_mask §2-1).

        A pure mask affects ranks *below* it (``rank < mask_rank``); a clipping
        writer affects ranks *above* it (``rank > clip_rank``). This is the cheap
        CPU pre-filter — the shader's per-writer ``active`` test stays
        authoritative — so it is intentionally inclusive.
        """
        if rank < self.max_mask_rank:
            return True
        if self.min_clip_rank is not None and rank > self.min_clip_rank:
            return True
        return False


def _quad_writer_geom(rt, fd, p, thash):
    """Coverage geometry for a Normal/Mask-kind writer part (a textured quad)."""
    wm, _ = rt.world_matrices()
    lv, _ = rt.local_vertices()
    uv, _ = rt.local_uvs()
    cm, _ = rt.cell_meta()
    if not wm or not lv:
        return None
    ps = fd.Parts(p)
    part = framedata._read_normal_part(wm, lv, uv, cm, ps, p, 0, thash, False)
    l, t, w, h = part.src_rect
    has_texture = bool(thash) and w > 0 and h > 0
    return dict(positions=list(part.positions[:4]), uvs=list(part.uvs[:4]),
                triangles=list(_QUAD_TRIS), texture_hash=thash,
                has_texture=has_texture)


def _shape_writer_geom(rt, fd, p):
    """Coverage geometry for a cell-less writer (Shape / draw_as_mask part).

    Shape parts carry no cell, so the runtime leaves their entry in the Normal
    ``local_vertices`` SoA empty (it collapses to a point). Their region is
    instead the part's ``PartState.Size`` box, which we transform by the world
    matrix to a quad — texture-less (whole geometry is the mask, 09_mask §2-5).
    A true vector shape (circle / polygon) is thus approximated by its bounding
    box; a rectangle shape is exact. Returns None for a zero-size part.
    """
    wm, _ = rt.world_matrices()
    if not wm:
        return None
    ps = fd.Parts(p)
    if ps is None:
        return None
    sx, sy = ps.SizeX() or 0.0, ps.SizeY() or 0.0
    if sx <= 0.0 or sy <= 0.0:
        return None
    hx, hy = sx / 2.0, sy / 2.0
    mo = p * framedata.MATRIX_STRIDE
    mat = wm[mo:mo + framedata.MATRIX_STRIDE]
    # Local corners LT, RT, LB, RB (Y-down), pivot assumed centred (matches how
    # a Normal part's cell quad is laid out about its origin).
    local = ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy))
    positions = [framedata._transform(mat, lx, ly) for (lx, ly) in local]
    return dict(positions=positions, uvs=[(0.0, 0.0)] * 4,
                triangles=list(_QUAD_TRIS), texture_hash=0, has_texture=False)


def _mesh_writer_geom(rt, fd, p, thash):
    """Coverage geometry for a Mesh(deform) clipping writer part."""
    mesh_soa = (rt.mesh_vertices_x(), rt.mesh_vertices_y(), rt.mesh_uvs(),
                rt.mesh_indices(), rt.mesh_vertex_offsets(),
                rt.mesh_index_offsets())
    ps = fd.Parts(p)
    mp = framedata._read_mesh_part(mesh_soa, ps, p, 0, thash, False)
    if mp is None:
        return None
    return dict(positions=list(mp.positions), uvs=list(mp.uvs),
                triangles=list(mp.triangles), texture_hash=thash,
                has_texture=bool(thash))


def build_frame_mask(rt, fd, part_infos) -> Optional[FrameMask]:
    """Build the :class:`FrameMask` for ``fd``, or ``None`` if no live writer.

    Walks ``fd``'s draw batches in draw order (the same order the renderable
    walk uses, so ranks line up), classifies each part via its static
    ``PartInfo`` (writer / clipping / pure), drops writers with per-frame
    ``mask == 0`` (§2-2 opt-out) and beyond :data:`MAX_WRITERS`, reads each
    writer's coverage geometry from the SoA, and records the world bbox + scope
    bounds. Must run right after ``rt.get_frame_data`` for ``fd`` — the SoA
    pointers are transient.

    ``part_infos`` is a list indexed by part index (``SsabMeta.parts()``).
    """
    parts = framedata.bulk_part_states(fd)
    writers: List[MaskWriter] = []
    seen_writers: set = set()
    rank_of: dict = {}
    bx0 = by0 = float("inf")
    bx1 = by1 = float("-inf")
    capped = False
    for b in range(fd.DrawBatchesLength()):
        batch = fd.DrawBatches(b)
        kind = batch.Kind()
        thash = batch.TextureHash()
        start, count = batch.StartRank(), batch.Count()
        for k in range(count):
            p = fd.DrawOrder(start + k)
            # Rank is the draw_order *slot* index, not a per-batch counter: one
            # part can be emitted as several batches sharing a slot (e.g. a
            # draw_as_mask Shape appears as both a Mask and a Shape batch at the
            # same start_rank), and §2-1 defines rank as the position in
            # draw_order. Dedupe writers on part index for the same reason.
            rank = start + k
            rank_of[p] = rank
            pinfo = part_infos[p] if 0 <= p < len(part_infos) else None
            if pinfo is None or not pinfo.is_mask_writer or p in seen_writers:
                continue
            if len(writers) >= MAX_WRITERS:
                capped = True
                continue
            ps = parts[p] if parts is not None else fd.Parts(p)
            mask_val = ps.Mask() if ps is not None else 0.0
            if not mask_val:                       # §2-2: mask == 0 → no write
                continue
            if kind == framedata.KIND_MESH:
                geom = _mesh_writer_geom(rt, fd, p, thash)
            else:
                # Cell-less writers (Shape / draw_as_mask) have no quad in the
                # Normal local_vertices SoA — it collapses to a point — so their
                # region comes from PartState.Size instead. (``parts[p]`` may be
                # a fast-path _PartLite without ``Cell()``, so read the real
                # PartState for the cell index.)
                psf = fd.Parts(p)
                cell = psf.Cell() if psf is not None else -1
                if cell is not None and cell >= 0:
                    geom = _quad_writer_geom(rt, fd, p, thash)   # textured quad
                else:
                    geom = _shape_writer_geom(rt, fd, p)         # size-based quad
            if geom is None or not geom["positions"]:
                continue
            w = MaskWriter(
                part_index=p, rank=rank, bit=len(writers),
                op_invert=bool(pinfo.mask_influence),
                is_clipping=bool(pinfo.is_clipping),
                mask_value=float(mask_val), **geom)
            writers.append(w)
            seen_writers.add(p)
            for (x, y) in w.positions:
                if x < bx0:
                    bx0 = x
                if y < by0:
                    by0 = y
                if x > bx1:
                    bx1 = x
                if y > by1:
                    by1 = y

    if not writers:
        return None

    bw = max(bx1 - bx0, 1e-3)
    bh = max(by1 - by0, 1e-3)
    meta = [(w.rank, w.bit, 1 if w.op_invert else 0, 1 if w.is_clipping else 0)
            for w in writers]
    mask_ranks = [w.rank for w in writers if not w.is_clipping]
    clip_ranks = [w.rank for w in writers if w.is_clipping]
    fm = FrameMask(
        writers=writers, meta=meta, bmin=(bx0, by0), bsize=(bw, bh),
        max_mask_rank=max(mask_ranks) if mask_ranks else -1,
        min_clip_rank=min(clip_ranks) if clip_ranks else None,
        rank_of=rank_of)
    fm.capped = capped       # diagnostics only (not part of the dataclass)
    return fm


def attach_target(mp, frame_mask: FrameMask, part_infos) -> None:
    """Stamp ``mp.mask`` if the drawable Normal/Mesh part is a masked target.

    A drawing part is masked only when its static ``mask_influence == 1`` (§2-2
    opt-out) **and** it is in some writer's scope (or it is a ``visible_inside``
    target, which is always evaluated — it shows only where a mask covers it).
    Mutates ``mp`` in place; leaves ``mp.mask = None`` for non-targets.
    """
    p = mp.part_index
    pinfo = part_infos[p] if 0 <= p < len(part_infos) else None
    if pinfo is None or not pinfo.mask_influence:
        return
    rank = frame_mask.rank_of.get(p)
    if rank is None:
        return
    vis_inside = bool(pinfo.visible_inside_mask)
    if frame_mask.in_scope(rank) or vis_inside:
        mp.mask = MaskApply(frame_mask, rank, vis_inside)


def attach_inherited(mp, frame_mask: FrameMask, inst_info, inst_rank: int) -> None:
    """Stamp inherited masking onto an instance child's drawable (09_mask §3-2-2).

    The whole sub-animation is judged as ONE target by the **instance part's**
    ``rank`` + ``visible_inside_mask`` — never the child part's own. The child
    geometry has already been composed into the parent's world space by
    :func:`framedata.transform_mesh_part`, so its coverage UV maps into the
    parent's bbox directly (no separate ``M_parent · slot_xf`` needed — that
    composition is implicit in transforming the child into parent space).
    Single-stage: only applied when the instance part itself is a masked target.
    """
    if mp.mask is not None:
        return                                   # child's own mask wins (rare)
    if inst_info is None or not inst_info.mask_influence:
        return
    vis_inside = bool(inst_info.visible_inside_mask)
    if frame_mask.in_scope(inst_rank) or vis_inside:
        mp.mask = MaskApply(frame_mask, inst_rank, vis_inside)


def mask_passes(frame_mask: FrameMask, rank: int, visible_inside: bool,
                cov_uv, sample_bit) -> bool:
    """CPU reference of the replay shader's ``ss_mask_passes`` (09_mask §3-2-1).

    ``cov_uv`` is the target fragment's coverage UV; ``sample_bit(bit) -> bool``
    reports whether ``bit`` is set in the coverage at that UV (the headless
    rasterizer / test supplies this; the GPU samples the bitmap). Returns True to
    draw, False to ``discard``. This is the authority the GLSL must reproduce.
    """
    if frame_mask is None or frame_mask.count == 0:
        return True
    u, v = cov_uv
    if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
        # bbox-outside == "no writer covers it" (§3-2 CLAMP-avoidance):
        # visible_inside targets discard, outside targets draw.
        return not visible_inside
    stencil = 0
    for (w_rank, bit, op_invert, is_clipping) in frame_mask.meta:
        active = (rank > w_rank) if is_clipping else (rank < w_rank)   # §2-1
        if not active:
            continue
        if not sample_bit(bit):
            continue
        if op_invert:                       # §2-3 OP
            stencil = (~stencil) & 0xFF
        else:
            stencil = (stencil + 1) & 0xFF
    masked = stencil != 0
    return masked == visible_inside         # §2-4
