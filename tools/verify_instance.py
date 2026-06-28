#!/usr/bin/env python3
"""Headless check for Instance-part playback (roadmap "Instance/Effect").

Drives ``Instance.ssab`` (whose parts each embed the external pack
``Instance_SourceAnime``) through every frame via :func:`ss_renpy.instance.
collect_ordered`, and validates the recursively-composed child geometry: that
instance children actually render, that every child texture hash resolves
against the merged (root + external) cellmap map, and that positions are finite.
Plain CPython — no Ren'Py.

Usage:  python tools/verify_instance.py [pack.ssab ...]   (default: Instance.ssab)
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

from ss_renpy import ssruntime, instance  # noqa: E402
from ss_renpy.effect import EffectRig  # noqa: E402
from ss_renpy.instance import InstanceRig, collect_ordered, display_frame  # noqa: E402
from ss_renpy import framedata  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402


def make_loader(base_dir, texmap):
    """Loader(pack_name)->bytes that caches, and merges the pack's texture map.

    Mirrors what the Ren'Py player must do: external instance packs contribute
    their cellmap → image-path entries to a single lookup so child parts resolve.
    """
    cache = {}

    def load(pack_name):
        if pack_name in cache:
            return cache[pack_name]
        path = os.path.join(base_dir, pack_name + ".ssab")
        data = open(path, "rb").read() if os.path.exists(path) else b""
        cache[pack_name] = data
        if data:
            texmap.update(SsabMeta(data).texture_hash_map())
        return data

    return load


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
    anims = meta.animations()
    if not anims:
        print("    FAIL: no animations")
        return False

    texmap = dict(meta.texture_hash_map())
    loader = make_loader(base, texmap)
    rt = ssruntime.SSRuntime(lib)
    instances = effects = None
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

        instances = InstanceRig(rt, meta, loader, lib)
        effects = EffectRig(rt, meta)
        print(f"    instance children built: {len(instances._children)}"
              f"/{len(inst_parts)}")
        if not instances.has():
            print("    FAIL: no instance children could be built (loader/refs?)")
            return False

        fps = rt.fps or a0.fps or 30
        dt = 1.0 / fps
        total = max(1, a0.total_frame)
        frames_with_geom = 0
        max_mesh = 0
        total_fx = 0
        bad = 0
        unresolved = set()
        for fr in range(total + 2):
            frame_no = rt.update(dt)
            looped = rt.is_looped
            fb = rt.get_frame_data(display_frame(frame_no, False))
            if not fb:
                continue
            fd = framedata.parse(fb)
            items = collect_ordered(rt, fd, instances, effects, frame_no, dt,
                                    looped, sub_frame=False)
            meshes = [p for (t, p) in items if t == "mesh"]
            fx = [p for (t, p) in items if t == "fx"]
            if meshes or fx:
                frames_with_geom += 1
            max_mesh = max(max_mesh, len(meshes))
            total_fx += len(fx)
            for mp in meshes:
                if mp.texture_hash not in texmap:
                    unresolved.add(mp.texture_hash)
                for (x, y) in mp.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        bad += 1

        print(f"    frames with geometry: {frames_with_geom}/{total + 2}"
              f"   max child meshes/frame = {max_mesh}   fx renderables = {total_fx}")
        print(f"    non-finite positions: {bad}"
              + (f"   UNRESOLVED child textures={sorted(unresolved)}"
                 if unresolved else "   all child textures resolved"))
        if bad:
            print("    FAIL: non-finite child geometry")
            ok = False
        if frames_with_geom == 0 or max_mesh == 0:
            print("    FAIL: instance children produced no geometry")
            ok = False
        if unresolved:
            print("    FAIL: unresolved child textures (merge external cellmaps)")
            ok = False
        return ok
    finally:
        if instances:
            instances.close()
        if effects:
            effects.close()
        rt.close()


def main(argv) -> int:
    targets = argv[1:] or [os.path.join(_GAME, "ss_assets", "overall", "Instance.ssab")]
    lib = ssruntime.load_library()
    print("== Instance playback verification ==\n")
    allok = True
    for t in targets:
        allok &= check_pack(lib, t)
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
