#!/usr/bin/env python3
"""Headless verification of the timeline-event layer (UserData / Signal / Audio).

This is "Step 4 — interactive features" of the porting roadmap: the runtime
reports, after each ``update``, the indices of the ``EventsPerFrame`` records
the playhead crossed, and ``ss_renpy.events.EventResolver`` decodes them into
payloads. None of that needs a GUI, so this tool proves the whole path against
the real native library and the overall packs:

  1. the resolver finds the animation and its events vector matches the ssab;
  2. playing one non-looping pass fires **every** static event **exactly once**,
     and each fired ``frame_index`` matches a static one (the index→Events
     mapping is correct);
  3. payloads decode to native values — UserData integer/string, Signal
     command_id + typed params, Audio sound_name + loop_num;
  4. ``is_end_frame_reached`` trips at the end; looping replays the events and
     ``is_looped`` trips at the boundary.

Exits non-zero if any check fails. Needs the native library built
(``scripts/build-runtime.sh``); pure stdlib otherwise.

Usage:
    python tools/verify_events.py            # default overall event packs
    python tools/verify_events.py Foo.ssab   # a specific pack (first animation)
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime, events  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402

_OVERALL = os.path.join(_GAME, "ss_assets", "overall")
# Packs that actually carry the three event kinds (others have no events table).
_DEFAULT_PACKS = ["UserData.ssab", "Signal.ssab", "Sound.ssab"]


def _kind_counts(fe: events.FrameEvents) -> tuple[int, int, int]:
    return (len(fe.users), len(fe.signals), len(fe.audios))


def _static_expectation(resolver: events.EventResolver):
    """Multiset of (frame_index, u, s, a) for every non-empty static record."""
    exp = {}
    for idx in range(resolver.events_length):
        fe = resolver.resolve(idx)
        if fe is not None and not fe.is_empty:
            exp[idx] = (fe.frame_index, *_kind_counts(fe))
    return exp


def _playthrough(rt, resolver, fps, end_frame, *, extra_steps=4):
    """Step one frame at a time to the end, collecting every fired record."""
    dt = 1.0 / float(fps)
    collected = []
    # +extra to be sure we cross the final frame's [end, end+1) window.
    for _ in range(end_frame + extra_steps):
        rt.update(dt)
        collected.extend(resolver.collect(rt))
        if rt.is_end_frame_reached:
            break
    return collected


def verify_pack(pack: str) -> list[str]:
    """Return a list of failure strings for one pack ([] == all good)."""
    fails: list[str] = []
    path = pack if os.path.isabs(pack) else os.path.join(_OVERALL, pack)
    name = os.path.basename(path)
    if not os.path.exists(path):
        return [f"{name}: file not found ({path})"]

    data = open(path, "rb").read()
    meta = SsabMeta(data)
    anims = meta.animations()
    if not anims:
        return [f"{name}: no animations"]
    anim = anims[0]

    resolver = events.EventResolver(data, anim.name)
    if not resolver.available:
        fails.append(f"{name}: resolver could not find animation {anim.name!r}")
        return fails

    exp = _static_expectation(resolver)
    n_events = len(exp)
    print(f"  {name}: anim={anim.name!r} fps={anim.fps} "
          f"frames={anim.start_frame}..{anim.end_frame} "
          f"events_records={resolver.events_length} non_empty={n_events}")
    if n_events == 0:
        fails.append(f"{name}: no non-empty event records to verify")
        return fails

    rt = ssruntime.SSRuntime(_SS_LIB)
    rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                 origin=ssruntime.ORIGIN_CENTER)
    rt.load_ssab_bytes(data)
    if not rt.setup_animation(anim.name):
        rt.close()
        return [f"{name}: setup_animation failed"]
    rt.set_loop(1)
    rt.play()

    collected = _playthrough(rt, resolver, anim.fps, anim.end_frame)

    # (2) exactly-once + frame_index correctness over one non-looping pass.
    if not rt.is_end_frame_reached:
        fails.append(f"{name}: is_end_frame_reached never tripped")
    got = sorted((fe.frame_index, *_kind_counts(fe)) for fe in collected)
    want = sorted(exp.values())
    if got != want:
        fails.append(f"{name}: fired set {got} != static set {want}")
    else:
        print(f"    fired {len(collected)} record(s), each static event once: "
              f"frames={[fe.frame_index for fe in collected]}")

    # (3) payload decode sanity + human-readable dump.
    for fe in collected:
        for u in fe.users:
            if u.integer is None and u.string is None \
                    and u.rect is None and u.point is None:
                fails.append(f"{name}@f{fe.frame_index}: UserData part "
                             f"{u.part_index} carries no payload")
            print(f"    UserData f{fe.frame_index} part={u.part_index} "
                  f"int={u.integer} str={u.string!r} rect={u.rect} pt={u.point}")
        for s in fe.signals:
            if not s.command_id:
                fails.append(f"{name}@f{fe.frame_index}: Signal part "
                             f"{s.part_index} has empty command_id")
            if not isinstance(s.params, dict):
                fails.append(f"{name}@f{fe.frame_index}: Signal params not a dict")
            print(f"    Signal   f{fe.frame_index} part={s.part_index} "
                  f"cmd={s.command_id!r} active={s.active} params={s.params}")
        for a in fe.audios:
            if not a.sound_name:
                fails.append(f"{name}@f{fe.frame_index}: Audio part "
                             f"{a.part_index} has empty sound_name")
            if not isinstance(a.loop_num, int):
                fails.append(f"{name}@f{fe.frame_index}: Audio loop_num not int")
            print(f"    Audio    f{fe.frame_index} part={a.part_index} "
                  f"name={a.sound_name!r} loop={a.loop_num} "
                  f"hash={a.sound_name_hash}/{a.sound_list_name_hash}")

    # (4) looping replays the events and is_looped trips at the wrap.
    # NB: is_end_frame_reached is a per-update flag that trips at *every* clip
    # end (verified), so we cannot use it to stop a multi-loop play — we run a
    # fixed budget covering two full clip spans. is_looped trips on the wrap.
    rt.stop()
    rt.set_loop(2)
    rt.play()
    looped_seen = False
    loop2 = []
    dt = 1.0 / float(anim.fps)
    span = anim.end_frame - anim.start_frame + 1
    for _ in range(span * 2 + 8):
        rt.update(dt)
        loop2.extend(resolver.collect(rt))
        if rt.is_looped:
            looped_seen = True
    if not looped_seen:
        fails.append(f"{name}: is_looped never tripped over a 2-loop play")
    # The second loop must replay events: strictly more than one loop's worth.
    if len(loop2) <= n_events:
        fails.append(f"{name}: 2-loop fired {len(loop2)} <= one loop "
                     f"({n_events}); events did not replay")
    else:
        print(f"    2-loop replayed {len(loop2)} record(s); is_looped tripped")

    rt.close()
    return fails


def main(argv) -> int:
    global _SS_LIB
    try:
        _SS_LIB = ssruntime.load_library(
            base_dir=os.path.join(_GAME, "spritestudio", "libs"))
    except OSError as e:
        print(f"FAIL: could not load native library: {e}\n"
              f"      build it first: scripts/build-runtime.sh", file=sys.stderr)
        return 2

    packs = argv[1:] if len(argv) > 1 else _DEFAULT_PACKS
    all_fails: list[str] = []
    print("verify_events: timeline events (UserData / Signal / Audio)")
    for pack in packs:
        all_fails.extend(verify_pack(pack))

    print()
    if all_fails:
        print(f"FAIL ({len(all_fails)}):")
        for f in all_fails:
            print(f"  - {f}")
        return 1
    print(f"ALL PASS ({len(packs)} pack(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
