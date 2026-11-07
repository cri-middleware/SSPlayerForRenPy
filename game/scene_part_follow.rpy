# Part-tracking (attach) sample. It pins a plain
# Ren'Py displayable (a crosshair marker) to a live part's transform so it rides
# the animation, and — the point of this scene — it teaches WHY a bone-skinned
# mesh part is a poor follow target, both visually and in words.
#
# Ringo is the rig that carries the lesson in ONE character: its hands / legs /
# ears / tail are SKINNED (bone-bound) mesh parts, whose own transform stays near
# the character root while the art is drawn by the bones — so a marker pinned to
# one snaps to the root, not onto the visible hand. Its `head` is a mesh too but
# NOT skinned (a rigid deform mesh), so it follows fine: proof that it is the
# *skinning*, not "being a mesh", that breaks tracking. `bone_14` — a bone in the
# right-hand chain — is the recommended kind of target (a bone / joint / NULL
# part), so it is the default.
#
# The part picker lists every part and FLAGS the skinned ones (⚠ + red) without
# hiding them: forcing a mesh target is a legitimate thing to do and we don't
# forbid it, we just make it checkable — `ss_is_part_skinned_mesh()` is the query
# behind the flag and the warning, and `ss_attach` itself also logs a one-time
# note to log.txt when handed such a target. (Reached from the start menu in
# script.rpy. Uses only the deployed Ringo pack, so it runs anywhere the demo
# does — no Comipo / local-only asset.)

# Interactive state (mutated by the screen's buttons; `default` so it survives
# rollback and is seeded once).
default ss_pf_player = None          # the live Ringo SSPlayer (one held instance)
default ss_pf_parts = []             # cached [(part_name, is_skinned), ...] for the picker
default ss_pf_part = "bone_14"       # current follow target (a good default: a bone)
default ss_pf_anim = "run"           # current animation
default ss_pf_drive_scale = False    # also follow the part's scale?
default ss_pf_on_hide = "follow"     # "follow" keeps drawing while hidden / "hide" drops it
default ss_pf_attached = True        # attached, or detached (nothing pinned)?

init python:
    SS_PF_SRC = "ss_assets/Ringo/Ringo.ssab"
    # Ringo's local origin (the root part) sits at his FEET, and his art extends
    # only UPWARD from there. SSPlayer centres that origin in its box (render():
    # oy = rh/2), so a tight box puts his feet mid-box and throws the whole body up
    # and off the top. The fix follows the art: give him a box tall enough to hold
    # the body ABOVE the feet, then stand the origin on the stage FLOOR
    # (yanchor 0.5, ypos = SS_PF_FLOOR) so the body rises into the stage. The box's
    # empty lower half falls below the stage and draws nothing. Tune the box height
    # if a pack's body is taller (too short clips the head).
    SS_PF_BOX = (600, 1080)          # origin(feet) at its centre -> ~540px of body room above
    SS_PF_STAGE = (600, 520)         # on-screen stage the sprite is drawn into
    SS_PF_ZOOM = 0.85                # sprite size; smaller if the head reaches the header
    SS_PF_FLOOR = 1.0                # where the feet stand: 1.0 = stage floor, lower to lift him
    # Motions offered as buttons (all present in Ringo.ssab). `run` swings the
    # limbs, so the skinned-hand drift is easy to see.
    SS_PF_MOTIONS = ["run", "walk", "dance", "attack1", "jump", "wait1"]

    def _ss_pf_marker(skinned):
        """A small crosshair marker: RED when the target is a skinned mesh (the
        trap), GREEN when it is a good target. Drawn from two Solids so it needs
        no image asset; its centre is the point ss_attach pins to the part."""
        col = "#e23b2e" if skinned else "#25c469"
        SZ, TH = 34, 3
        return Composite(
            (SZ, SZ),
            ((SZ - TH) // 2, 0), Solid(col, xysize=(TH, SZ)),   # vertical bar
            (0, (SZ - TH) // 2), Solid(col, xysize=(SZ, TH)))   # horizontal bar

    def ss_pf_is_skinned(name):
        """Whether `name` is a bone-skinned mesh on the current player (safe)."""
        p = store.ss_pf_player
        try:
            return bool(p is not None and p.ss_is_part_skinned_mesh(name))
        except Exception:
            return False

    def ss_pf_apply():
        """Re-pin the marker from the current state. Attachments are pure host
        data, so we just clear and re-add — no need to rebuild the player."""
        p = store.ss_pf_player
        if p is None:
            return
        p.ss_clear_attachments()
        if store.ss_pf_attached:
            skinned = ss_pf_is_skinned(store.ss_pf_part)
            p.ss_attach(store.ss_pf_part, _ss_pf_marker(skinned),
                        drive_scale=store.ss_pf_drive_scale,
                        on_hide=store.ss_pf_on_hide)

    def ss_pf_rebuild():
        """(Re)build the held SSPlayer with `ss_pf_anim` as its initial
        animation, then re-pin. The (name, skinned) list is cached here so the
        picker does not re-query every screen refresh."""
        try:
            # `add ss_pf_player` shows this very instance, so the attaches
            # ss_pf_apply makes on it reach the screen as they are made.
            p = SSPlayer(SS_PF_SRC, animation=store.ss_pf_anim, size=SS_PF_BOX)
            store.ss_pf_parts = [(n, bool(p.ss_is_part_skinned_mesh(n)))
                                 for n in p.ss_part_names()]
            store.ss_pf_player = p
        except Exception as e:
            store.ss_pf_player = None
            store.ss_pf_parts = []
            renpy.notify("Ringo load failed: %s" % (e,))
            return
        ss_pf_apply()

    def ss_pf_set_part(name):
        store.ss_pf_part = name
        ss_pf_apply()

    def ss_pf_set_anim(name):
        store.ss_pf_anim = name
        ss_pf_rebuild()

    def ss_pf_toggle_attached():
        store.ss_pf_attached = not store.ss_pf_attached
        ss_pf_apply()

    def ss_pf_toggle_scale():
        store.ss_pf_drive_scale = not store.ss_pf_drive_scale
        ss_pf_apply()

    def ss_pf_toggle_on_hide():
        store.ss_pf_on_hide = "hide" if store.ss_pf_on_hide == "follow" else "follow"
        ss_pf_apply()

    def ss_pf_call_text():
        """Echo the ss_attach call the current state maps to (a teaching aid)."""
        if not store.ss_pf_attached:
            return "ss_clear_attachments()"
        return ("ss_attach(%r, marker, drive_scale=%s, on_hide=%r)"
                % (store.ss_pf_part, store.ss_pf_drive_scale,
                   store.ss_pf_on_hide))

    def ss_pf_cleanup():
        p = store.ss_pf_player
        if p is not None:
            try:
                p.ss_stop_audio()
            except Exception:
                pass
        store.ss_pf_player = None


label part_follow_demo:
    $ ss_pf_rebuild()
    call screen ss_part_follow
    $ ss_pf_cleanup()
    return


screen ss_part_follow():
    modal True
    zorder 100
    key "K_ESCAPE" action Return()

    add Solid("#1c2026")

    # Live facts for the warning / status (the picker list itself is cached).
    $ _skinned = ss_pf_is_skinned(ss_pf_part)
    $ _axes = ("position + rotation" + (" + scale" if ss_pf_drive_scale else ""))
    $ _call = ss_pf_call_text()

    # --- header (pinned top) -------------------------------------------
    frame:
        xfill True
        yalign 0.0
        background "#00000099"
        padding (24, 12)
        vbox:
            spacing 4
            text _("Part tracking — attach a marker to a live part") size 24 color "#ffffff"
            text _("⚠ parts are skinned (bone-bound) meshes: the marker snaps near the character root, not onto the art. Not forbidden — check ss_is_part_skinned_mesh() and prefer a NULL / bone / joint part (bone_14 is the default).") size 13 color "#9aa0ab"

    # --- body: controls (left) | stage (center) | part picker (right) --
    hbox:
        xalign 0.5
        yalign 0.5
        spacing 18

        # Left: animation + attach options.
        vbox:
            spacing 6
            xsize 210

            text _("Animation") size 16 color "#7fd0ff"
            for _m in SS_PF_MOTIONS:
                textbutton _m:
                    action Function(ss_pf_set_anim, _m)
                    text_size 15
                    text_color ("#ffd479" if _m == ss_pf_anim else "#cfd3da")

            null height 14
            text _("Options") size 16 color "#7fd0ff"
            textbutton (_("Attached: ON") if ss_pf_attached else _("Attached: OFF")):
                action Function(ss_pf_toggle_attached)
                text_size 15
                text_color ("#ffd479" if ss_pf_attached else "#cfd3da")
            textbutton (_("Scale follow: ON") if ss_pf_drive_scale else _("Scale follow: OFF")):
                action Function(ss_pf_toggle_scale)
                text_size 15
                text_color ("#ffd479" if ss_pf_drive_scale else "#cfd3da")
            textbutton (_("On hide: HIDE") if ss_pf_on_hide == "hide" else _("On hide: FOLLOW")):
                action Function(ss_pf_toggle_on_hide)
                text_size 15
                text_color ("#ffd479" if ss_pf_on_hide == "hide" else "#cfd3da")

        # Center: the live Ringo, with the marker composited in at the part.
        vbox:
            spacing 8
            frame:
                xsize SS_PF_STAGE[0]
                ysize SS_PF_STAGE[1]
                padding (0, 0)
                background Solid("#101216")
                if ss_pf_player is not None:
                    # Stand the feet-origin on the stage floor (yanchor 0.5 = the box
                    # centre, where the origin is; ypos SS_PF_FLOOR) so the body rises
                    # into the stage, head last. The box's empty lower half overhangs
                    # below the stage and draws nothing. The marker is composited
                    # inside the player's render, so it scales with SS_PF_ZOOM and
                    # stays on the part.
                    add ss_pf_player:
                        zoom SS_PF_ZOOM
                        xalign 0.5
                        yanchor 0.5
                        ypos SS_PF_FLOOR
                else:
                    text _("(Ringo failed to load)") xalign 0.5 yalign 0.5 color "#ff8888"

            # Warning line (red) — the textual half of the lesson.
            if _skinned:
                text _("⚠ '[ss_pf_part]' is a skinned mesh — the marker sits near the root, not on the art. Place a NULL part there in SpriteStudio (or follow a bone / joint) for accurate tracking.") size 14 color "#ff6b5e" xsize 600
            else:
                text _("Following '[ss_pf_part]' — a good target (its node moves with the art).") size 14 color "#7fd0ff" xsize 600

            text ("[ss_pf_part]  |  drives [_axes]  |  on_hide=[ss_pf_on_hide]") size 13 color "#9aa0ab"

        # Right: the follow-target picker. Skinned parts flagged, not hidden.
        vbox:
            spacing 6
            text _("Follow target") size 16 color "#7fd0ff"
            text _("scroll: wheel / drag  ·  ⚠ = skinned") size 11 color "#667085"
            viewport:
                mousewheel True
                draggable True
                xsize 240
                ysize 470
                vbox:
                    spacing 1
                    for _n, _sk in ss_pf_parts:
                        textbutton ("⚠ " + _n if _sk else _n):
                            action Function(ss_pf_set_part, _n)
                            text_size 14
                            text_color ("#ffd479" if _n == ss_pf_part
                                        else ("#e2685c" if _sk else "#cfd3da"))

    # --- footer (pinned bottom): the live ss_attach call + Close --------
    frame:
        xfill True
        yalign 1.0
        background "#00000099"
        padding (24, 10)
        hbox:
            spacing 24
            text "[_call!q]" size 13 color "#8fe3a6" yalign 0.5
            null width 1 xfill True
            textbutton _("Close") action Return() text_size 16 yalign 0.5
