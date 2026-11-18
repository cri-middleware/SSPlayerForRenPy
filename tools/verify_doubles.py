#!/usr/bin/env python3
"""Headless regression check: every test double still accepts what production sends.

A stub that has drifted from the class it stands in for does not fail honestly.
Python binds arguments at call time, so the stub keeps passing until some test
happens to exercise the new argument, and then it raises ``TypeError`` from
inside the double -- a crash that reads like a product bug and is not one.

That is not hypothetical here. ``fix(mask): carry instance-internal clipping
writers out to the parent`` gave ``SSInternalPlayer.render_at`` a ``clip_out``
keyword; ``verify_hidden._StubSub.render_at`` was not updated, and the tool
died with ``_StubSub.render_at() got an unexpected keyword argument 'clip_out'``.
Nothing pointed at the double until someone read the traceback.

So this pins the doubles themselves -- but only where a mismatch actually breaks
a call, because a guard that cries wolf gets switched off. The doubles here
abbreviate their positional parameters on purpose (``dt`` for ``dt_s``, ``ctx``
for ``child_ctx``) and every such argument is passed positionally, so comparing
those names would report eight failures against code that works. Two things do
break a call, and those are what this checks:

  * **capacity** -- the double must accept at least as many parameters as
    production. A new trailing parameter is exactly what ``clip_out`` was.
  * **the names that carry defaults** -- those are the ones callers pass by
    keyword (``clip_out=clip_out``), so for them the spelling is load-bearing,
    and their order among themselves must hold.

A double that declares ``*args``/``**kwargs`` absorbs anything and is accepted
as-is: that is deliberate where one stub stands in for two classes of different
arity (``_StubRig`` covers both ``InstanceRig.step_idle`` and
``EffectRig.step_idle``).

What this does NOT cover: doubles that carry data rather than behaviour.
``verify_mask._FakePart`` and ``_FakeMesh`` are attribute bags with no methods,
so there is no signature to compare; drift there shows up as ``AttributeError``
in the test that uses them, which at least names the attribute.

Plain CPython -- no Ren'Py.

Usage:  python tools/verify_doubles.py
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))
sys.path.insert(0, _HERE)

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

# (double, production it stands in for, methods that must stay callable-compatible)
#
# Add a row when a tool grows a stub with methods. The cost of a missing row is
# the failure above: a TypeError from inside the double, blamed on the product.
_PAIRS = [
    ("verify_hidden._StubSub", "ss_renpy.player.SSInternalPlayer",
     ["play", "step_slots_only", "render_at"]),
    ("verify_hidden._StubRT", "ss_renpy.ssruntime_native._NativeRuntime",
     ["active_event_instance", "instance_slot_step",
      "instance_slot_get_speed"]),
    ("verify_hidden._StubRig", "ss_renpy.instance.InstanceRig",
     ["part_indices", "step_idle"]),
    ("verify_hidden._StubRig", "ss_renpy.effect.EffectRig",
     ["part_indices", "step_idle"]),
]

_VAR = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
_NAMED = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


def _resolve(dotted: str):
    """`pkg.mod.Class` -> the class object, importing the module."""
    mod_name, _, cls_name = dotted.rpartition(".")
    return getattr(importlib.import_module(mod_name), cls_name)


def _params(cls, name):
    """The method's parameters minus `self`, or None when it has no such method."""
    fn = getattr(cls, name, None)
    if fn is None:
        return None
    ps = list(inspect.signature(fn).parameters.values())
    return ps[1:] if ps and ps[0].name == "self" else ps


def _compare(double, prod, name) -> list[str]:
    """Reasons `double.name` cannot take every call `prod.name` can. Empty = fine."""
    dp, pp = _params(double, name), _params(prod, name)
    if pp is None:
        return [f"{prod.__name__} has no {name}() -- the row is stale"]
    if dp is None:
        return [f"{double.__name__} has no {name}()"]

    # A catch-all absorbs any call, which is why _StubRig can cover two arities.
    if any(p.kind in _VAR for p in dp):
        return []

    bad = []
    if len(dp) < len(pp):
        bad.append(f"{name}(): takes {len(dp)} parameter(s), production passes "
                   f"up to {len(pp)} ({', '.join(p.name for p in pp)})")

    # Defaulted parameters are the ones callers name, so their spelling counts.
    d_names = [p.name for p in dp if p.kind in _NAMED]
    kw = [p.name for p in pp
          if p.kind in _NAMED and p.default is not inspect.Parameter.empty]
    for n in kw:
        if n not in d_names:
            bad.append(f"{name}(): missing keyword {n!r}")

    shared = [n for n in kw if n in d_names]
    if [n for n in d_names if n in shared] != shared:
        bad.append(f"{name}(): keyword order differs (double {d_names}, "
                   f"production {kw})")
    return bad


def check_doubles() -> bool:
    print("### test doubles accept every call their production class accepts")
    ok = True
    for double_path, prod_path, methods in _PAIRS:
        try:
            double, prod = _resolve(double_path), _resolve(prod_path)
        except (ImportError, AttributeError) as e:
            print(f"    FAIL: cannot resolve {double_path} / {prod_path}: {e}")
            ok = False
            continue

        for name in methods:
            for reason in _compare(double, prod, name):
                print(f"    FAIL: {double_path} vs {prod_path}: {reason}")
                ok = False

    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def main(argv) -> int:
    print(f"== verify_doubles: {len(_PAIRS)} pairs ==")
    ok = check_doubles()
    print(f"== RESULT: {'PASS' if ok else 'FAIL'} ==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
