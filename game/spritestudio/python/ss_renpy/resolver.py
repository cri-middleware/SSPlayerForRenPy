"""Resolve a bare ``.ssab`` short name to its gamedir-relative path (no renpy).

Lets a caller write ``SSPlayer("Ringo")`` instead of the full
``"ss_assets/Ringo/Ringo.ssab"``. We scan the asset roots for ``.ssab`` files
and match by file stem — keying off the *output* packs (not the ``.sspj``
import pipeline), so this works identically for auto-imported and hand-dropped
packs. Explicit paths (anything containing ``/`` or ending in ``.ssab``) never
reach here: the displayable uses them verbatim, so existing code is unaffected
and pays no scan cost.

Pure CPython: the engine layer hands us ``gamedir`` + relative roots; we walk
them with ``os`` and read animation names via :class:`SsabMeta`. A pack that is
referenced as another pack's *external instance* (e.g. ``Instance_SourceAnime``)
is marked non-primary so it never shadows the "main" pack in a short-name
lookup. Headless-testable (``tools/verify_resolver.py``).
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass


class SSResolveError(Exception):
    """A short name could not be resolved (unknown / ambiguous / bad animation)."""


@dataclass(frozen=True)
class AssetRecord:
    rel_path: str        # gamedir-relative, posix: "ss_assets/Ringo/Ringo.ssab"
    stem: str            # "Ringo"
    anim_names: tuple     # ("wait1", "joy", ...)
    is_primary: bool      # not referenced as an external instance by a sibling


class AssetIndex:
    """An immutable lookup over the ``.ssab`` packs discovered under the roots."""

    def __init__(self, records):
        self._records = list(records)
        self._by_stem: dict = {}
        for r in self._records:
            self._by_stem.setdefault(r.stem, []).append(r)

    def records(self) -> list:
        return list(self._records)

    def names(self) -> list:
        """Resolvable (primary) short names, sorted — for discovery / catalogs."""
        primary = {r.stem for r in self._records if r.is_primary}
        return sorted(primary or {r.stem for r in self._records})

    def find(self, name: str) -> AssetRecord:
        """The :class:`AssetRecord` for short ``name`` (primary preferred).

        Raises :class:`SSResolveError` (with close-match hints) when the name is
        unknown, or when two primary packs share it.
        """
        matches = self._by_stem.get(name)
        if not matches:
            low = name.lower()                       # case-insensitive retry
            matches = [r for r in self._records if r.stem.lower() == low]
        if not matches:
            sugg = difflib.get_close_matches(
                name, [r.stem for r in self._records], n=3)
            hint = (" Did you mean: %s?" % ", ".join(sugg)) if sugg else ""
            raise SSResolveError(
                "no .ssab named %r under the asset roots.%s" % (name, hint))
        primaries = [r for r in matches if r.is_primary] or matches
        if len(primaries) > 1:
            paths = ", ".join(sorted(r.rel_path for r in primaries))
            raise SSResolveError(
                "ambiguous .ssab name %r — matches: %s. Pass the full path."
                % (name, paths))
        return primaries[0]

    def resolve(self, name: str) -> str:
        """Short ``name`` -> gamedir-relative ``.ssab`` path (or raise)."""
        return self.find(name).rel_path

    def validate_animation(self, record: AssetRecord, animation) -> None:
        """Raise :class:`SSResolveError` if a requested animation isn't in
        ``record``. ``animation`` may be ``None``, a name, or a list of names."""
        if not animation:
            return
        names = [animation] if isinstance(animation, str) else list(animation)
        avail = set(record.anim_names)
        if not avail:                                # couldn't read names; skip
            return
        for a in names:
            if a and a not in avail:
                sugg = difflib.get_close_matches(a, sorted(avail), n=3)
                hint = (" Did you mean: %s?" % ", ".join(sugg)) if sugg else ""
                raise SSResolveError(
                    "animation %r not found in %r (have: %s).%s"
                    % (a, record.stem, ", ".join(sorted(avail)), hint))


def _posix_relpath(path: str, start: str) -> str:
    return os.path.relpath(path, start).replace("\\", "/")


def build_index(rel_paths, reader) -> AssetIndex:
    """Build an :class:`AssetIndex` from gamedir-relative ``.ssab`` paths.

    ``reader(rel_path)`` returns that file's bytes — engine-agnostic, so the host
    chooses the source: the filesystem for headless tools, or ``renpy.open_file``
    in-engine (which reads ``.rpa`` archives transparently). Reads each pack's
    animation names + external-instance refs via :class:`SsabMeta`; per-file
    errors are swallowed (that pack gets empty ``anim_names`` but is still
    path-resolvable). A pack referenced as another's external instance is marked
    non-primary so it doesn't shadow the 'main' pack.
    """
    from ss_renpy.ssab_meta import SsabMeta

    raw = []                # (rel_path, stem, anim_names)
    referenced: set = set()  # pack names used as external instances
    seen: set = set()
    for rel in rel_paths:
        rel = rel.replace("\\", "/")
        if not rel.endswith(".ssab") or rel in seen:
            continue
        seen.add(rel)
        anims = ()
        try:
            meta = SsabMeta(reader(rel))
            anims = tuple(meta.animation_names())
            for e in meta.external_instances():
                if e.anime_pack_name:
                    referenced.add(e.anime_pack_name)
        except Exception:
            pass
        raw.append((rel, rel.rsplit("/", 1)[-1][:-len(".ssab")], anims))

    records = [AssetRecord(rel_path=rel, stem=stem, anim_names=anims,
                           is_primary=(stem not in referenced))
               for (rel, stem, anims) in raw]
    return AssetIndex(records)


def scan_filesystem(gamedir: str, roots):
    """Yield gamedir-relative ``.ssab`` paths under ``roots`` (filesystem)."""
    for root in roots:
        parts = [p for p in root.replace("\\", "/").split("/") if p]
        root_abs = os.path.join(gamedir, *parts) if parts else gamedir
        if not os.path.isdir(root_abs):
            continue
        for dirpath, _, files in os.walk(root_abs):
            for f in files:
                if f.endswith(".ssab") and not f.startswith("."):
                    yield _posix_relpath(os.path.join(dirpath, f), gamedir)


def build_index_fs(gamedir: str, roots) -> AssetIndex:
    """Filesystem-backed :class:`AssetIndex` (headless convenience / tools)."""
    def reader(rel):
        with open(os.path.join(gamedir, *rel.split("/")), "rb") as fh:
            return fh.read()
    return build_index(scan_filesystem(gamedir, roots), reader)
