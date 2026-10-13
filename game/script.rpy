# SpriteStudio Player for Ren'Py — demo entry point (shared bits).
#
# This file holds only what the whole demo shares: the bare dialogue window, the
# ss_stand transform, the ss_escape text helper, and the start menu. Each menu
# choice jumps to a scene that lives in its own file (Ren'Py loads every .rpy
# under game/, so labels, images and screens may live anywhere):
#   - scene_ringo.rpy   — ringo_demo (image attributes / Character image=)
#   - scene_helper.rpy  — ringo_helper_demo (SSCharacter / attachments / helpers)
#   - scene_part_follow.rpy — part_follow_demo (ss_attach / part tracking + skinned-mesh check)
#   - scene_blend.rpy   — blend_demo (crossfade / layering through the track stack)
#   - scene_mask.rpy    — mask_demo (mask / clipping-mask sample)
#   - scene_viewer.rpy  — viewer_demo + screen ss_demo (legacy pack cycler)
#   - asset_picker.rpy  — asset_picker_demo (auto-discovered .ssab browser)

style default:
    font "SourceHanSansLite.ttf"
style text:
    font "SourceHanSansLite.ttf"

# Minimal say screen for the demo (no screens.rpy here, so we define a bare dialogue window).
screen say(who, what):
    frame:
        id "window"
        background Solid("#000000c0")
        xfill True
        yalign 1.0
        yminimum 200
        padding (40, 40)

        vbox:
            spacing 10
            if who is not None:
                text who:
                    id "who"
                    color "#ffcc00"
                    size 28

            text what:
                id "what"
                size 28

# Where the demo's characters stand. A SpriteStudio character is authored
# standing on its canvas's bottom edge, and without a `size` the canvas is the
# SSPlayer's box — so, anchored at its bottom centre like any image, ypos is
# where the feet go. 560 sets them just inside the top of the dialogue window.
transform ss_stand(x=0.5):
    xpos x xanchor 0.5 ypos 560 yanchor 1.0

init python:
    def ss_escape(s):
        # Event payloads (a signal's params dict repr, user strings) can contain
        # "{" / "[", which Ren'Py text would parse as a tag / substitution
        # ("Unknown text tag ..."). Escape them for safe display. Shared by the
        # event log (scene_viewer.rpy) and the asset picker (asset_picker.rpy).
        return str(s).replace("{", "{{").replace("[", "[[")

label start:
    # Language picker + main menu are both custom screens (instead of `menu`s) so
    # they share the same centered, styled look. The language picker returns
    # "en"/"ja" (we set the language here, between interactions — the safe place);
    # the main menu returns the target label name.
    call screen ss_language_menu
    $ renpy.change_language("japanese" if _return == "ja" else None)

    call screen ss_main_menu
    jump expression _return

# Language picker — same centered/styled frame as ss_main_menu. The prompt is
# bilingual in the source (the language isn't chosen yet); each button sets the
# language and returns. "English" / "日本語" are language names, not translated.
screen ss_language_menu():
    add Solid("#1c2026")

    frame:
        xalign 0.5
        yalign 0.5
        padding (44, 32)
        background Solid("#00000088")

        vbox:
            spacing 6
            xsize 760

            text "Select language / 言語を選択" size 18 color "#7fd0ff"
            textbutton "English":
                action Return("en")
                text_size 24
            textbutton "日本語":
                action Return("ja")
                text_size 24


# Main menu, grouped into "for users" (the SSPlayer usage samples) and "for
# developers" (the inspection / viewer tools). Each button returns its target
# label; `label start` jumps there. Strings are translatable (_()), so the JA
# translations in tl/japanese/script.rpy apply.
screen ss_main_menu():
    add Solid("#1c2026")

    frame:
        xalign 0.5
        yalign 0.5
        padding (44, 32)
        background Solid("#00000088")

        vbox:
            spacing 6
            xsize 760

            text _("SSPlayer usage — for users") size 18 color "#7fd0ff"
            textbutton _("Ringo display sample using SSPlayer"):
                action Return("ringo_demo")
                text_size 24
            textbutton _("SSPlayer helper functions sample"):
                action Return("ringo_helper_demo")
                text_size 24
            textbutton _("Part tracking (attach) sample"):
                action Return("part_follow_demo")
                text_size 24
            textbutton _("Animation blending (crossfade / layering) sample"):
                action Return("blend_demo")
                text_size 24

            null height 20

            text _("For developers") size 18 color "#7fd0ff"
            textbutton _("Basic Feature Viewer"):
                action Return("viewer_demo")
                text_size 24
            textbutton _("Browse Imported Assets (auto-discovered)"):
                action Return("asset_picker_demo")
                text_size 24
