"""Freshness marker for auto-imported ``.ssab`` packs (no ``renpy`` import).

The dev-only auto-importer (``auto_importer.rpy``) converts each
``SpriteStudio_Source/<project>/*.sspj`` into ``game/ss_assets/<project>/`` and
must skip a project whose output is already current. It cannot judge that from
output mtimes alone: the converter writes ``.ssab`` files before textures and
can error part-way, leaving fresh-looking *partial* output. So a success marker
(``.ss_import_ok``) records the source snapshot the last SUCCESSFUL conversion
covered, and only that marker is trusted to skip reconversion.

This module is the single home for that convention so every producer agrees on
it: the auto-importer (which writes it after its own conversions) and
``tools/ss_stamp_import.py`` (which stamps it for packs built out-of-band by
``scripts/deploy-examples.*`` via ``tools/cli_convert.py`` — kept a plain
converter that knows nothing about this marker, so it stays reusable on its own).

Engine-independent (plain CPython) so both callers — one inside Ren'Py, one a
headless CLI — share one implementation, mirroring ``events`` / ``ssab_meta``.
"""

from __future__ import annotations

import os

# Hidden (dot-prefixed) so it never lists as a pack and the source/output walks
# below — and Ren'Py's own scans — skip it. A ``build.classify`` rule keeps it
# out of shipped builds (auto_importer.rpy); it is a build-machine artifact.
MARKER_NAME = ".ss_import_ok"


def iter_source_files(source_dir: str):
    """Yield every file a conversion of ``source_dir`` depends on — a project's
    ``.sspj`` and its ``.ssae`` / ``.ssce`` / ``.png`` siblings.

    Hidden files and directories are pruned: their contents are not
    dot-prefixed, so a ``.git`` checkout beside the sources would otherwise
    bump the time and force reconversion every run.

    One home for the set, because two things read it and must agree: the
    freshness check below, and the autoreload watch list the auto-importer
    registers (a file that can make an import stale has to be watched, or the
    change lands with nothing noticing).
    """
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            yield os.path.join(root, f)


def latest_source_mtime(source_dir: str) -> float:
    """Newest mtime among :func:`iter_source_files`, or ``0.0`` for an
    empty/absent tree."""
    latest = 0.0
    for path in iter_source_files(source_dir):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue  # vanished mid-scan / dangling symlink
        if mtime > latest:
            latest = mtime
    return latest


def read_marker(out_dir: str):
    """The source mtime the last successful import of ``out_dir`` covered, or
    ``None`` when the marker is missing or corrupt (either way: reconvert)."""
    try:
        with open(os.path.join(out_dir, MARKER_NAME), "r") as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


def stamp(out_dir: str, source_mtime: float) -> None:
    """Record ``source_mtime`` in ``out_dir``'s marker as the snapshot it was
    converted from.

    ``repr()`` keeps full float precision; ``"%f"`` truncates to 6 decimals and
    rounds down about half the time on sub-microsecond mtimes, which would make
    :func:`read_marker` compare stale and reconvert on every launch. Raises
    ``OSError`` if the marker cannot be written (the caller decides whether that
    is fatal).
    """
    with open(os.path.join(out_dir, MARKER_NAME), "w") as fh:
        fh.write(repr(source_mtime))
