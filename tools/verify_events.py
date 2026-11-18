#!/usr/bin/env python3
"""Headless verification of the timeline-event layer (UserData / Signal / Audio).

The runtime reports, after each ``update``, the indices of the
``EventsPerFrame`` records the playhead crossed, and
``ss_renpy.events.EventResolver`` decodes them into payloads. None of that
needs a GUI, so this tool proves the whole path against the real native
library and the overall packs:

  1. the resolver finds the animation and its events vector matches the ssab;
  2. playing one non-looping pass fires **every** static event **exactly once**,
     and each fired ``frame_index`` matches a static one (the index→Events
     mapping is correct);
  3. payloads decode to native values — UserData integer/string, Signal
     command_id + typed params, Audio sound_name + loop_num;
  4. ``is_finished`` trips once the configured loops have played; looping
     replays the events and ``just_looped`` trips at the boundary.

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
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402
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
    """Step one frame at a time to the end, collecting every fired record.

    Also returns the ``is_playing_forward`` reading after the first forward
    update — the signal the host uses to gate audio."""
    dt = 1.0 / float(fps)
    collected = []
    forward_after_first = None
    # +extra to be sure we cross the final frame's [end, end+1) window.
    for i in range(end_frame + extra_steps):
        rt.update(dt)
        if i == 0:
            forward_after_first = rt.is_playing_forward
        collected.extend(resolver.collect(rt))
        if rt.is_finished:
            break
    return collected, forward_after_first


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

    # Pack sound table (the pack's SoundList table): the map the resolver uses to fill each
    # AudioEvent.file_path, and the set the host preloads.
    sound_map = meta.sound_file_map()
    sfiles = meta.sound_files()
    if sfiles:
        print(f"  {name}: has_audio={meta.has_audio()} sound_files="
              f"{[sf.file_path for sf in sfiles]}")

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
    rt.set_loop_count(1)
    rt.play()

    collected, forward_after_first = _playthrough(
        rt, resolver, anim.fps, anim.end_frame)

    # (2) exactly-once + frame_index correctness over one non-looping pass.
    if not rt.is_finished:
        fails.append(f"{name}: is_finished never tripped over a set_loop_count(1) pass")
    # Forward playback must report forward (the audio gate).
    if forward_after_first is not True:
        fails.append(f"{name}: is_playing_forward was {forward_after_first!r} "
                     f"during forward playback (audio gate would misfire)")
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
            # (3b) each Audio event resolves to its ssab-relative file via the
            # pack's SoundList table — this is what the host plays.
            want_fp = sound_map.get((a.sound_list_name_hash, a.sound_name_hash)) \
                or sound_map.get(a.sound_name_hash, "")
            if not a.file_path:
                fails.append(f"{name}@f{fe.frame_index}: Audio {a.sound_name!r} "
                             f"did not resolve to a file path")
            elif a.file_path != want_fp:
                fails.append(f"{name}@f{fe.frame_index}: Audio {a.sound_name!r} "
                             f"file {a.file_path!r} != map {want_fp!r}")
            print(f"    Audio    f{fe.frame_index} part={a.part_index} "
                  f"name={a.sound_name!r} loop={a.loop_num} file={a.file_path!r} "
                  f"hash={a.sound_name_hash}/{a.sound_list_name_hash}")

    # (4) looping replays the events and just_looped trips at the wrap. We run a
    # fixed budget covering two full clip spans rather than stopping on a flag:
    # is_finished only trips after *both* loops, and just_looped is the per-wrap
    # pulse we are actually measuring here.
    rt.stop()
    rt.set_loop_count(2)
    rt.play()
    looped_seen = False
    loop2 = []
    dt = 1.0 / float(anim.fps)
    span = anim.end_frame - anim.start_frame + 1
    for _ in range(span * 2 + 8):
        rt.update(dt)
        loop2.extend(resolver.collect(rt))
        if rt.just_looped:
            looped_seen = True
    if not looped_seen:
        fails.append(f"{name}: just_looped never tripped over a 2-loop play")
    # The second loop must replay events: strictly more than one loop's worth.
    if len(loop2) <= n_events:
        fails.append(f"{name}: 2-loop fired {len(loop2)} <= one loop "
                     f"({n_events}); events did not replay")
    else:
        print(f"    2-loop replayed {len(loop2)} record(s); just_looped tripped")

    rt.close()
    return fails


def _player(data: bytes) -> SSInternalPlayer:
    return SSInternalPlayer(data, lib=_SS_LIB, base_dir="ss_assets/overall",
                            resource_manager=RecordingResourceManager(),
                            pack_reader=filesystem_pack_reader(_OVERALL))


def check_inactive_signal() -> list[str]:
    """A Signal switched off in the editor is not delivered."""
    path = os.path.join(_OVERALL, "Signal.ssab")
    if not os.path.exists(path):
        return ["Signal.ssab: file not found"]
    data = bytearray(open(path, "rb").read())
    anim = events.EventResolver(bytes(data))._anims[0]
    off = None
    total = 0
    for i in range(anim.EventsLength()):
        epf = anim.Events(i)
        for k in range(epf.SignalsLength()):
            value = epf.Signals(k).Value()
            total += 1
            slot = value._tab.Offset(4)      # PartAttributeSignal.active
            if off is None and slot and value.Active():
                off = value.CommandId().decode("utf-8")
                data[value._tab.Pos + slot] = 0
    if off is None or total < 2:
        return [f"Signal.ssab: wants two active signals to switch one off ({total})"]
    p = _player(bytes(data))
    try:
        p.set_animation(None)
        p.set_loop_count(1)
        p.play()
        got = []
        for _ in range(400):
            for fe in p.update(1000.0 / 30).events:
                got.extend(s.command_id for s in fe.signals)
            if p.is_finished():
                break
    finally:
        p.close()
    print(f"  inactive signal: switched off {off!r}, delivered {got}")
    if off in got or len(got) != total - 1:
        return [f"inactive signal: delivered {got} with {off!r} off"]
    return []


def check_landing() -> list[str]:
    """A section change or a source seek reports the frame it lands on as a seek,
    and a host holding the pose can leave that report unheard."""
    path = os.path.join(_OVERALL, "Sound.ssab")
    if not os.path.exists(path):
        return ["Sound.ssab: file not found"]
    data = open(path, "rb").read()
    anim = SsabMeta(data).animations()[0]
    resolver = events.EventResolver(data, anim.name)
    # The last audio key: the head has to move to reach it.
    frame = max(fe.frame_index for fe in map(resolver.resolve,
                                             range(resolver.events_length))
                if fe is not None and fe.audios)
    fails = []
    p = _player(data)
    try:
        p.set_animation(anim.name)
        p.set_animation_section(frame, anim.end_frame)
        plan = p.update(0.0)
        if ([fe.frame_index for fe in plan.events] != [frame]
                or plan.seek_frame != frame):
            fails.append(f"section: reported {plan.events} seek={plan.seek_frame}, "
                         f"want frame {frame} as a seek")
        p.set_animation_section(frame, anim.end_frame)
        p.stop()
        p.discard_landing()
        plan = p.update(0.0)
        if plan.events or plan.seek_frame != -1:
            fails.append(f"held: reported {plan.events} seek={plan.seek_frame}")
        # Playing from there is the head reaching the frame, and it sounds.
        p.play()
        plan = p.update(0.0)
        if [fe.frame_index for fe in plan.events] != [frame] or plan.seek_frame != -1:
            fails.append(f"play: reported {plan.events} seek={plan.seek_frame}")
        p.set_source_frame(p.track_main_source(0), frame)
        plan = p.update(0.0)
        if plan.seek_frame != frame:
            fails.append(f"source seek: seek={plan.seek_frame}, want {frame}")
    finally:
        p.close()
    print(f"  landing: frame {frame} of {anim.name!r}: "
          f"{'PASS' if not fails else 'FAIL'}")
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
    if len(argv) <= 1:
        all_fails.extend(check_inactive_signal())
        all_fails.extend(check_landing())

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
