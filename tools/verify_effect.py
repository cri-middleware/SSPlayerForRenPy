#!/usr/bin/env python3
"""Headless check for Effect-part playback.

Drives ``Effect.ssab`` through every frame: creates one Effect slot per effect
part, steps it via the C-API each frame, decodes the returned ``EffectDrawPlan``
with :mod:`ss_renpy.effectplan`, and validates the geometry. Prints how many
effects produced visible particles, the UV span (pixel vs normalized), the
blend modes and cellmap hashes seen, and whether all positions/colours are
finite. Plain CPython — no Ren'Py.

Usage:  python tools/verify_effect.py [pack.ssab ...]   (default: Effect.ssab)
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

from ss_renpy import ssruntime, effectplan  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402


def _matrix_for(wm, n, p):
    base = p * 16
    if base + 16 > n:
        return None
    return list(wm[base:base + 16])


def check_pack(lib, path: str) -> bool:
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    eff_parts = meta.effect_parts()
    texmap = meta.texture_hash_map()
    name = os.path.basename(path)
    print(f"### {name}  effect_parts={len(eff_parts)}  "
          f"embedded_effects={[e.name for e in meta.effects()]}")
    if not eff_parts:
        print("    (no effect parts — nothing to verify)")
        return True
    anims = meta.animations()
    if not anims:
        print("    FAIL: no animations")
        return False

    rt = ssruntime.SSRuntime(lib)
    slots = {}
    ok = True
    try:
        rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                     origin=ssruntime.ORIGIN_CENTER)
        rt.load_ssab_bytes(data)
        a0 = anims[0]
        if not rt.setup_animation(a0.name):
            print(f"    FAIL: setup_animation({a0.name!r})")
            return False
        rt.set_loop(-1)
        rt.play()

        for p in eff_parts:
            slot = rt.effect_slot_create(p.ref_effect_name_hash, seed=0)
            if slot is None:
                print(f"    FAIL: effect_slot_create for part {p.index} "
                      f"{p.name!r} (hash={p.ref_effect_name_hash})")
                ok = False
            else:
                slots[p.index] = slot

        fps = rt.fps or a0.fps or 30
        dt = 1.0 / fps
        total = max(1, a0.total_frame)
        visible_parts = set()
        bad = 0
        total_quads = 0
        blends = set()
        chashes = set()
        max_u = max_v = 0.0
        for fr in range(total + 2):
            frame_no = rt.update(dt)
            rt.get_frame_data(frame_no)               # evaluate world matrices
            wm, wn = rt.world_matrices()
            looped = rt.is_looped
            for p in eff_parts:
                slot = slots.get(p.index)
                if slot is None:
                    continue
                ev = rt.active_effect_event(p.index)
                vis, buf = rt.effect_slot_step(
                    slot, ev, frame_no, dt, float(fps), looped,
                    y_flip=True, vert_stride=2)
                if not vis or not buf:
                    continue
                m = _matrix_for(wm, wn, p.index)
                batches = effectplan.build_effect_batches(buf, matrix=m,
                                                          alpha=1.0, merge=True)
                if batches:
                    visible_parts.add(p.index)
                for b in batches:
                    blends.add(b.blend)
                    chashes.add(b.cellmap_hash)
                    total_quads += len(b.positions) // 4
                    for (x, y) in b.positions:
                        if not (math.isfinite(x) and math.isfinite(y)):
                            bad += 1
                    for (r, g, bb, a) in b.colors:
                        if not all(math.isfinite(v) for v in (r, g, bb, a)):
                            bad += 1
                mu, mv = effectplan.uv_span(batches)
                max_u = max(max_u, mu)
                max_v = max(max_v, mv)

        unresolved = sorted(h for h in chashes if h not in texmap)
        uv_kind = ("normalized 0..1" if max_u <= 1.5 and max_v <= 1.5
                   else "texture-pixel (divide by atlas size)")
        print(f"    visible effect parts: {len(visible_parts)}/{len(eff_parts)}"
              f"   total quads (all frames) = {total_quads}")
        print(f"    blends={sorted(effectplan.FX_BLEND_NAMES.get(b, b) for b in blends)}"
              f"   cellmap_hashes={sorted(chashes)}")
        print(f"    UV span max=({max_u:.3f},{max_v:.3f}) -> {uv_kind}")
        print(f"    non-finite values: {bad}"
              + (f"   UNRESOLVED cellmap_hashes={unresolved}" if unresolved else ""))
        if bad:
            print("    FAIL: non-finite geometry/colour")
            ok = False
        if not visible_parts:
            print("    FAIL: no effect produced visible particles")
            ok = False
        return ok
    finally:
        for slot in slots.values():
            rt.effect_slot_destroy(slot)
        rt.close()


def main(argv) -> int:
    targets = argv[1:] or [os.path.join(_GAME, "ss_assets", "overall", "Effect.ssab")]
    lib = ssruntime.load_library()
    print("== Effect playback verification ==\n")
    allok = True
    for t in targets:
        allok &= check_pack(lib, t)
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
