#!/usr/bin/env python3
"""Headless check for label tables and playback sections named by labels.

The pack keeps an animation's labels sorted by name hash, so `label_table`
re-sorts them by frame -- checked on a pack built here with its labels stored
out of frame order and one real label named `_end`. `label_section` is checked
on `Signal` (labels `Start` at 10 and `End` at 20): the frames it resolves,
the offsets, `_start` / `_end`, a missing label, and a backward pair the
section setter refuses.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_labels.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

import flatbuffers  # noqa: E402
from ss.format import AnimationData, Label, SsAnimeBinary  # noqa: E402
from ss_renpy import ssruntime  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402
from ss_renpy.ssab_meta import LabelInfo, SsabMeta  # noqa: E402

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    print(f"    {'PASS' if good else 'FAIL'}  {label}: {got!r}"
          + ("" if good else f" (want {want!r})"))
    _ok = _ok and good


def _pack(animations) -> bytes:
    """A pack of ``(name, start, end, [(label, frame), ...])`` animations,
    holding nothing else, with each label vector stored in the order given."""
    b = flatbuffers.Builder(512)
    anims = []
    for name, start, end, labels in animations:
        offs = []
        for lname, frame in labels:
            n = b.CreateString(lname)
            Label.LabelStart(b)
            Label.LabelAddName(b, n)
            Label.LabelAddTime(b, frame)
            offs.append(Label.LabelEnd(b))
        AnimationData.AnimationDataStartLabelsVector(b, len(offs))
        for o in reversed(offs):
            b.PrependUOffsetTRelative(o)
        vec = b.EndVector()
        n = b.CreateString(name)
        AnimationData.AnimationDataStart(b)
        AnimationData.AnimationDataAddName(b, n)
        AnimationData.AnimationDataAddLabels(b, vec)
        AnimationData.AnimationDataAddStartFrame(b, start)
        AnimationData.AnimationDataAddEndFrame(b, end)
        anims.append(AnimationData.AnimationDataEnd(b))
    SsAnimeBinary.SsAnimeBinaryStartAnimationsVector(b, len(anims))
    for a in reversed(anims):
        b.PrependUOffsetTRelative(a)
    vec = b.EndVector()
    SsAnimeBinary.SsAnimeBinaryStart(b)
    SsAnimeBinary.SsAnimeBinaryAddAnimations(b, vec)
    b.Finish(SsAnimeBinary.SsAnimeBinaryEnd(b), b"SSAB")
    return bytes(b.Output())


def check_table() -> None:
    print("### label_table  frame order, _start / _end")
    meta = SsabMeta(_pack([
        ("first", 0, 30, [("hover", 20), ("_end", 25), ("normal", 5)]),
        ("second", 3, 9, []),
    ]))
    table = meta.label_table("first")
    check("re-sorted by frame", table.labels,
          (LabelInfo("normal", 5), LabelInfo("hover", 20), LabelInfo("_end", 25)))
    check("no name is the first animation", meta.label_table(), table)
    check("a label's frame", table.frame_of("hover"), 20)
    check("_start is the animation's first frame", table.frame_of("_start"), 0)
    check("a real _end wins over the last frame", table.frame_of("_end"), 25)
    check("an unknown label", table.frame_of("pressed"), None)
    second = meta.label_table("second")
    check("no labels", second.labels, ())
    check("_start / _end of an animation not starting at 0",
          (second.frame_of("_start"), second.frame_of("_end")), (3, 9))
    check("an unknown animation", meta.label_table("no-such-anim"), None)


def check_section(lib) -> None:
    print("### label_section  Signal: Start=10, End=20")
    path = os.path.join(_GAME, "ss_assets", "overall", "Signal.ssab")
    if not os.path.exists(path):
        print(f"SKIP: {path} not found (run scripts/deploy-examples.* first)")
        return
    with open(path, "rb") as f:
        data = f.read()
    p = SSInternalPlayer(data, lib=lib, base_dir="ss_assets/overall",
                         resource_manager=RecordingResourceManager(),
                         pack_reader=filesystem_pack_reader(os.path.dirname(path)))
    try:
        check("no table before an animation is set up", p.label_table(), None)
        check("a named animation before one is set up",
              [l.name for l in p.label_table("anime_1").labels], ["Start", "End"])
        p.set_animation("anime_1")
        check("the labels' frames", p.label_section("Start", "End"), (10, 20))
        check("offsets", p.label_section("Start", "End", 1, -1), (11, 19))
        check("_start / _end", p.label_section("_start", "_end"), (0, 30))
        check("a missing label", p.label_section("Start", "normal"), None)
        p.set_animation_section(*p.label_section("Start", "End"))
        check("the section the frames make", (p.start_frame, p.end_frame), (10, 20))
        check("a backward pair is refused",
              p.set_animation_section(*p.label_section("End", "Start")), False)
        check("and leaves the section", (p.start_frame, p.end_frame), (10, 20))
    finally:
        p.close()


def main() -> int:
    print("== label table / label section verification ==\n")
    check_table()
    check_section(ssruntime.load_library())
    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
