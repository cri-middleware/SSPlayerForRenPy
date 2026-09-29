# SpriteStudio Auto Importer
# This script runs during the init phase in developer mode.
# It automatically detects changes in .sspj projects and converts them.

init -10 python:
    import os
    import re
    import sys
    import glob
    import time

    # Keep the freshness marker out of distributed builds. It is a build-machine
    # artifact (written by the importer below / tools/ss_stamp_import.py), useless
    # to players — the importer is dev-only — and Ren'Py's built-in dotfile
    # exclusion covers only its OWN base dir, not game/ss_assets/, so a broad
    # asset rule or the "**"->all catch-all would otherwise ship it. Registered
    # unconditionally (not dev-gated) so any project holding this drop-in is
    # covered. A game whose options.rpy routes game/ss_assets/** into an archive
    # at an EARLIER init must repeat this there too (first-match-wins by order).
    try:
        build.classify('**/.ss_import_ok', None)
    except Exception:
        pass

    def _ss_source_changed(fn):
        """A watched source file changed: reload, which re-runs the import below.

        Ren'Py's own rules (config.autoreload_functions) send every .png and
        every .ogg to an image / audio cache flush and return WITHOUT reloading,
        first match wins. That is right for game assets and wrong for these
        files: they are conversion INPUTS, so a repainted cell image would flush
        a texture Ren'Py never loaded and the re-import would silently not
        happen. This rule is registered ahead of them, and does what the key
        does — reload the script.
        """
        # The same guard check_autoreload sets on its own path: reload_script
        # saves and restores around an interaction, and that interaction must
        # not start a second reload. Ren'Py resets it when the reload lands.
        renpy.loader.reloading = True
        renpy.reload_script()

    # A conversion nobody sees is the same as no conversion: the game reloads,
    # the old artwork is still on screen, and nothing says why. print() goes to
    # stdout — log.txt under the launcher — which is not where a creator is
    # looking while iterating, so the outcome is also raised in-game; the bottom
    # of this file delivers it.
    def _ss_import_notice(imported, failed, skipped, stale):
        parts = []
        if imported:
            parts.append("imported " + ", ".join(sorted(imported)))
        if failed:
            parts.append("FAILED " + ", ".join(sorted(failed)) + " — see the console")
        if skipped:
            parts.append("SKIPPED %d .sspj named like another project — see the console"
                         % len(skipped))
        if stale:
            parts.append("%d file(s) the projects no longer make are still in the "
                         "output — see the console" % stale)
        if parts:
            renpy.session["_ss_import_notice"] = "SpriteStudio: " + "; ".join(parts)

    def _ss_show_import_notice():
        msg = renpy.session.pop("_ss_import_notice", None)
        if msg:
            try:
                renpy.notify(msg)
            except Exception:
                pass  # a project without the stock `notify` screen

    def _ss_auto_import():
        if not config.developer:
            return

        # Safely read from store (if user defined them via `define -15 ss_source_dir = ...`)
        source_dir = getattr(store, "ss_source_dir", None)
        if source_dir is None:
            source_dir = os.path.abspath(os.path.join(config.basedir, "SpriteStudio_Source"))
        else:
            source_dir = os.path.abspath(os.path.join(config.basedir, source_dir))
            
        out_dir = getattr(store, "ss_output_dir", None)
        if out_dir is None:
            out_dir = os.path.abspath(os.path.join(config.basedir, "game", "ss_assets"))
        else:
            out_dir = os.path.abspath(os.path.join(config.basedir, out_dir))

        if not os.path.exists(source_dir):
            return

        # Ensure the python bindings are in sys.path
        py_dir = os.path.join(config.basedir, "game", "spritestudio", "python")
        if py_dir not in sys.path:
            sys.path.insert(0, py_dir)

        try:
            from ss_renpy.converter import SsConverter, ConverterResult
            from ss_renpy import import_marker
        except ImportError as e:
            print(f"[SpriteStudio] Auto-importer disabled: could not load native converter ({e})")
            return

        sspj_files = glob.glob(os.path.join(source_dir, "**", "*.sspj"), recursive=True)
        if not sspj_files:
            return

        # Claim every path under the source dir, ahead of Ren'Py's built-in
        # image and audio rules (see _ss_source_changed).
        # config.autoreload_functions is rebuilt before each init phase, so this
        # re-applies on every reload.
        config.autoreload_functions.insert(
            0, ("^" + re.escape(source_dir.replace("\\", "/")) + "(?:/|$)",
                _ss_source_changed))

        # Ren'Py rewrites game/cache/shaders.txt while it starts up (its shader
        # cache is dirty the moment it loads one), and watches it like every
        # other file it loads through its loader — so with autoreload on, that
        # rewrite reloads the game, which rewrites it again, forever. It
        # happens with or without this importer, and the file is a generated
        # artifact, never an import input — so keep it out of the watch list.
        if "cache/shaders.txt" not in config.autoreload_blacklist:
            config.autoreload_blacklist.append("cache/shaders.txt")

        # The glob above is an input too, so watch the folder itself: a project
        # added or removed changes the directory's own mtime, and the import
        # that follows the reload picks it up. Without this, a project dropped
        # in while the game runs would wait for a keypress that — autoreload
        # being already on — would only turn the watch back off.
        renpy.loader.add_auto(source_dir.replace("\\", "/"))

        # Loaded up front, not on the first conversion: what the converter
        # version is decides whether an output is current (see step 2).
        try:
            converter = SsConverter()
            converter_version = converter.version()
        except (OSError, ImportError, AttributeError) as e:
            # ctypes.CDLL raises OSError on a missing/wrong-ABI libssconverter; a
            # present-but-stale library missing an expected export raises
            # AttributeError from _declare(). Disable cleanly instead of a
            # traceback at launch.
            print(f"[SpriteStudio] Auto-importer disabled: could not load native converter ({e})")
            return

        changed = False
        imported = []
        failed = []
        skipped = []
        stale = 0

        def _shown(path):
            return os.path.relpath(path, config.basedir).replace("\\", "/")

        for sspj_path, project_out_dir, owner in import_marker.plan_outputs(sspj_files, out_dir):
            project_name = os.path.basename(project_out_dir)

            # 1. Watch the source project (its .sspj + .ssae / .ssce / .png
            # siblings) — the same files the snapshot in step 2 reads. Ren'Py's
            # autoreload watches every file it opens through its loader — the
            # .rpy, the textures, the .ssab packs — but never these: they sit
            # outside game/ and are read with plain os calls, so a save in
            # SpriteStudio would otherwise sit there until someone pressed the
            # key. add_auto() is a no-op while autoreload is off, so this arms on
            # the first Shift+R and re-registers on every reload (Ren'Py empties
            # the watch list each time). A project skipped below is watched too,
            # so renaming its .sspj reloads and converts it.
            sspj_dir = os.path.dirname(sspj_path)
            renpy.loader.add_auto(sspj_dir.replace("\\", "/"))
            for src in import_marker.iter_source_files(sspj_dir):
                renpy.loader.add_auto(src.replace("\\", "/"))

            if owner is not None:
                print(f"[SpriteStudio] Skipped {_shown(sspj_path)}: {_shown(project_out_dir)} "
                      f"is converted from {_shown(owner)}, and one folder holds one "
                      "project. Rename one of the two .sspj files.")
                skipped.append(sspj_path)
                continue

            # 2. Conversion is needed unless the last run SUCCEEDED from what
            # this run would convert: this .sspj, its sources as they are now,
            # and this converter. Output mtimes alone cannot tell: the converter
            # writes .ssab files before textures and returns an error part-way
            # through on failure, leaving fresh-looking partial output behind.
            # So a success marker recording that snapshot is written only on
            # ConverterResult.Success (below), and only a marker equal to it
            # skips reconversion (see ss_renpy.import_marker).
            current = import_marker.snapshot(sspj_path, converter_version)
            needs_conversion = True
            if os.path.exists(project_out_dir):
                has_files = False
                for root, dirs, files in os.walk(project_out_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    if any(not f.startswith('.') for f in files):
                        has_files = True
                        break
                if has_files and import_marker.read_marker(project_out_dir) == current:
                    needs_conversion = False

            if needs_conversion:
                print(f"[SpriteStudio] Auto-converting project: {project_name} ...")

                def on_log(msg):
                    print(f"  [Converter] {msg.strip()}")

                started = time.time()
                converter.convert(sspj_path, project_out_dir, on_log)
                
                # Block the init phase until conversion is finished
                while not converter.is_finished():
                    time.sleep(0.05)
                
                res = converter.get_result()
                if res == ConverterResult.Success:
                    print(f"[SpriteStudio] Successfully converted {project_name}.")
                    # Stamp the snapshot this conversion was made from; the
                    # freshness check above only trusts this marker.
                    try:
                        import_marker.stamp(project_out_dir, current)
                    except OSError as e:
                        print(f"[SpriteStudio] Warning: could not write import marker ({e})")
                    changed = True
                    imported.append(project_name)
                    # The converter overwrites and deletes nothing, so a pack
                    # from a removed .ssae stays, loading and shipping. Name
                    # it; deleting is the creator's call.
                    left = import_marker.stale_outputs(project_out_dir, started)
                    if left:
                        print(f"[SpriteStudio] {project_name}: not made by the project "
                              f"any more, delete if unused: "
                              + ", ".join(_shown(p) for p in left))
                        stale += len(left)
                else:
                    err = converter.get_error()
                    print(f"[SpriteStudio] Error converting {project_name}: {err}")
                    failed.append(project_name)

        # If we wrote any new/updated .ssab files this run, refresh Ren'Py's
        # file index. renpy.list_files() — which the asset browser (Shift+B) and
        # the pack resolver use to discover packs — is built once at boot, so
        # files created here during init are otherwise invisible until the next
        # launch (loading a pack by exact path still works; only enumeration is
        # stale). index_files() is the same rescan Ren'Py runs at startup.
        if changed:
            try:
                renpy.loader.index_files()
                print("[SpriteStudio] Asset index refreshed; newly imported packs are now discoverable.")
            except Exception as e:
                print(f"[SpriteStudio] Warning: could not refresh asset index ({e}); "
                      "newly imported packs may not appear in the browser until restart.")

        _ss_import_notice(imported, failed, skipped, stale)

        # The watch is only live in autoreload mode, and the key that turns that
        # on is a TOGGLE with nothing on screen to say which side it is on
        # (press once: on, and it reloads; press again: off, and it does not).
        # So say it here, once per launch.
        if renpy.get_autoreload():
            print(f"[SpriteStudio] Hot reload ON — watching {len(sspj_files)} project(s); "
                  "save in SpriteStudio and Ren'Py re-imports and reloads by itself.")
        else:
            print("[SpriteStudio] Hot reload OFF — press Shift+R once to turn it on; "
                  "after that a save in SpriteStudio re-imports and reloads by itself.")

    # Run once at init; the function itself gates on config.developer.
    _ss_auto_import()

    # Show the outcome on the first interaction that follows, from wherever the
    # game got back into play: a fresh launch enters through start_callbacks, a
    # reload through the save it restores, and neither hook fires on both routes
    # (measured — the reload path leaves start_callbacks unrun, and the notify
    # raised from after_load never reaches the screen). The periodic callback
    # runs inside the interaction itself, so it covers every route.
    # renpy.session carries the notice across the utter restart in between and
    # never reaches a save file, so it ships nowhere.
    if config.developer and _ss_show_import_notice not in config.periodic_callbacks:
        config.periodic_callbacks.append(_ss_show_import_notice)
