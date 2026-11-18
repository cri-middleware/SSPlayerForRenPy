# Imported-asset picker — a demo-side browser for auto-discovered .ssab packs.
#
# Split out of script.rpy to keep that file focused on the story scenes. This
# screen lists EVERY .ssab the resolver finds under ss_assets/ (including packs
# the auto importer wrote to ss_assets/<project>/) and previews any of them live
# with a clickable animation list, drag to move and wheel to zoom. It only reuses
# the existing discovery (_ss_get_index / SsabMeta, from spritestudio.rpy) and the
# SSPlayer displayable, so neither the auto importer nor the core changes. The
# menu entry that jumps to `asset_picker_demo` lives in script.rpy. (Demo-side
# companion to the Shift+B dev browser in ss_browser.rpy.)

default ss_picker_pack = None     # selected pack's gamedir-relative .ssab path
default ss_picker_anims = []      # animation names for the selected pack
default ss_picker_player = None   # live SSPlayer for the preview
default ss_picker_zoom = 1.0      # preview scale (wheel / + - keys, 0 resets)
default ss_picker_view = 0        # bumped by a reset; see ss_picker_reset_view
default ss_picker_fit = True      # canvas fitted to the box, else at its own pixels

init python:
    def ss_picker_records():
        """Every discovered pack, sorted by path. Uses ALL index records (not
        just `ss_list_assets()`, which hides packs referenced as another pack's
        external instance, e.g. Ringo — pulled in by Ringo_tyu). A browser wants
        to show everything, so we key off the full .ssab path, not the stem."""
        try:
            return sorted(_ss_get_index().records(), key=lambda r: r.rel_path)
        except Exception:
            return []

    # The preview box. A pack opens with its whole authored canvas fitted into
    # it and centred — the framing a Reset view returns to, and what 100% on
    # the zoom readout means. The 1:1 button shows the canvas at its own pixels
    # instead, around the same centre.
    SS_PICKER_BOX = (820, 380)

    # Zoom range for the preview. The zoom is a Transform wrapped around the live
    # SSPlayer, so changing it neither rebuilds the player nor restarts the
    # animation — the sprite keeps playing while you scale it.
    SS_PICKER_ZOOM_MIN = 0.2
    # Up to 16 times the fitted size: a canvas the size of an Animate stage fits
    # at a few percent, and this still reaches its own pixels.
    SS_PICKER_ZOOM_MAX = 16.0
    SS_PICKER_ZOOM_STEP = 1.1        # one wheel notch

    def ss_picker_zoom_by(factor):
        """Scale the preview by `factor`, clamped to the range above."""
        z = store.ss_picker_zoom * factor
        store.ss_picker_zoom = max(SS_PICKER_ZOOM_MIN,
                                   min(SS_PICKER_ZOOM_MAX, z))

    def ss_picker_reset_view():
        """Put the preview back the way a pack opens: fitted, centred.

        A new view number is a new drag, placed afresh; see the drag in
        ss_asset_picker for why it takes one."""
        store.ss_picker_zoom = 1.0
        store.ss_picker_view += 1

    def ss_picker_set_fit(fit):
        """Fit the canvas to the box (True) or show it at its own pixels, and
        start that framing at 100%, centred. The choice holds across packs."""
        store.ss_picker_fit = fit
        ss_picker_reset_view()

    def _ss_picker_stop_audio():
        # Held-and-swapped preview player: stop its sound before we replace it, so
        # a Sound pack does not keep playing after you pick another (the library
        # reaper also catches it shortly, this is the immediate + recommended way).
        old = getattr(store, "ss_picker_player", None)
        if old is not None:
            try:
                old.ss_stop_audio()
            except Exception:
                pass

    def ss_picker_select(rel_path, anims):
        """Select a pack by its .ssab path: build a live SSPlayer for its 1st anim."""
        _ss_picker_stop_audio()
        store.ss_picker_pack = rel_path
        # A new pack is a new subject: start it fitted rather than at whatever
        # scale the previous one needed. Switching ANIMATION keeps the zoom, so
        # you can compare two clips of one pack at the same scale.
        store.ss_picker_zoom = 1.0
        try:
            store.ss_picker_anims = list(anims)
            anim = store.ss_picker_anims[0] if store.ss_picker_anims else None
            store.ss_picker_player = SSPlayer(rel_path, animation=anim)
        except Exception as e:
            store.ss_picker_player = None
            store.ss_picker_anims = []
            renpy.notify("Preview failed: %s" % (e,))

    def ss_picker_play(anim):
        """Switch the previewed animation by rebuilding the SSPlayer with `anim`
        as its initial animation — the path picking a pack takes, so the
        preview starts `anim` from its first frame."""
        rel = store.ss_picker_pack
        if not rel:
            return
        _ss_picker_stop_audio()
        try:
            store.ss_picker_player = SSPlayer(rel, animation=anim)
        except Exception as e:
            renpy.notify("Play failed: %s" % (e,))

label asset_picker_demo:
    # Start unselected (the right pane shows "Select a pack on the left."). We
    # deliberately do NOT auto-select a pack: auto-building a live SSPlayer on
    # open would turn any pack-specific render failure into a crash-on-open;
    # letting the user pick keeps the browser reachable.
    call screen ss_asset_picker
    return

screen ss_asset_picker():
    modal True
    zorder 100
    key "K_ESCAPE" action Return()

    # Wheel = zoom the preview. These sit BEFORE the body, so they are offered
    # the event last: a wheel over one of the two lists still scrolls it (a
    # `mousewheel True` viewport only takes the event while the pointer is
    # inside it) and anywhere else it reaches these and scales the sprite.
    # Binding the wheel here also keeps it away from rollback while the browser
    # is up. + / - / 0 do the same from the keyboard.
    key "mousedown_4" action Function(ss_picker_zoom_by, SS_PICKER_ZOOM_STEP)
    key "mousedown_5" action Function(ss_picker_zoom_by, 1.0 / SS_PICKER_ZOOM_STEP)
    key "K_EQUALS" action Function(ss_picker_zoom_by, SS_PICKER_ZOOM_STEP)
    key "K_PLUS" action Function(ss_picker_zoom_by, SS_PICKER_ZOOM_STEP)
    key "K_MINUS" action Function(ss_picker_zoom_by, 1.0 / SS_PICKER_ZOOM_STEP)
    key "K_0" action Function(ss_picker_reset_view)

    add Solid("#1c2026")

    $ _recs = ss_picker_records()
    $ _count = len(_recs)
    $ _cur_anim = ss_picker_player.ss_get_current_animation() if ss_picker_player is not None else None
    $ _cur_disp = ss_escape(_cur_anim) if _cur_anim else "—"

    # --- header (pinned top) -------------------------------------------
    frame:
        xfill True
        yalign 0.0
        background "#00000099"
        padding (24, 12)
        hbox:
            spacing 16
            text _("Imported Asset Browser") size 26 color "#ffffff" yalign 0.5
            text _("auto-discovered under ss_assets/ (includes auto-imported packs) — [_count] found") size 14 color "#9aa0ab" yalign 0.5

    # --- body: pack list (left) + preview (right), centered ------------
    # NOTE: the viewports below use `mousewheel True draggable True` and do NOT
    # use `scrollbars "vertical"`. This demo runs on a minimal GUI (no
    # screens.rpy), so the default scrollbar styles are absent and a
    # `scrollbars`-enabled viewport collapses its content to zero size — the
    # Packs list then renders empty even though the index finds the packs.
    # Mouse-wheel + drag scrolling works without those styles.
    hbox:
        xalign 0.5
        yalign 0.5
        spacing 16

        vbox:
            spacing 6
            text _("Packs ([_count])") size 18 color "#7fd0ff"
            text _("scroll: wheel / drag") size 11 color "#667085"
            viewport:
                mousewheel True
                draggable True
                xsize 320
                ysize 540
                vbox:
                    spacing 2
                    if _recs:
                        for _r in _recs:
                            textbutton "[_r.stem]":
                                action Function(ss_picker_select, _r.rel_path, _r.anim_names)
                                text_size 15
                                text_color ("#ffd479" if _r.rel_path == ss_picker_pack else "#dddddd")
                    else:
                        text _("No .ssab found under ss_assets/.") size 14 color "#ff8888"

        vbox:
            spacing 10
            if ss_picker_pack:
                text "[ss_picker_pack]" size 24 color "#ffffff"
                # Preview: the SSPlayer, its canvas fitted into SS_PICKER_BOX, is
                # wrapped in a draggable `drag` and scaled by ss_picker_zoom. We
                # deliberately do NOT clip: zoomed in, the parts past the box are
                # what the drag is there to bring into view, so the sprite renders
                # in full (it may spill over the surrounding UI).
                frame:
                    xsize 820
                    ysize 380
                    padding (0, 0)
                    background Solid("#101216")
                    if ss_picker_player is not None:
                        draggroup:
                            # One drag per pack and view number. The screen hands a
                            # rebuilt drag the one it replaces, and a drag takes that
                            # one's position, so a new pack or a Reset view would stay
                            # where the last drag was dropped; a new index key builds
                            # the drag afresh. The name changes with it because the
                            # group also keeps each dropped drag's position by name.
                            for _view index _view in [(ss_picker_pack, ss_picker_view)]:
                                drag:
                                    drag_name "%s#%d" % _view
                                    draggable True
                                    drag_offscreen True
                                    xpos 0.5 ypos 0.5 xanchor 0.5 yanchor 0.5
                                    # The zoom scales the whole rendered sprite, so the
                                    # drag's hit area grows with it and a scaled-up
                                    # sprite stays draggable by any of its pixels.
                                    # reset: a screen update hands the new transform the old
                                    # one's properties, and Fit's size and fit would outlive
                                    # a switch to 1:1.
                                    add ss_picker_player at (Transform(xysize=SS_PICKER_BOX, fit="contain", zoom=ss_picker_zoom, reset=True) if ss_picker_fit else Transform(zoom=ss_picker_zoom, reset=True))
                    else:
                        text _("(no preview)") xalign 0.5 yalign 0.5 color "#888888"
                # Percent, not a "x1.25" factor: at 11px the decimal point is
                # easy to miss, and "125%" cannot be misread.
                $ _zoom_disp = "%d%%" % round(ss_picker_zoom * 100)
                hbox:
                    spacing 12
                    text _("drag to move  |  wheel (or + / -) to zoom: [_zoom_disp]") size 11 color "#667085" yalign 0.5
                    textbutton _("Fit") action Function(ss_picker_set_fit, True) selected ss_picker_fit text_size 11 yalign 0.5
                    textbutton _("1:1") action Function(ss_picker_set_fit, False) selected (not ss_picker_fit) text_size 11 yalign 0.5
                    textbutton _("Reset view (0)") action Function(ss_picker_reset_view) text_size 11 yalign 0.5
                $ _na = len(ss_picker_anims)
                text _("animation: [_cur_disp]  |  [_na] animation(s)") size 14 color "#9aa0ab"
                text _("click an animation to preview:") size 13 color "#9aa0ab"
                viewport:
                    mousewheel True
                    draggable True
                    xsize 820
                    ysize 110
                    vbox:
                        spacing 2
                        for _a in ss_picker_anims:
                            # Escaped label, raw name to the action: Ren'Py
                            # interpolates [..] / {..} in a button's text, so an
                            # animation called "[NG]_dance" would raise NameError.
                            textbutton ss_escape(_a):
                                action Function(ss_picker_play, _a)
                                text_size 14
                                text_color ("#ffd479" if _a == _cur_anim else "#dddddd")
            else:
                vbox:
                    xsize 820
                    ysize 540
                    text _("Select a pack on the left.") xalign 0.5 yalign 0.5 color "#888888"

    # --- footer (pinned bottom) ----------------------------------------
    frame:
        xfill True
        yalign 1.0
        background "#00000099"
        padding (24, 10)
        hbox:
            spacing 24
            text _("click a pack to preview | click an animation to switch | drag / wheel to move / zoom | Esc to return") size 14 color "#9aa0ab" yalign 0.5
            textbutton _("Close") action Return() text_size 16 yalign 0.5
