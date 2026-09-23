"""Engine-independent mask / clipping-mask core.

SpriteStudio "mask" and "clipping" are two features over one stencil. Ren'Py's
GL2 model layer does not expose a stencil buffer, so — exactly like the Godot
port — we use the **coverage-bitmap hybrid**:

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

Field provenance is split across two tables:
  * **static** (``PartInfo`` from ``ssab_meta``): ``mask_influence`` /
    ``mask_write`` / ``visible_inside_mask`` / ``draw_as_mask`` / part type.
  * **per-frame** (``PartState``): ``Mask`` (cutout 0..255) / ``Priority`` /
    ``Hide``. Hidden parts are already absent from ``draw_order``, so a writer's
    only per-frame gate here is ``mask != 0``.
"""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field
from typing import List, Optional

from ss_renpy import framedata

# Coverage encodes one writer per bit across the RGB channels of an RGBA8
# bitmap (8 bits x 3). The alpha channel is reserved (premultiplied accumulator
# in the GPU path), so the hard cap is 24.
MAX_WRITERS = 24

# Identity element of the instance-hierarchy composition.
# A top-level animation is reached with
# "influence still allowed / draw outside", so every part evaluates exactly its
# own settings; ``visible_inside`` accumulates by OR and ``influence`` chains by
# AND from here down.
ROOT_CONTEXT = (True, False)          # (influence, visible_inside)

# Two triangles for a 4-corner quad (LT, RT, LB, RB) — matches the non-fan
# layout in framedata._mesh_part_from so winding is consistent with the
# drawable path.
_QUAD_TRIS = [(framedata.LT, framedata.RT, framedata.LB),
              (framedata.RT, framedata.RB, framedata.LB)]


@dataclass
class MaskWriter:
    """One coverage writer for the current frame.

    ``positions`` / ``uvs`` / ``triangles`` are the geometry to rasterize into
    the coverage bitmap (world space, texture-pixel UVs — the render layer
    normalizes by the atlas size, as everywhere else). ``op_invert`` is the OP
    (``mask_influence``: False = increment, True = invert). ``is_clipping``
    distinguishes a clipping writer (also drawn in colour, applies to *higher*
    ranks) from a pure mask (applies to *lower* ranks). ``mask_value`` is the
    per-frame cutout (0..255) → threshold ``(255 - mask) / 255``; ``has_texture``
    is False for a texture-less shape mask (whole geometry is the mask).
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
    """Per-target replay parameters stamped onto a drawable.

    A drawable part that is masked carries one of these. ``frame_mask`` is the
    coverage it samples (the *parent's* coverage for an inherited instance
    child); ``rank`` and ``visible_inside`` are this target's draw-order rank and
    polarity. The render layer uses ``frame_mask`` for the coverage
    texture + ``mask_meta`` and ``rank`` / ``visible_inside`` for the replay
    uniforms; ``mask_passes`` below is the CPU reference of that replay.
    """
    frame_mask: "FrameMask"
    rank: int
    visible_inside: bool


@dataclass
class MaskInherit:
    """The effective mask context an Instance part hands to its sub-animation.

    ``influence`` / ``visible_inside`` are the values *already composed* down to
    (and including) the Instance part — each part of the sub-animation composes
    its own settings on top via :func:`compose`. ``rank`` stays the **outermost**
    Instance part's rank in the root's ``draw_order``, because that is where the
    whole sub-animation sits in the parent's draw order — nesting deeper does not
    move it. ``frame_mask`` is likewise always the root's coverage: a child never
    builds its own.
    """
    frame_mask: "FrameMask"
    rank: int
    influence: bool
    visible_inside: bool


def compose(parent, pinfo):
    """One hierarchy step of the mask-setting composition.

    ``parent`` is the caller's effective ``(influence, visible_inside)`` —
    :data:`ROOT_CONTEXT` at the top level. Returns the part's own effective pair:
    ``mask_influence`` chains by **AND** (once a caller opts its subtree out it
    can never come back), ``visible_inside_mask`` accumulates by **OR** (any
    level asking for "inside" wins below it). ``mask_write`` deliberately does
    not take part: writing a mask is a local fact about that one part, not
    something descendants inherit.
    """
    p_influence, p_visible = parent
    return (bool(p_influence) and bool(pinfo.mask_influence),
            bool(p_visible) or bool(pinfo.visible_inside_mask))


@dataclass
class FrameMask:
    """All masking state for one frame of one animation (one coverage bitmap).

    Built by :func:`build_frame_mask`. ``meta`` is parallel to ``writers``:
    ``(rank, bit, op_invert, is_clipping)`` per writer — exactly the replay
    shader's ``mask_meta``. ``bmin`` /
    ``bsize`` are the world bbox of all writer geometry; a target's coverage UV
    is ``(world - bmin) / bsize``. ``max_mask_rank`` / ``min_clip_rank`` are the
    scope bounds used to skip targets no writer can reach.
    """
    writers: List[MaskWriter] = field(default_factory=list)
    meta: list = field(default_factory=list)       # [(rank, bit, op_invert, is_clipping)]
    bmin: tuple = (0.0, 0.0)
    bsize: tuple = (1.0, 1.0)
    max_mask_rank: int = -1                         # max rank of pure-mask writers
    min_clip_rank: Optional[int] = None             # min rank of clipping writers
    rank_of: dict = field(default_factory=dict)     # part_index -> draw-order rank
    # Raw world bbox accumulator [x0, y0, x1, y1], kept so add_bubbled can extend
    # it before finalize re-derives bmin/bsize.
    _raw: list = field(default_factory=lambda: [float("inf"), float("inf"),
                                                float("-inf"), float("-inf")])

    @property
    def count(self) -> int:
        return len(self.writers)

    def in_scope(self, rank: int) -> bool:
        """True if any writer can affect a target at ``rank``.

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

    def finalize(self) -> None:
        """(Re)derive ``bmin`` / ``bsize`` / ``meta`` / scope bounds from the
        current writers. Called by :func:`build_frame_mask` after the owner's own
        writers, and again after :meth:`add_bubbled` has folded in any
        instance-child clipping writers."""
        raw = self._raw
        if self.writers and raw[2] >= raw[0]:
            self.bmin = (raw[0], raw[1])
            self.bsize = (max(raw[2] - raw[0], 1e-3), max(raw[3] - raw[1], 1e-3))
        self.meta = [(w.rank, w.bit, 1 if w.op_invert else 0,
                      1 if w.is_clipping else 0) for w in self.writers]
        mask_ranks = [w.rank for w in self.writers if not w.is_clipping]
        clip_ranks = [w.rank for w in self.writers if w.is_clipping]
        self.max_mask_rank = max(mask_ranks) if mask_ranks else -1
        self.min_clip_rank = min(clip_ranks) if clip_ranks else None

    def note_pending_clip_ranks(self, ranks) -> None:
        """Lower ``min_clip_rank`` to include instance parts that WILL bubble a
        clipping writer this frame, so :meth:`in_scope` — the cheap
        pre-filter run while targets are stamped, *before* the child clippers are
        actually gathered — already counts them. The per-writer replay test stays
        authoritative, so an over-inclusive rank here only costs a redundant
        shader pass, never a wrong pixel."""
        if not ranks:
            return
        m = min(ranks)
        self.min_clip_rank = m if self.min_clip_rank is None \
            else min(self.min_clip_rank, m)

    def add_bubbled(self, desc, mat, rank: int, inherited_influence: bool) -> bool:
        """Fold one instance-child clipping writer into this coverage.

        ``desc`` is a :func:`clip_writer_desc` read from the sub-animation's drawn
        geometry (sub-anim-local space); ``mat`` is the instance slot's world
        matrix (sub-anim local → this coverage's space); ``rank`` is the instance
        part's rank in this owner's draw order (the whole sub-animation sits
        there, so its writers clip the owner's parts drawn after it);
        ``inherited_influence`` is the composed ``mask_influence`` reaching the
        child, ANDed into the writer's OP so a ``mask_influence == 0`` instance
        drops its writers onto the union (increment) plane. Extends the raw bbox;
        the caller re-runs :meth:`finalize` afterwards. Returns False when the
        writer budget is full."""
        if len(self.writers) >= MAX_WRITERS:
            self.capped = True
            return False
        if mat is not None:
            positions = [framedata._transform(mat, x, y)
                         for (x, y) in desc["positions"]]
        else:
            positions = list(desc["positions"])
        w = MaskWriter(
            part_index=-2, rank=rank, bit=len(self.writers),
            op_invert=bool(desc["op_invert"] and inherited_influence),
            is_clipping=True, mask_value=float(desc["mask_value"]),
            texture_hash=desc["texture_hash"], has_texture=desc["has_texture"],
            positions=positions, uvs=list(desc["uvs"]),
            triangles=list(desc["triangles"]))
        self.writers.append(w)
        raw = self._raw
        for (x, y) in positions:
            if x < raw[0]:
                raw[0] = x
            if y < raw[1]:
                raw[1] = y
            if x > raw[2]:
                raw[2] = x
            if y > raw[3]:
                raw[3] = y
        return True


# Every SoA buffer the three writer-geometry builders below can need. Each field
# is one FFI call returning a pointer that is fixed for the frame, so they are
# fetched ONCE per build_frame_mask instead of per writer (a quad writer needs
# four of them, a mesh writer six).
_WriterSoA = namedtuple(
    "_WriterSoA", "world local_verts local_uvs cell shape mesh")


def _writer_soa(rt) -> _WriterSoA:
    """Snapshot the transient SoA pointers for one frame's writer geometry."""
    return _WriterSoA(
        world=rt.world_matrices(),
        local_verts=rt.local_vertices(),
        local_uvs=rt.local_uvs(),
        cell=rt.cell_meta(),
        shape=(rt.shape_vertices(), rt.shape_vertex_box_coords(),
               rt.shape_vertex_counts()),
        mesh=(rt.mesh_vertices_x(), rt.mesh_vertices_y(), rt.mesh_uvs(),
              rt.mesh_indices(), rt.mesh_vertex_offsets(),
              rt.mesh_index_offsets()))


def _quad_writer_geom(soa, fd, p, thash):
    """Coverage geometry for a Normal/Mask-kind writer part (a textured quad)."""
    (wm, _), (lv, _) = soa.world, soa.local_verts
    (uv, _), (cm, _) = soa.local_uvs, soa.cell
    if not wm or not lv:
        return None
    ps = fd.Parts(p)
    part = framedata._read_normal_part(wm, lv, uv, cm, ps, p, 0, thash, False)
    l, t, w, h = part.src_rect
    has_texture = bool(thash) and w > 0 and h > 0
    return dict(positions=list(part.positions[:4]), uvs=list(part.uvs[:4]),
                triangles=list(_QUAD_TRIS), texture_hash=thash,
                has_texture=has_texture)


def _shape_writer_geom(soa, fd, p):
    """Coverage geometry for a cell-less writer (Shape / draw_as_mask part).

    Prefer the runtime's **real Shape geometry** (the ``shape_vertices`` SoA — a
    TRIANGLE_FAN of the actual rectangle / triangle / star / arrow), so a shape
    mask cuts its true silhouette rather than a bounding box. Falls back to the
    part's ``PartState.Size`` box (transformed by the world matrix) for a
    cell-less writer the runtime exposes no shape geometry for — texture-less,
    whole geometry is the mask. Returns None
    for a zero-size / empty part.
    """
    wm, wn = soa.world
    if not wm:
        return None
    ps = fd.Parts(p)
    if ps is None:
        return None
    # Real shape polygon (exact silhouette) when the runtime provides it.
    sp = framedata._read_shape_part(soa.shape, wm, wn, fd, ps, p, 0, False)
    if sp is not None and len(sp.positions) >= 3:
        return dict(positions=list(sp.positions),
                    uvs=[(0.0, 0.0)] * len(sp.positions),
                    triangles=list(sp.triangles), texture_hash=0,
                    has_texture=False)
    # Fallback: size-based bounding quad (pivot assumed centred, matching how a
    # Normal part's cell quad is laid out about its origin).
    sx, sy = ps.SizeX() or 0.0, ps.SizeY() or 0.0
    if sx <= 0.0 or sy <= 0.0:
        return None
    hx, hy = sx / 2.0, sy / 2.0
    mo = p * framedata.MATRIX_STRIDE
    mat = wm[mo:mo + framedata.MATRIX_STRIDE]
    local = ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy))   # LT, RT, LB, RB (Y-down)
    positions = [framedata._transform(mat, lx, ly) for (lx, ly) in local]
    return dict(positions=positions, uvs=[(0.0, 0.0)] * 4,
                triangles=list(_QUAD_TRIS), texture_hash=0, has_texture=False)


def _mesh_writer_geom(soa, fd, p, thash):
    """Coverage geometry for a Mesh(deform) clipping writer part."""
    ps = fd.Parts(p)
    mp = framedata._read_mesh_part(soa.mesh, ps, p, 0, thash, False)
    if mp is None:
        return None
    return dict(positions=list(mp.positions), uvs=list(mp.uvs),
                triangles=list(mp.triangles), texture_hash=thash,
                has_texture=bool(thash))


def build_frame_mask(rt, fd, part_infos, parts=None,
                     allow_empty=False) -> Optional[FrameMask]:
    """Build the :class:`FrameMask` for ``fd``, or ``None`` if no live writer.

    Walks ``fd``'s draw batches in draw order (the same order the renderable
    walk uses, so ranks line up), classifies each part via its static
    ``PartInfo`` (writer / clipping / pure), drops writers with per-frame
    ``mask == 0`` (the per-frame opt-out) and beyond :data:`MAX_WRITERS`, reads
    each writer's coverage geometry from the SoA, and records the world bbox + scope
    bounds. Must run right after ``rt.get_frame_data`` for ``fd`` — the SoA
    pointers are transient.

    ``part_infos`` is a list indexed by part index (``SsabMeta.parts()``).
    ``parts`` is an optional pre-decoded :func:`framedata.bulk_part_states` array
    (the caller already needs one for the renderable walk).
    """
    if parts is None:
        parts = framedata.bulk_part_states(fd)
    # This loop visits EVERY part in the pack, not just the writers, because rank
    # is the draw_order slot index — so it walks the batch/draw-order vectors with
    # the same bulk struct decodes the renderable walk uses rather than the
    # per-element FlatBuffers accessor chain.
    batches = framedata._draw_batch_list(fd)
    do = framedata._draw_order_array(fd)
    soa = _writer_soa(rt)
    writers: List[MaskWriter] = []
    seen_writers: set = set()
    rank_of: dict = {}
    bx0 = by0 = float("inf")
    bx1 = by1 = float("-inf")
    capped = False
    for (start, count, thash, _vc, _ic, _bl, kind, _fl) in batches:
        for k in range(count):
            p = do[start + k]
            # Rank is the draw_order *slot* index, not a per-batch counter: one
            # part can be emitted as several batches sharing a slot (e.g. a
            # draw_as_mask Shape appears as both a Mask and a Shape batch at the
            # same start_rank), and rank is defined as the position in
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
            if not mask_val:                       # mask == 0 → no write
                continue
            if kind == framedata.KIND_MESH:
                geom = _mesh_writer_geom(soa, fd, p, thash)
            else:
                # Cell-less writers (Shape / draw_as_mask) have no quad in the
                # Normal local_vertices SoA — it collapses to a point — so their
                # region comes from PartState.Size instead. (``parts[p]`` may be
                # a fast-path _PartLite without ``Cell()``, so read the real
                # PartState for the cell index.)
                psf = fd.Parts(p)
                cell = psf.Cell() if psf is not None else -1
                if cell is not None and cell >= 0:
                    geom = _quad_writer_geom(soa, fd, p, thash)  # textured quad
                else:
                    geom = _shape_writer_geom(soa, fd, p)        # size-based quad
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

    # ``allow_empty`` keeps a writer-less FrameMask alive so an owner whose only
    # masks come from an instance child's carried-out clipping writers still has
    # a coverage to bubble them into; the caller drops it after
    # collect_ordered if nothing landed.
    if not writers and not allow_empty:
        return None

    fm = FrameMask(writers=writers, rank_of=rank_of)
    fm._raw = [bx0, by0, bx1, by1]
    fm.capped = capped       # diagnostics only (not part of the dataclass)
    fm.finalize()
    return fm


def clip_writer_desc(mp, mask_value) -> dict:
    """Coverage-writer descriptor for a clipping part, from its drawn MeshPart.

    ``positions`` / ``uvs`` / ``triangles`` are the part's drawn geometry in the
    SUB-ANIMATION's local space; the instance owner transforms them into coverage
    space via the slot matrix (:meth:`FrameMask.add_bubbled`). ``op_invert`` is
    the clipper's own ``mask_influence`` (its write OP); the owner composes it
    with the inherited influence. ``mask_value`` is the per-frame cutout."""
    return dict(positions=list(mp.positions), uvs=list(mp.uvs),
                triangles=list(mp.triangles), texture_hash=mp.texture_hash,
                has_texture=bool(mp.texture_hash),
                op_invert=bool(mp.mask_influence), mask_value=float(mask_value))


def attach_target(mp, frame_mask: Optional[FrameMask], part_infos,
                  inherited: Optional[MaskInherit] = None) -> None:
    """Stamp ``mp.mask`` if the drawable Normal/Mesh part is a masked target.

    Handles both the root animation (``frame_mask``, ``inherited=None``) and a
    part inside an Instance sub-animation (``inherited`` carries the composed
    context; ``frame_mask`` is unused then — a child never owns coverage).

    A drawing part is masked only when its **effective** ``mask_influence`` is 1
    after the hierarchy composition (:func:`compose`) — the opt-out — and it is
    in some writer's scope, or it is an effective ``visible_inside`` target,
    which is always evaluated because it shows only where a mask covers it.
    Mutates ``mp`` in place; leaves ``mp.mask = None`` for non-targets.
    """
    p = mp.part_index
    pinfo = part_infos[p] if 0 <= p < len(part_infos) else None
    if pinfo is None:
        return
    if inherited is None:
        if frame_mask is None:
            return
        fm, rank, parent = frame_mask, frame_mask.rank_of.get(p), ROOT_CONTEXT
    else:
        # Scope is judged at the Instance part's slot in the *root's* draw order —
        # the child's own rank means nothing to the parent's
        # coverage, and part indices are a per-pack namespace anyway.
        fm, rank = inherited.frame_mask, inherited.rank
        parent = (inherited.influence, inherited.visible_inside)
    if rank is None:
        return
    influence, vis_inside = compose(parent, pinfo)
    if not influence:
        return
    if fm.in_scope(rank) or vis_inside:
        mp.mask = MaskApply(fm, rank, vis_inside)


def inherit_for(part_index: int, part_infos, frame_mask: Optional[FrameMask],
                inherited: Optional[MaskInherit] = None) -> Optional[MaskInherit]:
    """Context to hand down into an Instance part's sub-animation, or ``None``.

    Composes the Instance part's own settings onto the caller's context
    so the sub-animation's parts can compose their
    own on top. ``None`` means "nothing below can be masked": either there is no
    coverage this frame, or the AND chain of ``mask_influence`` has latched off,
    which no descendant can undo.

    Deliberately *not* gated on scope: ``visible_inside`` only accumulates going
    down, so a descendant may be an inside-target even where the Instance part
    itself is out of every writer's reach — and an inside-target out of scope
    must discard, not draw. :func:`attach_target` makes that call per part.
    """
    pinfo = part_infos[part_index] if 0 <= part_index < len(part_infos) else None
    if pinfo is None:
        return None
    if inherited is None:
        if frame_mask is None:
            return None
        rank = frame_mask.rank_of.get(part_index)
        if rank is None:
            return None
        fm, parent = frame_mask, ROOT_CONTEXT
    else:
        fm, rank = inherited.frame_mask, inherited.rank
        parent = (inherited.influence, inherited.visible_inside)
    influence, vis_inside = compose(parent, pinfo)
    if not influence:
        return None
    return MaskInherit(fm, rank, influence, vis_inside)


def mask_passes(frame_mask: FrameMask, rank: int, visible_inside: bool,
                cov_uv, sample_bit) -> bool:
    """CPU reference of the replay shader's ``ss_mask_passes``.

    ``cov_uv`` is the target fragment's coverage UV; ``sample_bit(bit) -> bool``
    reports whether ``bit`` is set in the coverage at that UV (the headless
    rasterizer / test supplies this; the GPU samples the bitmap). Returns True to
    draw, False to ``discard``. This is the authority the GLSL must reproduce.

    The two writer OPs get **separate accumulators**. ``Invert``
    and ``Increment`` are each self-inverse but do not commute, so replaying both
    into one accumulator makes the coverage depend on writer order — ``incr ->
    invert`` covers where ``invert -> incr`` does not. Splitting them keeps
    ``mask_influence == 1`` writers on parity (odd overlap covers) and
    ``mask_influence == 0`` writers on a counter (any overlap covers); the result
    is their **union**, which is what SS7.5 does when the two kinds overlap.
    Unlike the GPU-stencil ports there is no bit budget here — these are plain
    variables — so the counter has no overlap ceiling beyond
    :data:`MAX_WRITERS`.
    """
    if frame_mask is None or frame_mask.count == 0:
        return True
    u, v = cov_uv
    if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
        # bbox-outside == "no writer covers it" (CLAMP-avoidance):
        # visible_inside targets discard, outside targets draw.
        return not visible_inside
    parity = 0          # Invert writers  (mask_influence == 1): odd overlap
    count = 0           # Increment writers (mask_influence == 0): any overlap
    for (w_rank, bit, op_invert, is_clipping) in frame_mask.meta:
        active = (rank > w_rank) if is_clipping else (rank < w_rank)   # scope rule
        if not active:
            continue
        if not sample_bit(bit):
            continue
        if op_invert:                       # writer OP: invert vs increment
            parity ^= 1
        else:
            count += 1
    masked = parity != 0 or count != 0       # union of the two planes
    return masked == visible_inside         # inside/outside polarity
