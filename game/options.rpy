# SpriteStudio Player for Ren'Py — demo project configuration.
#
# This is part of the DEMO, not the library (see CLAUDE.md). It exists so the
# project runs as a standalone Ren'Py app via `renpy-sdk/renpy.sh .`.
#
# The key line is `gui.init(...)`: it triggers `layout.defaults()`
# (renpy/common/00gui.rpy), which wires up the quit / main-menu prompts. Without
# it, a bare project (script.rpy only) crashes when you close the window with
#   AttributeError: 'Layout' object has no attribute 'yesno_prompt'
# because the layout system was never initialized.

define config.name = _("SpriteStudio Player for Ren'Py — Demo")
define config.version = "demo"
# Base name for desktop/web distributions (Build Distributions / scripts/
# deploy-desktop.*). WITHOUT this, Ren'Py leaves the packaged app's
# CFBundleExecutable / executable name empty, producing a `-mac.zip` whose `.app`
# has no launcher binary and will not start. Downstream games should set their
# own. See docs/export.md (Desktop Export).
define build.name = "SSPlayerForRenPy"
define config.save_directory = "SSPlayerForRenPy-demo"
define config.window_title = "SpriteStudio Player for Ren'Py — Demo"
define config.has_autosave = False
define config.has_quicksave = False

init python:
    gui.init(1280, 720)

# --- Optional: pack the SpriteStudio demo assets into a .rpa archive --------
# Ren'Py distributes game files LOOSE by default; it only builds a `.rpa` for
# files you classify into a declared archive. SSPlayer loads packs through
# renpy.loader.load / Image, so they work either loose OR inside a `.rpa` (see
# CLAUDE.md §2), which makes this a safe, transparent toggle.
#
# This MUST run at an earlier init priority than the library's `**.ssab -> 'all'`
# classify (spritestudio.rpy, init -10): build.classify is FIRST-MATCH-WINS — the
# earliest-*registered* pattern for a file decides its package — and patterns are
# registered in init order. Hence init -20 here so the archive pattern wins.
define -30 ss_pack_assets_into_rpa = True   # set False to distribute assets loose
init -20 python:
    if ss_pack_assets_into_rpa:
        # Declare the archive (included in every package via the "all" tag) and
        # route the demo's asset tree (.ssab + textures + audio) into it.
        build.archive("ssdata", "all")
        build.classify("game/ss_assets/**", "ssdata")
