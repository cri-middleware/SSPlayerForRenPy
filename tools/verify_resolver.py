#!/usr/bin/env python3
"""Headless check for the zero-config short-name resolver (no Ren'Py).

Builds an AssetIndex over ``game/ss_assets`` and asserts:
  * bare short names resolve to the right gamedir-relative .ssab path;
  * a pack referenced as another's external instance is non-primary (hidden
    from ``names()`` but still resolvable);
  * animation validation accepts real names and rejects typos (with hints);
  * unknown / ambiguous names raise SSResolveError.

Usage:  python tools/verify_resolver.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import resolver  # noqa: E402
from ss_renpy.resolver import AssetIndex, AssetRecord, SSResolveError  # noqa: E402

_ok = True


def check(label, cond):
    global _ok
    print(f"    {'PASS' if cond else 'FAIL'}  {label}")
    _ok = _ok and bool(cond)


def expect_raises(label, fn):
    try:
        fn()
        check(label + " (should raise)", False)
    except SSResolveError as e:
        print(f"    PASS  {label}  -> {e}")


def main() -> int:
    idx = resolver.build_index_fs(_GAME, ["ss_assets"])
    print("== resolver verification ==\n")
    print(f"### real index over game/ss_assets  ({len(idx.records())} packs)")

    check("resolve('Ringo') == ss_assets/Ringo/Ringo.ssab",
          idx.resolve("Ringo") == "ss_assets/Ringo/Ringo.ssab")
    check("resolve('Basic') == ss_assets/overall/Basic.ssab",
          idx.resolve("Basic") == "ss_assets/overall/Basic.ssab")
    check("resolve('e001') == ss_assets/ParticleEffect/e001.ssab",
          idx.resolve("e001") == "ss_assets/ParticleEffect/e001.ssab")
    check("case-insensitive resolve('ringo') works",
          idx.resolve("ringo") == "ss_assets/Ringo/Ringo.ssab")

    # External-instance pack: Instance.ssab references 'Instance_SourceAnime'.
    names = idx.names()
    check("'Instance' is a primary name", "Instance" in names)
    check("'Instance_SourceAnime' hidden from names() (non-primary)",
          "Instance_SourceAnime" not in names)
    check("'Instance_SourceAnime' is still path-resolvable",
          idx.resolve("Instance_SourceAnime") ==
          "ss_assets/overall/Instance_SourceAnime.ssab")

    # Animation validation against the real Ringo pack.
    ringo = idx.find("Ringo")
    check("'wait1' is among Ringo's animations", "wait1" in ringo.anim_names)
    idx.validate_animation(ringo, "wait1")          # ok
    idx.validate_animation(ringo, ["wait1", "joy"])  # ok
    print("    PASS  validate_animation accepts real Ringo anims")
    expect_raises("validate_animation('wait99') rejects typo",
                  lambda: idx.validate_animation(ringo, "wait99"))

    expect_raises("resolve('Nope') unknown name",
                  lambda: idx.resolve("Nope"))

    # Synthetic ambiguity: two primary packs sharing a stem.
    amb = AssetIndex([
        AssetRecord("ss_assets/a/Hero.ssab", "Hero", ("idle",), True),
        AssetRecord("ss_assets/b/Hero.ssab", "Hero", ("idle",), True),
    ])
    expect_raises("ambiguous 'Hero' across two dirs",
                  lambda: amb.resolve("Hero"))

    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
