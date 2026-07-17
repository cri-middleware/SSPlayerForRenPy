#!/usr/bin/env python3
"""Stamp the auto-importer freshness marker for an already-converted pack.

``scripts/deploy-examples.*`` builds packs out-of-band with
``tools/cli_convert.py`` — a plain ``.sspj`` -> ``.ssab`` converter that knows
nothing about the importer. Without the marker, the dev-mode auto-importer
(``auto_importer.rpy``) sees output-but-no-marker and reconverts on every
launch. This stamps the marker so it skips, using the exact convention the
importer itself writes (``ss_renpy.import_marker``) — keeping ``cli_convert.py``
free of any marker knowledge.

Usage:  python tools/ss_stamp_import.py <source_project_dir> <output_pack_dir>
  <source_project_dir>  the SpriteStudio_Source/<project>/ the .sspj lives in
                        (its newest mtime is the snapshot recorded)
  <output_pack_dir>     the game/ss_assets/<project>/ the .ssab were written to
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, "game", "spritestudio", "python"))

from ss_renpy import import_marker  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python ss_stamp_import.py <source_project_dir> <output_pack_dir>",
              file=sys.stderr)
        return 2
    source_dir, out_dir = sys.argv[1], sys.argv[2]
    if not os.path.isdir(out_dir):
        print(f"[ss_stamp_import] output dir not found: {out_dir}", file=sys.stderr)
        return 1
    mtime = import_marker.latest_source_mtime(source_dir)
    try:
        import_marker.stamp(out_dir, mtime)
    except OSError as e:
        print(f"[ss_stamp_import] could not write marker: {e}", file=sys.stderr)
        return 1
    print(f"[ss_stamp_import] stamped {import_marker.MARKER_NAME} in {out_dir} "
          f"(source snapshot {mtime!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
