# SSCharacter — a living, talking SpriteStudio character in one line.
#
#     define ringo = SSCharacter("ss_assets/Ringo/Ringo.ssab",
#                                talk="talk", idle="wait1")
#     # then just speak — the sprite plays `talk` while the line is typing
#     # and returns to what it was showing before when it finishes:
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
                    start=("show_done",), stop=("end",),
                    **char_kwargs):
        """Define a talking SpriteStudio character.

        `ssab`         : gamedir-relative .ssab path.
        `talk` / `idle`: animation names played while speaking / when idle.
        `who`          : display name (default: the .ssab filename stem).
        `tag`          : image tag to register + drive (default: stem, lower-cased).
        `aliases`      : extra attribute->animation aliases for the image
                         (e.g. emotions). An emotion shown via an attribute is
                         replaced by `talk` while speaking and comes back when
                         the line ends — there is no per-emotion talk.
        `size`         : passed to SSPlayer. Leave it out and the image is the
                         canvas `idle` was authored on, so `at left` / xalign
                         place it like any image.
        `start`/`stop` : Character callback events that begin / end the talk loop.
                         Default: talk from `show_done` until the line is
                         dismissed (`end`), so the talk animation is visible even
                         with instant text. For lip-sync that stops when the text
                         finishes typing, pass `stop=("slow_done", "end")`.
        `**char_kwargs`: forwarded to `Character` (e.g. who_color).

        Returns the `Character`. Also registers `image <tag> = SSPlayer(...)`,
        so `show <tag>` / `show <tag> attr` work as usual.
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
        # Default to the idle animation so `show <tag>` (no attributes) rests idle.
        renpy.image(tag, SSPlayer(ssab, animation=idle, aliases=al, size=size))

        has_lipflap = (talk is not None) and (idle is not None)
        # What the sprite showed when the line began, put back when it ends —
        # forcing `idle` instead would drop the `happy` a creator had shown.
        rest = {"attrs": ()}

        def _ss_lipflap(event, interact=True, **kwargs):
            # Only drive the sprite while it is actually on screen; narration or
            # an off-screen speaker leaves it untouched.
            if not interact or not has_lipflap or not renpy.showing(tag):
                return
            # Attributes go in the NAME (renpy.show's 2nd arg is at_list, not
            # attributes); the leading tag + space-separated attrs, "-x" removes.
            if event in start:
                rest["attrs"] = tuple(a for a in (renpy.get_attributes(tag) or ())
                                      if a != "talk")
                renpy.show(tag + " talk -idle")
            elif event in stop:
                # A bare `show <tag>` has no attribute to put back; it rests idle.
                back = rest["attrs"] or ("idle",)
                renpy.show(" ".join((tag,) + back + ("-talk",)))

        return Character(who, image=tag, callback=_ss_lipflap, **char_kwargs)
