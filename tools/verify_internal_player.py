#!/usr/bin/env python3
"""Headless check for the engine-independent playback core (``SSInternalPlayer``).

Exercises the canonical imperative flow with NO Ren'Py:

    p = SSInternalPlayer(bytes, lib=..., base_dir=..., resource_manager=rm,
                         pack_reader=...)
    p.set_animation(name)   # -> Brain setup + rm.acquire(textures)
    p.play()
    plan = p.update(dt_ms)  # -> FramePlan (z-ordered world-space items)

and validates, per pack kind:
  * animation names enumerate;
  * ``set_animation`` asks the ResourceManager for this pack's textures;
  * ``update`` yields finite, texture-resolved geometry (and effect batches /
    instance children where expected);
  * timeline events drain via ``poll_events``.

Usage:  python tools/verify_internal_player.py
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


def check(lib, rel_ssab: str, base_dir: str, anim, kind: str) -> bool:
    abs_ssab = os.path.join(_GAME, rel_ssab)
    if not os.path.exists(abs_ssab):
        print(f"### {rel_ssab}  SKIP (not found)")
        return True
    data = open(abs_ssab, "rb").read()
    meta = SsabMeta(data)
    rm = RecordingResourceManager()
    reader = filesystem_pack_reader(os.path.dirname(abs_ssab))

    p = SSInternalPlayer(data, lib=lib, base_dir=base_dir,
                         resource_manager=rm, pack_reader=reader)
    name = anim or (p.animation_names()[0] if p.animation_names() else None)
    print(f"### {rel_ssab}  [{kind}]  anims={len(p.animation_names())}  "
          f"play={name!r}")
    ok = True

    if not p.animation_names():
        print("    FAIL: no animations"); return False
    if name not in p.animation_names():
        print(f"    FAIL: {name!r} not in animation_names()"); return False

    # set_animation must request this pack's (root) textures.
    expect_tex = {(base_dir + "/" + c.image_path) for c in meta.cellmaps()
                  if c.image_path}
    if not p.set_animation(name):
        print(f"    FAIL: set_animation({name!r})"); return False
    if p.animation != name:
        print(f"    FAIL: animation is {p.animation!r}, expected {name!r}")
        ok = False
    missing_tex = expect_tex - rm.acquired_set
    if missing_tex:
        print(f"    FAIL: set_animation did not acquire {sorted(missing_tex)}")
        ok = False

    p.play()
    if not p.is_playing():
        print("    FAIL: not playing after play()"); ok = False

    fps = p.fps or 30
    dt_ms = 1000.0 / fps
    total = max(1, p.total_frames)
    frames_with_items = max_mesh = total_fx = bad = 0
    advanced = False
    unresolved = set()
    events_seen = 0
    f0 = p.frame_no
    try:
        for _ in range(total + 4):
            plan = p.update(dt_ms)
            if plan.frame_no != f0:
                advanced = True
            meshes = [pl for (t, pl) in plan.items if t == "mesh"]
            fx = [pl for (t, pl) in plan.items if t == "fx"]
            if meshes or fx:
                frames_with_items += 1
            max_mesh = max(max_mesh, len(meshes))
            total_fx += len(fx)
            for mp in meshes:
                if mp.texture_hash not in p._texmap:
                    unresolved.add(mp.texture_hash)
                for (x, y) in mp.positions:
                    if not (math.isfinite(x) and math.isfinite(y)):
                        bad += 1
            events_seen += len(p.poll_events())
    finally:
        p.close()

    print(f"    frames_with_items={frames_with_items}/{total + 4}  "
          f"max_mesh={max_mesh}  fx={total_fx}  events={events_seen}  "
          f"textures_acquired={len(rm.acquired)}")
    if bad:
        print(f"    FAIL: {bad} non-finite mesh positions"); ok = False
    if unresolved:
        print(f"    FAIL: unresolved texture hashes {sorted(unresolved)}"); ok = False
    if not advanced:
        print("    FAIL: frame head never advanced"); ok = False

    if kind == "character":
        if frames_with_items == 0 or max_mesh == 0:
            print("    FAIL: no mesh geometry produced"); ok = False
    elif kind == "instance":
        if max_mesh == 0:
            print("    FAIL: instance children produced no geometry"); ok = False
        if not rm.acquired:
            print("    FAIL: no textures acquired (external pack not merged?)")
            ok = False
    elif kind == "effect":
        if total_fx == 0:
            print("    FAIL: no effect batches produced"); ok = False
    elif kind == "events":
        if events_seen == 0:
            print("    FAIL: no timeline events drained"); ok = False

    print("    ->", "PASS" if ok else "FAIL")
    return ok


def check_loop_counts(lib) -> bool:
    """``FramePlan.finished`` must pulse once after *every* configured loop, not
    once per loop, and never under an infinite one. A commanded stop is not a
    finish either. Covers the cases the finished-edge check below does not:
    loop > 1, loop == -1, loop == 0 (a synonym for infinite), and stop()."""
    rel = "ss_assets/Ringo/Ringo.ssab"
    abs_ssab = os.path.join(_GAME, rel)
    if not os.path.exists(abs_ssab):
        print("### loop-counts  SKIP (Ringo not found)"); return True
    data = open(abs_ssab, "rb").read()

    def run(loop, steps):
        p = SSInternalPlayer(data, lib=lib, base_dir="ss_assets/Ringo",
                             resource_manager=RecordingResourceManager(),
                             pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))
        try:
            p.set_loop(loop)
            p.set_animation("attack1")
            p.play()
            dt_ms = 1000.0 / (p.fps or 30)
            events = []
            for _ in range(steps):
                plan = p.update(dt_ms)
                if plan.looped:
                    events.append("looped")
                if plan.finished:
                    events.append("finished")
            return events
        finally:
            p.close()

    print("### loop-counts  finished pulses once, after every loop")
    ok = True
    got3 = run(3, 2000)
    if got3 != ["looped", "looped", "finished"]:
        print(f"    FAIL: loop=3 gave {got3}"); ok = False
    got1 = run(1, 2000)
    if got1 != ["finished"]:
        print(f"    FAIL: loop=1 gave {got1}"); ok = False
    for loop in (-1, 0):
        got = run(loop, 2000)
        if "finished" in got or not got:
            print(f"    FAIL: loop={loop} gave {got} (want looped-only, never finished)")
            ok = False

    # A commanded stop is not a finish.
    p = SSInternalPlayer(data, lib=lib, base_dir="ss_assets/Ringo",
                         resource_manager=RecordingResourceManager(),
                         pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))
    try:
        p.set_loop(3)
        p.set_animation("attack1")
        p.play()
        dt_ms = 1000.0 / (p.fps or 30)
        p.update(dt_ms)
        p.stop()
        if any(p.update(dt_ms).finished for _ in range(120)):
            print("    FAIL: stop() reported finished"); ok = False
    finally:
        p.close()

    print(f"    loop=3 -> {got3}  loop=1 -> {got1}  -> {'PASS' if ok else 'FAIL'}")
    return ok


def check_finished_edge(lib) -> bool:
    """The pure core reports the play->stop edge via ``FramePlan.finished``; the
    HOST advances the sequence. The core itself has no queue. We act as the host:
    play 'attack1' once, and on the finished edge switch to 'wait1' and confirm
    it renders cleanly from a fresh head (no mid-update frame skew)."""
    rel = "ss_assets/Ringo/Ringo.ssab"
    abs_ssab = os.path.join(_GAME, rel)
    if not os.path.exists(abs_ssab):
        print("### finished-edge  SKIP (Ringo not found)"); return True
    data = open(abs_ssab, "rb").read()
    p = SSInternalPlayer(data, lib=lib, base_dir="ss_assets/Ringo",
                         resource_manager=RecordingResourceManager(),
                         pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))
    print("### finished-edge  play 'attack1' once -> host advances to 'wait1'")
    p.set_loop(1)            # play once so it finishes
    p.set_animation("attack1")
    p.play()
    fps = p.fps or 30
    dt_ms = 1000.0 / fps
    finished_seen = False
    advanced_to = None
    advanced_ok = False
    try:
        for _ in range(400):
            plan = p.update(dt_ms)
            if plan.finished:
                finished_seen = True
                # Host policy (what SSPlayer.render does on plan.finished):
                p.set_loop(-1)
                p.set_animation("wait1")
                p.play()
                nxt = p.update(dt_ms)            # the frame after the switch
                advanced_to = p.animation
                advanced_ok = (advanced_to == "wait1" and bool(nxt.items)
                               and nxt.frame_no >= 0)
                break
    finally:
        p.close()
    ok = finished_seen and advanced_ok
    print(f"    finished_edge={finished_seen}  advanced_to={advanced_to!r}  "
          f"-> {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("    FAIL: core did not report a clean finished edge / host advance")
    return ok


def main() -> int:
    lib = ssruntime.load_library()
    targets = [
        ("ss_assets/Ringo/Ringo.ssab",            "ss_assets/Ringo",          "wait1",    "character"),
        ("ss_assets/overall/Instance.ssab",       "ss_assets/overall",        None,       "instance"),
        ("ss_assets/ParticleEffect/e001.ssab",    "ss_assets/ParticleEffect", "emission", "effect"),
        ("ss_assets/overall/UserData.ssab",       "ss_assets/overall",        None,       "events"),
    ]
    print("== SSInternalPlayer (engine-independent core) verification ==\n")
    allok = True
    for rel, base, anim, kind in targets:
        allok &= check(lib, rel, base, anim, kind)
        print()
    allok &= check_finished_edge(lib)
    allok &= check_loop_counts(lib)
    print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
