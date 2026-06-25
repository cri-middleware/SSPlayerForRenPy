# SSPlayer for Ren'Py — M1 demo entry point.
#
# Replaces the template's `label start`. Shows a .ssab animation centered, with
# keys to cycle through the bundled "overall" test packs.

init python:
    # Packs from tests/overall that render fully (or mostly) at M1 (Normal).
    SS_DEMO_PACKS = [
        "Basic.ssab",
        "BlendMode.ssab",
        "Shader.ssab",
        "Interpolation_Easing_v1.ssab",
        "Bounding.ssab",
        "TextureChange.ssab",
    ]

    def ss_switch(delta):
        store.ss_index = (store.ss_index + delta) % len(SS_DEMO_PACKS)
        store.ss_current = SpriteStudioDisplayable(
            SS_DEMO_PACKS[store.ss_index], sprites_subdir="sprites/overall")
        renpy.restart_interaction()

label start:
    $ ss_index = 0
    $ ss_current = SpriteStudioDisplayable(SS_DEMO_PACKS[0], sprites_subdir="sprites/overall")
    call screen ss_demo
    return

screen ss_demo():
    add Solid("#2a2e36")
    add ss_current:
        xalign 0.5
        yalign 0.5

    frame:
        xalign 0.5
        yalign 0.97
        background "#000000c0"
        padding (16, 8)
        hbox:
            spacing 18
            text "[SS_DEMO_PACKS[ss_index]]" size 20 color "#ffffff"
            text "←/→ switch · Esc quit" size 16 color "#9aa0ab" yalign 0.5

    key "K_RIGHT" action Function(ss_switch, 1)
    key "K_LEFT" action Function(ss_switch, -1)
    key "K_ESCAPE" action Return()
