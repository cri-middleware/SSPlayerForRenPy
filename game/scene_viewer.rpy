# Basic-feature viewer: a `screen ss_demo` that cycles through the bundled
# sample packs with the arrow keys, with a live timeline-event log overlay. Each
# SS_DEMO_PACKS entry is (sprites_subdir, pack) so packs in different folders
# coexist. (Reached from the start menu in script.rpy.)

init python:
    import os

    # Sample packs. The full `overall/` feature set is listed so the viewer
    # exercises every supported feature (Basic alpha, PartsColor, blends, mesh
    # deform, shapes, masks, the ss-* user shaders, instances, timeline events).
    # Text / NineSlice are listed for completeness but their batch kinds are not
    # rendered yet (they show empty — later milestones). Ringo is a real
    # character (Normal parts render; Mesh-deform parts do). A trimmed sample of
    # the ParticleEffect packs is appended after these (see below).
    SS_DEMO_PACKS = [
        ("ss_assets/overall", "Basic.ssab"),                  # alpha / local-alpha
        ("ss_assets/overall", "PartsColor.ssab"),             # per-vertex part colour
        ("ss_assets/overall", "BlendMode.ssab"),              # framebuffer blends
        ("ss_assets/overall", "Interpolation.ssab"),          # interpolation
        ("ss_assets/overall", "Interpolation_Easing_v1.ssab"),
        ("ss_assets/overall", "Mesh.ssab"),                   # mesh deform
        ("ss_assets/overall", "Shape.ssab"),                  # shapes (incl. shape masks)
        ("ss_assets/overall", "Mask.ssab"),                   # mask / clipping mask
        ("ss_assets/overall", "Shader.ssab"),                 # ss-* user shaders
        ("ss_assets/overall", "Bounding.ssab"),               # bounding
        ("ss_assets/overall", "TextureChange.ssab"),          # runtime cell/tex swap
        ("ss_assets/overall", "Effect.ssab"),                 # particle effects
        ("ss_assets/overall", "Instance.ssab"),               # nested instances
        ("ss_assets/overall", "Instance_SourceAnime.ssab"),   # instance source
        ("ss_assets/overall", "UserData.ssab"),               # timeline: user data
        ("ss_assets/overall", "Signal.ssab"),                 # timeline: signal
        ("ss_assets/overall", "Sound.ssab"),                  # timeline: audio
        ("ss_assets/overall", "01-new.ssab"),
        ("ss_assets/overall", "Text.ssab"),                   # (not rendered yet)
        ("ss_assets/overall", "NineSlice.ssab"),              # (not rendered yet)
        ("ss_assets/Ringo",   "Ringo.ssab"),                  # character
        ("ss_assets/Ringo",   "Ringo_tyu.ssab"),              # companion
    ]

    # Particle-effect packs: there are ~40, so show only a small curated sample
    # (the full set is still browsable via Shift+B). e040a / e040b are the
    # showpiece composite effects; the rest are a spread across the range.
    _fx_dir = os.path.join(renpy.config.gamedir, "ss_assets", "ParticleEffect")
    if os.path.isdir(_fx_dir):
        _fx_pick = ["e001.ssab", "e012.ssab", "e024.ssab", "e036.ssab",
                    "e040a.ssab", "e040b.ssab"]
        for f in _fx_pick:
            if os.path.isfile(os.path.join(_fx_dir, f)):
                SS_DEMO_PACKS.append(("ss_assets/ParticleEffect", f))

    def ss_make(entry, animation=None):
        # entry is (dir, pack); we just join them into the .ssab path. The
        # event-log overlay consumes events via ss_poll_events() (see
        # ss_drain_events), so we don't pass callbacks here — but the constructor
        # accepts on_user_data / on_signal / on_audio / on_finished / on_looped /
        # on_started if you prefer push delivery.
        subdir, pack = entry
        return SSPlayer(subdir + "/" + pack, animation=animation)

    def ss_pack_name(entry):
        return entry[1]

    def ss_stop_current_audio():
        # We hold the player in a variable and swap it, so Ren'Py never hides the
        # old one (no `_hide`). Stop its audio explicitly so it doesn't play on
        # after we switch away (the library reaper would also catch it within a
        # fraction of a second, but this is immediate and the recommended pattern
        # when you keep + replace an SSPlayer reference yourself).
        old = getattr(store, "ss_current", None)
        if old is not None:
            try:
                old.ss_stop_audio()
            except Exception:
                pass

    def ss_switch(delta):
        ss_stop_current_audio()
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
        ss_stop_current_audio()
        store.ss_current = ss_make(SS_DEMO_PACKS[store.ss_index], animation=names[new_idx])
        store.ss_event_log = []
        renpy.restart_interaction()

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
        # ss_escape (defined in script.rpy) keeps "{" / "[" in payloads from being
        # parsed as Ren'Py text tags / substitutions.
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

label viewer_demo:
    $ ss_index = 0
    $ ss_event_log = []
    $ ss_current = ss_make(SS_DEMO_PACKS[0])
    call screen ss_demo
    # Leaving the viewer: quiet any sound the current pack was playing (the
    # displayable is dropped without a hide, so stop it explicitly).
    $ ss_stop_current_audio()
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
