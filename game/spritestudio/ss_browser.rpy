# SpriteStudio Asset Browser — a developer-mode inspector / snippet generator.
#
# Press **Shift+B** in developer mode to toggle it. It lists every .ssab the
# resolver can find (all discovered packs, incl. instance sub-packs), previews any
# animation live (drag to move it, wheel to scale it), and saves a ready-to-paste
# snippet for the role you pick (character / one-shot / UI) — so a creator picks
# the role while watching the animation, instead of guessing.
#
# It sits on top of the zero-config resolver + SSInternalPlayer. Only the hotkey
# registration is dev-gated, so this file is harmless in a release build (the
# screen exists but is unreachable). Drop the file to remove the tool entirely.

init python:
    import os as _ss_os
    from ss_renpy import snippet as _ss_snippet

    def _ss_browser_escape(s):
        # For text written into a screen statement, where Ren'Py reads { as a
        # tag and [ as a substitution. A value substituted in with [x!q] needs
        # neither: its [ is not substituted again, and !q quotes its {.
        return str(s).replace("{", "{{").replace("[", "[[")

    def _ss_browser_detail(name):
        """Resolve + read richer meta for the detail pane. Never raises."""
        d = {"path": "", "anims": [], "fps": 0, "has_effects": False,
             "instance_packs": []}
        try:
            rec = _ss_get_index().find(name)
            d["path"] = rec.rel_path
            d["anims"] = list(rec.anim_names)
            # Read via the archive-aware loader (like the rest of the library), so
            # the detail pane also works for packs shipped inside a .rpa.
            meta = SsabMeta(_ss_open_bytes(rec.rel_path))
            ai = meta.animations()
            d["fps"] = ai[0].fps if ai else 0
            d["has_effects"] = bool(meta.effect_parts()) or bool(meta.effects())
            d["instance_packs"] = [e.anime_pack_name
                                   for e in meta.external_instances()]
        except Exception:
            pass
        return d

    def _ss_browser_default_role(d):
        return _ss_snippet.default_role(len(d["anims"]), d["has_effects"])

    # Preview zoom range. The zoom is a Transform around the live SSPlayer, so
    # scaling neither rebuilds the player nor restarts the animation.
    SS_BROWSER_ZOOM_MIN = 0.2
    SS_BROWSER_ZOOM_MAX = 5.0
    SS_BROWSER_ZOOM_STEP = 1.1       # one wheel notch

    def _ss_browser_zoom_by(factor):
        """Scale the preview by `factor`, clamped to the range above."""
        z = store.ss_browser_zoom * factor
        store.ss_browser_zoom = max(SS_BROWSER_ZOOM_MIN,
                                    min(SS_BROWSER_ZOOM_MAX, z))

    def _ss_browser_reset_view():
        """Put the preview back the way a pack opens: 1:1, centred.

        The drag group keeps a dropped drag's position under its drag_name
        and hands it to any drag built with that name again, so the name
        carries a view number, and a new number is a drag placed afresh."""
        store.ss_browser_zoom = 1.0
        store.ss_browser_view += 1

    def _ss_browser_select(name, anim=None):
        """Select a pack (and optional animation); build the live preview."""
        # Stop the outgoing preview's audio: it is held in a variable and swapped,
        # so Ren'Py never hides it (no `_hide`). The library reaper also catches a
        # closed/switched preview shortly, but this makes a Sound pack quiet
        # immediately when you pick another.
        _old = getattr(store, "ss_browser_player", None)
        if _old is not None:
            try:
                _old.ss_stop_audio()
            except Exception:
                pass
        # A new pack is a new subject: start it at 1:1. Switching ANIMATION comes
        # through here too and keeps the zoom, so two clips of one pack can be
        # compared at the same scale.
        if name != store.ss_browser_pack:
            store.ss_browser_zoom = 1.0
        store.ss_browser_pack = name
        d = _ss_browser_detail(name)
        store.ss_browser_detail = d
        if anim is None and d["anims"]:
            anim = d["anims"][0]
        store.ss_browser_anim = anim
        store.ss_browser_role = _ss_browser_default_role(d)
        try:
            # size=(470, 360): give the preview a definite size so the draggable
            # `drag` wrapping it has a real hit area — an unsized CDD can't be
            # dragged. Same proven pattern as the demo picker (asset_picker.rpy).
            store.ss_browser_player = SSPlayer(d["path"], animation=anim, size=(470, 360)) if d["path"] else None
        except Exception as e:
            store.ss_browser_player = None
            renpy.notify("Preview failed: %s" % (e,))

    def _ss_browser_snippet(path, role, anims):
        """Ready-to-paste .rpy snippet for the .ssab at `path` in the chosen `role`."""
        return _ss_snippet.build_snippet(path, role, anims)

    def _ss_browser_export(name, path, role, anims):
        """Append the snippet to <basedir>/ss_snippets.txt (+ clipboard if any)."""
        snip = _ss_browser_snippet(path, role, anims)
        target = "(write failed)"
        try:
            p = _ss_os.path.join(renpy.config.basedir, "ss_snippets.txt")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("# --- %s (%s) ---\n%s\n\n" % (name, role, snip))
            target = "ss_snippets.txt"
        except Exception:
            pass
        try:
            if hasattr(renpy, "copy_to_clipboard"):
                renpy.copy_to_clipboard(snip)
        except Exception:
            pass
        renpy.notify("Snippet saved to %s" % target)

    # Dev-only hotkey: register the Shift+B toggle screen as an overlay.
    if config.developer and "_ss_browser_key" not in config.overlay_screens:
        config.overlay_screens.append("_ss_browser_key")


default ss_browser_pack = None
default ss_browser_anim = None
default ss_browser_role = None
default ss_browser_detail = {"path": "", "anims": [], "fps": 0,
                             "has_effects": False, "instance_packs": []}
default ss_browser_player = None
default ss_browser_zoom = 1.0
default ss_browser_view = 0


screen _ss_browser_key():
    # Cheaply pick up newly imported packs before (re)opening: the refresh drops
    # the cached asset index only if the .ssab set actually changed (near-free
    # otherwise), then the toggle shows the browser rebuilt from the fresh list.
    key "shift_K_b" action [Function(_ss_refresh_index_if_changed), ToggleScreen("ss_browser")]


screen ss_browser():
    modal True
    zorder 200
    key "K_ESCAPE" action Hide("ss_browser")

    # Wheel = zoom the preview. Declared before the body so the lists are offered
    # the event first (a `mousewheel True` viewport only takes it while the
    # pointer is inside), which leaves the wheel elsewhere to scale the sprite.
    # + / - do the same from the keyboard, and 0 resets the view.
    key "mousedown_4" action Function(_ss_browser_zoom_by, SS_BROWSER_ZOOM_STEP)
    key "mousedown_5" action Function(_ss_browser_zoom_by, 1.0 / SS_BROWSER_ZOOM_STEP)
    key "K_EQUALS" action Function(_ss_browser_zoom_by, SS_BROWSER_ZOOM_STEP)
    key "K_PLUS" action Function(_ss_browser_zoom_by, SS_BROWSER_ZOOM_STEP)
    key "K_MINUS" action Function(_ss_browser_zoom_by, 1.0 / SS_BROWSER_ZOOM_STEP)
    key "K_0" action Function(_ss_browser_reset_view)

    add Solid("#000000d8")

    frame:
        xalign 0.5
        yalign 0.5
        xsize 0.95
        ysize 0.92
        padding (14, 14)

        hbox:
            spacing 14

            # --- left: pack list -------------------------------------------
            vbox:
                spacing 6
                xsize 290
                text "SpriteStudio Browser" size 22
                text "Shift+B toggle | Esc close" size 12
                null height 4
                viewport:
                    mousewheel True
                    draggable True
                    ysize 540
                    vbox:
                        spacing 1
                        # List EVERY discovered .ssab, not just primaries — a
                        # sub-part pack that back-references the main pack would
                        # otherwise hide the main pack (e.g. Ringo_tyu -> Ringo
                        # demotes Ringo). ss_list_assets() stays primary-only for
                        # name resolution / diagnostics; the browser shows all.
                        # The LABEL is escaped, the action keeps the raw name:
                        # Ren'Py interpolates [..] / {..} in a button's text, so a
                        # pack called "[NG]_medalDANCE" would otherwise raise
                        # NameError: name 'NG' is not defined and take the whole
                        # browser down.
                        for _n in sorted({_r.stem for _r in _ss_get_index().records()}):
                            textbutton _ss_browser_escape(_n) action Function(_ss_browser_select, _n) text_size 14

            # --- center: live preview + animation list ---------------------
            vbox:
                spacing 8
                xsize 480
                if ss_browser_pack:
                    text "[ss_browser_pack!q]" size 20
                    frame:
                        xsize 470
                        ysize 360
                        background Solid("#222222")
                        if ss_browser_player is not None:
                            # Drag the preview to reposition it, wheel to scale it.
                            # A definite size (SSPlayer size=) makes the Drag
                            # grabbable, and the zoom scales the whole rendered
                            # sprite, so its hit area grows with it. Mirrors the
                            # demo picker (asset_picker.rpy).
                            draggroup:
                                drag:
                                    drag_name "%s#%d" % (ss_browser_pack, ss_browser_view)
                                    draggable True
                                    drag_offscreen True
                                    xpos 0.5 ypos 0.5 xanchor 0.5 yanchor 0.5
                                    add ss_browser_player at Transform(zoom=ss_browser_zoom)
                        else:
                            text "(no preview)" xalign 0.5 yalign 0.5
                    # Percent, not a "x1.25" factor: at this size the decimal point
                    # is easy to miss, and "125%" cannot be misread.
                    $ _zoom_disp = "%d%%" % round(ss_browser_zoom * 100)
                    hbox:
                        spacing 10
                        text "drag to move | wheel (or + / -) to zoom: [_zoom_disp]" size 11 yalign 0.5
                        textbutton "Reset view (0)" action Function(_ss_browser_reset_view) text_size 11 yalign 0.5
                    $ _na = len(ss_browser_detail["anims"])
                    $ _fps = ss_browser_detail["fps"]
                    $ _fx = ss_browser_detail["has_effects"]
                    text "animations: [_na] | fps: [_fps] | effects: [_fx]" size 13
                    if ss_browser_detail["instance_packs"]:
                        $ _ip = ", ".join(ss_browser_detail["instance_packs"])
                        text "instance packs: [_ip]" size 12
                    text "click an animation to preview:" size 12
                    viewport:
                        mousewheel True
                        draggable True
                        ysize 110
                        xsize 470
                        vbox:
                            spacing 1
                            for _a in ss_browser_detail["anims"]:
                                # Escaped label, raw name to the action (as above).
                                textbutton _ss_browser_escape(_a) action Function(_ss_browser_select, ss_browser_pack, _a) text_size 13
                else:
                    text "Select a pack on the left." xalign 0.5 yalign 0.5

            # --- right: role picker + snippet ------------------------------
            vbox:
                spacing 8
                xsize 370
                text "Use it in your script" size 18
                hbox:
                    spacing 6
                    textbutton "Character" action SetVariable("ss_browser_role", "character") text_size 13
                    textbutton "One-shot" action SetVariable("ss_browser_role", "oneshot") text_size 13
                    textbutton "UI" action SetVariable("ss_browser_role", "ui") text_size 13
                if ss_browser_pack and ss_browser_role:
                    $ _snip_disp = _ss_browser_snippet(ss_browser_detail["path"], ss_browser_role, ss_browser_detail["anims"])
                    frame:
                        xsize 360
                        ysize 360
                        background Solid("#111111")
                        viewport:
                            mousewheel True
                            draggable True
                            text "[_snip_disp!q]" size 13
                    textbutton "Save snippet -> ss_snippets.txt" action Function(_ss_browser_export, ss_browser_pack, ss_browser_detail["path"], ss_browser_role, ss_browser_detail["anims"]) text_size 13
                else:
                    text "Pick a pack, then a role." size 13
                null height 6
                textbutton "Close" action Hide("ss_browser") text_size 14
