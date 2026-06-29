# Imported-asset picker — a demo-side browser for auto-discovered .ssab packs.
#
# Split out of script.rpy to keep that file focused on the story scenes. This
# screen lists EVERY .ssab the resolver finds under ss_assets/ (including packs
# the auto importer wrote to ss_assets/<project>/) and previews any of them live
# with a clickable animation list. It only reuses the existing discovery
# (_ss_get_index / SsabMeta, from spritestudio.rpy) and the SSPlayer displayable,
# so neither the auto importer nor the core changes. The menu entry that jumps to
# `asset_picker_demo` lives in script.rpy. (Demo-side companion to the Shift+B
# dev browser in ss_browser.rpy.)

default ss_picker_pack = None     # selected pack's gamedir-relative .ssab path
default ss_picker_anims = []      # animation names for the selected pack
default ss_picker_player = None   # live SSPlayer for the preview

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

    # Fixed preview box. Giving the SSPlayer an explicit `size` makes it a
    # definite-size displayable (so the draggable `drag` wrapping it has a real
    # size) and centers the animation in that box; larger sprites overflow it and
    # are clipped to the preview window — drag repositions them within the window.
    SS_PICKER_BOX = (820, 380)

    def ss_picker_select(rel_path, anims):
        """Select a pack by its .ssab path: build a live SSPlayer for its 1st anim."""
        store.ss_picker_pack = rel_path
        try:
            store.ss_picker_anims = list(anims)
            anim = store.ss_picker_anims[0] if store.ss_picker_anims else None
            store.ss_picker_player = SSPlayer(rel_path, animation=anim, size=SS_PICKER_BOX)
        except Exception as e:
            store.ss_picker_player = None
            store.ss_picker_anims = []
            renpy.notify("Preview failed: %s" % (e,))

    def ss_picker_play(anim):
        """Switch the previewed animation by REBUILDING the SSPlayer with `anim`
        as its initial animation.

        An in-place `player.ss_play(anim)` looks like it does nothing here: the
        anim-button click restarts the screen interaction, which resets the
        displayable's shown-time, and SSPlayer.render() reads that as a re-show
        and calls `_start_initial()` — replaying the player's ORIGINAL initial
        animation and clobbering the switch (so it snaps back to e.g. attack1).
        Rebuilding makes `anim` the new initial, so the re-show path replays the
        animation we actually want. (Same proven path as picking a pack.)"""
        rel = store.ss_picker_pack
        if not rel:
            return
        try:
            store.ss_picker_player = SSPlayer(rel, animation=anim, size=SS_PICKER_BOX)
        except Exception as e:
            renpy.notify("Play failed: %s" % (e,))

label asset_picker_demo:
    # Start unselected (the right pane shows "Select a pack on the left."). We
    # deliberately do NOT auto-select a pack: previewing renders a live SSPlayer,
    # and a few packs (e.g. the Mask sample) currently hit a mask-shader compile
    # issue on some GPUs — letting the user choose avoids crashing on open.
    call screen ss_asset_picker
    return

screen ss_asset_picker():
    modal True
    zorder 100
    key "K_ESCAPE" action Return()

    add Solid("#1c2026")

    $ _recs = ss_picker_records()
    $ _count = len(_recs)
    $ _cur_anim = ss_picker_player.ss_get_animation() if ss_picker_player is not None else None
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
    # Mouse-wheel + drag scrolling works without those styles. (ss_browser.rpy
    # had the same latent bug.)
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
                # Preview: the SSPlayer (built with size=SS_PICKER_BOX) is wrapped
                # in a draggable `drag`. We deliberately do NOT clip — a clip window
                # smaller than the sprite hides the parts that overflow (Ringo would
                # show up headless), and the whole point of the drag is to bring
                # those parts into view. So the sprite renders in full (it may spill
                # over the surrounding UI) and you drag it to reposition.
                frame:
                    xsize 820
                    ysize 380
                    padding (0, 0)
                    background Solid("#101216")
                    if ss_picker_player is not None:
                        draggroup:
                            drag:
                                drag_name ss_picker_pack
                                draggable True
                                drag_offscreen True
                                xpos 0.5 ypos 0.5 xanchor 0.5 yanchor 0.5
                                add ss_picker_player
                    else:
                        text _("(no preview)") xalign 0.5 yalign 0.5 color "#888888"
                text _("drag the preview to reposition") size 11 color "#667085"
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
                            textbutton _a:
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
            text _("click a pack to preview | click an animation to switch | Esc to return") size 14 color "#9aa0ab" yalign 0.5
            textbutton _("Close") action Return() text_size 16 yalign 0.5
