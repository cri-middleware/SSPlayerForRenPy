# SpriteStudio Asset Browser — a developer-mode inspector / snippet generator.
#
# Press **Shift+B** in developer mode to toggle it. It lists every .ssab the
# resolver can find (ss_list_assets), previews any animation live, and saves a
# ready-to-paste snippet for the role you pick (character / effect / UI) — so a
# creator picks the role while watching the animation, instead of guessing.
#
# It sits on top of the zero-config resolver + SSInternalPlayer. Only the hotkey
# registration is dev-gated, so this file is harmless in a release build (the
# screen exists but is unreachable). Drop the file to remove the tool entirely.

init python:
    import os as _ss_os
    from ss_renpy import snippet as _ss_snippet

    def _ss_browser_escape(s):
        # Ren'Py text treats { and [ as tags / substitutions — escape for display
        # (the file export keeps the raw, correct text).
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

    def _ss_browser_select(name, anim=None):
        """Select a pack (and optional animation); build the live preview."""
        store.ss_browser_pack = name
        d = _ss_browser_detail(name)
        store.ss_browser_detail = d
        if anim is None and d["anims"]:
            anim = d["anims"][0]
        store.ss_browser_anim = anim
        store.ss_browser_role = _ss_browser_default_role(d)
        try:
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


screen _ss_browser_key():
    key "shift_K_b" action ToggleScreen("ss_browser")


screen ss_browser():
    modal True
    zorder 200
    key "K_ESCAPE" action Hide("ss_browser")

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
                        for _n in sorted(ss_list_assets().keys()):
                            textbutton _n action Function(_ss_browser_select, _n) text_size 14

            # --- center: live preview + animation list ---------------------
            vbox:
                spacing 8
                xsize 480
                if ss_browser_pack:
                    text "[ss_browser_pack]" size 20
                    frame:
                        xsize 470
                        ysize 360
                        background Solid("#222222")
                        if ss_browser_player is not None:
                            add ss_browser_player xalign 0.5 yalign 0.5
                        else:
                            text "(no preview)" xalign 0.5 yalign 0.5
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
                                textbutton _a action Function(_ss_browser_select, ss_browser_pack, _a) text_size 13
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
                    textbutton "Effect" action SetVariable("ss_browser_role", "effect") text_size 13
                    textbutton "UI" action SetVariable("ss_browser_role", "ui") text_size 13
                if ss_browser_pack and ss_browser_role:
                    $ _snip_disp = _ss_browser_escape(_ss_browser_snippet(ss_browser_detail["path"], ss_browser_role, ss_browser_detail["anims"]))
                    frame:
                        xsize 360
                        ysize 360
                        background Solid("#111111")
                        viewport:
                            mousewheel True
                            draggable True
                            text "[_snip_disp]" size 13
                    textbutton "Save snippet -> ss_snippets.txt" action Function(_ss_browser_export, ss_browser_pack, ss_browser_detail["path"], ss_browser_role, ss_browser_detail["anims"]) text_size 13
                else:
                    text "Pick a pack, then a role." size 13
                null height 6
                textbutton "Close" action Hide("ss_browser") text_size 14
