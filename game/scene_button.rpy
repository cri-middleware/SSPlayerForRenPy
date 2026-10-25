# Button sample — Ringo as Ren'Py buttons, through SSButton
# (spritestudio/ss_ui.rpy). Ringo has no labels named after the states, so
# `clips` gives each state an animation: idle plays wait1, hover joy and
# insensitive sitdown_wait. The four buttons differ only in where the mouse
# counts:
#
#   1. the whole box (the default);
#   2. the drawn pixels (focus_mask=True);
#   3. the apple (parts=["apple"]);
#   4. the head and the body (parts=["head", "body"]).
#
# The keyboard reaches every one of them. The controls below make the buttons
# insensitive, and hold them still (reduced motion).
#
# (Reached from the start menu in script.rpy. Uses only the deployed Ringo pack.)

default ss_ui_players = None
default ss_ui_reduced = False
default ss_ui_sensitive = True
default ss_ui_pressed = None

init python:
    SS_UI_SRC = "ss_assets/Ringo/Ringo.ssab"
    SS_UI_CLIPS = {"normal": "wait1", "hover": "joy", "disabled": "sitdown_wait"}
    SS_UI_BUTTONS = [
        (_("Whole box"), {}),
        (_("Drawn pixels"), {"focus_mask": True}),
        (_("Apple"), {"parts": ["apple"]}),
        (_("Head and body"), {"parts": ["head", "body"]}),
    ]

    def ss_ui_build():
        store.ss_ui_players = [SSPlayer(SS_UI_SRC, animation="wait1")
                               for _b in SS_UI_BUTTONS]
        store.ss_ui_reduced = False
        store.ss_ui_sensitive = True
        store.ss_ui_pressed = None

transform ss_ui_zoom:
    zoom 0.36


label button_demo:
    $ ss_ui_build()
    call screen ss_ui_buttons
    $ ss_ui_players = None
    return


screen ss_ui_buttons():
    modal True
    zorder 100
    key "K_ESCAPE" action Return()

    add Solid("#1c2026")

    frame:
        xfill True
        yalign 0.0
        background "#00000099"
        padding (24, 12)
        vbox:
            spacing 4
            text _("Buttons — Ringo as Ren'Py buttons (SSButton)") size 24 color "#ffffff"
            text _("Idle plays wait1, hover joy and insensitive sitdown_wait. Each button takes the mouse on a different area; the keyboard reaches all four.") size 13 color "#9aa0ab"

    hbox:
        xalign 0.5
        yalign 0.45
        spacing 16
        for _i, (_caption, _kw) in enumerate(SS_UI_BUTTONS):
            vbox:
                spacing 8
                frame:
                    padding (0, 0)
                    background Solid("#101216")
                    add SSButton(ss_ui_players[_i], clips=SS_UI_CLIPS,
                                 reduced_motion=ss_ui_reduced,
                                 sensitive=ss_ui_sensitive,
                                 action=SetVariable("ss_ui_pressed", _i),
                                 alt=__(_caption), **_kw) at ss_ui_zoom
                text __(_caption) size 16 color "#cfd3da" xalign 0.5

    if ss_ui_pressed is not None:
        text (__("Pressed: %s") % __(SS_UI_BUTTONS[ss_ui_pressed][0])):
            size 18
            color "#ffd479"
            xalign 0.5
            yalign 0.78

    frame:
        xfill True
        yalign 1.0
        background "#00000099"
        padding (24, 10)
        hbox:
            spacing 24
            textbutton (_("Reduced motion: on") if ss_ui_reduced else _("Reduced motion: off")):
                action ToggleVariable("ss_ui_reduced")
                text_size 16
            textbutton (_("Buttons: sensitive") if ss_ui_sensitive else _("Buttons: insensitive")):
                action ToggleVariable("ss_ui_sensitive")
                text_size 16
            textbutton _("Close") action Return() text_size 16
