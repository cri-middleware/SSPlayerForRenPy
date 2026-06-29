"""Generate ready-to-paste Ren'Py snippets for an SSPlayer pack (no renpy import).

The dev-mode asset browser (``ss_browser.rpy``) turns a chosen pack + role into
copy-pasteable code with these. Pure CPython, so the snippet shapes are unit-
testable headlessly (``tools/verify_snippet.py``).
"""

from __future__ import annotations

ROLES = ("character", "effect", "ui")


def default_role(num_anims: int, has_effects: bool) -> str:
    """Heuristic *starting* role for a pack (the human can override in the UI).

    A pack with effect parts and a single animation is most likely a one-shot
    effect; a multi-animation pack is most likely a character; anything else
    defaults to a plain UI add.
    """
    if has_effects and num_anims <= 1:
        return "effect"
    if num_anims >= 2:
        return "character"
    return "ui"


def build_snippet(ssab_path: str, role: str, anims) -> str:
    """A ready-to-paste ``.rpy`` snippet using ``ssab_path`` as the given ``role``.

    ``ssab_path`` is the gamedir-relative ``.ssab`` path passed to ``SSPlayer()``
    (e.g. ``"ss_assets/Ringo/Ringo.ssab"``); the image / screen identifier is
    derived from its filename stem. ``character`` -> an ``image`` with an aliases
    skeleton + a ``Character``; ``effect`` -> a one-shot ``image`` (loop=1);
    ``ui`` -> a screen that adds it. ``anims`` seeds the first animation / the
    aliases (each mapped to itself, as a starting point to rename).
    """
    anims = list(anims)
    a0 = anims[0] if anims else "anime_1"
    stem = ssab_path.replace("\\", "/").rsplit("/", 1)[-1]
    if stem.endswith(".ssab"):
        stem = stem[:-len(".ssab")]
    low = stem.lower()
    if role == "effect":
        return ('image %s = SSPlayer("%s", animation="%s", loop=1)\n'
                '# show %s:\n#     xalign 0.5 yalign 0.5'
                % (low, ssab_path, a0, low))
    if role == "ui":
        return ('screen %s_screen():\n    add SSPlayer("%s") xalign 0.5 yalign 0.5'
                % (low, ssab_path))
    # character (default)
    al = "\n".join('        "%s": "%s",' % (a, a) for a in anims[:8])
    return ('image %s = SSPlayer(\n    "%s",\n    aliases={\n%s\n    },\n)\n'
            'define %s_chr = Character("%s", image="%s")'
            % (low, ssab_path, al, low, stem, low))
