# SpriteStudio Auto Importer
# This script runs during the init phase in developer mode.
# It automatically detects changes in .sspj projects and converts them.

init -10 python:
    import os
    import sys
    import glob
    import time

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

            # 1. Find the latest modification time in the source project directory
            # (Checks all files like .ssae, .ssce, .png alongside the .sspj)
            sspj_dir = os.path.dirname(sspj_path)
            latest_source_mtime = 0
            for root, dirs, files in os.walk(sspj_dir):
                # Prune hidden directories (.git etc.) — their contents are not
                # dot-prefixed and would spuriously trigger reconversion.
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for f in files:
                    # Ignore hidden files
                    if f.startswith('.'):
                        continue
                    try:
                        mtime = os.path.getmtime(os.path.join(root, f))
                    except OSError:
                        continue  # vanished mid-scan / dangling symlink
                    if mtime > latest_source_mtime:
                        latest_source_mtime = mtime
            
            # 2. Conversion is needed unless the last run both SUCCEEDED and
            # covered the current sources. Output mtimes alone cannot tell:
            # the converter writes .ssab files before textures and returns an
            # error part-way through on failure, which would leave fresh-looking
            # partial output behind. So a success marker recording the source
            # snapshot is written only on ConverterResult.Success (below), and
            # only that marker skips reconversion.
            marker_path = os.path.join(project_out_dir, ".ss_import_ok")
            needs_conversion = True
            if os.path.exists(project_out_dir):
                has_files = False
                for root, dirs, files in os.walk(project_out_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    if any(not f.startswith('.') for f in files):
                        has_files = True
                        break
                if has_files:
                    try:
                        with open(marker_path, "r") as fh:
                            if float(fh.read().strip()) >= latest_source_mtime:
                                needs_conversion = False
                    except (OSError, ValueError):
                        pass  # missing/corrupt marker -> reconvert

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
                        with open(marker_path, "w") as fh:
                            # repr() keeps full float precision; "%f" truncates
                            # to 6 decimals and rounds down ~half the time on
                            # sub-microsecond mtimes, which would make the
                            # freshness check below reconvert on every launch.
                            fh.write(repr(latest_source_mtime))
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
