# SSPlayer for Ren'Py — demo entry point.
#
# Replaces the template's `label start`. Shows a .ssab animation centered, with
# keys to cycle through the bundled sample packs. Each entry is
# (sprites_subdir, pack) so packs in different folders (overall, Ringo) coexist.

style default:
    font "SourceHanSansLite.ttf"

init python:
    # Sample packs. Basic exercises alpha / local-alpha; Effect and Instance
    # exercise the particle and nested-animation features; Ringo is a real
    # character (its Normal parts render; its Mesh-deform parts are not drawn
    # yet). The event packs carry UserData / Signal / Audio timeline events.
    SS_DEMO_PACKS = [
        ("sprites/overall", "Basic.ssab"),                  # alpha / local-alpha
        ("sprites/overall", "Effect.ssab"),                 # particle effects
        ("sprites/overall", "Instance.ssab"),               # nested instances
        ("sprites/overall", "PartsColor.ssab"),             # per-vertex part colour
        ("sprites/overall", "BlendMode.ssab"),              # framebuffer blends
        ("sprites/overall", "Interpolation_Easing_v1.ssab"),
        ("sprites/overall", "UserData.ssab"),
        ("sprites/overall", "Signal.ssab"),
        ("sprites/overall", "Sound.ssab"),
        ("sprites/Ringo",   "Ringo.ssab"),                  # character (Mesh gap)
    ]

    def ss_make(entry):
        # entry is (sprites_subdir, pack). The event-log overlay consumes events
        # via ss_poll_events() (see ss_drain_events), so we don't pass callbacks
        # here — but the constructor accepts on_user_data / on_signal / on_audio
        # / on_finished / on_looped / on_started if you prefer push delivery.
        subdir, pack = entry
        return SSPlayer(pack, sprites_subdir=subdir)

    def ss_pack_name(entry):
        return entry[1]

    def ss_switch(delta):
        store.ss_index = (store.ss_index + delta) % len(SS_DEMO_PACKS)
        store.ss_current = ss_make(SS_DEMO_PACKS[store.ss_index])
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

label start:
    $ ss_index = 0
    $ ss_event_log = []
    $ ss_current = ss_make(SS_DEMO_PACKS[0])
    call screen ss_demo
    return

screen ss_demo():
    add Solid("#2a2e36")
    add ss_current:
        xalign 0.5
        yalign 0.5

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
            text "[SS_DEMO_PACKS[ss_index][1]]" size 20 color "#ffffff"
            text "←/→ switch · Esc quit" size 16 color "#9aa0ab" yalign 0.5

    key "K_RIGHT" action Function(ss_switch, 1)
    key "K_LEFT" action Function(ss_switch, -1)
    key "K_ESCAPE" action Return()
