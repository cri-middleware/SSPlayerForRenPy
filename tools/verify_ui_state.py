#!/usr/bin/env python3
"""Headless check for the button state rule in ``ss_renpy.ui_state``.

Which state wins, which section each state plays, where a state without a
label falls back to, how a clip stands in for a label, how a selected button
reads the selected labels first, and what reduced motion holds. The label tables are written out here, since no example pack names its
labels after the states.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_ui_state.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ui_state  # noqa: E402
from ss_renpy.ssab_meta import LabelInfo, LabelTable  # noqa: E402

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    print(f"    {'PASS' if good else 'FAIL'}  {label}: {got!r}"
          + ("" if good else f" (want {want!r})"))
    _ok = _ok and good


def _table(end, labels):
    return LabelTable(
        labels=tuple(sorted((LabelInfo(n, f) for n, f in labels.items()),
                            key=lambda l: l.frame)),
        start_frame=0, end_frame=end)


TABLES = {
    "button": _table(99, {"normal": 0, "hover": 20, "pressed": 40,
                          "disabled": 60, "reduced_motion": 80}),
    "only_normal": _table(49, {"normal": 10, "other": 30}),
    "with_hover": _table(49, {"normal": 0, "hover": 25}),
    "plain": _table(29, {}),
    "glow": _table(39, {"calm": 5}),
    "caps": _table(9, {"Normal": 0, "HOVER": 5}),
    "toggle": _table(119, {"normal": 0, "hover": 20, "selected_normal": 40,
                           "selected_hover": 60, "disabled": 80,
                           "reduced_motion": 100}),
    "on_only": _table(59, {"normal": 0, "hover": 20, "selected_normal": 40}),
}


def resolve(state, animation, clips=None, reduced=False, missing=None,
            selected=False):
    s = ui_state.resolve(
        state, animation, TABLES.get, clips=clips, reduced_motion=reduced,
        on_missing_clip=(lambda st, clip: missing.append((st, clip)))
        if missing is not None else None, selected=selected)
    return s and (s.animation, s.start_frame, s.end_frame, s.hold)


def main() -> int:
    print("== button state rule verification ==\n")

    print("### one state wins: disabled, pressed, hover, focused, normal")
    check("all", ui_state.state_of(True, True, True, True), "disabled")
    check("pressed", ui_state.state_of(pressed=True, hovered=True, focused=True), "pressed")
    check("hover", ui_state.state_of(hovered=True, focused=True), "hover")
    check("focused", ui_state.state_of(focused=True), "focused")
    check("none", ui_state.state_of(), "normal")

    print("### each state runs from its label to the frame before the next")
    check("normal", resolve("normal", "button"), ("button", 0, 19, False))
    check("hover", resolve("hover", "button"), ("button", 20, 39, False))
    check("pressed", resolve("pressed", "button"), ("button", 40, 59, False))
    check("disabled", resolve("disabled", "button"), ("button", 60, 79, False))
    check("the last label runs to the end", resolve("hover", "with_hover"),
          ("with_hover", 25, 49, False))
    check("to the next label of any name", resolve("normal", "only_normal"),
          ("only_normal", 10, 29, False))

    print("### a state without a label falls back")
    for s in ("hover", "focused", "disabled", "pressed"):
        check(f"{s} to normal", resolve(s, "only_normal"), ("only_normal", 10, 29, False))
    check("pressed to hover", resolve("pressed", "with_hover"), ("with_hover", 25, 49, False))
    check("focused to normal", resolve("focused", "button"), ("button", 0, 19, False))
    check("no normal either: the whole animation", resolve("hover", "plain"),
          ("plain", 0, 29, False))
    check("labels match exactly", resolve("hover", "caps"), ("caps", 0, 9, False))

    print("### clips")
    clips = {"hover": "glow", "disabled": {"label": "reduced_motion"},
             "focused": {"animation": "glow", "label": "calm"}}
    check("an animation's whole", resolve("hover", "only_normal", clips), ("glow", 0, 39, False))
    check("and the states falling back to it", resolve("pressed", "only_normal", clips),
          ("glow", 0, 39, False))
    check("a label of the same animation", resolve("disabled", "button", clips),
          ("button", 80, 99, False))
    check("a label of another animation", resolve("focused", "button", clips),
          ("glow", 5, 39, False))
    missing = []
    check("an animation the pack lacks plays the label",
          resolve("hover", "button", {"hover": "nope"}, missing=missing),
          ("button", 20, 39, False))
    check("and is reported", missing, [("hover", "nope")])
    missing = []
    check("a label the pack lacks plays the label",
          resolve("hover", "button", {"hover": {"label": "nope"}}, missing=missing),
          ("button", 20, 39, False))
    check("and is reported", missing, [("hover", {"label": "nope"})])
    check("no section for an animation the pack lacks", resolve("normal", "nope"), None)

    print("### reduced motion")
    check("hover is held", resolve("hover", "button", reduced=True), ("button", 20, 39, True))
    check("disabled is held", resolve("disabled", "button", reduced=True), ("button", 60, 79, True))
    check("normal plays reduced_motion", resolve("normal", "button", reduced=True),
          ("button", 80, 99, False))
    check("so does a state falling back to normal",
          resolve("focused", "button", reduced=True), ("button", 80, 99, False))
    check("normal is held without reduced_motion",
          resolve("normal", "only_normal", reduced=True), ("only_normal", 10, 29, True))
    check("the whole animation is held", resolve("normal", "plain", reduced=True),
          ("plain", 0, 29, True))

    print("### selected")
    check("the chain: selected first, then plain", ui_state.chain("hover", True),
          ("selected_hover", "selected_normal", "hover", "normal"))
    check("normal", resolve("normal", "toggle", selected=True), ("toggle", 40, 59, False))
    check("hover", resolve("hover", "toggle", selected=True), ("toggle", 60, 79, False))
    check("pressed falls to selected_hover",
          resolve("pressed", "toggle", selected=True), ("toggle", 60, 79, False))
    check("disabled keeps on over disabled",
          resolve("disabled", "toggle", selected=True), ("toggle", 40, 59, False))
    check("hover keeps on over hover", resolve("hover", "on_only", selected=True),
          ("on_only", 40, 59, False))
    check("no selected labels: as unselected", resolve("hover", "button", selected=True),
          ("button", 20, 39, False))
    check("unselected ignores the selected labels", resolve("normal", "toggle"),
          ("toggle", 0, 19, False))
    check("a clip under a selected name",
          resolve("hover", "only_normal", {"selected_normal": "glow"}, selected=True),
          ("glow", 0, 39, False))
    check("which unselected states do not take", resolve("hover", "only_normal",
                                                           {"selected_normal": "glow"}),
          ("only_normal", 10, 29, False))
    missing = []
    check("a selected clip the pack lacks plays the label",
          resolve("hover", "toggle", {"selected_hover": "nope"}, missing=missing,
                  selected=True), ("toggle", 60, 79, False))
    check("and is reported under its name", missing, [("selected_hover", "nope")])
    check("reduced motion holds selected normal",
          resolve("normal", "toggle", reduced=True, selected=True), ("toggle", 40, 59, True))
    check("but plays reduced_motion where nothing is selected-labelled",
          resolve("normal", "button", reduced=True, selected=True),
          ("button", 80, 99, False))

    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
