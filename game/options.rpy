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

# --- Packaging (build.classify) for THIS demo project -----------------------
# build.classify decides which package(s) each file ships in, FIRST-MATCH-WINS by
# registration order (earliest-registered pattern for a file decides it). These
# run at init -20, before the library's own rules (spritestudio.rpy, init -10),
# so the demo-specific rules here win. A downstream game keeps its OWN options.rpy
# and is unaffected by anything below.
#
# Optional: pack the demo's SpriteStudio assets into a .rpa archive. Ren'Py ships
# game files LOOSE by default and only builds a `.rpa` for files classified into a
# declared archive. SSPlayer loads packs through renpy.loader.load / Image, so
# they work either loose OR inside a `.rpa` (CLAUDE.md §2) — a transparent toggle.
define -30 ss_pack_assets_into_rpa = True   # set False to distribute assets loose
init -20 python:
    # Keep this development repo's tooling / build output / docs out of the
    # packaged demo. Registered FIRST so a stray asset (.ssab / .wav / …) sitting
    # inside one of these dev dirs is excluded rather than swept in by the
    # library's `**.ssab -> all` or the `**.wav/**.mp3 -> all` rules below.
    # (`*.md` / `*.txt` match root-level files only — `*` does not cross `/` — so
    # bundled licences under game/…/libs/ are kept.) These are demo/repo-specific
    # paths, which is exactly why they live here and not in the reusable library.
    for _dev_pat in ('renpy-sdk/**', 'SpriteStudio-SDK/**', 'SpriteStudio_Source/**',
                     'web_out/**', 'web_out.zip', 'dist/**', 'docs/**', 'mkdocs.yml',
                     '*.md', '*.txt', '.git/**', 'tools/**', 'scripts/**'):
        build.classify(_dev_pat, None)

    # Route the demo's asset tree (.ssab + textures + audio) into the .rpa archive.
    if ss_pack_assets_into_rpa:
        build.archive("ssdata", "all")            # "all" tag: in every package
        build.classify("game/ss_assets/**", "ssdata")

    # Ren'Py's web build drops uncompressed audio and unknown extensions, so make
    # sure the demo's SpriteStudio audio ships. Registered AFTER the archive above
    # so audio under game/ss_assets/ still lands in ssdata.rpa when the toggle is
    # on. (The library only classifies its own **.ssab format; generic audio is
    # the game's call — hence these live here. A downstream game that plays SS
    # Audio events must add the same two lines to its own options.rpy.)
    build.classify('**.wav', 'all')
    build.classify('**.mp3', 'all')
