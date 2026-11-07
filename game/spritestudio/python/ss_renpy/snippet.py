"""Generate ready-to-paste Ren'Py snippets for an SSPlayer pack (no renpy import).

The dev-mode asset browser (``ss_browser.rpy``) turns a chosen pack + role into
copy-pasteable code with these. Pure CPython, so the snippet shapes are unit-
testable headlessly (``tools/verify_snippet.py``).
"""

from __future__ import annotations

import re

ROLES = ("character", "oneshot", "ui")

# What a show statement can spell in an image tag.
_UNSPELLABLE = re.compile("[^-0-9a-z_ -�]")


def image_tag(stem: str) -> str:
    """The image tag of a pack: its file name, lower-cased, with what a show
    statement cannot spell (a space, a bracket) turned into ``_``."""
    return _UNSPELLABLE.sub("_", stem.lower())


def _identifier(tag: str) -> str:
    """``tag`` as a Python name, for a ``define`` or a ``screen``: a hyphen can
    be spelled in a tag and not there, and neither can start with a digit."""
    name = re.sub(r"\W", "_", tag)
    return "ss_" + name if name[:1].isdigit() else name


def display_name(stem: str) -> str:
    """``stem`` as text for a ``Character``, where Ren'Py reads ``[`` as a
    substitution and ``{`` as a tag."""
    return stem.replace("[", "[[").replace("{", "{{")


def default_role(num_anims: int, has_effects: bool) -> str:
    """Heuristic *starting* role for a pack (the human can override in the UI).

    A pack with effect parts and a single animation is most likely a one-shot
    play (a hit spark, a stinger, any fire-and-forget clip); a multi-animation
    pack is most likely a character; anything else defaults to a plain UI add.
    """
    if has_effects and num_anims <= 1:
        return "oneshot"
    if num_anims >= 2:
        return "character"
    return "ui"


def build_snippet(ssab_path: str, role: str, anims) -> str:
    """A ready-to-paste ``.rpy`` snippet using ``ssab_path`` as the given ``role``.

    ``ssab_path`` is the gamedir-relative ``.ssab`` path passed to ``SSPlayer()``
    (e.g. ``"ss_assets/Ringo/Ringo.ssab"``); the image / screen identifier is
    derived from its filename stem. ``character`` -> an ``image`` with an aliases
    skeleton + a ``Character``; ``oneshot`` -> a one-shot ``image`` (loop=1);
    ``ui`` -> a screen that adds it. ``anims`` seeds the first animation / the
    aliases (each mapped to itself, as a starting point to rename).
    """
    anims = list(anims)
    a0 = anims[0] if anims else "anime_1"
    stem = ssab_path.replace("\\", "/").rsplit("/", 1)[-1]
    if stem.endswith(".ssab"):
        stem = stem[:-len(".ssab")]
    tag = image_tag(stem)
    name = _identifier(tag)
    if role == "oneshot":
        return ('image %s = SSPlayer("%s", animation="%s", loop=1)\n'
                '# show %s:\n#     xalign 0.5 yalign 0.5'
                % (tag, ssab_path, a0, tag))
    if role == "ui":
        return ('screen %s_screen():\n    add SSPlayer("%s") xalign 0.5 yalign 0.5'
                % (name, ssab_path))
    # character (default)
    al = "\n".join('        "%s": "%s",' % (a, a) for a in anims[:8])
    return ('image %s = SSPlayer(\n    "%s",\n    aliases={\n%s\n    },\n)\n'
            'define %s_chr = Character("%s", image="%s")'
            % (tag, ssab_path, al, name, display_name(stem), tag))
