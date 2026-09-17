#!/usr/bin/env python3
"""Headless check for runtime texture replacement (a Player-side override).

Exercises the engine-independent half with NO Ren'Py: the name<->path resolution
the ``SSPlayer.ss_set_cellmap_texture`` API is built on (``SsabMeta`` +
``SSInternalPlayer.replaceable_texture_names`` / ``resolve_texture_name``). The
actual displayable swap lives in ``_base_image`` (GL2 render path) and is signed
off in a GUI run — here we prove the resolver the override is keyed by.

Runtime texture replacement is a Player-side override, NOT the per-part Override
Layer (SDK doc: 40_components/70_external_resources.md). Its whole design is:
key a texture map by ``DrawBatch.texture_hash``; the host replaces an entry, the
draw loop binds it for free. This port keys the override by the *resolved path*
instead (ForRenPy resolves every ``texture_hash`` to a path), so the invariant
that matters is: the path a name resolves to is exactly the path that texture's
``texture_hash`` resolves to — otherwise the override would never be hit.

Validates:
  * ``replaceable_texture_names()`` lists every cellmap (and any TCHG-target
    external texture) and is non-empty;
  * ``resolve_texture_name(name)`` equals ``texture_path(fnv1a(name))`` for every
    cellmap name — i.e. the override key lands on the draw-time lookup key;
  * external-texture names (the second hash space) resolve too, when present;
  * unknown / empty names resolve to "" rather than raising.

Usage:  python tools/verify_texture_replace.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402

_RINGO = "ss_assets/Ringo/Ringo.ssab"
# A pack with an authored texture change: cellmap ``common`` plus the
# ``external_textures`` its TCHG selects — the second hash space Ringo lacks.
_TCHG = "ss_assets/overall/TextureChange.ssab"


def _player_pack(relpath: str):
    """A fresh core on ``relpath`` (gamedir-relative), or None when absent."""
    abs_ssab = os.path.join(_GAME, relpath)
    if not os.path.exists(abs_ssab):
        return None
    data = open(abs_ssab, "rb").read()
    base_dir = os.path.dirname(relpath)
    return SSInternalPlayer(
        data, lib=_LIB, base_dir=base_dir,
        resource_manager=RecordingResourceManager(),
        pack_reader=filesystem_pack_reader(os.path.dirname(abs_ssab)))


def _player():
    """A fresh core on the Ringo pack, or None when the demo assets are absent."""
    return _player_pack(_RINGO)


def check_names() -> bool:
    print("### names  replaceable_texture_names lists cellmaps + externals")
    p = _player()
    if p is None:
        print("    SKIP (Ringo not found)"); return True
    ok = True
    try:
        names = p.replaceable_texture_names()
        if not names:
            print("    FAIL: replaceable_texture_names() is empty"); return False
        # Every cell-override cellmap name must be replaceable too (cellmaps are
        # the first, always-present source of the two hash spaces).
        for cm in p.cellmap_names():
            if cm not in names:
                print(f"    FAIL: cellmap {cm!r} missing from replaceable names")
                ok = False
        # External-texture names (the TCHG file-name space) are optional — a pack
        # with no texture change has none. Report, do not fail, when absent.
        externals = [t.name for t in p.meta.external_textures() if t.name]
        for ext in externals:
            if ext not in names:
                print(f"    FAIL: external texture {ext!r} missing from names")
                ok = False
        if not externals:
            print("    SKIP: pack has no external (TCHG) textures to list")
        print(f"    cellmaps={len(p.cellmap_names())} externals={len(externals)} "
              f"total={len(names)}  -> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def check_resolution() -> bool:
    print("### resolve  name -> path lands on the draw-time texture_hash key")
    p = _player()
    if p is None:
        print("    SKIP (Ringo not found)"); return True
    ok = True
    try:
        for cm in p.cellmap_names():
            path = p.resolve_texture_name(cm)
            if not path:
                print(f"    FAIL: resolve_texture_name({cm!r}) is empty"); ok = False
                continue
            # THE invariant: the path an override is keyed by is the path this
            # cellmap's DrawBatch.texture_hash resolves to. fnv1a of the cellmap
            # name is that hash (the default, non-TCHG space).
            want = p.texture_path(ssruntime.hash_string(cm))
            if path != want:
                print(f"    FAIL: {cm!r} resolves to {path!r}, but its "
                      f"texture_hash resolves to {want!r}"); ok = False

        # External textures resolve through the second space; a TCHG file name
        # hashes to its own key, and both must land on the same path.
        for t in p.meta.external_textures():
            if not t.name:
                continue
            path = p.resolve_texture_name(t.name)
            want = p.texture_path(t.name_hash)
            if not path or path != want:
                print(f"    FAIL: external {t.name!r} -> {path!r}, "
                      f"texture_hash -> {want!r}"); ok = False

        # Unknown / empty names resolve to "" (the API returns False on these),
        # never raise.
        for bad in ("no_such_cellmap", "no_such.png", ""):
            got = p.resolve_texture_name(bad)
            if got != "":
                print(f"    FAIL: resolve_texture_name({bad!r}) -> {got!r}, want ''")
                ok = False
        print(f"    checked {len(p.cellmap_names())} cellmap(s)  "
              f"-> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def check_texture_change() -> bool:
    print("### TCHG  both hash spaces collapse to one path (a pack with TextureChange)")
    p = _player_pack(_TCHG)
    if p is None:
        print("    SKIP (overall/TextureChange.ssab not found)"); return True
    ok = True
    try:
        externals = [t for t in p.meta.external_textures() if t.name]
        if not externals:
            print("    SKIP: pack unexpectedly has no external textures"); return True
        # Each external (TCHG file-name) resolves, and to the same path its own
        # texture_hash resolves to — so an override keyed by that name is bound
        # on the frames the texture change is active.
        for t in externals:
            path = p.resolve_texture_name(t.name)
            want = p.texture_path(t.name_hash)
            if not path or path != want:
                print(f"    FAIL: external {t.name!r} -> {path!r}, "
                      f"texture_hash -> {want!r}"); ok = False
        # The ForRenPy property that spares this port ForGodot's caveat: a
        # cellmap and the TCHG target file that names the same image collapse to
        # ONE resolved path, so replacing the cellmap also covers the TCHG frames
        # (both are keyed on the same path this Player overrides).
        cms = {c.name: c.image_path for c in p.meta.cellmaps()}
        shared = 0
        for t in externals:
            for cm_name, img in cms.items():
                if img == t.name:  # cellmap image file == this external file name
                    if p.resolve_texture_name(cm_name) != p.resolve_texture_name(t.name):
                        print(f"    FAIL: cellmap {cm_name!r} and TCHG {t.name!r} "
                              "name one file but resolve to different paths"); ok = False
                    else:
                        shared += 1
        print(f"    externals={len(externals)} shared-file cellmap/TCHG pairs="
              f"{shared}  -> {'PASS' if ok else 'FAIL'}")
    finally:
        p.close()
    return ok


def main() -> int:
    global _LIB
    _LIB = ssruntime.load_library()
    print("== Runtime texture replacement (name<->path resolver) verification ==\n")
    allok = True
    for fn in (check_names, check_resolution, check_texture_change):
        allok &= fn()
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
