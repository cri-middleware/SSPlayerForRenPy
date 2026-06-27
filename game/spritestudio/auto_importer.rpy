# SpriteStudio Auto Importer
# This script runs during the init phase in developer mode.
# It automatically detects changes in .sspj projects and converts them.

init -10 python:
    import os
    import sys
    import glob
    import time

    def _ss_auto_import():
        # Only run in developer mode
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

        for sspj_path in sspj_files:
            project_name = os.path.splitext(os.path.basename(sspj_path))[0]
            project_out_dir = os.path.join(out_dir, project_name)

            # 1. Find the latest modification time in the source project directory
            # (Checks all files like .ssae, .ssce, .png alongside the .sspj)
            sspj_dir = os.path.dirname(sspj_path)
            latest_source_mtime = 0
            for root, _, files in os.walk(sspj_dir):
                for f in files:
                    # Ignore hidden files
                    if f.startswith('.'):
                        continue
                    mtime = os.path.getmtime(os.path.join(root, f))
                    if mtime > latest_source_mtime:
                        latest_source_mtime = mtime
            
            # 2. Check if output exists and find its newest modification time
            # Since a project can output multiple .ssab files, we check the newest file 
            # in the output directory. If it's older than the newest source file, we rebuild.
            needs_conversion = True
            if os.path.exists(project_out_dir):
                latest_out_mtime = 0
                has_files = False
                for root, _, files in os.walk(project_out_dir):
                    for f in files:
                        if f.startswith('.'):
                            continue
                        has_files = True
                        mtime = os.path.getmtime(os.path.join(root, f))
                        if mtime > latest_out_mtime:
                            latest_out_mtime = mtime
                
                # If output has files and its latest file is newer than or equal to source's latest, skip conversion
                if has_files and latest_out_mtime >= latest_source_mtime:
                    needs_conversion = False

            if needs_conversion:
                print(f"[SpriteStudio] Auto-converting project: {project_name} ...")
                
                if converter is None:
                    converter = SsConverter()
                
                def on_log(msg):
                    print(f"  [Converter] {msg.strip()}")

                converter.convert(sspj_path, project_out_dir, on_log)
                
                # Block the init phase until conversion is finished
                while not converter.is_finished():
                    time.sleep(0.05)
                
                res = converter.get_result()
                if res == ConverterResult.Success:
                    print(f"[SpriteStudio] Successfully converted {project_name}.")
                else:
                    err = converter.get_error()
                    print(f"[SpriteStudio] Error converting {project_name}: {err}")

    # Execute auto-import
    _ss_auto_import()
