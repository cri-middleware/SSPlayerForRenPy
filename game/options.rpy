# SpriteStudio Player for Ren'Py — demo project configuration.
#
# This is part of the DEMO, not the library (see README.md). It exists so the
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
# own. See docs/en/export.md (Desktop Export).
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
# they work either loose OR inside a `.rpa` — a transparent toggle.
define -30 ss_pack_assets_into_rpa = True   # set False to distribute assets loose
init -20 python:
    # Keep this development repo's tooling / build output / docs out of the
    # packaged demo. Registered FIRST so a stray asset (.ssab / .wav / …) sitting
    # inside one of these dev dirs is excluded rather than swept in by the
    # `**.ssab / **.ssqb -> all` / `**.wav/**.mp3 -> all` rules below.
    # (`*.md` / `*.txt` match root-level files only — `*` does not cross `/` — so
    # bundled licences under game/…/libs/ are kept.) These are demo/repo-specific
    # paths, which is exactly why they live here and not in the reusable library.
    #
    # `site/**` is the built documentation (scripts/build-docs.*, and everything
    # scripts/build-pages.* puts beside it). Excluding `docs/**` is not enough:
    # the build COPIES the screencasts into site/*/assets/, and Ren'Py's own
    # rules classify `**.webm` into every package — so a working tree that has
    # ever built the docs was shipping ~20 MB of documentation video in the
    # demo, web export included.
    for _dev_pat in ('renpy-sdk/**', 'SpriteStudio-SDK/**', 'SpriteStudio_Source/**',
                     'web_out/**', 'web_out.zip', 'dist/**', 'site/**',
                     'docs/**', 'mkdocs*.yml', 'overrides/**',
                     '*.md', '*.txt', '.git/**', 'tools/**', 'scripts/**'):
        build.classify(_dev_pat, None)

    # Exclude the auto-importer's dev-only freshness marker BEFORE the ss_assets
    # rule below claims it: it lives under game/ss_assets/<project>/ (so the
    # archive rule would otherwise ship it), is useless to players, and leaks a
    # source mtime. First-match-wins, so this must precede the ss_assets classify.
    build.classify('**/.ss_import_ok', None)

    # Route the demo's asset tree (.ssab + textures + audio) into the .rpa archive.
    if ss_pack_assets_into_rpa:
        build.archive("ssdata", "all")            # "all" tag: in every package
        build.classify("game/ss_assets/**", "ssdata")

    # Ren'Py's web build drops uncompressed audio and unknown extensions (incl. the
    # `.ssab` / `.ssqb` SpriteStudio pack formats), so classify the demo's assets
    # explicitly. These are the GAME's own content — not the reusable library's
    # files — so they live here, not in spritestudio.rpy. Registered AFTER the
    # archive above so assets under game/ss_assets/ still land in ssdata.rpa when
    # the toggle is on. A downstream game must add `**.ssab` / `**.ssqb` to its own
    # options.rpy (and the `**.wav` / `**.mp3` lines too if it plays SS Audio events).
    build.classify('**.ssab', 'all')          # the SpriteStudio pack format
    build.classify('**.ssqb', 'all')          # the SpriteStudio sequence pack
    build.classify('**.wav', 'all')
    build.classify('**.mp3', 'all')
