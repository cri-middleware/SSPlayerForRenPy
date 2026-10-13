#!/usr/bin/env python3
"""Headless check for animation mixing on ``SSInternalPlayer`` (the track stack).

The runtime owns the mixing itself; what this checks is the seam the Player
layer adds over it:

  * a crossfade (or a track animation) on track 0 switches the current
    animation at the call, so ``set_animation`` can go back to the one a
    crossfade left, and the loop count is put back on the incoming animation;
  * an outgoing animation running out mid-fade does not finish the player;
  * the track playback settings go through and outlast the animations laid on
    the track, track 0's through the copies ``set_animation`` replays;
  * overlays and fades advance with ``update``, hold on ``pause``, and keep the
    player animating after track 0 has finished;
  * every event is read from the table of the animation whose source fired
    it, carries that source, and the outgoing side of a crossfade falls silent
    unless its track's threshold lets it run on.

Ringo has short (``attack1``: 20 frames at 60fps) and long (``wait1`` /
``walk``: 80 frames) animations; ``overall/UserData.ssab`` fires events on
frames 0 and 10 of its one animation. No sample pack has user events in one
animation and none in another, so reading an event against the wrong table is
pinned only by the source each event carries.

Usage:  python tools/verify_tracks.py
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

_RINGO = "ss_assets/Ringo/Ringo.ssab"
_USERDATA = "ss_assets/overall/UserData.ssab"
_FAILS: list = []


def _fail(msg: str) -> None:
    print("    FAIL: " + msg)
    _FAILS.append(msg)


def _player(lib, rel):
    abs_ssab = os.path.join(_GAME, rel)
    if not os.path.exists(abs_ssab):
        return None
    return SSInternalPlayer(open(abs_ssab, "rb").read(), lib=lib,
                            base_dir=os.path.dirname(rel),
                            resource_manager=RecordingResourceManager(),
                            pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))


def _ringo(lib, anim="wait1"):
    p = _player(lib, _RINGO)
    if p is not None:
        p.set_animation(anim)
        p.play()
    return p


_DT = 1000.0 / 60.0    # one Ringo frame


def check_current_animation(lib) -> None:
    print("### the current animation switches when a crossfade on track 0 begins")
    p = _ringo(lib)
    try:
        p.update(_DT)
        outgoing = p.track_main_source(0)
        if not p.crossfade(0, "walk", 400):
            _fail("crossfade(0, 'walk') refused"); return
        if p.current_animation != "walk":
            _fail(f"current_animation is {p.current_animation!r} right after "
                  f"the crossfade, want 'walk'")
        if p.track_main_source(0) == outgoing:
            _fail("track 0's main source is still the outgoing one")
        if p.track_fade_progress(0) is None:
            _fail("no fade in flight on track 0 after the crossfade")
        # Track 1 does not touch the current animation.
        p.set_track_animation(1, "attack1")
        p.crossfade(1, "dash", 100)
        if p.current_animation != "walk":
            _fail(f"a track-1 call moved current_animation to "
                  f"{p.current_animation!r}")
        # The animation the crossfade left is a real switch for set_animation.
        if not p.set_animation("wait1") or p.current_animation != "wait1":
            _fail("set_animation('wait1') after the crossfade did not switch back")
        if p.track_count() != 1:
            _fail(f"set_animation left {p.track_count()} tracks, want 1")
        # set_track_animation on track 0 switches it as well.
        p.set_track_animation(0, "run")
        if p.current_animation != "run":
            _fail(f"set_track_animation(0, 'run') left {p.current_animation!r}")
    finally:
        p.close()


def check_settings_carry(lib) -> None:
    print("### speed and loop count outlast a crossfade on track 0")
    p = _ringo(lib)
    try:
        p.set_speed_scale(2.0)
        p.set_loop_count(1)
        p.crossfade(0, "attack1", 50)
        if abs((p.track_speed(0) or 0) - 2.0) > 1e-6 or abs(p.speed_scale - 2.0) > 1e-6:
            _fail(f"speed after the crossfade is {p.track_speed(0)} / "
                  f"{p.speed_scale}, want 2.0")
        if p.track_loop_count(0) != 1:
            _fail(f"loop count after the crossfade is {p.track_loop_count(0)}, want 1")
        # 2x: the incoming animation advances two frames per frame of time.
        f0 = p.track_frame(0)
        p.update(_DT * 3)
        f1 = p.track_frame(0)
        if f0 is None or f1 is None or abs((f1 - f0) - 6.0) > 0.5:
            _fail(f"at 2x the incoming animation moved {f0} -> {f1}, want +6")
        finished = sum(1 for _ in range(200) if p.update(_DT).finished)
        if finished != 1 or not p.is_finished():
            _fail(f"loop count 1 on the incoming animation: {finished} finish "
                  f"edge(s), is_finished={p.is_finished()}")
        # set_track_animation on track 0 keeps them too.
        p.set_track_animation(0, "walk")
        if p.track_loop_count(0) != 1 or abs(p.speed_scale - 2.0) > 1e-6:
            _fail(f"set_track_animation(0) left loop {p.track_loop_count(0)}, "
                  f"speed {p.speed_scale}")
        # ...and set_animation does not put back a value older than a
        # track-0 setting made through the track API.
        p.set_track_speed(0, 0.5)
        p.set_track_loop_count(0, 3)
        p.set_animation("wait1")
        if abs(p.speed_scale - 0.5) > 1e-6 or p.track_loop_count(0) != 3:
            _fail(f"set_animation replayed an older speed / loop: "
                  f"{p.speed_scale} / {p.track_loop_count(0)}")
    finally:
        p.close()


def check_outgoing_does_not_finish(lib) -> None:
    print("### an outgoing animation running out mid-fade does not finish the player")
    p = _player(lib, _RINGO)
    try:
        p.set_loop_count(1)
        p.set_animation("attack1")      # 20 frames, about 330 ms
        p.play()
        p.update(_DT * 10)
        p.set_loop_count(-1)
        p.crossfade(0, "wait1", 2000)
        edges = sum(1 for _ in range(60) if p.update(_DT).finished)
        if edges or p.is_finished():
            _fail(f"the outgoing attack1 ending finished the player "
                  f"(edges={edges}, is_finished={p.is_finished()})")
        if not p.is_playing():
            _fail("the player stopped playing when the outgoing side ran out")
    finally:
        p.close()


def check_fade_completes(lib) -> None:
    print("### a fade completes in update and the outgoing source is released")
    p = _ringo(lib)
    try:
        old = p.track_main_source(0)
        p.crossfade(0, "walk", 200)
        for _ in range(20):
            p.update(_DT)
        if p.track_fade_progress(0) is not None:
            _fail(f"fade still in flight: {p.track_fade_progress(0)}")
        new = p.track_main_source(0)
        if new is None or abs((p.source_weight(new) or 0) - 1.0) > 1e-6:
            _fail(f"incoming source {new} weighs {p.source_weight(new)}, want 1")
        if old != new and p.source_weight(old) is not None:
            _fail(f"the outgoing source {old} was not released")
    finally:
        p.close()


def check_refold(lib) -> None:
    print("### a crossfade in flight is folded, not settled, by the next one")
    p = _ringo(lib)
    try:
        a = p.track_main_source(0)
        p.crossfade(0, "walk", 1000)
        b = p.track_main_source(0)
        for _ in range(30):
            p.update(_DT)
        wa, wb = p.source_weight(a), p.source_weight(b)
        p.crossfade(0, "run", 1000)
        if wa is None or wb is None or 0.0 in (wa, wb):
            _fail(f"mid-fade weights read {wa} / {wb}")
        elif (abs((p.source_weight(a) or 0) - wa) > 1e-6
              or abs((p.source_weight(b) or 0) - wb) > 1e-6):
            _fail(f"the restart moved the weights: {wa}/{wb} -> "
                  f"{p.source_weight(a)}/{p.source_weight(b)}")
    finally:
        p.close()


def check_overlay(lib) -> None:
    print("### an overlay advances with update, holds on pause, loops and finishes")
    p = _ringo(lib)
    try:
        p.set_track_animation(1, "attack1")
        f0 = p.track_frame(1)
        p.update(_DT * 4)
        f1 = p.track_frame(1)
        if f0 is None or f1 is None or f1 <= f0:
            _fail(f"the overlay did not advance: {f0} -> {f1}")
        p.pause()
        p.update(_DT * 4)
        if p.track_frame(1) != f1:
            _fail(f"pause did not hold the overlay: {f1} -> {p.track_frame(1)}")
        if p.is_animating():
            _fail("a paused stack still asks for redraws")
        p.resume()
        p.set_track_frame(1, 0.0)
        if not p.set_track_loop_count(1, 2) or p.track_loop_count(1) != 2:
            _fail(f"track 1 loop count reads {p.track_loop_count(1)}, want 2")
        loops = 0
        for _ in range(120):
            p.update(_DT)
            loops += p.track_just_looped(1)
        if loops != 1 or not p.is_track_finished(1):
            _fail(f"loop count 2 on track 1: {loops} loop(s), "
                  f"finished={p.is_track_finished(1)}")
        held = p.track_frame(1)
        p.update(_DT * 5)
        if p.track_frame(1) != held or p.track_count() < 2:
            _fail("a finished overlay did not hold its last frame on the stack")
        if p.is_finished():
            _fail("an overlay finishing finished the player")
        # Laying another animation there starts it looping forever again,
        # while the track's speed stays.
        p.set_track_speed(1, 1.5)
        p.set_track_animation(1, "dash")
        if p.track_loop_count(1) != -1 or abs((p.track_speed(1) or 0) - 1.5) > 1e-6:
            _fail(f"a new animation on track 1: loop {p.track_loop_count(1)} "
                  f"(want -1), speed {p.track_speed(1)} (want 1.5)")
    finally:
        p.close()


def check_animating_after_track_zero(lib) -> None:
    print("### the stack keeps the player animating after track 0 has finished")
    p = _player(lib, _RINGO)
    try:
        p.set_loop_count(1)
        p.set_animation("attack1")
        p.play()
        p.set_track_animation(1, "walk")
        for _ in range(60):
            p.update(_DT)
        if not p.is_finished():
            _fail("attack1 did not finish under loop count 1")
        f = p.track_frame(1)
        p.update(_DT * 3)
        if not p.is_animating() or p.track_frame(1) == f:
            _fail("the overlay stopped with track 0")
        p.stop()
        if p.is_animating():
            _fail("a stopped stack still asks for redraws")
        p.set_animation("attack1")
        if p.track_count() != 1 or p.is_animating():
            _fail("set_animation left the stack in use")
    finally:
        p.close()


def check_track_settings(lib) -> None:
    print("### the track playback settings read back, and refuse what has no track")
    p = _ringo(lib)
    try:
        # A setting may go on a track with nothing laid on it yet.
        if not p.set_track_frame_rate(2, 30) or p.track_frame_rate(2) != 30:
            _fail(f"frame-rate override on an empty track reads "
                  f"{p.track_frame_rate(2)}")
        if p.set_track_loop_count(2, 1):
            _fail("a loop count on a track with no animation was accepted")
        if p.track_loop_count(2) is not None:
            _fail(f"loop count of an empty track reads {p.track_loop_count(2)}")
        p.set_track_animation(2, "walk")
        p.set_track_frame_skip_enabled(2, False)
        p.set_track_playback_direction(2, 1, 1)
        got = (p.track_frame_skip_enabled(2), p.track_playback_direction(2),
               p.track_playback_style(2))
        if got != (False, 1, 1):
            _fail(f"track 2 skip / direction / style read {got}")
        p.set_track_alpha(2, 0.25)
        p.set_track_blend(2, ssruntime.TRACK_BLEND_ADDITIVE)
        p.set_track_sync(3, ssruntime.TRACK_SYNC_START)
        got = (p.track_alpha(2), p.track_blend(2), p.track_sync(3))
        if got != (0.25, ssruntime.TRACK_BLEND_ADDITIVE, ssruntime.TRACK_SYNC_START):
            _fail(f"track alpha / blend / sync read {got}")
        thr = p.track_outgoing_event_threshold(0)
        if thr is None or not math.isinf(thr):
            _fail(f"outgoing event threshold defaults to {thr}, want inf")
        p.set_track_outgoing_event_threshold(0, 0.5)
        if p.track_outgoing_event_threshold(0) != 0.5:
            _fail("outgoing event threshold does not round-trip")
        h = p.add_track_source(2, "run", 0.5)
        if h is None or p.source_weight(h) != 0.5:
            _fail(f"add_track_source gave {h} weighing {p.source_weight(h)}")
        p.set_source_event_threshold(h, 0.25)
        if p.source_event_threshold(h) != 0.25:
            _fail("source event threshold does not round-trip")
        # What does not exist reads None, and refuses.
        nothing = (p.track_alpha(9), p.track_frame(9), p.track_loop_count(9),
                   p.track_frame_skip_enabled(9), p.track_main_source(9),
                   p.track_fade_progress(0), p.source_weight(4000),
                   p.track_alpha(-1))
        if any(v is not None for v in nothing):
            _fail(f"reads of nothing gave {nothing}")
        if p.set_track_alpha(-1, 1.0) or p.crossfade(-1, "walk", 10) \
                or p.crossfade(0, "no-such-animation", 10) \
                or p.add_track_source(1, "no-such-animation") is not None:
            _fail("a negative track or an unknown animation was accepted")
        if p.current_animation != "wait1":
            _fail("a refused crossfade moved current_animation")
    finally:
        p.close()


def check_events(lib) -> None:
    print("### events are read per source, and the outgoing side falls silent")
    p = _player(lib, _USERDATA)
    if p is None:
        print(f"### events  SKIP ({_USERDATA} not found)"); return
    try:
        name = p.animation_names()[0]
        dt = 1000.0 / 30.0

        def run(threshold):
            p.set_animation(name)
            p.play()
            p.update(dt)
            p.poll_events()
            old = p.track_main_source(0)
            if threshold is not None:
                p.set_track_outgoing_event_threshold(0, threshold)
            p.crossfade(0, name, 2000)
            new = p.track_main_source(0)
            got = []
            for _ in range(60):
                got.extend(p.update(dt).events)
            return old, new, got

        old, new, got = run(None)
        sources = {fe.source for fe in got}
        if not got:
            _fail("no events fired across the crossfade")
        elif sources != {new}:
            _fail(f"by default the events came from {sources}, want only the "
                  f"incoming source {new} (outgoing {old})")
        if any(u.source != fe.source for fe in got for u in fe.users):
            _fail("an event does not carry its record's source")

        old, new, got = run(0.5)
        if old not in {fe.source for fe in got}:
            _fail(f"threshold 0.5 let no event of the outgoing source {old} fire")
        print(f"    default -> {len([fe for fe in got if fe.source == new])} "
              f"incoming record(s); 0.5 -> outgoing fires too")
    finally:
        p.close()


def main() -> int:
    lib = ssruntime.load_library()
    print("== animation mixing (track stack) verification ==\n")
    if not os.path.exists(os.path.join(_GAME, _RINGO)):
        print(f"### tracks  SKIP ({_RINGO} not found)")
        return 0
    for check in (check_current_animation, check_settings_carry,
                  check_outgoing_does_not_finish, check_fade_completes,
                  check_refold, check_overlay, check_animating_after_track_zero,
                  check_track_settings, check_events):
        check(lib)
    print()
    print("== RESULT:", "ALL PASS" if not _FAILS else
          "%d FAILURE(S)" % len(_FAILS), "==")
    return 0 if not _FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
