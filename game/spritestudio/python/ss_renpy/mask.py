"""Engine-independent mask / clipping-mask core.

SpriteStudio "mask" and "clipping" are two features over one stencil. Ren'Py's
GL2 model layer does not expose a stencil buffer, so — exactly like the Godot
port — we use the **coverage-bitmap hybrid**:

  1. Per frame, rasterize every mask *writer* into an offscreen RGBA8 bitmap,
     one bit per writer (24 packed into the RGB channels; past that the bitmap
     splits into tiles, see :data:`MAX_WRITERS`).
  2. Each masked *target* part, in its fragment shader, samples that coverage and
     *replays* the writers that hold their bit at its position to reconstruct
     the stencil, then ``discard``\\ s by the inside/outside test.

One coverage serves a whole instance tree. The root numbers every part of the
tree in draw order — a sub-animation is numbered in its Instance part's place —
and each writer holds its bit over an open interval of that number (``seq``): a
pure mask from the start of its own animation up to itself, a clipping writer
from itself to the end of the tree. That is where a shared stencil would hold
it, so a sub-animation's masks clip its own parts, the caller's masks clip the
sub-animation, and a clipping written at any depth keeps clipping everything the
tree draws after it.

This module owns the **engine-independent half**: reading the mask fields from
the draw plan, classifying writers (pure mask / clipping), building each
writer's coverage geometry, the bbox + ``local -> uv`` data the render layer
needs, the per-writer ``mask_meta`` the replay shader consumes, and a CPU
reference of the replay (:func:`mask_passes`) so the whole thing is testable
headless. The actual offscreen render + GLSL live in the Ren'Py layer
(``spritestudio.rpy``), the same split as UV normalization.

Field provenance is split across two tables:
  * **static** (``PartInfo`` from ``ssab_meta``): ``mask_influence`` /
    ``mask_write`` / ``visible_inside_mask`` / ``draw_as_mask`` / part type.
  * **per-frame** (``PartState``): ``Mask`` (cutout 0..255) / ``Priority`` /
    ``Hide``. A writer writes only where ``mask != 0`` and it is not hidden, and
    both are checked here: a hidden ``draw_as_mask`` part still has its Mask
    batch in the plan, so what the plan holds cannot stand in for ``Hide``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ss_renpy import framedata

# Coverage encodes one writer per bit across the RGB channels of an RGBA8
# bitmap (8 bits x 3). The alpha channel is reserved (premultiplied accumulator
# in the GPU path), so one tile holds 24.
TILE_WRITERS = 24
# An instance tree counts an instance's writers again each time it is placed,
# so 24 runs out quickly. Past it the same texture splits into 2, then 2x2,
# tiles, each mapping the same bbox with its own 24 bits: resolution is traded
# for writers without using more memory. The rest are dropped.
MAX_WRITERS = TILE_WRITERS * 4
# (tiles across, tiles down) for 1, 2 and 4 tiles.
_TILE_LAYOUTS = ((1, 1), (2, 1), (2, 2), (2, 2))

# Past every ``seq`` a tree can reach: a clipping writer's interval closes here
# while the tree is walked. :meth:`FrameMask.finalize` brings it down to the
# tree's own end, so the shader never compares a number larger than the tree:
# a GLES device without highp fragment floats holds integers exactly only up
# to 2048.
SEQ_END = 16777216.0

# What an Instance part hands its sub-animation, as ``(influence,
# visible_inside)``. A top-level animation is reached with "receives masks /
# draws outside", so each of its parts is decided by its own settings alone.
ROOT_CONTEXT = (True, False)

# Two triangles for a 4-corner quad (LT, RT, LB, RB) — matches the non-fan
# layout in framedata._mesh_part_from so winding is consistent with the
# drawable path.
_QUAD_TRIS = [(framedata.LT, framedata.RT, framedata.LB),
              (framedata.RT, framedata.RB, framedata.LB)]


@dataclass
class MaskWriter:
    """One coverage writer for the current frame.

    ``positions`` / ``uvs`` / ``triangles`` are the geometry to rasterize into
    the coverage bitmap (the root's world space once the owning animation has
    handed it up; texture-pixel UVs — the render layer normalizes by the atlas
    size, as everywhere else). ``open`` / ``close`` are the open interval of the
    tree's draw sequence over which the writer holds its bit. ``op_invert`` is
    the write op (effective ``mask_influence``: False = increment, True =
    invert). ``mask_value`` is the per-frame cutout (0..255) → threshold
    ``(255 - mask) / 255``; ``has_texture`` is False for a texture-less shape
    mask (whole geometry is the mask). ``bit`` is assigned by
    :meth:`FrameMask.finalize`.
    """
    part_index: int
    is_clipping: bool
    op_invert: bool
    mask_value: float
    texture_hash: int
    has_texture: bool
    positions: list           # [(x, y)]
    uvs: list                 # [(u, v)] texture px
    triangles: list           # [(i, j, k)] into positions
    rank: int = -1            # draw_order slot in the owning animation
    open: float = -1.0
    close: float = SEQ_END
    bit: int = -1


@dataclass
class MaskApply:
    """Per-target replay parameters stamped onto a drawable.

    ``frame_mask`` is the tree's one coverage; ``seq`` is this target's position
    in the tree's draw sequence and ``visible_inside`` its effective polarity.
    The render layer uses ``frame_mask`` for the coverage texture +
    ``mask_meta`` and ``seq`` / ``visible_inside`` for the replay uniforms;
    ``mask_passes`` below is the CPU reference of that replay.
    """
    frame_mask: "FrameMask"
    seq: float
    visible_inside: bool


@dataclass
class FrameMask:
    """All masking state for one frame of one instance tree (one coverage).

    Filled while the tree is walked (:class:`MaskTree`), then
    :meth:`finalize`\\ d by the root. ``meta`` is parallel to ``writers``:
    ``(open, close, bit, op_invert)`` per writer — exactly the replay shader's
    ``mask_meta``. ``bmin`` / ``bsize`` are the root-space bbox of all writer
    geometry; a target's coverage UV is ``(pos - bmin) / bsize``. ``capped`` is
    True when the tree had more live writers than :data:`MAX_WRITERS`.
    """
    writers: List[MaskWriter] = field(default_factory=list)
    meta: list = field(default_factory=list)       # [(open, close, bit, op_invert)]
    bmin: tuple = (0.0, 0.0)
    bsize: tuple = (1.0, 1.0)
    capped: bool = False
    end: float = SEQ_END          # where clipping intervals close (finalize)

    @property
    def count(self) -> int:
        return len(self.writers)

    @property
    def tiles(self) -> tuple:
        """``(across, down)`` tiles the coverage splits into: writer ``bit``
        lives in tile ``bit // TILE_WRITERS`` (row-major), at bit
        ``bit % TILE_WRITERS`` of it."""
        n = max(1, -(-len(self.writers) // TILE_WRITERS))
        return _TILE_LAYOUTS[min(n, 4) - 1]

    def covers(self, seq: float) -> bool:
        """True if any writer holds its bit at ``seq``.

        A target no writer covers is unmasked, so a part that draws outside can
        skip the replay; one that draws inside must not — it is hidden there.
        """
        for (o, c, _b, _op) in self.meta:
            if o < seq < c:
                return True
        return False

    def finalize(self, end: Optional[float] = None) -> None:
        """Keep the first :data:`MAX_WRITERS` writers in draw order, number
        their bits and derive ``bmin`` / ``bsize`` / ``meta`` from them.

        ``end`` is the tree's last ``seq`` + 1 (``MaskTree.seq`` after the
        walk): a clipping writer's interval closes there instead of at
        :data:`SEQ_END`, which reaches the same targets with a smaller number.
        """
        if len(self.writers) > MAX_WRITERS:
            # The writers arrive a sub-animation's first, then its caller's, so
            # sort them by where they are drawn: what is dropped is what the
            # tree draws last, not the top-level animation's own.
            self.writers.sort(key=lambda w: w.open if w.is_clipping else w.close)
            del self.writers[MAX_WRITERS:]
            self.capped = True
        if end is not None:
            self.end = end
            for w in self.writers:
                if w.close > end:
                    w.close = end
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for i, w in enumerate(self.writers):
            w.bit = i
            for (x, y) in w.positions:
                if x < x0:
                    x0 = x
                if y < y0:
                    y0 = y
                if x > x1:
                    x1 = x
                if y > y1:
                    y1 = y
        if self.writers and x1 >= x0:
            self.bmin = (x0, y0)
            self.bsize = (max(x1 - x0, 1e-3), max(y1 - y0, 1e-3))
        self.meta = [(w.open, w.close, w.bit, 1 if w.op_invert else 0)
                     for w in self.writers]

    def meta_uniform(self) -> list:
        """Flat ``vec4[24]`` — ``vec4[96]`` past 24 writers, for the tiled
        shader — of (open, close, op_invert, 0).

        The writer's bit is its index, so it is not stored. Padded to the full
        array length the shader declares. Depends only on the mask, so the
        render layer builds it once per mask per frame rather than once per
        target — here rather than in ``spritestudio.rpy``, for the reason
        :func:`pack_writer_mesh` gives."""
        vals = []
        v_ext = vals.extend
        for (w_open, w_close, _bit, op) in self.meta:
            v_ext((float(w_open), float(w_close), float(op), 0.0))
        need = (MAX_WRITERS if self.count > TILE_WRITERS else TILE_WRITERS) * 4
        diff = need - len(vals)
        if diff > 0:
            vals.extend([0.0] * diff)
        return vals


class MaskTree:
    """The per-frame masking state one instance tree shares while it is walked.

    The root creates it and hands it down with every sub-animation (inside a
    :class:`MaskInherit`). ``seq`` is the running draw-sequence counter; every
    animation takes its numbers from it in draw order, a sub-animation's right
    after its Instance part's. ``frame_mask`` is the coverage the root
    finalizes once the walk is over; targets reference it as soon as they are
    stamped. ``writes`` says whether the tree statically holds any writer — a
    target that draws outside needs the replay only then.
    """
    __slots__ = ("seq", "frame_mask", "writes")

    def __init__(self, writes: bool):
        self.seq = 0.0
        self.frame_mask = FrameMask()
        self.writes = bool(writes)


class MaskInherit:
    """What an Instance part hands the sub-animation it draws.

    ``influence`` / ``visible_inside`` are the Instance part's **own** flags —
    only one level reaches down, never what the Instance part itself received
    from further up. ``start_seq`` is the Instance part's position in the tree,
    where the sub-animation's pure masks open. ``writers`` collects the
    sub-animation's writers (with those of its own sub-animations) in its local
    space; the caller maps them into its own space.
    """
    __slots__ = ("tree", "influence", "visible_inside", "start_seq", "writers")

    def __init__(self, tree, influence, visible_inside, start_seq):
        self.tree = tree
        self.influence = bool(influence)
        self.visible_inside = bool(visible_inside)
        self.start_seq = start_seq
        self.writers = []


def child_context(tree, pinfo, start_seq) -> MaskInherit:
    """The context Instance part ``pinfo`` hands its sub-animation.

    Its own ``mask_influence`` / ``visible_inside_mask`` reach the
    sub-animation whether or not anything above masks, and only they do: an
    Instance part under a ``mask_influence == 0`` caller still hands down 1, so
    the parts of a nested instance are clipped again (SpriteStudio 7.6 on
    InstancePropagationTired3). ``mask_write`` takes no part — writing a mask is
    a fact about that one part.
    """
    return MaskInherit(tree, pinfo.mask_influence, pinfo.visible_inside_mask,
                       start_seq)


def target_mask(tree, pinfo, ctx, seq) -> Optional[MaskApply]:
    """The replay parameters for a drawing part at ``seq``, or ``None``.

    ``ctx`` is the ``(influence, visible_inside)`` the part's animation was
    reached with (:data:`ROOT_CONTEXT` at the top). The part receives masks only
    when its own ``mask_influence`` and the Instance part's are both 1, and its
    polarity is inside when either asks for it. A part that draws inside is
    always tested, even where the tree has no writer at all — the test is what
    hides it. The writers are only known once the whole tree is walked, so a
    part that draws outside is stamped whenever the tree can write, and the
    root drops the stamps no writer reaches (:func:`settle`).
    """
    if not (pinfo.mask_influence and ctx[0]):
        return None
    inside = bool(pinfo.visible_inside_mask or ctx[1])
    if not inside and not tree.writes:
        return None
    return MaskApply(tree.frame_mask, seq, inside)


def draws_only_inside(pinfo, ctx) -> bool:
    """Whether a part reached with ``ctx`` shows only where a mask covers it —
    the same effective flags as :func:`target_mask`.

    For a draw that has to go without masks (the mask walk failed): such a part
    is left out rather than drawn whole, which is what it would show with no
    mask at all. A part that draws outside is drawn whole, as with no mask.
    """
    return bool(pinfo.mask_influence and ctx[0]
                and (pinfo.visible_inside_mask or ctx[1]))


def settle(items, frame_mask: FrameMask) -> None:
    """Drop the stamps of the targets the replay cannot change.

    Run by the root after :meth:`FrameMask.finalize`: a target that draws
    outside where no writer holds its bit draws plainly, and keeps batching with
    its neighbours. A target that draws inside keeps its stamp — with no writer
    it must not draw at all.
    """
    for tag, mp in items:
        if tag != "mesh":
            continue
        ap = mp.mask
        if ap is not None and not ap.visible_inside \
                and not frame_mask.covers(ap.seq):
            mp.mask = None


class _WriterSoA:
    """The transient SoA buffers the three writer-geometry builders below read.

    Each is one FFI call returning a pointer that is fixed for the frame, so
    each is fetched once per collect_writers instead of per writer; the Shape
    and Mesh ones only when a writer of that kind reads them.
    """
    __slots__ = ("_rt", "world", "local_verts", "local_uvs", "cell",
                 "_shape", "_mesh")

    def __init__(self, rt):
        self._rt = rt
        self.world = rt.world_matrices()
        self.local_verts = rt.local_vertices()
        self.local_uvs = rt.local_uvs()
        self.cell = rt.cell_meta()
        self._shape = self._mesh = None

    @property
    def shape(self):
        if self._shape is None:
            self._shape = framedata._shape_soa(self._rt)
        return self._shape

    @property
    def mesh(self):
        if self._mesh is None:
            self._mesh = framedata._mesh_soa(self._rt)
        return self._mesh


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


def collect_writers(rt, fd, part_infos, parts=None,
                    influence=True) -> List[MaskWriter]:
    """This frame's live writers of ``fd``, in its own local space.

    Walks ``fd``'s draw batches in draw order, classifies each part via its
    static ``PartInfo`` (writer / clipping / pure), drops writers that write
    nothing this frame (``mask == 0`` or ``Hide``), and reads each writer's
    coverage geometry from the SoA. Each writer carries its ``draw_order`` slot
    as ``rank``; the caller turns that into its ``open`` / ``close`` once it
    has numbered the animation. ``influence`` is the ``mask_influence`` of the
    Instance part that draws this animation (True at the top): the write op is
    invert only when both it and the writer's own are 1, so under a
    ``mask_influence == 0`` instance the writer joins the union (increment)
    plane. Must run right after ``rt.get_frame_data`` for ``fd`` — the SoA
    pointers are transient.

    ``part_infos`` is a list indexed by part index (``SsabMeta.parts()``).
    ``parts`` is an optional pre-decoded :func:`framedata.bulk_part_states` array
    (the caller already needs one for the renderable walk).
    """
    if parts is None:
        parts = framedata.bulk_part_states(fd)
    batches = framedata._draw_batch_list(fd)
    do = framedata._draw_order_array(fd)
    soa = None
    writers: List[MaskWriter] = []
    seen_writers: set = set()
    for (start, count, thash, _vc, _ic, _bl, kind, _fl) in batches:
        for k in range(count):
            p = do[start + k]
            pinfo = part_infos[p] if 0 <= p < len(part_infos) else None
            if pinfo is None or not pinfo.is_mask_writer or p in seen_writers:
                continue
            ps = parts[p] if parts is not None else fd.Parts(p)
            if ps is None or ps.Hide():            # hidden → no write
                continue
            mask_val = ps.Mask()
            if not mask_val:                       # mask == 0 → no write
                continue
            if soa is None:
                soa = _WriterSoA(rt)
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
            # Rank is the draw_order *slot* index, not a per-batch counter: one
            # part can be emitted as several batches sharing a slot (a
            # draw_as_mask Shape appears as both a Mask and a Shape batch), so
            # writers are deduped on part index for the same reason.
            writers.append(MaskWriter(
                part_index=p, rank=start + k,
                is_clipping=bool(pinfo.is_clipping),
                op_invert=bool(pinfo.mask_influence and influence),
                mask_value=float(mask_val), **geom))
            seen_writers.add(p)
    return writers


def transform_writer(w: MaskWriter, m) -> MaskWriter:
    """Send ``w``'s positions through the Instance part's 4x4 matrix ``m``
    (sub-animation local → the caller's space), in place."""
    if m is not None:
        w.positions = [framedata._transform(m, x, y) for (x, y) in w.positions]
    return w


def pack_writer_mesh(w: MaskWriter, bx, by, sx, sy, tile_x, tile_y,
                     tex_size=None) -> tuple:
    """Pack ``w`` into flat (geometry, attributes, indices) arrays for the
    render layer's coverage mesh (a_tex_coord).

    Positions go from root space into the coverage tile whose top-left is
    (``tile_x``, ``tile_y``): ``(x - bx) * sx + tile_x``. UVs are normalized by
    ``tex_size`` (the atlas ``(w, h)``); with None the writer draws untextured
    and its UVs go unsampled, so they are zeros.

    Kept out of ``spritestudio.rpy`` for the reason
    :func:`ss_renpy.framedata.pack_pc_mesh` gives: a list built there is a
    ``RevertableList``.
    """
    geometry = []
    g_ext = geometry.extend
    for (x, y) in w.positions:
        g_ext(((x - bx) * sx + tile_x, (y - by) * sy + tile_y))
    if tex_size is not None:
        tw, th = tex_size
        inv_tw = (1.0 / tw) if tw > 0 else 1.0
        inv_th = (1.0 / th) if th > 0 else 1.0
        attributes = []
        a_ext = attributes.extend
        for (u, v) in w.uvs:
            a_ext((u * inv_tw, v * inv_th))
    else:
        attributes = [0.0] * (len(w.positions) * 2)
    indices = []
    i_ext = indices.extend
    for tri in w.triangles:
        i_ext(tri)
    return geometry, attributes, indices


def mask_passes(frame_mask: FrameMask, seq: float, visible_inside: bool,
                cov_uv, sample_bit) -> bool:
    """CPU reference of the replay shader's ``ss_mask_passes``.

    ``cov_uv`` is the target fragment's coverage UV; ``sample_bit(bit) -> bool``
    reports whether ``bit`` is set in the coverage at that UV (the headless
    rasterizer / test supplies this; the GPU samples the bitmap). Returns True to
    draw, False to ``discard``. This is the authority the GLSL must reproduce.

    With no writer, or outside the writers' bbox, nothing is masked, so the
    polarity alone decides: a target that draws inside is hidden there.

    The two writer OPs get **separate accumulators**. ``Invert``
    and ``Increment`` are each self-inverse but do not commute, so replaying both
    into one accumulator makes the coverage depend on writer order — ``incr ->
    invert`` covers where ``invert -> incr`` does not. Splitting them keeps
    ``mask_influence == 1`` writers on parity (odd overlap covers) and
    ``mask_influence == 0`` writers on a counter (any overlap covers); the result
    is their **union**, which is what SpriteStudio 7.6 does when the two kinds overlap.
    Unlike the GPU-stencil ports there is no bit budget here — these are plain
    variables — so the counter has no overlap ceiling beyond
    :data:`MAX_WRITERS`.
    """
    if frame_mask is None or frame_mask.count == 0:
        return not visible_inside
    u, v = cov_uv
    if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
        # bbox-outside == "no writer covers it" (CLAMP-avoidance).
        return not visible_inside
    parity = 0          # Invert writers  (mask_influence == 1): odd overlap
    count = 0           # Increment writers (mask_influence == 0): any overlap
    for (w_open, w_close, bit, op_invert) in frame_mask.meta:
        if not (w_open < seq < w_close):    # the writer's interval
            continue
        if not sample_bit(bit):
            continue
        if op_invert:                       # writer OP: invert vs increment
            parity ^= 1
        else:
            count += 1
    masked = parity != 0 or count != 0       # union of the two planes
    return masked == visible_inside         # inside/outside polarity
