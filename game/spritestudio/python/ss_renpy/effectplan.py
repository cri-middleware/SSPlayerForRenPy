"""Decode an ``EffectDrawPlan`` (from ``ss_effect_slot_step``) into batches.

This is the engine-independent render-data core for **Effect parts**
(particles), the analogue of :mod:`ss_renpy.framedata` for Normal parts. The
Brain simulates the particle system and hands back a FlatBuffers
``EffectDrawPlan``: a set of per-emitter draw *commands* pointing into four flat
arrays (verts / uvs / colors / indices). We slice those per command, apply the
parent Effect-part's world matrix, and emit triangulated, coloured world-space
:class:`EffectBatch` quads the Ren'Py layer can mesh.

Buffer layout (``runtime/effect_draw_plan.fbs`` + docs/08 §2):

* ``vert_stride`` is 2 (XY) for a 2D host like Ren'Py (we request 2).
* ``verts``   = ``total_quads * 4 * vert_stride`` floats
* ``uvs``     = ``total_quads * 4 * 2`` floats (interleaved ``u, v``)
* ``colors``  = ``total_quads * 4 * 4`` floats (RGBA, normalized 0..1)
* ``indices`` = ``total_quads * 6`` ints, **command-local 0-based** (0..N within
  the command's own vertex slice — slice both verts and indices for a command
  and they line up with no rebasing; only when *merging* commands into one
  buffer do indices need the running vertex count added).

Each ``EffectDrawCommand`` carries ``cellmap_hash`` (texture key, same space as
``DrawBatch.texture_hash``), ``blend`` (0=Mix, 1=Add — the raw
``EmitterState.blend_type``), ``quad_count`` and ``particle_offset`` (in quads).

Lifetime: ``build_effect_batches`` drains the plan into Python lists in a single
pass and never retains the input, so it accepts either an owned ``bytes``
(``SSRuntime.effect_slot_step``) or a transient zero-copy ``memoryview``
(``SSRuntime.effect_slot_step_view``) — the latter being the hot path.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ss.runtime.EffectDrawPlan import EffectDrawPlan

# EmitterState.blend_type values carried on EffectDrawCommand.blend.
FX_BLEND_MIX, FX_BLEND_ADD = 0, 1
FX_BLEND_NAMES = {0: "Mix", 1: "Add"}

# FlatBuffers vtable slot offsets for EffectDrawPlan's flat vectors (from the
# generated accessors: Commands=4, VertStride=6, Verts=8, Uvs=10, Colors=12,
# Indices=14). We read the scalar vectors in bulk via struct rather than the
# per-element accessors (the §07 "per-element accessors are heavy" warning).
_OFF_VERTS, _OFF_UVS, _OFF_COLORS, _OFF_INDICES = 8, 10, 12, 14


@dataclass
class EffectBatch:
    """One emitter's particle quads resolved to a coloured world-space mesh.

    ``positions`` are world pixels (the parent Effect-part matrix already
    applied; coordinate-system Y-flip already applied by the runtime via
    ``y_flip``). ``uvs`` are passed through verbatim from the plan (see
    :func:`uv_span` to detect pixel vs normalized). ``colors`` are RGBA 0..1
    (the parent part's alpha pre-multiplied in). ``triangles`` index into the
    vertex arrays. ``blend`` is the particle framebuffer blend (Mix/Add).
    """
    cellmap_hash: int
    blend: int
    positions: list   # [(x, y)] world
    uvs: list         # [(u, v)]
    colors: list      # [(r, g, b, a)] 0..1
    triangles: list   # [(i, j, k)]


def parse(buf) -> EffectDrawPlan:
    return EffectDrawPlan.GetRootAs(buf, 0)


def _bulk_floats(plan: EffectDrawPlan, vtable_off: int, n: int) -> list:
    """Read ``n`` floats of a plan vector in one ``struct`` call (no numpy)."""
    if n <= 0:
        return []
    o = plan._tab.Offset(vtable_off)
    if o == 0:
        return []
    a = plan._tab.Vector(o)
    return list(struct.unpack_from("<%df" % n, plan._tab.Bytes, a))


def _bulk_ints(plan: EffectDrawPlan, vtable_off: int, n: int) -> list:
    if n <= 0:
        return []
    o = plan._tab.Offset(vtable_off)
    if o == 0:
        return []
    a = plan._tab.Vector(o)
    return list(struct.unpack_from("<%di" % n, plan._tab.Bytes, a))


def _apply(m, x, y):
    # 4x4 column-major affine subset, same convention as framedata._transform.
    if m is None:
        return (x, y)
    return (m[0] * x + m[4] * y + m[12],
            m[1] * x + m[5] * y + m[13])


def build_effect_batches(buf, matrix=None, alpha: float = 1.0,
                         merge: bool = True) -> list:
    """Decode an ``EffectDrawPlan`` buffer into world-space :class:`EffectBatch`.

    ``matrix`` is the parent Effect-part's 16-float column-major world matrix
    (from the parent SoA buffer); particle verts are slot-local and must be
    transformed by it (docs/08 §2). ``alpha`` (0..1) is the parent part's
    hierarchical alpha, multiplied into every vertex colour's alpha — the flat
    renderer's stand-in for hierarchical modulate inheritance. When ``merge``
    is set, consecutive commands sharing ``(cellmap_hash, blend)`` are merged
    into one batch (dynamic batching, docs/08 §2 最適化), rebasing indices by the
    running vertex count.
    """
    if not buf:
        return []
    plan = parse(buf)
    ncmd = plan.CommandsLength()
    if ncmd == 0:
        return []
    stride = plan.VertStride() or 2

    verts = _bulk_floats(plan, _OFF_VERTS, plan.VertsLength())
    uvs = _bulk_floats(plan, _OFF_UVS, plan.UvsLength())
    colors = _bulk_floats(plan, _OFF_COLORS, plan.ColorsLength())
    indices = _bulk_ints(plan, _OFF_INDICES, plan.IndicesLength())
    a_mul = max(0.0, min(1.0, alpha))

    batches: list[EffectBatch] = []
    for c in range(ncmd):
        cmd = plan.Commands(c)
        if cmd is None:
            continue
        quad_count = cmd.QuadCount()
        if quad_count == 0:
            continue
        poff = cmd.ParticleOffset()
        nverts = quad_count * 4
        v_off = poff * 4 * stride
        u_off = poff * 4 * 2
        c_off = poff * 4 * 4
        i_off = poff * 6

        positions = []
        for i in range(nverts):
            base = v_off + i * stride
            positions.append(_apply(matrix, verts[base], verts[base + 1]))
        uv = [(uvs[u_off + i * 2], uvs[u_off + i * 2 + 1]) for i in range(nverts)]
        col = []
        for i in range(nverts):
            b = c_off + i * 4
            col.append((colors[b], colors[b + 1], colors[b + 2],
                        colors[b + 3] * a_mul))
        flat_idx = indices[i_off:i_off + quad_count * 6]
        tris = [(flat_idx[t], flat_idx[t + 1], flat_idx[t + 2])
                for t in range(0, len(flat_idx) - 2, 3)]

        batch = EffectBatch(
            cellmap_hash=cmd.CellmapHash(), blend=cmd.Blend(),
            positions=positions, uvs=uv, colors=col, triangles=tris)

        if (merge and batches
                and batches[-1].cellmap_hash == batch.cellmap_hash
                and batches[-1].blend == batch.blend):
            prev = batches[-1]
            base = len(prev.positions)
            prev.positions.extend(batch.positions)
            prev.uvs.extend(batch.uvs)
            prev.colors.extend(batch.colors)
            prev.triangles.extend((i + base, j + base, k + base)
                                  for (i, j, k) in batch.triangles)
        else:
            batches.append(batch)
    return batches


def transform_effect_batch(eb: EffectBatch, m, alpha_mul: float = 1.0) -> EffectBatch:
    """Copy ``eb`` with positions through 4x4 ``m`` and vertex alpha scaled.

    Used when an Effect part lives inside an Instance child: the effect batch is
    built in the child's world space, then composed up by the Instance part's
    world matrix (``m``) and hierarchical alpha (``alpha_mul``), mirroring
    :func:`ss_renpy.framedata.transform_mesh_part`.
    """
    if m is None and alpha_mul == 1.0:
        return eb
    positions = ([_apply(m, x, y) for (x, y) in eb.positions]
                 if m is not None else list(eb.positions))
    colors = ([(r, g, b, a * alpha_mul) for (r, g, b, a) in eb.colors]
              if alpha_mul != 1.0 else list(eb.colors))
    return EffectBatch(
        cellmap_hash=eb.cellmap_hash, blend=eb.blend, positions=positions,
        uvs=list(eb.uvs), colors=colors, triangles=list(eb.triangles))


def uv_span(batches: list) -> tuple:
    """``(max_u, max_v)`` across all batches — to tell pixel UVs from normalized.

    Effect UVs come straight from the runtime; if the span is well above 1 they
    are texture-pixel coordinates (divide by atlas size like Normal parts),
    otherwise they are already normalized 0..1. Diagnostic helper for the
    renderer / verify tool.
    """
    mu = mv = 0.0
    for b in batches:
        for (u, v) in b.uvs:
            mu = max(mu, u)
            mv = max(mv, v)
    return (mu, mv)
