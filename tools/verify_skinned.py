#!/usr/bin/env python3
"""Headless check: the skinned-mesh part query answers correctly and consistently.

``is_part_skinned_mesh`` is the static twin of ``is_part_hidden`` — it tells a
caller whether a part is a *bone-skinned* mesh, which is the one thing that makes
a part a poor ``ss_attach`` (part-tracking) target: its vertices are drawn from
its bound bones while its own node transform stays at the setup pose (near the
character root), so a follower snaps to the root rather than onto the visible
art. This is a shared-``libssruntime`` property, not a bug (SSPlayerForUnity
_MEMO_PartTracking_Mesh_Error), so the fix is a query + a warning + docs, not a
behaviour change.

The answer is read from static ``.ssab`` metadata (``PartMeshBinding`` with a
non-empty ``influence_bone``), so there are three surfaces that must agree, and
this pins all three against index / schema drift — the exact breakage the
"Verification" section of AGENTS.md warns of, since nothing but an
``AttributeError`` or a wrong bool would show it otherwise:

  * ``SsabMeta.is_part_skinned_mesh`` / ``PartInfo.skinned_mesh`` (pure parse),
  * ``SSInternalPlayer.is_part_skinned_mesh`` (the core, over the built pack).

The gate is the *bone count*, not the mere presence of a mesh: a deform-only
(rigid) mesh has no bones and tracks fine, so it must answer ``False``. No demo
pack ships a rigid-mesh part to assert that leg positively, so the ``False`` side
is pinned by a non-mesh part and an unknown name; the ``True`` side by Ringo's
bone-bound limbs and ``overall/Mesh.ssab``'s ``mesh_skin``.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_skinned.py
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
from ss_renpy.resource import (  # noqa: E402
    RecordingResourceManager, filesystem_pack_reader)
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402

# (pack-relative .ssab, part name, expected skinned?). Ringo's limbs/ears/tail
# are bone-bound (the memo's hand_r example among them); root is a non-mesh part.
CASES = [
    ("Ringo/Ringo.ssab", "hand_r", True),
    ("Ringo/Ringo.ssab", "hand_l", True),
    ("Ringo/Ringo.ssab", "tail", True),
    ("overall/Mesh.ssab", "mesh_skin", True),
]


def _open(rel: str):
    return os.path.join(_GAME, "ss_assets", *rel.split("/"))


def _core(lib, path: str) -> SSInternalPlayer:
    base = os.path.dirname(path)
    return SSInternalPlayer(
        open(path, "rb").read(), lib=lib,
        base_dir=os.path.relpath(base, _GAME).replace("\\", "/"),
        resource_manager=RecordingResourceManager(),
        pack_reader=filesystem_pack_reader(base))


def check(lib) -> bool:
    ok = True
    # Group the cases by pack so each pack is parsed / built once.
    by_pack: dict[str, list[tuple[str, bool]]] = {}
    for rel, name, want in CASES:
        by_pack.setdefault(rel, []).append((name, want))

    for rel, expect in by_pack.items():
        path = _open(rel)
        if not os.path.exists(path):
            print(f"SKIP: {path} not found (run scripts/deploy-examples.* first)")
            return ok
        meta = SsabMeta(open(path, "rb").read())
        by_name = {p.name: p for p in meta.parts()}
        p = _core(lib, path)
        try:
            for name, want in expect:
                if name not in by_name:
                    print(f"    FAIL: {rel}: expected part {name!r} not in pack")
                    ok = False
                    continue
                m_meta = meta.is_part_skinned_mesh(name)
                m_field = by_name[name].skinned_mesh
                m_core = p.is_part_skinned_mesh(name)
                agree = (m_meta == m_field == m_core == want)
                print(f"    {rel:<20} {name:<12} "
                      f"meta={m_meta!s:<5} field={m_field!s:<5} core={m_core!s:<5} "
                      f"want={want!s:<5} {'ok' if agree else 'MISMATCH'}")
                if not agree:
                    ok = False

            # The False side: a non-mesh part and an unknown name, on every
            # surface. Pick a part the pack has that is not in our True set.
            true_names = {n for n, w in expect if w}
            neg = next((nm for nm in meta.part_names() if nm not in true_names), None)
            for probe, label in ((neg, "non-skinned"), ("__no_such_part__", "unknown")):
                if probe is None:
                    continue
                vals = (meta.is_part_skinned_mesh(probe), p.is_part_skinned_mesh(probe))
                if any(vals):
                    print(f"    FAIL: {rel}: {label} part {probe!r} reported "
                          f"skinned (meta/core={vals})")
                    ok = False
                else:
                    print(f"    {rel:<20} {probe:<12} -> False  ({label}) ok")
        finally:
            p.close()
    return ok


def main() -> int:
    target = _open("Ringo/Ringo.ssab")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found (run scripts/deploy-examples.* first)")
        return 0
    lib = ssruntime.load_library()
    print("== Skinned-mesh part-query verification ==\n")
    ok = check(lib)
    print("\n== RESULT:", "ALL PASS" if ok else "FAILURES PRESENT", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
