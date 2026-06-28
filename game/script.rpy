# SpriteStudio Player for Ren'Py — demo entry point.
#
# Replaces the template's `label start`. Shows a .ssab animation centered, with
# keys to cycle through the bundled sample packs. Each entry is
# (sprites_subdir, pack) so packs in different folders (overall, Ringo) coexist.

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
    import os

    # Sample packs. Basic exercises alpha / local-alpha; Effect and Instance
    # exercise the particle and nested-animation features; Ringo is a real
    # character (its Normal parts render; its Mesh-deform parts are not drawn
    # yet). The event packs carry UserData / Signal / Audio timeline events.
    SS_DEMO_PACKS = [
        ("ss_assets/overall", "Basic.ssab"),                  # alpha / local-alpha
        ("ss_assets/overall", "Effect.ssab"),                 # particle effects
        ("ss_assets/overall", "Instance.ssab"),               # nested instances
        ("ss_assets/overall", "PartsColor.ssab"),             # per-vertex part colour
        ("ss_assets/overall", "BlendMode.ssab"),              # framebuffer blends
        ("ss_assets/overall", "Interpolation_Easing_v1.ssab"),
        ("ss_assets/overall", "UserData.ssab"),
        ("ss_assets/overall", "Signal.ssab"),
        ("ss_assets/overall", "Sound.ssab"),
        ("ss_assets/Ringo",   "Ringo.ssab"),                  # character (Mesh gap)
        ("ss_assets/Ringo",   "Ringo_tyu.ssab"),              # companion
    ]

    _fx_dir = os.path.join(renpy.config.gamedir, "ss_assets", "ParticleEffect")
    if os.path.isdir(_fx_dir):
        for f in sorted(os.listdir(_fx_dir)):
            if f.endswith(".ssab"):
                SS_DEMO_PACKS.append(("ss_assets/ParticleEffect", f))

    def ss_make(entry):
        # entry is (dir, pack); we just join them into the .ssab path. The
        # event-log overlay consumes events via ss_poll_events() (see
        # ss_drain_events), so we don't pass callbacks here — but the constructor
        # accepts on_user_data / on_signal / on_audio / on_finished / on_looped /
        # on_started if you prefer push delivery.
        subdir, pack = entry
        return SSPlayer(subdir + "/" + pack)

    def ss_pack_name(entry):
        return entry[1]

    def ss_switch(delta):
        store.ss_index = (store.ss_index + delta) % len(SS_DEMO_PACKS)
        store.ss_current = ss_make(SS_DEMO_PACKS[store.ss_index])
        store.ss_event_log = []
        renpy.restart_interaction()

    def ss_switch_anim(delta):
        player = store.ss_current
        names = player.ss_animation_names()
        if not names:
            return
        curr = player.ss_get_animation()
        try:
            idx = names.index(curr)
        except ValueError:
            idx = 0
        new_idx = (idx + delta) % len(names)
        player.ss_play(names[new_idx])
        store.ss_event_log = []
        renpy.restart_interaction()

    def ss_escape(s):
        # Event payloads (a signal's params dict repr, user strings) can contain
        # "{" / "[", which Ren'Py text would parse as a tag / substitution
        # ("Unknown text tag ..."). Escape them for safe display.
        return str(s).replace("{", "{{").replace("[", "[[")

    def ss_fmt_event(fe):
        """One human-readable line per event in a FrameEvents record."""
        out = []
        for u in fe.users:
            bits = []
            if u.integer is not None: bits.append("int=%d" % u.integer)
            if u.string: bits.append("str=%r" % u.string)
            out.append("f%d UserData[p%d] %s" % (fe.frame_index, u.part_index,
                                                 " ".join(bits) or "(no payload)"))
        for s in fe.signals:
            out.append("f%d Signal[p%d] %s %s" % (fe.frame_index, s.part_index,
                                                  s.command_id, s.params))
        for a in fe.audios:
            out.append("f%d Audio[p%d] %r loop=%d" % (fe.frame_index, a.part_index,
                                                      a.sound_name, a.loop_num))
        return [ss_escape(x) for x in out]

    def ss_drain_events():
        d = getattr(store, "ss_current", None)
        if d is None:
            return
        try:
            records = d.ss_poll_events()
        except Exception:
            return
        for fe in records:
            store.ss_event_log.extend(ss_fmt_event(fe))
        if len(store.ss_event_log) > 10:        # keep the tail
            del store.ss_event_log[:-10]

image ringo = SSPlayer(
    "Ringo",   # short name is enough: the asset index resolves it to Ringo.ssab under ss_assets
    aliases={
        "idle": "wait1",
        "happy": "joy",
        "walk": "walk",
        "attack": ["attack1", "wait1"]  # a list plays the animations in sequence
    }
)

image ringo_tyu = SSPlayer("Ringo_tyu")

define r = Character(_("Ringo"), image="ringo")

image hit_effect = SSPlayer(
    "e038",          # resolved by short name; a bad animation name errors at definition time
    animation="hit",
    loop=1 # an effect: play once, then stop
)

image effect_e040b = SSPlayer("e040b")

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
        "Watch Basic Feature Viewer (Legacy Demo)":
            jump viewer_demo

label ringo_demo:
    scene bg room
    window show  # keep the dialogue window up (handy for checking layers)

    show ringo idle:
        yoffset 200

    "Ringo has appeared." id ringo_msg1

    r happy "I can change my motion just by changing my attributes, su!" id ringo_msg2

    r piyo "I can even play the dizzy motion (piyo) just by specifying its name, su." id ringo_msg3

    # SSPlayer is drawn fullscreen, use offset instead of align for position
    show ringo walk:
        xoffset -400 yoffset 200
    with move
    r walk "Of course, I can use 'move' and other Transforms together with this, su." id ringo_msg4

    show ringo walk:
        xoffset 0 yoffset 200
    with move
    r "After moving back to the center..." id ringo_msg5

    show ringo attack
    $ renpy.pause(0.05) # wait briefly for the attack's hit moment (the downward swing)

    # fire the effect at the hand to match the attack (offset toward the right hand)
    show hit_effect:
        xoffset -150 yoffset 50

    r "Ei! (When the attack finishes, I automatically return to the idle motion, su.)" id ringo_msg6

    r idle "Furthermore, by linking with the Character's 'image' argument, you can control expressions and motions just with say statements like this, su!" id ringo_msg7

    hide ringo
    with dissolve

    # Show Ringo_tyu and e040b together as a test case
    show ringo_tyu:
        xoffset 0 yoffset 150
    show effect_e040b:
        xoffset 0 yoffset 150
    "As a bonus, here's my companion Ringo_tyu, along with a cool particle effect (e040b) playing at the same time!" id ringo_msg8

    return

label viewer_demo:
    $ ss_index = 0
    $ ss_event_log = []
    $ ss_current = ss_make(SS_DEMO_PACKS[0])
    call screen ss_demo
    return

screen ss_demo():
    add Solid("#2a2e36")
    add ss_current:
        xalign 0.5
        yalign (0.95 if "Ringo" in SS_DEMO_PACKS[ss_index][1] else 0.5)

    # Drain timeline events from the displayable's poll queue a few times a
    # second; the screen re-renders each tick to show the latest log.
    timer 0.1 action Function(ss_drain_events) repeat True

    if ss_event_log:
        frame:
            xalign 0.02
            yalign 0.5
            background "#000000c0"
            padding (12, 10)
            vbox:
                spacing 3
                text "events" size 14 color "#7fd0ff"
                for line in ss_event_log:
                    text "[line]" size 14 color "#e6e6e6"

    frame:
        xalign 0.5
        yalign 0.97
        background "#000000c0"
        padding (16, 8)
        hbox:
            spacing 18
            text "[SS_DEMO_PACKS[ss_index][1]] : [ss_current.animation]" size 20 color "#ffffff"
            text "< > pack | ^ v anim | Esc quit" size 16 color "#9aa0ab" yalign 0.5

    key "K_RIGHT" action Function(ss_switch, 1)
    key "K_LEFT" action Function(ss_switch, -1)
    key "K_UP" action Function(ss_switch_anim, -1)
    key "K_DOWN" action Function(ss_switch_anim, 1)
    key "K_ESCAPE" action Return()
