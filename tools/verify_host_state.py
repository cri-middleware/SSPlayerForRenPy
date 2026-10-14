#!/usr/bin/env python3
"""Headless check for the host policy ``SSPlayer`` keeps in ``ss_renpy.host_state``.

What ``spritestudio.rpy`` decides as a Ren'Py host, driven here with NO Ren'Py:

  * ``ShowClock``: which render of a frame advances the animation, by how much,
    and when a render means the player was shown afresh -- for one placement,
    a SnowBlossom (several particles, the oldest dying), and one player shown
    under two tags (the first hidden);
  * ``start_initial``: the constructor's animation or sequence, ``still``, and
    the error for an animation the pack lacks;
  * ``playback_state`` + ``restore`` + ``apply_kept``: a core rebuilt after a
    load comes back on the same animation, frame, state, section, frame rate
    and frame skipping as the one Ren'Py dropped.

Usage:  python tools/verify_host_state.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import host_state, ssruntime  # noqa: E402
from ss_renpy.host_state import PAUSED, PLAYING, STOPPED, ShowClock  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402

_RINGO = "ss_assets/Ringo/Ringo.ssab"
_EPS = 1e-6


def _frames(clock, frames):
    """Feed ``frames`` -- one list of render ``st`` per frame -- through
    ``clock``; return one ``(dt, reshown)`` per render."""
    out = []
    for n, renders in enumerate(frames, start=1):
        for st in renders:
            dt = clock.advance(n, st)
            out.append((dt, clock.reshown))
    return out


def _same(got, want) -> bool:
    if len(got) != len(want):
        return False
    for (gdt, gre), (wdt, wre) in zip(got, want):
        if gre != wre or (gdt is None) != (wdt is None):
            return False
        if gdt is not None and abs(gdt - wdt) > _EPS:
            return False
    return True


def check_show_clock() -> bool:
    """Each case is a sequence of frames, each frame the ``st`` of every render
    in the order Ren'Py makes them (a SpriteManager draws its sprites oldest
    first), and the ``(dt, reshown)`` each render must get."""
    print("### ShowClock  one timeline, however many places draw it")
    cases = [
        ("one placement",
         [[0.0], [0.016], [0.05]],
         [(0.0, False), (0.016, False), (0.034, False)]),
        ("shown afresh",
         [[0.0], [0.5], [0.0], [0.016]],
         [(0.0, False), (0.5, False), (0.0, True), (0.016, False)]),
        # Hidden for a while, then shown again: no render in between, so the
        # next one is matched against the last frame that drew it.
        ("shown afresh after a gap",
         [[2.0], [], [], [0.0]],
         [(0.0, False), (0.0, True)]),
        # Only the first render of a frame moves the animation.
        ("drawn twice in a frame",
         [[1.0, 1.0], [1.016, 1.016]],
         [(0.0, False), (None, False), (0.016, False), (None, False)]),
        # Three particles; the oldest dies, and a new one is born last.
        ("SnowBlossom, the oldest dying",
         [[3.0, 2.0, 1.0], [2.016, 1.016], [2.033, 1.033, 0.0]],
         [(0.0, False), (None, False), (None, False),
          (0.016, False), (None, False),
          (0.017, False), (None, False), (None, False)]),
        # `show expression ringo as a`, then `as b`, then `hide a`.
        ("two tags, the first hidden",
         [[5.0], [5.016, 0.0], [5.033, 0.016], [0.033]],
         [(0.0, False),
          (0.016, False), (None, False),
          (0.017, False), (None, False),
          (0.017, False)]),
    ]
    ok = True
    for name, frames, want in cases:
        got = _frames(ShowClock(), frames)
        if not _same(got, want):
            print(f"    FAIL: {name}: got {got}, want {want}")
            ok = False
    print(f"    {len(cases)} cases  -> {'PASS' if ok else 'FAIL'}")
    return ok


def _ringo(lib):
    abs_ssab = os.path.join(_GAME, _RINGO)
    return SSInternalPlayer(open(abs_ssab, "rb").read(), lib=lib,
                            base_dir=os.path.dirname(_RINGO),
                            resource_manager=RecordingResourceManager(),
                            pack_reader=filesystem_pack_reader(
                                os.path.dirname(abs_ssab)))


def check_start_initial(lib) -> bool:
    print("### start_initial  the constructor's animation, sequence and still")
    ok = True

    p = _ringo(lib)
    try:
        queue = host_state.start_initial(p, ["jump_in", "jump_wait", "jump_out"],
                                         3, 1.0, pack=_RINGO)
        if queue != ["jump_wait", "jump_out"]:
            print(f"    FAIL: sequence queue is {queue}"); ok = False
        if p.current_animation != "jump_in" or not p.is_playing():
            print(f"    FAIL: sequence did not play its first clip "
                  f"({p.current_animation!r}, playing={p.is_playing()})"); ok = False
        if p.loop_count != 1:
            print(f"    FAIL: a clip mid-sequence plays {p.loop_count} times, not once")
            ok = False
    finally:
        p.close()

    p = _ringo(lib)
    try:
        queue = host_state.start_initial(p, ["wait1"], 3, 1.0, pack=_RINGO)
        if queue or p.loop_count != 3:
            print(f"    FAIL: the last clip of a sequence: queue={queue}, "
                  f"loop={p.loop_count} (want [], 3)"); ok = False
    finally:
        p.close()

    p = _ringo(lib)
    try:
        queue = host_state.start_initial(p, None, -1, 0.5, start_frame=4.0,
                                         pack=_RINGO)
        if queue or p.current_animation != p.animation_names()[0]:
            print(f"    FAIL: None did not set up the first animation "
                  f"({p.current_animation!r})"); ok = False
        if abs(p.frame_no - 4.0) > _EPS:
            print(f"    FAIL: start_frame=4 began at {p.frame_no}"); ok = False
    finally:
        p.close()

    p = _ringo(lib)
    try:
        host_state.start_initial(p, "wait1", -1, 1.0, still=True, pack=_RINGO)
        dt_ms = 1000.0 / (p.frame_rate or 30)
        before = p.frame_no
        p.update(dt_ms * 5)
        if not p.is_pausing() or abs(p.frame_no - before) > _EPS:
            print(f"    FAIL: still did not hold the first frame "
                  f"(pausing={p.is_pausing()}, {before} -> {p.frame_no})"); ok = False
    finally:
        p.close()

    p = _ringo(lib)
    try:
        try:
            host_state.start_initial(p, "no_such_anim", -1, 1.0, pack=_RINGO)
            print("    FAIL: a missing animation did not raise"); ok = False
        except Exception as e:  # noqa: BLE001 -- the message is what is checked
            msg = str(e)
            if "no_such_anim" not in msg or _RINGO not in msg or "wait1" not in msg:
                print(f"    FAIL: the error does not name the animation, the pack "
                      f"and what it has: {msg}"); ok = False
    finally:
        p.close()

    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def _record(core):
    """What SSPlayer.render() records each frame, and __getstate__ keeps."""
    return (core.current_animation, core.frame_no, core.loop_count,
            host_state.playback_state(core))


def check_restore(lib) -> bool:
    """A core played, saved and rebuilt draws what the original would have."""
    print("### restore  a rebuilt core picks up where the dropped one stood")
    ok = True

    def rebuild(rec, section=None, frame_skip=True, frame_rate=None):
        anim, frame, loop, state = rec
        q = _ringo(lib)
        host_state.apply_kept(q, frame_skip, frame_rate)
        restored = host_state.restore(q, anim, 1.0, loop, frame, state, section)
        return q, restored

    # Playing, inside a section, at a frame-rate override: both cores then
    # run in step.
    p = _ringo(lib)
    q = None
    try:
        p.set_frame_rate(30)
        host_state.start_initial(p, "wait1", -1, 1.0, pack=_RINGO)
        p.set_animation_section(10, 30)
        dt_ms = 1000.0 / 30
        for _ in range(7):
            p.update(dt_ms)
        rec = _record(p)
        q, restored = rebuild(rec, section=(10, 30), frame_rate=30)
        if not restored:
            print("    FAIL: restore refused an animation the pack has"); ok = False
        if (q.start_frame, q.end_frame) != (10, 30):
            print(f"    FAIL: section came back as {q.start_frame}..{q.end_frame}")
            ok = False
        if q.frame_rate != 30:
            print(f"    FAIL: frame rate came back as {q.frame_rate}"); ok = False
        if _record(q) != rec:
            print(f"    FAIL: restored {_record(q)}, saved {rec}"); ok = False
        # Past the section end: the original wraps to the section start, and
        # a restore without the section would run on into frame 31+.
        drift = []
        for _ in range(30):
            a, b = p.update(dt_ms), q.update(dt_ms)
            if abs(a.frame_no - b.frame_no) > _EPS:
                drift.append((a.frame_no, b.frame_no))
        if drift:
            print(f"    FAIL: the rebuilt core plays differently, e.g. {drift[:3]}")
            ok = False
    finally:
        p.close()
        if q:
            q.close()

    # Paused and stopped hold their frame; a finished one-shot stays finished.
    for state_name, stop in (("paused", lambda c: c.pause()),
                             ("stopped", lambda c: c.stop()),
                             ("finished", None)):
        p = _ringo(lib)
        q = None
        try:
            host_state.start_initial(p, "attack1", 1, 1.0, pack=_RINGO)
            dt_ms = 1000.0 / (p.frame_rate or 30)
            for _ in range(200 if stop is None else 6):
                p.update(dt_ms)
            if stop:
                stop(p)
            rec = _record(p)
            want = PAUSED if state_name == "paused" else STOPPED
            if rec[3] != want:
                print(f"    FAIL: {state_name} read as {rec[3]!r}"); ok = False
            q, _ = rebuild(rec)
            held = [q.update(dt_ms) for _ in range(5)]
            if _record(q) != rec:
                print(f"    FAIL: {state_name}: restored {_record(q)}, saved {rec}")
                ok = False
            if any(abs(h.frame_no - rec[1]) > _EPS for h in held):
                print(f"    FAIL: {state_name}: moved off frame {rec[1]}"); ok = False
            if any(h.finished for h in held):
                print(f"    FAIL: {state_name}: the restore fired finished again")
                ok = False
        finally:
            p.close()
            if q:
                q.close()

    # A playing one stays playing.
    p = _ringo(lib)
    q = None
    try:
        host_state.start_initial(p, "walk", -1, 1.0, pack=_RINGO)
        dt_ms = 1000.0 / (p.frame_rate or 30)
        for _ in range(5):
            p.update(dt_ms)
        rec = _record(p)
        if rec[3] != PLAYING:
            print(f"    FAIL: playing read as {rec[3]!r}"); ok = False
        q, _ = rebuild(rec)
        if q.update(dt_ms).frame_no <= rec[1]:
            print("    FAIL: a playing restore did not move on"); ok = False
    finally:
        p.close()
        if q:
            q.close()

    # Frame skipping off: one frame per update, however long the update.
    q = _ringo(lib)
    try:
        host_state.apply_kept(q, frame_skip=False)
        host_state.start_initial(q, "walk", -1, 1.0, pack=_RINGO)
        q.update(1000.0)
        if abs(q.frame_no - 1.0) > _EPS:
            print(f"    FAIL: frame skipping off still advanced to {q.frame_no}")
            ok = False
    finally:
        q.close()

    # The pack re-exported without the saved animation: restore says so.
    q = _ringo(lib)
    try:
        if host_state.restore(q, "no_such_anim", 1.0, -1, 3.0, PLAYING):
            print("    FAIL: restore accepted an animation the pack lacks"); ok = False
    finally:
        q.close()

    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    print("== host_state (SSPlayer's host policy) verification ==\n")
    allok = check_show_clock()
    print()
    if not os.path.exists(os.path.join(_GAME, _RINGO)):
        print(f"### {_RINGO}  SKIP (not found)")
    else:
        lib = ssruntime.load_library()
        allok &= check_start_initial(lib)
        print()
        allok &= check_restore(lib)
    print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
