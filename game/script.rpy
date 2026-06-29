# SpriteStudio Player for Ren'Py — demo entry point (shared bits).
#
# This file holds only what the whole demo shares: the bare dialogue window, the
# ss_escape text helper, and the start menu. Each menu choice jumps to a scene
# that lives in its own file (Ren'Py loads every .rpy under game/, so labels,
# images and screens may live anywhere):
#   - scene_ringo.rpy   — ringo_demo (image attributes / Character image=)
#   - scene_helper.rpy  — ringo_helper_demo (SSCharacter / attachments / helpers)
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

init python:
    def ss_escape(s):
        # Event payloads (a signal's params dict repr, user strings) can contain
        # "{" / "[", which Ren'Py text would parse as a tag / substitution
        # ("Unknown text tag ..."). Escape them for safe display. Shared by the
        # event log (scene_viewer.rpy) and the asset picker (asset_picker.rpy).
        return str(s).replace("{", "{{").replace("[", "[[")

label start:
    "Please select your language. / 言語を選択してください。"
    menu:
        "English":
            $ renpy.change_language(None)
        "日本語":
            $ renpy.change_language("japanese")

    menu:
        "Watch Ringo's Image Attribute Demo":
            jump ringo_demo
        "Watch Helper Showcase (SSCharacter / effects / attachment)":
            jump ringo_helper_demo
        "Watch Mask / Clipping-Mask Sample":
            jump mask_demo
        "Browse Imported Assets (auto-discovered)":
            jump asset_picker_demo
        "Watch Basic Feature Viewer (Legacy Demo)":
            jump viewer_demo
