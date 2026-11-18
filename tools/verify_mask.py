#!/usr/bin/env python3
"""Headless check for the mask / clipping-mask core.

Exercises the engine-independent half of masking without a GUI:

  * **static classification** — that ``SsabMeta`` reads the four mask flags and
    the ``is_pure_mask`` / ``is_mask_writer`` / ``is_clipping`` helpers match the
    spec's three formulas on the ``overall/Mask`` fixture;
  * **per-frame coverage build** — that the player's frame walk finds the
    writers, assigns unique bits (≤ :data:`ss_renpy.mask.MAX_WRITERS`), drops
    writers that write nothing (``mask == 0``, or a hidden ``draw_as_mask``
    part), produces finite geometry + a finite, positive bbox, well-formed
    intervals and parallel ``mask_meta``; that the coverage mesh and replay
    uniform the render layer packs from them hold the same values; and that
    drawing targets are stamped (``MeshPart.mask``) in draw order;
  * **replay reference** — that :func:`ss_renpy.mask.mask_passes` (the CPU twin
    of the GLSL ``ss_mask_passes``) honours the writers' intervals, OP,
    polarity, the no-writer and bbox-outside cases, and that the two OPs replay
    into separate accumulators so coverage never depends on writer order;
  * **instance composition** — that an Instance part hands its sub-animation
    only its own ``mask_influence`` / ``visible_inside_mask`` (one level, never
    what it received), that each part combines them with its own (AND / OR),
    and that a part that draws inside a mask is tested even with no writer.

Actual GL2 coverage rendering / replay still needs a GUI run (Shift+B browser).

Usage:  python tools/verify_mask.py [pack.ssab ...]
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime, mask  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402


def _check(cond, msg, fails):
    if not cond:
        print("    FAIL:", msg)
        fails.append(msg)
    return cond


# --------------------------------------------------------------------------
# 1/2. Static classification + per-frame coverage on a real pack
# --------------------------------------------------------------------------
def check_pack(lib, path: str, anim=None) -> bool:
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    name = os.path.basename(path)
    texmap = meta.texture_hash_map()
    parts = meta.parts()
    names = {p.index: p.name for p in parts}
    fails: list = []

    writers = [p for p in parts if p.is_mask_writer]
    pures = [p for p in parts if p.is_pure_mask]
    clips = [p for p in parts if p.is_clipping]
    targets = [p for p in parts if p.mask_influence]
    print(f"### {name}  parts={len(parts)}  writers={len(writers)} "
          f"(pure={len(pures)} clipping={len(clips)})  targets={len(targets)}")

    # Spec formula invariants must hold for every part.
    for p in parts:
        _check(p.is_pure_mask == (p.is_mask_part or p.draw_as_mask),
               f"pure_mask formula on part {p.index}", fails)
        _check(p.is_mask_writer == (p.is_pure_mask or p.mask_write),
               f"is_writer formula on part {p.index}", fails)
        _check(p.is_clipping == (p.mask_write and not p.is_pure_mask),
               f"is_clipping formula on part {p.index}", fails)
        # A pure mask and a clipping writer are mutually exclusive roles.
        _check(not (p.is_pure_mask and p.is_clipping),
               f"part {p.index} is both pure and clipping", fails)

    anims = meta.animation_names()
    if not anims:
        return _check(False, "no animations", fails)
    a0 = anim or anims[0]

    pl = SSInternalPlayer(data, lib=lib, base_dir="ss_assets/overall")
    try:
        if not pl.set_animation(a0):
            return _check(False, f"set_animation({a0!r})", fails)
        pl.set_loop_count(-1)
        pl.play()
        fps = pl.frame_rate or 30
        dt = 1000.0 / fps
        total = max(1, meta.animations()[0].total_frame)

        frames_with_mask = 0
        max_writers = 0
        last_fm = None
        for fr in range(total + 1):
            plan = pl.update(0.0 if fr == 0 else dt)
            fm = plan.frame_mask
            if fm is None or fm.count == 0:
                continue
            frames_with_mask += 1
            max_writers = max(max_writers, fm.count)
            last_fm = fm

            # bits + part indices unique; cap respected.
            bits = [w.bit for w in fm.writers]
            pidx = [w.part_index for w in fm.writers]
            _check(len(bits) == len(set(bits)), "writer bits not unique", fails)
            _check(len(pidx) == len(set(pidx)), "writer parts not unique", fails)
            _check(fm.count <= mask.MAX_WRITERS, "writer count over cap", fails)
            _check(len(fm.meta) == fm.count, "mask_meta not parallel", fails)
            # The replay uniform: one vec4 per writer, padded to what the
            # shader declares.
            mu = fm.meta_uniform()
            need = (mask.MAX_WRITERS if fm.count > mask.TILE_WRITERS
                    else mask.TILE_WRITERS) * 4
            _check(len(mu) == need and all(
                       mu[4 * i:4 * i + 4] == [float(o), float(c), float(op), 0.0]
                       for i, (o, c, _b, op) in enumerate(fm.meta))
                   and not any(mu[4 * fm.count:]),
                   "meta_uniform layout", fails)
            n_tiles = fm.tiles[0] * fm.tiles[1]
            _check(n_tiles * mask.TILE_WRITERS >= fm.count,
                   "too few coverage tiles for the writers", fails)

            # bbox finite + positive.
            _check(all(math.isfinite(v) for v in (*fm.bmin, *fm.bsize)),
                   "bbox not finite", fails)
            _check(fm.bsize[0] > 0 and fm.bsize[1] > 0, "bbox not positive", fails)

            for i, w in enumerate(fm.writers):
                _check(0.0 < w.mask_value <= 255.0,
                       f"writer {w.part_index} mask out of range", fails)
                _check(w.bit == i and fm.meta[i] == (w.open, w.close, w.bit,
                                                     1 if w.op_invert else 0),
                       f"writer {w.part_index} bit/meta mismatch", fails)
                # A pure mask closes at itself, a clipping writer at the end.
                _check(w.open < w.close and (w.close == fm.end)
                       == w.is_clipping and fm.end < mask.SEQ_END,
                       f"writer {w.part_index} interval {w.open}..{w.close}",
                       fails)
                _check(all(math.isfinite(x) and math.isfinite(y)
                           for (x, y) in w.positions),
                       f"writer {w.part_index} geometry not finite", fails)
                _check(len(w.positions) >= 3 and len(w.triangles) >= 1,
                       f"writer {w.part_index} degenerate geometry", fails)
                # A zero-area writer (e.g. a Shape whose vertices were never
                # built) rasterizes to nothing, so its cut-out silently
                # disappears.
                xs = [x for (x, y) in w.positions]
                ys = [y for (x, y) in w.positions]
                _check((max(xs) - min(xs)) > 1e-3 and (max(ys) - min(ys)) > 1e-3,
                       f"writer {w.part_index} ({names.get(w.part_index,'')}) "
                       "has zero-area geometry (no coverage)", fails)
                for tri in w.triangles:
                    _check(all(0 <= idx < len(w.positions) for idx in tri),
                           f"writer {w.part_index} bad triangle index", fails)
                if w.has_texture:
                    _check(w.texture_hash in texmap,
                           f"writer {w.part_index} texture {w.texture_hash} "
                           "unresolved", fails)
                # The coverage mesh: every vertex moved into its tile, UVs over
                # the atlas size, or zeros for a writer drawn untextured.
                tex_size = (64.0, 32.0) if w.has_texture else None
                g, a, ix = mask.pack_writer_mesh(w, 1.0, 2.0, 0.5, 0.25,
                                                 8.0, 16.0, tex_size)
                want_g = [c for (x, y) in w.positions
                          for c in ((x - 1.0) * 0.5 + 8.0, (y - 2.0) * 0.25 + 16.0)]
                want_a = ([c for (u, v) in w.uvs for c in (u / 64.0, v / 32.0)]
                          if w.has_texture else [0.0] * (2 * len(w.positions)))
                _check(len(g) == len(want_g) and len(a) == len(want_a)
                       and all(abs(p - q) < 1e-6 for p, q in zip(g, want_g))
                       and all(abs(p - q) < 1e-6 for p, q in zip(a, want_a))
                       and ix == [i for tri in w.triangles for i in tri],
                       f"writer {w.part_index} coverage mesh packing", fails)

            # Stamped targets: the tree's coverage, numbered in draw order, and
            # none left that no writer reaches unless it draws inside.
            last_seq = -1.0
            for tag, mp in plan.items:
                if tag != "mesh" or mp.mask is None:
                    continue
                ap = mp.mask
                _check(ap.frame_mask is fm, "target references foreign coverage",
                       fails)
                _check(ap.seq > last_seq, "targets not numbered in draw order",
                       fails)
                last_seq = ap.seq
                _check(ap.visible_inside or fm.covers(ap.seq),
                       f"part {mp.part_index} stamped but no writer reaches it",
                       fails)

        print(f"    frames_with_mask={frames_with_mask}/{total + 1}  "
              f"max_writers={max_writers}")
        _check(frames_with_mask > 0, "no frame produced a coverage", fails)

        # A hidden draw_as_mask part still has its Mask batch in the plan; it
        # must write nothing all the same.
        dam = [w.part_index for w in (last_fm.writers if frames_with_mask else ())
               if parts[w.part_index].draw_as_mask]
        if dam:
            pi = dam[0]
            pl.set_part_visibility_override(names[pi], True)
            plan = pl.update(dt)
            fm = plan.frame_mask
            _check(fm is not None and all(w.part_index != pi for w in fm.writers),
                   f"hidden draw_as_mask part {names[pi]!r} still writes", fails)
            pl.clear_part_visibility_override(names[pi])
    finally:
        pl.close()

    ok = not fails
    print("   ", "PASS" if ok else f"FAIL ({len(fails)} issue(s))")
    return ok


# --------------------------------------------------------------------------
# 3. mask_passes — CPU reference of the replay shader
# --------------------------------------------------------------------------
E = mask.SEQ_END


def _fm(meta):
    """A bare FrameMask carrying just the replay metadata (no geometry):
    ``meta`` is ``(open, close, bit, op_invert)`` per writer."""
    return mask.FrameMask(writers=[None] * len(meta), meta=meta)


def check_replay() -> bool:
    fails: list = []
    inside = (0.5, 0.5)        # within coverage bbox
    outside = (1.5, 0.5)       # beyond coverage bbox

    def covered(*bits):
        s = set(bits)
        return lambda b: b in s

    # No writers: nothing is masked, so the polarity alone decides — a part
    # that draws inside a mask is hidden when there is no mask at all.
    _check(mask.mask_passes(_fm([]), 0, False, inside, covered()),
           "no writer: an outside target should draw", fails)
    _check(mask.mask_passes(_fm([]), 0, True, inside, covered()) is False,
           "no writer: an inside target should discard", fails)

    # bbox-outside: visible_inside discards, outside-target draws.
    one_mask = [(-1, 5, 0, 0)]  # pure mask at 5 in a top-level animation
    _check(mask.mask_passes(_fm(one_mask), 2, True, outside, covered(0)) is False,
           "visible_inside outside-bbox should discard", fails)
    _check(mask.mask_passes(_fm(one_mask), 2, False, outside, covered(0)) is True,
           "outside-polarity outside-bbox should draw", fails)

    # Pure mask (keeps OUTSIDE, visible_inside=0), target 2 in (-1, 5).
    #   inside the hole (bit set)  -> stencil 1 -> masked -> discard
    #   outside the hole (no bit)  -> stencil 0 -> draw
    _check(mask.mask_passes(_fm(one_mask), 2, False, inside, covered(0)) is False,
           "pure mask: inside hole should discard", fails)
    _check(mask.mask_passes(_fm(one_mask), 2, False, inside, covered()) is True,
           "pure mask: outside hole should draw", fails)
    # Past it: target 9 is outside (-1, 5) -> mask does not apply -> draw.
    _check(mask.mask_passes(_fm(one_mask), 9, False, inside, covered(0)) is True,
           "pure mask: a target drawn after it should draw", fails)
    # A sub-animation's pure mask opens at its Instance part (20): it does not
    # reach the caller's parts drawn before the instance.
    sub_mask = [(20, 25, 0, 0)]
    _check(mask.mask_passes(_fm(sub_mask), 22, False, inside, covered(0)) is False,
           "sub-animation pure mask: its own earlier part is masked", fails)
    _check(mask.mask_passes(_fm(sub_mask), 10, False, inside, covered(0)) is True,
           "sub-animation pure mask: the caller's earlier part is not", fails)

    # Clipping (keeps INSIDE, visible_inside=1), writer at 3, target 6 in (3, E).
    one_clip = [(3, E, 0, 0)]
    _check(mask.mask_passes(_fm(one_clip), 6, True, inside, covered(0)) is True,
           "clipping: inside should draw", fails)
    _check(mask.mask_passes(_fm(one_clip), 6, True, inside, covered()) is False,
           "clipping: outside should discard", fails)
    # Clipping scope: target 1 before it -> writer inactive -> discard if inside.
    _check(mask.mask_passes(_fm(one_clip), 1, True, inside, covered(0)) is False,
           "clipping: a target before it is unmasked (discard if vis_inside)",
           fails)
    # The writer itself is not in its own interval: its colour is not clipped
    # by the mask it writes.
    _check(mask.mask_passes(_fm(one_clip), 3, True, inside, covered(0)) is False,
           "clipping: the writer must not clip itself", fails)

    # OP invert: a single invert writer flips 0 -> 0xFF (masked).
    inv = [(-1, 5, 0, 1)]       # invert pure mask
    _check(mask.mask_passes(_fm(inv), 2, False, inside, covered(0)) is False,
           "invert: covered -> masked -> discard (vis_inside=0)", fails)

    # Two increment masks stack but masked stays "nonzero": covered by both -> 2.
    two = [(-1, 5, 0, 0), (-1, 6, 1, 0)]
    _check(mask.mask_passes(_fm(two), 2, False, inside, covered(0, 1)) is False,
           "two masks: covered -> discard", fails)
    _check(mask.mask_passes(_fm(two), 2, False, inside, covered()) is True,
           "two masks: uncovered -> draw", fails)

    # -- OP plane split ---------------------------------------------------
    # Invert writers are PARITY: an odd overlap covers, an even one does not.
    # Two overlapping inverts cancel; three cover. (Two alone cannot tell parity
    # from an "exactly one" reading — three is what distinguishes them, and
    # SpriteStudio 7.6 is parity.)
    inv2 = [(-1, 5, 0, 1), (-1, 6, 1, 1)]
    inv3 = [(-1, 5, 0, 1), (-1, 6, 1, 1), (-1, 7, 2, 1)]
    _check(mask.mask_passes(_fm(inv2), 2, False, inside, covered(0, 1)) is True,
           "invert x2: even overlap cancels -> draw", fails)
    _check(mask.mask_passes(_fm(inv3), 2, False, inside, covered(0, 1, 2)) is False,
           "invert x3: odd overlap covers -> discard", fails)

    # Mixed influence overlapping: the coverage is the UNION of the two planes
    # and must NOT depend on the order the writers were emitted in. With one
    # shared accumulator `incr -> invert` covered while `invert -> incr` did not.
    incr_first = [(-1, 5, 0, 0), (-1, 6, 1, 1)]   # increment at 5, invert at 6
    inv_first = [(-1, 5, 0, 1), (-1, 6, 1, 0)]    # invert at 5, increment at 6
    for label, meta in (("incr->invert", incr_first), ("invert->incr", inv_first)):
        _check(mask.mask_passes(_fm(meta), 2, False, inside,
                                covered(0, 1)) is False,
               f"mixed OP ({label}): overlap is the union -> discard", fails)
        _check(mask.mask_passes(_fm(meta), 2, False, inside, covered(0)) is False,
               f"mixed OP ({label}): first writer alone covers -> discard", fails)
        _check(mask.mask_passes(_fm(meta), 2, False, inside, covered(1)) is False,
               f"mixed OP ({label}): second writer alone covers -> discard", fails)
        _check(mask.mask_passes(_fm(meta), 2, False, inside, covered()) is True,
               f"mixed OP ({label}): uncovered -> draw", fails)

    # An invert writer must not be able to cancel a counter writer's coverage:
    # two inverts (which cancel each other) plus one increment stays covered.
    mixed3 = [(-1, 5, 0, 1), (-1, 6, 1, 0), (-1, 7, 2, 1)]
    _check(mask.mask_passes(_fm(mixed3), 2, False, inside,
                            covered(0, 1, 2)) is False,
           "mixed OP: cancelling inverts must not clear the counter", fails)

    print("### replay (mask_passes)", "PASS" if not fails else
          f"FAIL ({len(fails)})")
    return not fails


# --------------------------------------------------------------------------
# 4. instance composition (child_context / target_mask / settle)
# --------------------------------------------------------------------------
class _FakePart:
    def __init__(self, mask_influence, visible_inside_mask):
        self.mask_influence = mask_influence
        self.visible_inside_mask = visible_inside_mask


class _FakeMesh:
    def __init__(self, part_index=0):
        self.part_index = part_index
        self.mask = None


def _ctx(inherit):
    return (inherit.influence, inherit.visible_inside)


def check_composition() -> bool:
    fails: list = []
    tree = mask.MaskTree(writes=True)

    # -- the Instance part hands down its own flags, one level only --------
    # child_context never sees what the Instance part itself received, so an
    # opted-out caller cannot reach a nested instance's parts, and a caller
    # that masks nothing does not stop the flags reaching down.
    c = mask.child_context(tree, _FakePart(True, False), 7.0)
    _check(_ctx(c) == (True, False) and c.start_seq == 7.0 and c.tree is tree,
           "child_context: the instance part's own flags at its position",
           fails)
    _check(_ctx(mask.child_context(tree, _FakePart(False, True), 7.0))
           == (False, True),
           "child_context: an instance part's own flags reach its child",
           fails)

    # -- each part combines them with its own: MI by AND, VIM by OR --------
    def stamp(ctx, part, t=tree):
        return mask.target_mask(t, part, ctx, 9.0)

    _check(stamp((False, False), _FakePart(True, False)) is None,
           "AND: an opted-out instance part leaves its parts unmasked", fails)
    _check(stamp((True, False), _FakePart(False, False)) is None,
           "AND: a part that opts out is unmasked under a masking caller", fails)
    ma = stamp((True, False), _FakePart(True, False))
    _check(ma is not None and ma.seq == 9.0 and ma.visible_inside is False
           and ma.frame_mask is tree.frame_mask,
           "AND: an opted-in part is stamped at its own position", fails)
    mb = stamp((True, False), _FakePart(True, True))
    _check(mb is not None and mb.visible_inside is True,
           "OR: the part's own visible_inside_mask raises polarity", fails)
    mc = stamp((True, True), _FakePart(True, False))
    _check(mc is not None and mc.visible_inside is True,
           "OR: the instance part's visible_inside_mask reaches the part", fails)

    # -- a tree with no writer at all -------------------------------------
    bare = mask.MaskTree(writes=False)
    _check(stamp((True, False), _FakePart(True, False), bare) is None,
           "no writer: a part that draws outside needs no test", fails)
    md = stamp((True, False), _FakePart(True, True), bare)
    _check(md is not None and md.visible_inside is True,
           "no writer: a part that draws inside is still tested", fails)

    # -- a draw without masks leaves out what shows only inside one --------
    _check(mask.draws_only_inside(_FakePart(True, True), (True, False)),
           "no-mask draw: an inside part is left out", fails)
    _check(mask.draws_only_inside(_FakePart(True, False), (True, True)),
           "no-mask draw: the instance part's inside reaches its part", fails)
    _check(not mask.draws_only_inside(_FakePart(True, True), (False, False)),
           "no-mask draw: an opted-out part is drawn whole", fails)
    _check(not mask.draws_only_inside(_FakePart(True, False), (True, False)),
           "no-mask draw: an outside part is drawn whole", fails)

    # -- settle: stamps no writer reaches are dropped, unless inside -------
    fm = tree.frame_mask
    fm.meta = [(-1.0, 5.0, 0, 0)]              # one pure mask at 5
    fm.writers = [None]
    items = []
    for seq, inside in ((2.0, False), (8.0, False), (8.0, True)):
        mp = _FakeMesh()
        mp.mask = mask.MaskApply(fm, seq, inside)
        items.append(("mesh", mp))
    mask.settle(items, fm)
    _check(items[0][1].mask is not None,
           "settle: a target a writer reaches keeps its stamp", fails)
    _check(items[1][1].mask is None,
           "settle: an outside target no writer reaches draws plainly", fails)
    _check(items[2][1].mask is not None,
           "settle: an inside target keeps its stamp everywhere", fails)

    # -- finalize: bits, tiles and the cap ---------------------------------
    big = mask.FrameMask()
    for i in range(mask.MAX_WRITERS + 3):
        big.writers.append(mask.MaskWriter(
            part_index=i, is_clipping=False, op_invert=False, mask_value=255.0,
            texture_hash=0, has_texture=False,
            positions=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], uvs=[(0, 0)] * 3,
            triangles=[(0, 1, 2)]))
    big.finalize()
    _check(big.count == mask.MAX_WRITERS and big.capped,
           "finalize: writers past the cap are dropped and flagged", fails)
    _check([w.bit for w in big.writers] == list(range(mask.MAX_WRITERS)),
           "finalize: bits number the writers in order", fails)
    _check(big.tiles == (2, 2), "tiles: 96 writers take 2x2 tiles", fails)
    # Over the cap, what goes is what the tree draws last: a sub-animation's
    # writers arrive before their caller's, so list order would drop the
    # top-level animation's own first.
    late = mask.FrameMask()
    for i in range(mask.MAX_WRITERS + 2):
        clip = i % 2 == 0
        pos = float(mask.MAX_WRITERS + 2 - i)          # arrives last-drawn first
        late.writers.append(mask.MaskWriter(
            part_index=i, is_clipping=clip, op_invert=False, mask_value=255.0,
            texture_hash=0, has_texture=False,
            positions=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], uvs=[(0, 0)] * 3,
            triangles=[(0, 1, 2)],
            open=pos if clip else -1.0, close=mask.SEQ_END if clip else pos))
    late.finalize(end=500.0)
    kept = sorted(w.open if w.is_clipping else w.close for w in late.writers)
    _check(kept == [float(k) for k in range(1, mask.MAX_WRITERS + 1)],
           "finalize: over the cap, the writers drawn last are dropped", fails)
    _check(all(w.close == 500.0 for w in late.writers if w.is_clipping)
           and late.end == 500.0,
           "finalize: clipping intervals close at the tree's end", fails)
    del big.writers[mask.TILE_WRITERS + 1:]
    _check(big.tiles == (2, 1), "tiles: 25 writers take 2 tiles", fails)
    del big.writers[mask.TILE_WRITERS:]
    _check(big.tiles == (1, 1), "tiles: 24 writers fit one tile", fails)

    print("### composition (child_context / target_mask / settle)",
          "PASS" if not fails else f"FAIL ({len(fails)})")
    return not fails


def main(argv) -> int:
    if len(argv) > 1:
        targets = [(t, None) for t in argv[1:]]
    else:
        targets = [(os.path.join(_GAME, "ss_assets", "overall", "Mask.ssab"),
                    None)]
    lib = ssruntime.load_library()
    print("== Mask / clipping verification ==\n")
    allok = True
    for path, anim in targets:
        allok &= check_pack(lib, path, anim)
        print()
    allok &= check_replay()
    allok &= check_composition()
    print("\n== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
