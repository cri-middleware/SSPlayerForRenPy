# SpriteStudio Asset Browser — a developer-mode inspector / snippet generator.
#
# Press **Shift+B** in developer mode to toggle it. It lists every .ssab the
# resolver can find (all discovered packs, incl. instance sub-packs), previews any
# animation live (drag to move it, wheel to scale it), and saves a ready-to-paste
# snippet for the role you pick (character / one-shot / UI) — so a creator picks
# the role while watching the animation, instead of guessing. A pack the auto
# importer converted also names its .sspj, and opens it in SpriteStudio.
#
# It sits on top of the zero-config resolver + SSInternalPlayer. Only the hotkey
# registration is dev-gated, so this file is harmless in a release build (the
# screen exists but is unreachable). Drop the file to remove the tool entirely.

init python:
    import os as _ss_os
    import subprocess as _ss_subprocess
    import sys as _ss_sys
    from ss_renpy import import_marker as _ss_import_marker
    from ss_renpy import snippet as _ss_snippet

    # SpriteStudio runs on Windows and macOS, so the button that opens a pack's
    # .sspj is offered there only; elsewhere the source is still named.
    _SS_BROWSER_CAN_OPEN = (_ss_sys.platform == "darwin"
                            or _ss_sys.platform.startswith("win"))

    def _ss_browser_source(rel):
        """The .sspj the pack at gamedir-relative `rel` was converted from, or
        None when nothing records one or it is no longer there.

        The auto importer records it in the freshness marker beside the pack
        (tools/ss_stamp_import.py does too), so a pack converted any other way,
        or read from a .rpa, has none."""
        folder = _ss_os.path.join(renpy.config.gamedir, *rel.split("/")[:-1])
        marker = _ss_import_marker.read_marker(folder) or {}
        sspj = marker.get("sspj")
        return sspj if sspj and _ss_os.path.isfile(sspj) else None

    def _ss_browser_shown_path(path):
        """`path` relative to the project, or whole when it is not under it."""
        try:
            rel = _ss_os.path.relpath(path, renpy.config.basedir)
        except ValueError:          # another Windows drive
            return path
        return path if rel.startswith("..") else rel.replace("\\", "/")

    # The application id SpriteStudio registers on macOS. A SpriteStudio that
    # is already running takes no request to open another project — `open`
    # returns success and nothing loads — so the button has to know.
    _SS_SPRITESTUDIO_ID = "jp.co.webtech.SpriteStudio"

    def _ss_spritestudio_running():
        """Whether SpriteStudio is running (macOS). Asks by application id,
        which needs no automation permission; any failure reads as no."""
        try:
            r = _ss_subprocess.run(
                ["osascript", "-e", 'application id "%s" is running' % _SS_SPRITESTUDIO_ID],
                capture_output=True, text=True, timeout=5)
            return r.stdout.strip() == "true"
        except Exception:
            return False

    def _ss_browser_open_source(sspj):
        """Open `sspj` with the app the system opens .sspj files with.

        On macOS a SpriteStudio already running keeps its project, so it is
        brought forward and the path goes to the clipboard, with a notice to
        open it from SpriteStudio's File menu."""
        name = _ss_os.path.basename(sspj)
        try:
            if _ss_sys.platform.startswith("win"):
                _ss_os.startfile(sspj)
                return
            running = _ss_spritestudio_running()
            r = _ss_subprocess.run(["open", sspj], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                renpy.notify("Could not open %s (%s)" % (name, r.stderr.strip() or r.returncode))
            elif running:
                _ss_browser_copy(sspj)
                renpy.notify("SpriteStudio is already open and keeps its project: open %s "
                             "from its File menu (the path is on the clipboard)." % name)
        except Exception as e:
            renpy.notify("Could not open %s (%s)" % (name, e))

    def _ss_browser_copy(text):
        """Put `text` on the system clipboard, where the platform allows it.

        Through Ren'Py's CopyToClipboard action, the one way Ren'Py offers:
        there is no renpy.* function for it. It does nothing on the web."""
        try:
            CopyToClipboard(text)()
        except Exception:
            pass

    def _ss_browser_escape(s):
        # For text written into a screen statement, where Ren'Py reads { as a
        # tag and [ as a substitution. A value substituted in with [x!q] needs
        # neither: its [ is not substituted again, and !q quotes its {.
        return str(s).replace("{", "{{").replace("[", "[[")

    def _ss_browser_detail(name):
        """Resolve + read richer meta for the detail pane. Never raises."""
        d = {"path": "", "anims": [], "fps": 0, "has_effects": False,
             "instance_packs": [], "sspj": None}
        try:
            rec = _ss_get_index().find(name)
            d["path"] = rec.rel_path
            d["sspj"] = _ss_browser_source(rec.rel_path)
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

    # The preview box. A pack opens with its whole authored canvas fitted into
    # it and centred — the framing a Reset view returns to, and what 100% on
    # the zoom readout means — so a canvas far bigger or smaller than the box,
    # or an origin far from the canvas's centre, still opens fully in view.
    # The 1:1 button shows the canvas at its own pixels instead, around the same
    # centre, where a stage-sized canvas's fit would be too small to read.
    SS_BROWSER_BOX = (470, 360)

    # Preview zoom range. The zoom is a Transform around the live SSPlayer, so
    # scaling neither rebuilds the player nor restarts the animation.
    SS_BROWSER_ZOOM_MIN = 0.2
    # Up to 16 times the fitted size, as the Flutter player's demo allows: a
    # canvas the size of an Animate stage fits at a few percent, and this still
    # reaches its own pixels.
    SS_BROWSER_ZOOM_MAX = 16.0
    SS_BROWSER_ZOOM_STEP = 1.1       # one wheel notch

    def _ss_browser_zoom_by(factor):
        """Scale the preview by `factor`, clamped to the range above."""
        z = store.ss_browser_zoom * factor
        store.ss_browser_zoom = max(SS_BROWSER_ZOOM_MIN,
                                    min(SS_BROWSER_ZOOM_MAX, z))

    def _ss_browser_reset_view():
        """Put the preview back the way a pack opens: fitted, centred.

        A new view number is a new drag, placed afresh; see the drag in
        ss_browser for why it takes one."""
        store.ss_browser_zoom = 1.0
        store.ss_browser_view += 1

    def _ss_browser_set_fit(fit):
        """Fit the canvas to the box (True) or show it at its own pixels, and
        start that framing at 100%, centred. The choice holds across packs."""
        store.ss_browser_fit = fit
        _ss_browser_reset_view()

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
        # A new pack is a new subject: start it fitted. Switching ANIMATION comes
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
            # No size: the player is its authored canvas, which the preview then
            # fits into SS_BROWSER_BOX. A pack without a canvas fills what it is
            # offered instead, which the fit leaves at the box.
            store.ss_browser_player = SSPlayer(d["path"], animation=anim) if d["path"] else None
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
        _ss_browser_copy(snip)
        renpy.notify("Snippet saved to %s" % target)

    # Dev-only hotkey: register the Shift+B toggle screen as an overlay.
    if config.developer and "_ss_browser_key" not in config.overlay_screens:
        config.overlay_screens.append("_ss_browser_key")


default ss_browser_pack = None
default ss_browser_anim = None
default ss_browser_role = None
default ss_browser_detail = {"path": "", "anims": [], "fps": 0,
                             "has_effects": False, "instance_packs": [],
                             "sspj": None}
default ss_browser_player = None
default ss_browser_zoom = 1.0
default ss_browser_view = 0
default ss_browser_fit = True


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
                    $ _sspj = ss_browser_detail.get("sspj")
                    hbox:
                        spacing 12
                        text "[ss_browser_pack!q]" size 20 yalign 0.5
                        if _sspj and _SS_BROWSER_CAN_OPEN:
                            textbutton "Open .sspj" action Function(_ss_browser_open_source, _sspj) text_size 12 yalign 0.5
                    frame:
                        xsize SS_BROWSER_BOX[0]
                        ysize SS_BROWSER_BOX[1]
                        background Solid("#222222")
                        if ss_browser_player is not None:
                            # Drag the preview to reposition it, wheel to scale it.
                            # The canvas is fitted into the box and then zoomed,
                            # and the drag's hit area is what that draws. Mirrors
                            # the demo picker (asset_picker.rpy).
                            draggroup:
                                # One drag per pack and view number. The screen hands a
                                # rebuilt drag the one it replaces, and a drag takes that
                                # one's position, so a new pack or a Reset view would stay
                                # where the last drag was dropped; a new index key builds
                                # the drag afresh. The name changes with it because the
                                # group also keeps each dropped drag's position by name.
                                for _view index _view in [(ss_browser_pack, ss_browser_view)]:
                                    drag:
                                        drag_name "%s#%d" % _view
                                        draggable True
                                        drag_offscreen True
                                        xpos 0.5 ypos 0.5 xanchor 0.5 yanchor 0.5
                                        # reset: a screen update hands the new transform the old
                                        # one's properties, and Fit's size and fit would outlive
                                        # a switch to 1:1.
                                        add ss_browser_player at (Transform(xysize=SS_BROWSER_BOX, fit="contain", zoom=ss_browser_zoom, reset=True) if ss_browser_fit else Transform(zoom=ss_browser_zoom, reset=True))
                        else:
                            text "(no preview)" xalign 0.5 yalign 0.5
                    # Percent, not a "x1.25" factor: at this size the decimal point
                    # is easy to miss, and "125%" cannot be misread.
                    $ _zoom_disp = "%d%%" % round(ss_browser_zoom * 100)
                    hbox:
                        spacing 10
                        text "drag to move | wheel (or + / -) to zoom: [_zoom_disp]" size 11 yalign 0.5
                        textbutton "Fit" action Function(_ss_browser_set_fit, True) selected ss_browser_fit text_size 11 yalign 0.5
                        textbutton "1:1" action Function(_ss_browser_set_fit, False) selected (not ss_browser_fit) text_size 11 yalign 0.5
                        textbutton "Reset view (0)" action Function(_ss_browser_reset_view) text_size 11 yalign 0.5
                    $ _na = len(ss_browser_detail["anims"])
                    $ _fps = ss_browser_detail["fps"]
                    $ _fx = ss_browser_detail["has_effects"]
                    text "animations: [_na] | fps: [_fps] | effects: [_fx]" size 13
                    if ss_browser_detail["instance_packs"]:
                        $ _ip = ", ".join(ss_browser_detail["instance_packs"])
                        text "instance packs: [_ip]" size 12
                    if _sspj:
                        $ _src = _ss_browser_shown_path(_sspj)
                        text "source: [_src!q]" size 12
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
