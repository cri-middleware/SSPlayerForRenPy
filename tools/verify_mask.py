#!/usr/bin/env python3
"""Headless check for the mask / clipping-mask core.

Exercises the engine-independent half of masking without a GUI:

  * **static classification** — that ``SsabMeta`` reads the four mask flags and
    the ``is_pure_mask`` / ``is_mask_writer`` / ``is_clipping`` helpers match the
    spec's three formulas on the ``overall/Mask`` fixture;
  * **per-frame coverage build** — that :func:`ss_renpy.mask.build_frame_mask`
    finds the writers, assigns unique bits (≤ 24), drops ``mask == 0`` writers,
    produces finite geometry + a finite, positive bbox, and parallel
    ``mask_meta``; and that drawing targets are stamped (``MeshPart.mask``) with
    the right rank / polarity;
  * **replay reference** — that :func:`ss_renpy.mask.mask_passes` (the CPU twin
    of the GLSL ``ss_mask_passes``) honours scope, OP, polarity and
    bbox-outside handling, and that the two OPs replay into separate
    accumulators so coverage never depends on writer order;
  * **instance composition** — that :func:`ss_renpy.mask.inherit_for` /
    :func:`ss_renpy.mask.attach_target` compose a caller's context with each
    sub-animation part's own settings (``mask_influence`` by AND,
    ``visible_inside_mask`` by OR), chaining through nesting.

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
        for fr in range(total + 1):
            plan = pl.update(0.0 if fr == 0 else dt)
            fm = plan.frame_mask
            if fm is None:
                continue
            frames_with_mask += 1
            max_writers = max(max_writers, fm.count)

            # bits + part indices unique; cap respected.
            bits = [w.bit for w in fm.writers]
            pidx = [w.part_index for w in fm.writers]
            _check(len(bits) == len(set(bits)), "writer bits not unique", fails)
            _check(len(pidx) == len(set(pidx)), "writer parts not unique", fails)
            _check(fm.count <= mask.MAX_WRITERS, "writer count over cap", fails)
            _check(len(fm.meta) == fm.count, "mask_meta not parallel", fails)

            # bbox finite + positive.
            _check(all(math.isfinite(v) for v in (*fm.bmin, *fm.bsize)),
                   "bbox not finite", fails)
            _check(fm.bsize[0] > 0 and fm.bsize[1] > 0, "bbox not positive", fails)

            for i, w in enumerate(fm.writers):
                _check(0.0 < w.mask_value <= 255.0,
                       f"writer {w.part_index} mask out of range", fails)
                _check(w.bit == i and fm.meta[i][1] == w.bit,
                       f"writer {w.part_index} bit/meta mismatch", fails)
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

            # Drawing targets that were stamped: rank present, polarity matches
            # the static flag, and the rank is a real draw-order slot.
            for tag, mp in plan.items:
                if tag != "mesh" or mp.mask is None:
                    continue
                ap = mp.mask
                _check(ap.frame_mask is fm, "target references foreign coverage",
                       fails)
                _check(ap.rank in fm.rank_of.values(), "target rank not a slot",
                       fails)

        print(f"    frames_with_mask={frames_with_mask}/{total + 1}  "
              f"max_writers={max_writers}")
        _check(frames_with_mask > 0, "no frame produced a coverage", fails)
    finally:
        pl.close()

    ok = not fails
    print("   ", "PASS" if ok else f"FAIL ({len(fails)} issue(s))")
    return ok


# --------------------------------------------------------------------------
# 3. mask_passes — CPU reference of the replay shader
# --------------------------------------------------------------------------
def _fm(meta, max_mask_rank=-1, min_clip_rank=None):
    """A bare FrameMask carrying just the replay metadata (no geometry)."""
    fm = mask.FrameMask(writers=[None] * len(meta), meta=meta,
                        max_mask_rank=max_mask_rank, min_clip_rank=min_clip_rank)
    return fm


def check_replay() -> bool:
    fails: list = []
    inside = (0.5, 0.5)        # within coverage bbox
    outside = (1.5, 0.5)       # beyond coverage bbox

    def covered(*bits):
        s = set(bits)
        return lambda b: b in s

    # No writers -> always draws.
    _check(mask.mask_passes(_fm([]), 0, False, inside, covered()),
           "empty coverage should draw", fails)

    # bbox-outside: visible_inside discards, outside-target draws.
    one_mask = [(5, 0, 0, 0)]   # rank 5, bit 0, increment, pure mask
    _check(mask.mask_passes(_fm(one_mask), 2, True, outside, covered(0)) is False,
           "visible_inside outside-bbox should discard", fails)
    _check(mask.mask_passes(_fm(one_mask), 2, False, outside, covered(0)) is True,
           "outside-polarity outside-bbox should draw", fails)

    # Pure mask (keeps OUTSIDE, visible_inside=0), target rank 2 < slot 5 (scope).
    #   inside the hole (bit set)  -> stencil 1 -> masked -> discard
    #   outside the hole (no bit)  -> stencil 0 -> draw
    _check(mask.mask_passes(_fm(one_mask), 2, False, inside, covered(0)) is False,
           "pure mask: inside hole should discard", fails)
    _check(mask.mask_passes(_fm(one_mask), 2, False, inside, covered()) is True,
           "pure mask: outside hole should draw", fails)
    # Out of scope: target rank 9 > slot 5 -> mask does not apply -> draw.
    _check(mask.mask_passes(_fm(one_mask), 9, False, inside, covered(0)) is True,
           "pure mask: out-of-scope target should draw", fails)

    # Clipping (keeps INSIDE, visible_inside=1), writer rank 3, target rank 6>3.
    one_clip = [(3, 0, 0, 1)]
    _check(mask.mask_passes(_fm(one_clip), 6, True, inside, covered(0)) is True,
           "clipping: inside should draw", fails)
    _check(mask.mask_passes(_fm(one_clip), 6, True, inside, covered()) is False,
           "clipping: outside should discard", fails)
    # Clipping scope: target rank 1 < slot 3 -> writer inactive -> outside -> discard.
    _check(mask.mask_passes(_fm(one_clip), 1, True, inside, covered(0)) is False,
           "clipping: out-of-scope target is unmasked (discard if vis_inside)",
           fails)

    # OP invert: a single invert writer flips 0 -> 0xFF (masked).
    inv = [(5, 0, 1, 0)]        # invert pure mask
    _check(mask.mask_passes(_fm(inv), 2, False, inside, covered(0)) is False,
           "invert: covered -> masked -> discard (vis_inside=0)", fails)

    # Two increment masks stack but masked stays "nonzero": covered by both -> 2.
    two = [(5, 0, 0, 0), (6, 1, 0, 0)]
    _check(mask.mask_passes(_fm(two), 2, False, inside, covered(0, 1)) is False,
           "two masks: covered -> discard", fails)
    _check(mask.mask_passes(_fm(two), 2, False, inside, covered()) is True,
           "two masks: uncovered -> draw", fails)

    # -- OP plane split ---------------------------------------------------
    # Invert writers are PARITY: an odd overlap covers, an even one does not.
    # Two overlapping inverts cancel; three cover. (Two alone cannot tell parity
    # from an "exactly one" reading — three is what distinguishes them, and
    # SS7.5 is parity.)
    inv2 = [(5, 0, 1, 0), (6, 1, 1, 0)]
    inv3 = [(5, 0, 1, 0), (6, 1, 1, 0), (7, 2, 1, 0)]
    _check(mask.mask_passes(_fm(inv2), 2, False, inside, covered(0, 1)) is True,
           "invert x2: even overlap cancels -> draw", fails)
    _check(mask.mask_passes(_fm(inv3), 2, False, inside, covered(0, 1, 2)) is False,
           "invert x3: odd overlap covers -> discard", fails)

    # Mixed influence overlapping: the coverage is the UNION of the two planes
    # and must NOT depend on the order the writers were emitted in. With one
    # shared accumulator `incr -> invert` covered while `invert -> incr` did not.
    incr_first = [(5, 0, 0, 0), (6, 1, 1, 0)]     # increment at 5, invert at 6
    inv_first = [(5, 0, 1, 0), (6, 1, 0, 0)]      # invert at 5, increment at 6
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
    mixed3 = [(5, 0, 1, 0), (6, 1, 0, 0), (7, 2, 1, 0)]
    _check(mask.mask_passes(_fm(mixed3), 2, False, inside,
                            covered(0, 1, 2)) is False,
           "mixed OP: cancelling inverts must not clear the counter", fails)

    print("### replay (mask_passes)", "PASS" if not fails else
          f"FAIL ({len(fails)})")
    return not fails


# --------------------------------------------------------------------------
# 4. instance-hierarchy composition (inherit_for / attach_target)
# --------------------------------------------------------------------------
class _FakePart:
    def __init__(self, mask_influence, visible_inside_mask):
        self.mask_influence = mask_influence
        self.visible_inside_mask = visible_inside_mask


class _FakeMesh:
    def __init__(self, part_index=0):
        self.part_index = part_index
        self.mask = None


def _child_mask(caller_ctx, child_part):
    """``attach_target`` on a one-part sub-animation under ``caller_ctx``."""
    mp = _FakeMesh(0)
    mask.attach_target(mp, None, [child_part], caller_ctx)
    return mp.mask


def check_composition() -> bool:
    fails: list = []
    # One pure-mask writer at rank 5: ranks below it are in scope.
    fm = mask.FrameMask(writers=[None], meta=[(5, 0, 0, 0)], max_mask_rank=5,
                        rank_of={0: 2, 1: 7})

    # -- inherit_for: the Instance part composes onto ROOT_CONTEXT ---------
    ctx = mask.inherit_for(0, [_FakePart(True, False)], fm)
    _check(ctx is not None and ctx.rank == 2 and ctx.influence is True and
           ctx.visible_inside is False and ctx.frame_mask is fm,
           "instance target should yield a context at its own rank", fails)

    # mask_influence == 0 latches the AND off: nothing below can be masked.
    _check(mask.inherit_for(0, [_FakePart(False, True)], fm) is None,
           "opted-out instance must yield no context", fails)

    # -- composition rules on the sub-animation's own parts ----------------
    # AND: a child that opts out is not masked even under a masked caller.
    _check(_child_mask(ctx, _FakePart(False, False)) is None,
           "AND: opted-out child under a masked caller is not masked", fails)

    # AND: a child that opts in under a masked caller IS masked, at the
    # instance part's rank (not the child's own part index / rank).
    ma = _child_mask(ctx, _FakePart(True, False))
    _check(ma is not None and ma.rank == 2 and ma.frame_mask is fm,
           "AND: opted-in child under a masked caller is masked at inst rank",
           fails)

    # OR: the child's own visible_inside_mask raises polarity even when the
    # caller draws outside. (The pre-fix code judged the whole sub-animation by
    # the instance part alone, so this came out False.)
    mb = _child_mask(ctx, _FakePart(True, True))
    _check(mb is not None and mb.visible_inside is True,
           "OR: child's visible_inside_mask must raise polarity", fails)

    # OR: and the caller's raises it for a child that does not set it.
    ctx_in = mask.inherit_for(0, [_FakePart(True, True)], fm)
    mc = _child_mask(ctx_in, _FakePart(True, False))
    _check(mc is not None and mc.visible_inside is True,
           "OR: caller's visible_inside_mask must reach a child without it",
           fails)

    # -- nesting: both rules chain, and the rank stays the outermost one ---
    nested = mask.inherit_for(0, [_FakePart(True, False)], None, ctx_in)
    _check(nested is not None and nested.rank == 2 and
           nested.visible_inside is True,
           "nesting: OR stays latched on and rank stays the outermost", fails)
    _check(mask.inherit_for(0, [_FakePart(False, False)], None, ctx_in) is None,
           "nesting: an inner opt-out latches the AND off", fails)

    # -- scope: an out-of-scope caller masks nothing, but an inside-target
    # still discards (it is only visible where a mask covers it).
    ctx_out = mask.inherit_for(1, [_FakePart(True, False),
                                   _FakePart(True, False)], fm)   # rank 7 > 5
    _check(_child_mask(ctx_out, _FakePart(True, False)) is None,
           "scope: out-of-scope outside-target child is not masked", fails)
    md = _child_mask(ctx_out, _FakePart(True, True))
    _check(md is not None and md.visible_inside is True,
           "scope: out-of-scope inside-target child is still evaluated", fails)

    print("### composition (inherit_for / attach_target)",
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
