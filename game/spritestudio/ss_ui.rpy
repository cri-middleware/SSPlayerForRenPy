# SSButton — a SpriteStudio animation as a Ren'Py button.
#
#     screen title_menu():
#         add SSButton("ss_assets/ui/start.ssab", action=Start(),
#                      parts=["face"], alt=_("Start"))
#
# Idle, hover and insensitive play the labels named normal, hover and disabled
# in one animation, selected_normal and so on while the button is selected;
# `parts` keeps the mouse to those parts' outlines; and `reduced_motion` holds
# each state still. The state rule is
# ss_renpy.ui_state. Runs at init -9 (after spritestudio.rpy at -10 defines
# SSPlayer). Drop this file to remove it.

init -9 python:

    from ss_renpy import ui_state as _ss_ui_state

    class _SSHitMask(object):
        """An SSButton's focus_mask when it is given `parts`."""

        def __init__(self, button):
            self.button = button

        def __call__(self, x, y):
            return self.button._hits(x, y)

    class SSButton(renpy.display.behavior.Button):
        """A button drawn by an `SSPlayer`, whose states are its animation.

        `player` is an `SSPlayer`, or a .ssab path to make one from. The button
        takes its playback over -- the animation, the section, the loop count,
        playing and stopping -- so do not drive the same player elsewhere.

        Idle plays the `normal` label's section of `animation` (the player's
        current animation when omitted), hover the `hover` label's, and
        insensitive the `disabled` label's, each up to the frame before the
        next label and looping. A selected button plays the same labels with
        `selected_` in front (`selected_normal`, `selected_hover`, ...),
        falling back to the plain ones only after every selected one. `clips`
        replaces a state's label, under the same names, by an animation's
        name, or by a dict with an "animation" and / or a "label".
        `reduced_motion` holds each state on its first frame, except that an
        unselected idle plays the `reduced_motion` label's section where there
        is one.

        `parts` (names or indices) keeps the mouse to those parts' outlines,
        where by default the whole box takes it; the keyboard is not kept.
        `focus_mask=True` keeps it to the drawn pixels instead. Every other
        keyword is the Button's: `action`, `alt`, `hovered`, `style` (by
        default "image_button", which has no background or padding), and so
        on."""

        def __init__(self, player, parts=None, animation=None, clips=None,
                     reduced_motion=False, style="image_button", **properties):
            if isinstance(parts, str):
                parts = [parts]
            parts = None if parts is None else tuple(parts)
            self._spec = (player, parts, animation, clips, bool(reduced_motion),
                          style, dict(properties))
            if not isinstance(player, SSPlayer):
                player = SSPlayer(player, animation=animation)
            if parts is not None:
                properties["focus_mask"] = _SSHitMask(self)
            super(SSButton, self).__init__(player, style=style, **properties)
            self.player = player
            self.parts = parts
            self.animation = animation
            self.clips = dict(clips) if clips else {}
            self.reduced_motion = bool(reduced_motion)
            self._base = None
            self._shown = None

        # A screen builds the button again at every interaction and keeps
        # the one it has when the new one is equal, so the state shown does
        # not start over at every line of dialogue.
        def __eq__(self, o):
            return type(o) is type(self) and self._spec == o._spec

        __hash__ = object.__hash__

        def render(self, width, height, st, at):
            rv = super(SSButton, self).render(width, height, st, at)
            # After the player's own render, which starts the player over when
            # it is shown afresh; this frame is then drawn again.
            if self._show():
                renpy.display.render.invalidate(self.player)
                rv = super(SSButton, self).render(width, height, st, at)
            return rv

        def _state(self):
            """``(state, selected)`` from the button's style prefix."""
            prefix = self.style.prefix
            selected = prefix.startswith("selected_")
            if selected:
                prefix = prefix[len("selected_"):]
            return (_ss_ui_state.state_of(disabled=prefix == "insensitive_",
                                          hovered=prefix == "hover_"),
                    selected)

        @staticmethod
        def _playback(p):
            return (p.ss_get_current_animation(), p.ss_start_frame(),
                    p.ss_end_frame(), p.ss_is_playing())

        def _show(self):
            """Play the section of the state shown, unless the player already
            plays it. True when it changed what the player plays."""
            p = self.player
            key = self._state() + (self.reduced_motion,)
            if self._shown == (key, self._playback(p)):
                return False
            names = p.ss_animation_names()
            base = self._base if self._base in names else (
                self.animation or p.ss_get_current_animation()
                or (names[0] if names else None))
            if base not in names:
                p._warn_once(("ss_button", base),
                             "SSButton: %s has no animation %r to read the "
                             "states from" % (p.ssab, base))
                self._shown = (key, self._playback(p))
                return False
            self._base = base
            section = _ss_ui_state.resolve(
                key[0], base, p.ss_label_table, self.clips, key[2],
                self._missing_clip, selected=key[1])
            p.ss_set_animation(section.animation)
            p.ss_set_animation_section(section.start_frame, section.end_frame)
            if section.hold:
                p.ss_stop()
            else:
                p.ss_set_loop_count(-1)
                p.ss_play()
            self._shown = (key, self._playback(p))
            return True

        def _missing_clip(self, state, clip):
            p = self.player
            p._warn_once(("ss_button_clip", state, repr(clip)),
                         "SSButton: the clip for %s, %r, names what %s lacks, "
                         "so %s plays as if it had none"
                         % (state, clip, p.ssab, state))

        def _hits(self, x, y):
            # (x, y) is from the button's top left; the player sits where the
            # button placed it, and its animation's origin where its render put
            # it.
            p = self.player
            bx, by = self.offsets[0] if self.offsets else (0, 0)
            ox, oy = getattr(p, "_draw_origin", (0.0, 0.0))
            return p.ss_hit_test_part(x - bx - ox, y - by - oy, self.parts) >= 0
