"""Which section of an animation a button state plays, without Ren'Py.

A state is one of ``normal`` / ``hover`` / ``pressed`` / ``disabled`` /
``focused``. By default each plays from the label of its own name in one
animation, up to the frame before the next label (any label, the state names
or not), looping. A state the animation has no label for falls back --
``pressed`` to ``hover``, the rest to ``normal``, and ``normal`` to the whole
animation -- and a clip can stand in for a state's label. A selected button
(a toggle that is on) reads the same labels with ``selected_`` in front first,
and the plain ones after, so on and off stay apart when a label is missing --
except that a press, which lasts only while the button is held down, takes
``pressed`` right after ``selected_pressed``.
Under reduced motion the section is held on its first frame, except that an
unselected ``normal`` plays the ``reduced_motion`` label's section when the
animation has one.

``ss_ui.rpy`` (``SSButton``) maps a Ren'Py button onto a state and plays what
this returns; everything here reads label tables only, so the headless suite
covers every branch.
"""

from __future__ import annotations

from dataclasses import dataclass

STATES = ("normal", "hover", "pressed", "disabled", "focused")

REDUCED_MOTION_LABEL = "reduced_motion"

# The state, then the states it falls back to.
_CHAINS = {
    "normal": ("normal",),
    "hover": ("hover", "normal"),
    "pressed": ("pressed", "hover", "normal"),
    "disabled": ("disabled", "normal"),
    "focused": ("focused", "normal"),
}


@dataclass(frozen=True)
class UiSection:
    """What a state plays: ``start_frame`` .. ``end_frame`` of ``animation``,
    looping, or held on ``start_frame`` when ``hold``."""
    animation: str
    start_frame: int
    end_frame: int
    hold: bool


def state_of(disabled: bool = False, pressed: bool = False,
             hovered: bool = False, focused: bool = False) -> str:
    """The one state to show when several hold at once."""
    if disabled:
        return "disabled"
    if pressed:
        return "pressed"
    if hovered:
        return "hover"
    if focused:
        return "focused"
    return "normal"


def label_section(table, label: str):
    """``(start, end)``: from ``label``'s frame in ``table`` (a
    :class:`~ss_renpy.ssab_meta.LabelTable`) to the frame before the next
    label, or to the end of the animation; ``None`` without the label."""
    start = table.frame_of(label)
    if start is None:
        return None
    for l in table.labels:
        if l.frame > start:
            return (start, l.frame - 1)
    return (start, table.end_frame)


def clip_parts(clip):
    """``(animation, label)`` of a clip: an animation name, or a dict with an
    ``"animation"``, a ``"label"`` or both. Either may be ``None``: no
    animation is the one the states are read from, no label its whole."""
    if isinstance(clip, dict):
        return clip.get("animation"), clip.get("label")
    return clip, None


def chain(state: str, selected: bool = False) -> tuple:
    """The labels ``state`` looks up, in order: its own, then those it falls
    back to, each with ``selected_`` in front first when ``selected`` --
    ``pressed`` excepted, which comes right after ``selected_pressed``."""
    plain = _CHAINS.get(state, _CHAINS["normal"])
    if not selected:
        return plain
    names = tuple("selected_" + s for s in plain) + plain
    head = ("selected_pressed", "pressed") if state == "pressed" else ()
    return head + tuple(n for n in names if n not in head)


def resolve(state: str, animation: str, table_of, clips=None,
            reduced_motion: bool = False, on_missing_clip=None,
            selected: bool = False):
    """The :class:`UiSection` ``state`` plays, its labels read from
    ``animation``: the first name of its :func:`chain` with a clip in
    ``clips`` or a label of its own, or else the whole animation. ``None``
    when ``table_of(animation)`` is ``None``.

    ``table_of(name)`` returns an animation's label table, or ``None`` for one
    the pack lacks. A clip naming an animation or a label the pack lacks goes
    to ``on_missing_clip(state, clip)``, and the state goes on as if it had
    none.
    """
    base = table_of(animation)
    if base is None:
        return None
    clips = clips or {}
    name = animation
    section = None
    source = None
    for s in chain(state, selected):
        clip = clips.get(s)
        if clip is not None:
            clip_anim, clip_label = clip_parts(clip)
            clip_name = clip_anim or animation
            table = base if clip_name == animation else table_of(clip_name)
            if table is None:
                section = None
            elif clip_label is None:
                section = (table.start_frame, table.end_frame)
            else:
                section = label_section(table, clip_label)
            if section is not None:
                name = clip_name
                source = s
                break
            if on_missing_clip is not None:
                on_missing_clip(s, clip)
        section = label_section(base, s)
        if section is not None:
            source = s
            break
    if section is None:
        section = (base.start_frame, base.end_frame)
    if reduced_motion and source == "normal":
        calm = label_section(base, REDUCED_MOTION_LABEL)
        if calm is not None:
            return UiSection(animation, calm[0], calm[1], False)
    return UiSection(name, section[0], section[1], bool(reduced_motion))
