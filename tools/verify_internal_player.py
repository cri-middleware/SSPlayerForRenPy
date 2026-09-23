#!/usr/bin/env python3
"""Headless check for the engine-independent playback core (``SSInternalPlayer``).

Exercises the canonical imperative flow with NO Ren'Py:

    p = SSInternalPlayer(bytes, lib=..., base_dir=..., resource_manager=rm,
                         pack_reader=...)   # -> rm.acquire(textures)
    p.set_animation(name)   # -> Brain setup (a cheap, resource-free switch)
    p.play()
    plan = p.update(dt_ms)  # -> FramePlan (z-ordered world-space items)

and validates, per pack kind:
  * animation names enumerate;
  * *loading* asks the ResourceManager for every texture the pack draws from,
    and ``set_animation`` then acquires nothing;
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

    # Loading must request every texture this pack draws from — cellmap atlases
    # AND texture-change (TCHG) targets, which live in a separate table and would
    # otherwise leave those batches textureless.
    expect_tex = {(base_dir + "/" + c.image_path) for c in meta.cellmaps()
                  if c.image_path}
    expect_tex |= {(base_dir + "/" + t.name) for t in meta.external_textures()
                   if t.name}
    missing_tex = expect_tex - rm.acquired_set
    if missing_tex:
        print(f"    FAIL: loading did not acquire {sorted(missing_tex)}")
        ok = False
    # ...so that set_animation is a cheap switch a game can call per frame.
    acquired_at_load = set(rm.acquired_set)
    if not p.set_animation(name):
        print(f"    FAIL: set_animation({name!r})"); return False
    if p.current_animation != name:
        print(f"    FAIL: animation is {p.current_animation!r}, expected {name!r}")
        ok = False
    late_tex = rm.acquired_set - acquired_at_load
    if late_tex:
        print(f"    FAIL: set_animation acquired {sorted(late_tex)} "
              f"(textures belong to load)")
        ok = False

    p.play()
    if not p.is_playing():
        print("    FAIL: not playing after play()"); ok = False

    fps = p.frame_rate or 30
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
    elif kind == "texchange":
        # A part with a texture-change (TCHG) attribute draws from a file in
        # `external_textures`, keyed by the FILE-name hash — a namespace no
        # cellmap covers. The unresolved-hash check above is the real assertion
        # (a cellmaps-only player drops those parts); require geometry too.
        if max_mesh == 0:
            print("    FAIL: no mesh geometry produced"); ok = False

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
            p.set_loop_count(loop)
            p.set_animation("attack1")
            p.play()
            dt_ms = 1000.0 / (p.frame_rate or 30)
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
        p.set_loop_count(3)
        p.set_animation("attack1")
        p.play()
        dt_ms = 1000.0 / (p.frame_rate or 30)
        p.update(dt_ms)
        p.stop()
        if any(p.update(dt_ms).finished for _ in range(120)):
            print("    FAIL: stop() reported finished"); ok = False
    finally:
        p.close()

    print(f"    loop=3 -> {got3}  loop=1 -> {got1}  -> {'PASS' if ok else 'FAIL'}")
    return ok


def check_playback_modes(lib) -> bool:
    """The playback-mode knobs read back, and survive an animation switch.

    ``setup_animation`` resets direction / ping-pong / frame-skip in the Brain,
    so the core has to re-apply them — otherwise a reverse sprite silently
    turns forward the moment a sequence chains to its next clip. Also pins the
    two frame-skip modes behaviourally: Timed (on) advances by the elapsed
    time, Fixed (off) by exactly one frame per update."""
    rel = "ss_assets/overall/UserData.ssab"
    abs_ssab = os.path.join(_GAME, rel)
    if not os.path.exists(abs_ssab):
        print("### playback-modes  SKIP (UserData not found)"); return True
    data = open(abs_ssab, "rb").read()

    def mk():
        return SSInternalPlayer(
            data, lib=lib, base_dir="ss_assets/overall",
            resource_manager=RecordingResourceManager(),
            pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))

    print("### playback-modes  direction / ping-pong / frame-skip")
    ok = True
    p = mk()
    try:
        got = (p.playback_direction, p.playback_style, p.frame_skip_enabled)
        if got != (0, 0, True):
            print(f"    FAIL: defaults are {got}, want (0, 0, True)"); ok = False
        p.set_playback_direction(1, 1)
        p.set_frame_skip_enabled(False)
        got = (p.playback_direction, p.playback_style, p.frame_skip_enabled)
        if got != (1, 1, False):
            print(f"    FAIL: after set they read {got}, want (1, 1, False)")
            ok = False
        p.set_animation(p.animation_names()[0])      # resets them in the Brain
        after = (p.playback_direction, p.playback_style, p.frame_skip_enabled)
        if after != (1, 1, False):
            print(f"    FAIL: set_animation lost them: {after}, want (1, 1, False)")
            ok = False
    finally:
        p.close()

    # speed_scale reports what the Brain STORED, which is not always what it
    # was handed: a zero or negative rate clamps to a stop there (reverse is
    # set_playback_direction's business), so a host can tell that its negative
    # became a stop. There is deliberately no read-out for the request itself —
    # `_speed` is private since the request mirrors stopped being published.
    print("### speed_scale  the effective rate, not the requested one")
    p = mk()
    try:
        p.set_animation(p.animation_names()[0])
        for asked, effective in ((0.5, 0.5), (2.0, 2.0), (0.0, 0.0), (-1.0, 0.0)):
            p.set_speed_scale(asked)
            if abs(p.speed_scale - effective) > 1e-6:
                print(f"    FAIL: set_speed_scale({asked}) reads back "
                      f"{p.speed_scale}, want {effective}")
                ok = False
        print("    0.5/2.0 as asked; 0.0 and -1.0 both read back 0.0  -> "
              + ("PASS" if ok else "FAIL"))
    finally:
        p.close()

    # One update long enough to cover the whole animation: Timed follows the
    # clock, Fixed advances a single frame.
    heads = {}
    for skip in (True, False):
        q = mk()
        try:
            q.set_frame_skip_enabled(skip)
            q.set_animation(q.animation_names()[0])
            q.set_loop_count(1)
            q.play()
            span = max(1, q.total_frames - 1)
            heads[skip] = q.update(1000.0 / (q.frame_rate or 30) * span).frame_no
        finally:
            q.close()
    if heads.get(True, 0) <= heads.get(False, 0):
        print(f"    FAIL: frame-skip made no difference: {heads}"); ok = False
    if heads.get(False) != 1.0:
        print(f"    FAIL: with skip off one update advanced to {heads.get(False)},"
              f" want exactly 1 frame"); ok = False

    print(f"    one long update -> timed={heads.get(True)} fixed={heads.get(False)}"
          f"  -> {'PASS' if ok else 'FAIL'}")
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
    p.set_loop_count(1)            # play once so it finishes
    p.set_animation("attack1")
    p.play()
    fps = p.frame_rate or 30
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
                p.set_loop_count(-1)
                p.set_animation("wait1")
                p.play()
                nxt = p.update(dt_ms)            # the frame after the switch
                advanced_to = p.current_animation
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


def check_restore_state(lib) -> bool:
    """The rollback-restore mechanics SSPlayer._ensure() depends on.

    Ren'Py pickles the displayable WITHOUT the core and rebuilds it lazily, so
    the host restores the head by hand. A player that was paused, stopped, or
    naturally finished must come back that way — restoring it with play() would
    resume a paused sprite and re-trip the completion edge of a one-shot that
    had already fired on_finished. This pins the two non-playing restores:

      * "stopped": ``set_animation`` + ``set_frame`` with NO play() poses the
        saved frame, leaves the head parked, and reports no finished edge;
      * "paused":  play() -> set_frame() -> pause() holds that exact frame.
    """
    rel = "ss_assets/Ringo/Ringo.ssab"
    abs_ssab = os.path.join(_GAME, rel)
    if not os.path.exists(abs_ssab):
        print("### restore-state  SKIP (Ringo not found)"); return True
    data = open(abs_ssab, "rb").read()
    base = os.path.dirname(abs_ssab)

    def _new():
        return SSInternalPlayer(data, lib=lib, base_dir="ss_assets/Ringo",
                                resource_manager=RecordingResourceManager(),
                                pack_reader=filesystem_pack_reader(base))

    print("### restore-state  a finished / paused player restores as it was")
    ok = True
    p = _new()
    p.set_loop_count(1)
    p.set_animation("attack1")
    p.play()
    dt_ms = 1000.0 / (p.frame_rate or 30)
    saved = None
    for _ in range(400):
        if p.update(dt_ms).finished:
            saved = p.frame_no
            break
    finished_state = p.is_finished()
    still_playing = p.is_playing()
    p.close()
    if saved is None:
        print("    FAIL: 'attack1' never finished under set_loop_count(1)"); return False
    # What the host's _playback_state() reads to classify it as "stopped".
    if not finished_state or still_playing:
        print(f"    FAIL: a completed one-shot should read is_finished=True / "
              f"is_playing=False, got {finished_state}/{still_playing}"); ok = False

    q = _new()                       # "stopped": seek only, never play()
    q.set_loop_count(1)
    q.set_animation("attack1")
    q.set_frame_no(saved)
    first = q.update(0.0)
    second = q.update(dt_ms)
    q_playing = q.is_playing()
    q.close()
    if abs(first.frame_no - saved) > 1e-3 or not first.items:
        print(f"    FAIL: parked restore did not pose frame {saved} "
              f"(frame={first.frame_no}, items={len(first.items)})"); ok = False
    if first.finished or second.finished:
        print("    FAIL: parked restore re-fired the finished edge"); ok = False
    if q_playing or abs(second.frame_no - saved) > 1e-3:
        print(f"    FAIL: parked restore resumed playing "
              f"(playing={q_playing}, next frame={second.frame_no})"); ok = False

    r = _new()                       # "paused": play -> seek -> pause
    r.set_loop_count(1)
    r.set_animation("attack1")
    r.play()
    r.set_frame_no(5.0)
    r.pause()
    held = r.update(0.0)
    later = r.update(dt_ms * 3)
    r_pausing = r.is_pausing()
    r.close()
    if not r_pausing or abs(held.frame_no - 5.0) > 1e-3 \
            or abs(later.frame_no - 5.0) > 1e-3:
        print(f"    FAIL: paused restore did not hold frame 5 "
              f"(pausing={r_pausing}, {held.frame_no} -> {later.frame_no})"); ok = False

    print(f"    saved_frame={saved}  -> {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    lib = ssruntime.load_library()
    targets = [
        ("ss_assets/Ringo/Ringo.ssab",            "ss_assets/Ringo",          "wait1",    "character"),
        ("ss_assets/overall/Instance.ssab",       "ss_assets/overall",        None,       "instance"),
        ("ss_assets/ParticleEffect/e001.ssab",    "ss_assets/ParticleEffect", "emission", "effect"),
        ("ss_assets/overall/UserData.ssab",       "ss_assets/overall",        None,       "events"),
        ("ss_assets/overall/TextureChange.ssab",  "ss_assets/overall",        None,       "texchange"),
    ]
    print("== SSInternalPlayer (engine-independent core) verification ==\n")
    allok = True
    for rel, base, anim, kind in targets:
        allok &= check(lib, rel, base, anim, kind)
        print()
    allok &= check_finished_edge(lib)
    allok &= check_restore_state(lib)
    allok &= check_loop_counts(lib)
    allok &= check_playback_modes(lib)
    print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
