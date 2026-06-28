# SSCharacter — a living, talking SpriteStudio character in one line.
#
#     define ringo = SSCharacter("ss_assets/Ringo/Ringo.ssab",
#                                talk="talk", idle="wait1")
#     # then just speak — the sprite plays `talk` while the line is typing
#     # and returns to `idle` when it finishes:
#     #     show ringo
#     #     ringo "Hello!"
#
# It registers an `image` for the pack (tag = the .ssab filename stem, lower-
# cased, e.g. "ringo") and returns a Ren'Py `Character` whose callback drives
# lip-flap via the blessed attribute-reshow pattern. No per-line Python.
#
# Runs at init -9 (after spritestudio.rpy at -10 defines SSPlayer, before the
# default `define` pass at 0). Drop this file to remove the helper.

init -9 python:

    def SSCharacter(ssab, talk=None, idle=None, who=None, tag=None,
                    aliases=None, size=None,
                    start=("show_done",), stop=("slow_done", "end"),
                    **char_kwargs):
        """Define a talking SpriteStudio character.

        `ssab`         : gamedir-relative .ssab path.
        `talk` / `idle`: animation names played while speaking / when idle.
        `who`          : display name (default: the .ssab filename stem).
        `tag`          : image tag to register + drive (default: stem, lower-cased).
        `aliases`      : extra attribute->animation aliases for the image
                         (e.g. emotions). Note (v1): an emotion shown via an
                         attribute is replaced by talk/idle while speaking, then
                         returns to `idle` — per-emotion talk is not yet handled.
        `size`         : passed to SSPlayer (a (w, h) box makes xalign work).
        `start`/`stop` : Character callback events that begin / end the talk loop.
        `**char_kwargs`: forwarded to `Character` (e.g. who_color).

        Returns the `Character`. Also registers `image <tag> = SSPlayer(...)`,
        so `show <tag>` / `ring <tag> attr` work as usual.
        """
        stem = ssab.replace("\\", "/").rsplit("/", 1)[-1]
        if stem.endswith(".ssab"):
            stem = stem[:-len(".ssab")]
        tag = tag or stem.lower()
        if who is None:
            who = stem

        al = dict(aliases or {})
        if talk is not None:
            al["talk"] = talk
        if idle is not None:
            al["idle"] = idle

        # Register the displayable as a normal Ren'Py image (idempotent re-define).
        renpy.image(tag, SSPlayer(ssab, aliases=al, size=size))

        has_lipflap = (talk is not None) and (idle is not None)

        def _ss_lipflap(event, interact=True, **kwargs):
            # Only drive the sprite while it is actually on screen; narration or
            # an off-screen speaker leaves it untouched.
            if not interact or not has_lipflap or not renpy.showing(tag):
                return
            if event in start:
                renpy.show(tag, ["talk", "-idle"])
            elif event in stop:
                renpy.show(tag, ["idle", "-talk"])

        return Character(who, image=tag, callback=_ss_lipflap, **char_kwargs)
