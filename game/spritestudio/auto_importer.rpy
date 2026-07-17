# SpriteStudio Auto Importer
# This script runs during the init phase in developer mode.
# It automatically detects changes in .sspj projects and converts them.

init -10 python:
    import os
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

        converter = None
        changed = False

        for sspj_path in sspj_files:
            project_name = os.path.splitext(os.path.basename(sspj_path))[0]
            project_out_dir = os.path.join(out_dir, project_name)

            # 1. Newest mtime across the source project (its .sspj + .ssae /
            # .ssce / .png siblings) — the snapshot this run would convert.
            sspj_dir = os.path.dirname(sspj_path)
            latest_source_mtime = import_marker.latest_source_mtime(sspj_dir)

            # 2. Conversion is needed unless the last run both SUCCEEDED and
            # covered the current sources. Output mtimes alone cannot tell: the
            # converter writes .ssab files before textures and returns an error
            # part-way through on failure, leaving fresh-looking partial output
            # behind. So a success marker recording the source snapshot is
            # written only on ConverterResult.Success (below), and only that
            # marker skips reconversion (see ss_renpy.import_marker).
            needs_conversion = True
            if os.path.exists(project_out_dir):
                has_files = False
                for root, dirs, files in os.walk(project_out_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    if any(not f.startswith('.') for f in files):
                        has_files = True
                        break
                if has_files:
                    marker = import_marker.read_marker(project_out_dir)
                    if marker is not None and marker >= latest_source_mtime:
                        needs_conversion = False

            if needs_conversion:
                print(f"[SpriteStudio] Auto-converting project: {project_name} ...")
                
                if converter is None:
                    try:
                        converter = SsConverter()
                    except (OSError, ImportError, AttributeError) as e:
                        # ctypes.CDLL raises OSError on a missing/wrong-ABI
                        # libssconverter; a present-but-stale library missing an
                        # expected export raises AttributeError from _declare().
                        # Disable cleanly instead of a traceback at launch.
                        print(f"[SpriteStudio] Auto-importer disabled: could not load native converter ({e})")
                        return
                
                def on_log(msg):
                    print(f"  [Converter] {msg.strip()}")

                converter.convert(sspj_path, project_out_dir, on_log)
                
                # Block the init phase until conversion is finished
                while not converter.is_finished():
                    time.sleep(0.05)
                
                res = converter.get_result()
                if res == ConverterResult.Success:
                    print(f"[SpriteStudio] Successfully converted {project_name}.")
                    # Stamp the source snapshot this conversion covered; the
                    # freshness check above only trusts this marker.
                    try:
                        import_marker.stamp(project_out_dir, latest_source_mtime)
                    except OSError as e:
                        print(f"[SpriteStudio] Warning: could not write import marker ({e})")
                    changed = True
                else:
                    err = converter.get_error()
                    print(f"[SpriteStudio] Error converting {project_name}: {err}")

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

    # Run once at init; the function itself gates on config.developer.
    _ss_auto_import()
