"""Freshness marker for auto-imported ``.ssab`` packs (no ``renpy`` import).

The dev-only auto-importer (``auto_importer.rpy``) converts each
``SpriteStudio_Source/**/<name>.sspj`` into ``game/ss_assets/<name>/`` and
must skip a project whose output is already current. It cannot judge that from
output mtimes alone: the converter writes ``.ssab`` files before textures and
can error part-way, leaving fresh-looking *partial* output. So a success marker
(``.ss_import_ok``) records what the last SUCCESSFUL conversion was made from —
which ``.sspj``, the newest mtime among its sources, and the converter's
version — and only a marker that matches all three skips reconversion.

This module is the single home for that convention so every producer agrees on
it: the auto-importer (which writes it after its own conversions) and
``tools/ss_stamp_import.py`` (which stamps it for packs built out-of-band by
``scripts/deploy-examples.*`` via ``tools/cli_convert.py`` — kept a plain
converter that knows nothing about this marker, so it stays reusable on its own).

Engine-independent (plain CPython) so both callers — one inside Ren'Py, one a
headless CLI — share one implementation, mirroring ``events`` / ``ssab_meta``.
"""

from __future__ import annotations

import json
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


def plan_outputs(sspj_paths, out_dir: str):
    """Pair each ``.sspj`` with the folder it converts into, ``out_dir/<name>``.

    Returns ``(sspj, project_out_dir, owner)`` per project, in path order.
    ``owner`` is ``None`` for the project that converts into the folder, and the
    ``.sspj`` that already does for every other project with the same name: two
    of them would overwrite one folder, and whichever converted last would be
    the only one left, with nothing saying the others are gone. Names that
    differ only in case are one folder on macOS and Windows, so they collide
    too. Sorting makes the same project win on every launch and every machine.
    """
    owners: dict = {}
    plan = []
    for sspj in sorted(sspj_paths):
        name = os.path.splitext(os.path.basename(sspj))[0]
        owner = owners.setdefault(name.lower(), sspj)
        plan.append((sspj, os.path.join(out_dir, name),
                     None if owner == sspj else owner))
    return plan


def stale_outputs(out_dir: str, since: float) -> list:
    """Files under ``out_dir`` that a conversion begun at ``since`` did not
    write, sorted.

    The converter rewrites every ``.ssab``, ``.ssqb`` and asset it produces on
    each run and deletes nothing, so what it left untouched belongs to an
    ``.ssae``, image or sound the project no longer has. Such a file still
    loads, lists in the browser and ships, which is why the auto importer
    names it. Two seconds of slack keep a file written just after ``since``
    from reading as older on a filesystem that stores mtimes in whole or
    even seconds (FAT stores even ones). Hidden files, the marker among
    them, are not outputs.
    """
    cutoff = since - 2.0
    rv = []
    for root, dirs, files in os.walk(out_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            path = os.path.join(root, f)
            try:
                if os.path.getmtime(path) < cutoff:
                    rv.append(path)
            except OSError:
                continue  # vanished mid-scan
    return sorted(rv)


def snapshot(sspj_path: str, converter_version: str) -> dict:
    """What a conversion of ``sspj_path`` right now would be made from.

    A marker equal to this skips reconversion; anything else — a source edited,
    or put back to an older copy, another ``.sspj`` now owning the folder, a
    converter from a different build — reconverts. The converter is part of it
    because an update can change what the same sources convert into without
    changing the pack's schema version.
    """
    return {
        "sspj": os.path.abspath(sspj_path),
        "sources": latest_source_mtime(os.path.dirname(sspj_path)),
        "converter": converter_version,
    }


def read_marker(out_dir: str):
    """The :func:`snapshot` the last successful import of ``out_dir`` recorded,
    or ``None`` when the marker is missing, corrupt, or in an older format
    (each of which means: reconvert)."""
    try:
        with open(os.path.join(out_dir, MARKER_NAME), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def stamp(out_dir: str, snap: dict) -> None:
    """Record ``snap`` (a :func:`snapshot`) in ``out_dir``'s marker as what it
    was converted from.

    JSON writes a float with ``repr()`` precision, so the mtime reads back equal;
    a truncating format (``"%f"``) would compare stale and reconvert on every
    launch. Raises ``OSError`` if the marker cannot be written (the caller
    decides whether that is fatal).
    """
    with open(os.path.join(out_dir, MARKER_NAME), "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
