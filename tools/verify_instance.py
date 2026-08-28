#!/usr/bin/env python3
"""Headless check for Instance-part playback via the unified SSInternalPlayer.

Instance children are parent-driven ``SSInternalPlayer`` instances.
Drives ``Instance.ssab`` (whose parts embed the external
pack ``Instance_SourceAnime``) through every frame and validates that:
  * instance children actually render (mesh geometry appears),
  * every child texture hash resolves against the shared (root + external)
    texture map (proving external-pack textures merged), and
  * all positions are finite.
Plain CPython — no Ren'Py.

Usage:  python tools/verify_instance.py [pack.ssab ...]
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

from ss_renpy import ssruntime  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402


def check_pack(lib, path: str) -> bool:
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    base = os.path.dirname(path)
    name = os.path.basename(path)
    inst_parts = meta.instance_parts()
    print(f"### {name}  instance_parts={len(inst_parts)}  "
          f"external={[e.anime_pack_name for e in meta.external_instances()]}")
    if not inst_parts:
        print("    (no instance parts — nothing to verify)")
        return True
    anims = meta.animation_names()
    if not anims:
        print("    FAIL: no animations"); return False

    base_dir = os.path.relpath(base, _GAME).replace("\\", "/")
    p = SSInternalPlayer(data, lib=lib, base_dir=base_dir,
                         resource_manager=RecordingResourceManager(),
                         pack_reader=filesystem_pack_reader(base))
    a0 = anims[0]
    if not p.set_animation(a0):
        print(f"    FAIL: set_animation({a0!r})"); p.close(); return False
    # Children are built during set_animation (recursively, as SSInternalPlayer).
    if not (p._instances and p._instances.has()):
        print("    FAIL: no instance children built (loader/refs?)")
        p.close(); return False
    p.play()

    fps = p.frame_rate or 30
    dt_ms = 1000.0 / fps
    total = max(1, p.total_frames)
    frames_with_geom = max_mesh = total_fx = bad = 0
    unresolved = set()
    try:
        for _ in range(total + 2):
            plan = p.update(dt_ms)
            meshes = [pl for (t, pl) in plan.items if t == "mesh"]
            fx = [pl for (t, pl) in plan.items if t == "fx"]
            if meshes or fx:
                frames_with_geom += 1
            max_mesh = max(max_mesh, len(meshes))
            total_fx += len(fx)
            for mp in meshes:
                if not p.texture_path(mp.texture_hash):   # resolves via shared texmap
                    unresolved.add(mp.texture_hash)
                for (x, y) in mp.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        bad += 1
    finally:
        p.close()

    print(f"    frames with geometry: {frames_with_geom}/{total + 2}   "
          f"max child meshes/frame = {max_mesh}   fx renderables = {total_fx}")
    ok = True
    if bad:
        print(f"    FAIL: {bad} non-finite positions"); ok = False
    if unresolved:
        print(f"    FAIL: unresolved child textures {sorted(unresolved)} "
              "(external cellmaps not merged into the shared texmap)"); ok = False
    if frames_with_geom == 0 or max_mesh == 0:
        print("    FAIL: instance children produced no geometry"); ok = False
    if ok:
        print("    -> PASS (child geometry finite; all child textures resolved)")
    return ok


def main(argv) -> int:
    targets = argv[1:] or [os.path.join(_GAME, "ss_assets", "overall", "Instance.ssab")]
    lib = ssruntime.load_library()
    print("== Instance playback verification (unified SSInternalPlayer) ==\n")
    allok = True
    for t in targets:
        allok &= check_pack(lib, t)
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
