"""Decode an ``EffectDrawPlan`` (from ``ss_effect_slot_step``) into batches.

This is the engine-independent render-data core for **Effect parts**
(particles), the analogue of :mod:`ss_renpy.framedata` for Normal parts. The
Brain simulates the particle system and hands back a FlatBuffers
``EffectDrawPlan``: a set of per-emitter draw *commands* pointing into four flat
arrays (verts / uvs / colors / indices). We slice those per command, apply the
parent Effect-part's world matrix, and emit triangulated, coloured world-space
:class:`EffectBatch` quads the Ren'Py layer can mesh.

Buffer layout (``runtime/effect_draw_plan.fbs``):

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

from ss.runtime.EffectDrawCommand import EffectDrawCommand
from ss.runtime.EffectDrawPlan import EffectDrawPlan
from ss_renpy.framedata import _I32, _U8, _U16, _vector

# EmitterState.blend_type values carried on EffectDrawCommand.blend.
FX_BLEND_MIX, FX_BLEND_ADD = 0, 1
FX_BLEND_NAMES = {0: "Mix", 1: "Add"}

# EffectDrawPlan's vtable slots, from the generated EffectDrawPlan.py. _decode
# checks them against the generated accessors before trusting them.
_EP_COMMANDS, _EP_VERT_STRIDE = 4, 6
_EP_VERTS, _EP_UVS, _EP_COLORS, _EP_INDICES = 8, 10, 12, 14


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


# EffectDrawCommand is a 16-byte fixed-layout FlatBuffers *struct* (CellmapHash
# u32@0, QuadCount u32@4, ParticleOffset u32@8, Blend u8@12) in a contiguous
# vector — decode them all in one struct call rather than per-command accessors
# (mirrors framedata.bulk_part_states / SSPlayerForUnity's command-pointer read).
_FX_CMD_SIZE = 16
_FX_CMD = struct.Struct('<IIIB3x')
_fx_fastpath = None   # None = unvalidated, True = OK, False = disabled


def _decode(plan: EffectDrawPlan) -> tuple:
    """``(commands, vert_stride, verts, uvs, colors, indices)`` of ``plan``:
    the commands as ``(cellmap_hash, quad_count, particle_offset, blend)``
    tuples, the four vectors as flat lists.

    Read with one struct call per vector, from where the vtable says each
    starts. Until a plan holding all of them has read the same through the
    generated accessors, each plan is checked against them; one that differs
    turns the generated accessors on for good.
    """
    global _fx_fastpath
    if _fx_fastpath is False:
        return _decode_accessors(plan)
    tab = plan._tab
    buf, pos = tab.Bytes, tab.Pos
    vt = pos - _I32(buf, pos)[0]
    o = (_U16(buf, vt + _EP_VERT_STRIDE)[0]
         if _EP_VERT_STRIDE < _U16(buf, vt)[0] else 0)
    stride = _U8(buf, pos + o)[0] if o else 0
    cs, cn = _vector(tab, _EP_COMMANDS)
    vs, vn = _vector(tab, _EP_VERTS)
    us, un = _vector(tab, _EP_UVS)
    ks, kn = _vector(tab, _EP_COLORS)
    js, jn = _vector(tab, _EP_INDICES)
    if _fx_fastpath is None and (
            EffectDrawCommand.SizeOf() != _FX_CMD_SIZE
            or (cn, stride, vn, un, kn, jn) != (
                plan.CommandsLength(), plan.VertStride(), plan.VertsLength(),
                plan.UvsLength(), plan.ColorsLength(), plan.IndicesLength())):
        _fx_fastpath = False
        return _decode_accessors(plan)
    cmds = list(_FX_CMD.iter_unpack(buf[cs:cs + cn * _FX_CMD_SIZE]))
    verts = list(struct.unpack_from("<%df" % vn, buf, vs)) if vn else []
    uvs = list(struct.unpack_from("<%df" % un, buf, us)) if un else []
    colors = list(struct.unpack_from("<%df" % kn, buf, ks)) if kn else []
    indices = list(struct.unpack_from("<%di" % jn, buf, js)) if jn else []
    if _fx_fastpath is None and cn and vn and un and kn and jn:
        c0 = plan.Commands(0)
        _fx_fastpath = (
            cs == c0._tab.Pos
            and cmds[0] == (c0.CellmapHash(), c0.QuadCount(),
                            c0.ParticleOffset(), c0.Blend())
            and verts[0] == plan.Verts(0) and uvs[0] == plan.Uvs(0)
            and colors[0] == plan.Colors(0) and indices[0] == plan.Indices(0))
        if not _fx_fastpath:
            return _decode_accessors(plan)
    return cmds, stride, verts, uvs, colors, indices


def _decode_accessors(plan: EffectDrawPlan) -> tuple:
    """:func:`_decode` through the generated accessors, element by element."""
    cmds = []
    for c in range(plan.CommandsLength()):
        cmd = plan.Commands(c)
        if cmd is not None:
            cmds.append((cmd.CellmapHash(), cmd.QuadCount(),
                         cmd.ParticleOffset(), cmd.Blend()))
    return (cmds, plan.VertStride(),
            [plan.Verts(j) for j in range(plan.VertsLength())],
            [plan.Uvs(j) for j in range(plan.UvsLength())],
            [plan.Colors(j) for j in range(plan.ColorsLength())],
            [plan.Indices(j) for j in range(plan.IndicesLength())])


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
    transformed by it. ``alpha`` (0..1) is the parent part's
    hierarchical alpha, multiplied into every vertex colour's alpha — the flat
    renderer's stand-in for hierarchical modulate inheritance. When ``merge``
    is set, consecutive commands sharing ``(cellmap_hash, blend)`` are merged
    into one batch (dynamic batching), rebasing indices by the
    running vertex count.
    """
    if not buf:
        return []
    cmds, stride, verts, uvs, colors, indices = _decode(parse(buf))
    if not cmds:
        return []
    stride = stride or 2
    a_mul = max(0.0, min(1.0, alpha))

    batches: list[EffectBatch] = []
    for cellmap_hash, quad_count, poff, blend in cmds:
        if quad_count == 0:
            continue
        nverts = quad_count * 4
        v_off = poff * 4 * stride
        u_off = poff * 4 * 2
        c_off = poff * 4 * 4
        i_off = poff * 6

        # One pass per vertex, matrix inlined and invariants hoisted — this is
        # the effect hot loop (hundreds of verts × every slot × every frame),
        # so avoid per-vertex function calls.
        if matrix is None:
            positions = [(verts[v_off + i * stride], verts[v_off + i * stride + 1])
                         for i in range(nverts)]
        else:
            m0, m1, m4, m5, m12, m13 = (matrix[0], matrix[1], matrix[4],
                                        matrix[5], matrix[12], matrix[13])
            positions = []
            ap = positions.append
            b = v_off
            for _ in range(nverts):
                x = verts[b]; y = verts[b + 1]; b += stride
                ap((m0 * x + m4 * y + m12, m1 * x + m5 * y + m13))
        uv = [(uvs[u_off + i * 2], uvs[u_off + i * 2 + 1]) for i in range(nverts)]
        col = [(colors[c_off + i * 4], colors[c_off + i * 4 + 1],
                colors[c_off + i * 4 + 2], colors[c_off + i * 4 + 3] * a_mul)
               for i in range(nverts)]
        flat_idx = indices[i_off:i_off + quad_count * 6]
        tris = [(flat_idx[t], flat_idx[t + 1], flat_idx[t + 2])
                for t in range(0, len(flat_idx) - 2, 3)]

        batch = EffectBatch(
            cellmap_hash=cellmap_hash, blend=blend,
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


def pack_fx_mesh(eb: EffectBatch, ox, oy) -> tuple:
    """Pack ``eb`` into flat (geometry, attributes, indices) arrays for the
    render layer's batched effect mesh (a_tex_coord + a_ss_color).

    Per vertex: position offset to screen px by (ox, oy), the UV as given
    (effect UVs are already normalized), then the RGBA colour. Kept out of
    ``spritestudio.rpy`` for the reason :func:`ss_renpy.framedata.pack_pc_mesh`
    gives: a list built there is a ``RevertableList``.
    """
    geometry = []
    attributes = []
    indices = []
    g_ext = geometry.extend
    a_ext = attributes.extend
    i_ext = indices.extend
    for (x, y), (u, v), c in zip(eb.positions, eb.uvs, eb.colors):
        g_ext((ox + x, oy + y))
        a_ext((u, v, c[0], c[1], c[2], c[3]))
    for tri in eb.triangles:
        i_ext(tri)
    return geometry, attributes, indices


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
