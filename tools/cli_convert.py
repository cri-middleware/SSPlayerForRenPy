#!/usr/bin/env python3
"""
CLI wrapper for the Python bindings of libssconverter.
Usage: python3 tools/cli_convert.py <input.sspj> <output_dir>
"""

import sys
import os
import time

# Add the game/spritestudio/python directory to sys.path to resolve the binding
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_LIB_DIR = os.path.join(ROOT_DIR, "game", "spritestudio", "python")
sys.path.insert(0, PYTHON_LIB_DIR)

try:
    from ss_renpy.converter import SsConverter, ConverterResult
except ImportError as e:
    print(f"Error importing ss_renpy.converter: {e}", file=sys.stderr)
    print("Please ensure you have built the native runtime using scripts/build-runtime.sh", file=sys.stderr)
    sys.exit(1)

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 cli_convert.py <input.sspj> <output_dir>", file=sys.stderr)
        sys.exit(2)

    input_sspj = sys.argv[1]
    output_dir = sys.argv[2]

    converter = SsConverter()

    print(f"[cli_convert] Converting {input_sspj} -> {output_dir}")
    
    # We pass a simple callback to forward logs to stdout
    def on_log(msg: str):
        # The rust converter logs might contain newlines, so we print without adding an extra one
        print(f"{msg}", end="", flush=True)

    converter.convert(
        sspj_path=input_sspj,
        output_dir=output_dir,
        on_log=on_log
    )

    # Wait until finished
    while not converter.is_finished():
        time.sleep(0.05)

    result = converter.get_result()
    if result == ConverterResult.Success:
        print("\n[cli_convert] Conversion successful.")
        sys.exit(0)
    else:
        err_msg = converter.get_error()
        print(f"\n[cli_convert] Conversion failed with code {result}: {err_msg}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
