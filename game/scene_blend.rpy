# Animation blending sample — crossfade and layering on one player through the
# track stack (ss_crossfade / ss_set_track_animation / ss_fade_track / ...). The
# controls are the ones the hand checks of motion blending walk through, so each
# can be seen to hold:
#
#   1. Crossfade, then switch back with ss_set_animation: the animation the
#      crossfade left is a real switch (it is not taken for the one selected).
#   2. Speed 2x, then crossfade: the incoming animation plays at 2x too.
#   3. Loop once, then crossfade: the incoming animation finishes after one
#      loop (Finished turns True).
#   4. Overlay on, its loop once: track 1 finishes and holds its last frame.
#   5. Crossfade repeatedly in quick succession: the pose never jumps.
#   6. The events sample (right): crossfading it reports events from the
#      incoming source only, or from the outgoing one too through the first
#      half of the fade.
#
# (Reached from the start menu in script.rpy. Uses only the deployed Ringo and
# overall packs.)

default ss_bl_player = None          # the Ringo SSPlayer the controls drive
default ss_bl_events_player = None   # the UserData SSPlayer for the event check
default ss_bl_cut = False            # switch with ss_set_animation instead of a crossfade
default ss_bl_speed = 1.0
default ss_bl_loop_once = False
default ss_bl_overlay = False
default ss_bl_overlay_once = False
default ss_bl_overlay_half = False   # track 1's alpha at 0.5 instead of 1.0
default ss_bl_additive = False
default ss_bl_sync = False
default ss_bl_paused = False
default ss_bl_outgoing = False       # the outgoing side fires through the first half
default ss_bl_log = []

init python:
    SS_BL_SRC = "ss_assets/Ringo/Ringo.ssab"
    SS_BL_EVENTS_SRC = "ss_assets/overall/UserData.ssab"
    SS_BL_MOTIONS = ["wait1", "walk", "run", "dance", "joy", "attack1"]
    SS_BL_OVERLAY = "attack1"
    SS_BL_FADE = 0.4                 # seconds
    # Ringo's origin is at his feet, so the box is tall and the feet stand on
    # the stage floor; see scene_part_follow.rpy.
    SS_BL_BOX = (600, 1080)
    SS_BL_STAGE = (560, 500)
    SS_BL_ZOOM = 0.8

    def ss_bl_build():
        store.ss_bl_player = SSPlayer(SS_BL_SRC, animation="wait1", size=SS_BL_BOX)
        store.ss_bl_events_player = SSPlayer(SS_BL_EVENTS_SRC, size=(300, 300))
        store.ss_bl_cut = store.ss_bl_loop_once = store.ss_bl_overlay = False
        store.ss_bl_overlay_once = store.ss_bl_overlay_half = False
        store.ss_bl_additive = store.ss_bl_sync = store.ss_bl_paused = False
        store.ss_bl_outgoing = False
        store.ss_bl_speed = 1.0
        store.ss_bl_log = []

    def ss_bl_lay_overlay():
        """Lay the overlay on track 1 from the current settings. The sync goes
        first: it decides where the animation laid next starts."""
        p = store.ss_bl_player
        if not store.ss_bl_overlay:
            p.ss_clear_track(1)
            return
        p.ss_set_track_sync(1, ssruntime.TRACK_SYNC_START if store.ss_bl_sync
                            else ssruntime.TRACK_SYNC_FREE)
        p.ss_set_track_animation(1, SS_BL_OVERLAY)
        # The loop count belongs to the animation just laid, so it goes after.
        p.ss_set_track_loop_count(1, 1 if store.ss_bl_overlay_once else -1)
        ss_bl_apply_overlay()

    def ss_bl_apply_overlay():
        p = store.ss_bl_player
        if not store.ss_bl_overlay:
            return
        p.ss_set_track_alpha(1, 0.5 if store.ss_bl_overlay_half else 1.0)
        p.ss_set_track_blend(1, ssruntime.TRACK_BLEND_ADDITIVE if store.ss_bl_additive
                             else ssruntime.TRACK_BLEND_MIX)

    def ss_bl_switch(name):
        p = store.ss_bl_player
        if store.ss_bl_cut:
            # ss_set_animation of the animation already current does nothing,
            # so only a real switch is set up and played. It folds the stack
            # back to track 0, so the overlay is laid again.
            if name != p.ss_get_current_animation():
                p.ss_set_animation(name)
                p.ss_play()
                store.ss_bl_paused = False
                ss_bl_lay_overlay()
        else:
            p.ss_crossfade(0, name, SS_BL_FADE)

    def ss_bl_cycle_speed():
        store.ss_bl_speed = {1.0: 2.0, 2.0: 0.5}.get(store.ss_bl_speed, 1.0)
        store.ss_bl_player.ss_set_speed_scale(store.ss_bl_speed)

    def ss_bl_toggle(flag):
        setattr(store, flag, not getattr(store, flag))
        p = store.ss_bl_player
        if flag == "ss_bl_loop_once":
            p.ss_set_loop_count(1 if store.ss_bl_loop_once else -1)
        elif flag in ("ss_bl_overlay", "ss_bl_sync"):
            ss_bl_lay_overlay()
        elif flag == "ss_bl_overlay_once":
            if store.ss_bl_overlay:
                p.ss_set_track_loop_count(1, 1 if store.ss_bl_overlay_once else -1)
        elif flag == "ss_bl_paused":
            if store.ss_bl_paused:
                p.ss_pause()
            else:
                p.ss_resume()
        elif flag == "ss_bl_outgoing":
            share = 0.5 if store.ss_bl_outgoing else float("inf")
            for q in (p, store.ss_bl_events_player):
                q.ss_set_track_outgoing_event_threshold(0, share)
        elif flag in ("ss_bl_overlay_half", "ss_bl_additive"):
            ss_bl_apply_overlay()

    def ss_bl_replay():
        """Play track 0 from the top, which also clears a finish."""
        store.ss_bl_player.ss_play()
        store.ss_bl_paused = False

    def ss_bl_crossfade_events():
        q = store.ss_bl_events_player
        q.ss_crossfade(0, q.ss_get_current_animation(), 1.0)
        store.ss_bl_log = (store.ss_bl_log + ["-- crossfade (main source %s)"
                                              % q.ss_track_main_source(0)])[-8:]

    def ss_bl_poll():
        """Move the events sample's events into the log; each names its source."""
        q = store.ss_bl_events_player
        if q is None:
            return
        lines = ["frame %d  source %s" % (fe.frame_index, fe.source)
                 for fe in q.ss_poll_events()]
        if lines:
            store.ss_bl_log = (store.ss_bl_log + lines)[-8:]

    def _ss_bl_num(v, fmt="%.2f"):
        return "-" if v is None else (fmt % v)

    def ss_bl_status():
        p = store.ss_bl_player
        if p is None:
            return ""
        fade = p.ss_track_fade_progress(0)
        rows = [
            __("Current animation: %s") % p.ss_get_current_animation(),
            __("Track 0  main source %s  speed %s  loop %s  finished %s")
            % (p.ss_track_main_source(0), _ss_bl_num(p.ss_get_track_speed(0)),
               p.ss_get_track_loop_count(0), p.ss_is_finished()),
            __("Track 0  fade %s  outgoing events from %s")
            % (_ss_bl_num(fade),
               _ss_bl_num(p.ss_get_track_outgoing_event_threshold(0))),
        ]
        if p.ss_track_count() > 1 and p.ss_get_track_loop_count(1) is not None:
            rows.append(__("Track 1  frame %s  loop %s  finished %s  alpha %s")
                        % (_ss_bl_num(p.ss_get_track_frame(1), "%.1f"),
                           p.ss_get_track_loop_count(1), p.ss_is_track_finished(1),
                           _ss_bl_num(p.ss_get_track_alpha(1))))
        return "\n".join(rows)

    def ss_bl_cleanup():
        for q in (store.ss_bl_player, store.ss_bl_events_player):
            if q is not None:
                try:
                    q.ss_stop_audio()
                except Exception:
                    pass
        store.ss_bl_player = store.ss_bl_events_player = None


label blend_demo:
    $ ss_bl_build()
    call screen ss_blend
    $ ss_bl_cleanup()
    return


screen ss_blend():
    modal True
    zorder 100
    key "K_ESCAPE" action Return()
    # The status reads the players live; poll the events sample at the same time.
    timer 0.1 repeat True action Function(ss_bl_poll)

    add Solid("#1c2026")

    frame:
        xfill True
        yalign 0.0
        background "#00000099"
        padding (24, 12)
        vbox:
            spacing 4
            text _("Animation blending — crossfade and layering on one player") size 24 color "#ffffff"
            text _("Pick an animation to crossfade track 0 into it. The current animation switches as you click, not when the fade ends.") size 13 color "#9aa0ab"

    hbox:
        xalign 0.5
        yalign 0.5
        spacing 18

        # Left: switching and track 0.
        vbox:
            spacing 4
            xsize 230

            text _("Animation") size 16 color "#7fd0ff"
            for _m in SS_BL_MOTIONS:
                textbutton _m:
                    action Function(ss_bl_switch, _m)
                    text_size 15
                    text_color ("#ffd479" if ss_bl_player and _m == ss_bl_player.ss_get_current_animation() else "#cfd3da")
            textbutton (_("Switch by: ss_set_animation") if ss_bl_cut else _("Switch by: crossfade")):
                action Function(ss_bl_toggle, "ss_bl_cut")
                text_size 15

            null height 10
            text _("Track 0") size 16 color "#7fd0ff"
            textbutton _("Speed: [ss_bl_speed]×"):
                action Function(ss_bl_cycle_speed)
                text_size 15
            textbutton (_("Loop: once") if ss_bl_loop_once else _("Loop: forever")):
                action Function(ss_bl_toggle, "ss_bl_loop_once")
                text_size 15
            textbutton (_("Resume") if ss_bl_paused else _("Pause")):
                action Function(ss_bl_toggle, "ss_bl_paused")
                text_size 15
            textbutton _("Play from the top"):
                action Function(ss_bl_replay)
                text_size 15

        # Center: Ringo and the status.
        vbox:
            spacing 8
            frame:
                xsize SS_BL_STAGE[0]
                ysize SS_BL_STAGE[1]
                padding (0, 0)
                background Solid("#101216")
                if ss_bl_player is not None:
                    add ss_bl_player:
                        zoom SS_BL_ZOOM
                        xalign 0.5
                        yanchor 0.5
                        ypos 1.0
            # A fixed height, so the layout does not shift as rows come and go.
            frame:
                background None
                padding (0, 0)
                xsize SS_BL_STAGE[0]
                ysize 80
                text ss_bl_status() size 13 color "#9aa0ab" substitute False

        # Right: track 1 and the events sample.
        vbox:
            spacing 4
            xsize 300

            text _("Track 1 (overlay: attack1)") size 16 color "#7fd0ff"
            textbutton (_("Overlay: on") if ss_bl_overlay else _("Overlay: off")):
                action Function(ss_bl_toggle, "ss_bl_overlay")
                text_size 15
            textbutton (_("Loop: once") if ss_bl_overlay_once else _("Loop: forever")):
                action Function(ss_bl_toggle, "ss_bl_overlay_once")
                text_size 15
            textbutton (_("Alpha: 0.5") if ss_bl_overlay_half else _("Alpha: 1.0")):
                action Function(ss_bl_toggle, "ss_bl_overlay_half")
                text_size 15
            textbutton (_("Blend: additive") if ss_bl_additive else _("Blend: mix")):
                action Function(ss_bl_toggle, "ss_bl_additive")
                text_size 15
            textbutton (_("Start: in step with track 0") if ss_bl_sync else _("Start: from the top")):
                action Function(ss_bl_toggle, "ss_bl_sync")
                text_size 15

            null height 10
            text _("Events (overall/UserData)") size 16 color "#7fd0ff"
            if ss_bl_events_player is not None:
                add ss_bl_events_player zoom 0.5
            textbutton _("Crossfade it into itself (1s)"):
                action Function(ss_bl_crossfade_events)
                text_size 15
            textbutton (_("Outgoing side: fires in the first half") if ss_bl_outgoing else _("Outgoing side: silent")):
                action Function(ss_bl_toggle, "ss_bl_outgoing")
                text_size 15
            text "\n".join(ss_bl_log) size 12 color "#8fe3a6" substitute False

    frame:
        xfill True
        yalign 1.0
        background "#00000099"
        padding (24, 10)
        hbox:
            spacing 24
            text _("Switch by ss_set_animation folds the stack back to track 0; the overlay is laid again.") size 13 color "#9aa0ab" yalign 0.5
            null width 1 xfill True
            textbutton _("Close") action Return() text_size 16 yalign 0.5
