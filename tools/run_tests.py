#!/usr/bin/env python3
"""Run the headless test suite — every ``tools/verify_*.py`` plus ``m0_smoke.py``.

The suite these drive has always been runnable (plain CPython, no Ren'Py, no
GUI); what it lacked was one command, and an accounting of what actually ran.
Both gaps have the same shape: a tool that cannot find its pack **prints
``SKIP`` and exits 0**, so a suite driven by a bare shell loop reports green for
a tree where nothing was ever loaded. That is the failure this runner exists to
make impossible, in two steps:

  1. **Preflight before anything runs.** The Brain and the four asset packs are
     checked up front — present, and current: the Brain must load through the
     same gate the player uses, and every pack must bind against it — and a
     missing or stale one stops the run with the script that produces it. A
     partial suite is never started, nor one that would die on tracebacks.
  2. **A skip is not a pass.** Preflight having passed, a tool that still
     reports a pack missing is reporting a real defect, so its ``SKIP`` is
     surfaced and fails the run. (Sub-case skips — "this part does not draw in
     this animation" — are a different thing and are counted, not failed.)

GL2 rendering (PMA, mesh, blend, mask, the ``ss-*`` GLSL) is out of scope here
and stays a GUI sign-off: ``Shift+B`` or ``scripts/run-demo.*``. So is
``render_png.py`` / ``render_mask_png.py``, which need Pillow and write images
rather than assert on them.

Usage: python3 tools/run_tests.py [only=<names>] [skip=<names>] [list=yes] [verbose=yes]
  only    : comma-separated substrings; run only the tools that match
  skip    : comma-separated substrings; skip the tools that match
  list    : yes to list the discovered tools and exit
  verbose : yes to stream every tool's output, not just the failing ones

Exit status: 0 all passed · 1 something failed or was skipped · 2 preflight failed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_GAME = os.path.join(_ROOT, "game")

sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))  # import ss_renpy

# The packs every tool resolves against; deploy-examples produces all of them.
_REQUIRED_PACKS = ("overall", "Ringo", "ParticleEffect", "Doll")


def _script(name: str) -> str:
    """Spell a repo script the way the reader's shell wants to hear it."""
    return f"scripts\\{name}.ps1" if os.name == "nt" else f"scripts/{name}.sh"


def _unbindable(ssruntime, lib, packs) -> tuple[int, list[str]]:
    """``(checked, failures)`` for binding every ``.ssab`` of ``packs``.

    Bound the way the player binds one — the identifier gate, then the native
    bridge, which refuses a schema version the runtime does not read before
    the runtime sees it — so a stale pack is caught here, with the bridge's
    reason, rather than as a traceback in whichever tool loads it first."""
    from ss_renpy.ssab_meta import SsabMeta
    checked, failures = 0, []
    for pack in packs:
        folder = os.path.join(_GAME, "ss_assets", pack)
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".ssab"):
                continue
            checked += 1
            rt = None
            try:
                with open(os.path.join(folder, name), "rb") as fh:
                    data = fh.read()
                SsabMeta(data)
                rt = ssruntime.SSRuntime(lib)
                rt.load_ssab_bytes(data)
            except Exception as e:  # noqa: BLE001 — any refusal is the finding
                failures.append(f"{pack}/{name}: {e}")
            finally:
                if rt is not None:
                    rt.close()
    return checked, failures


def preflight() -> list[str]:
    """Return the reasons the suite cannot run yet — empty when it can."""
    problems: list[str] = []

    try:
        from ss_renpy import ssruntime, ssruntime_native
        lib_path = ssruntime_native.default_library_path()
    except Exception as e:  # noqa: BLE001 — a broken import is a preflight failure
        return [f"ss_renpy did not import ({e}) — is game/spritestudio/python intact?"]
    lib = None
    if not os.path.exists(lib_path):
        problems.append(
            f"the Brain is not built: {os.path.relpath(lib_path, _ROOT)} is missing\n"
            f"      -> {_script('build-runtime')}")
    else:
        try:
            lib = ssruntime.load_library()
        except Exception as e:  # noqa: BLE001 — what every tool would die on
            problems.append(
                f"the Brain does not load: {e}\n"
                f"      -> {_script('build-runtime')}")

    present = [p for p in _REQUIRED_PACKS
               if os.path.isdir(os.path.join(_GAME, "ss_assets", p))]
    missing = [p for p in _REQUIRED_PACKS if p not in present]
    if missing:
        problems.append(
            f"playback data is not deployed: game/ss_assets/{{{','.join(missing)}}}\n"
            f"      -> {_script('deploy-examples')}")
    if lib is not None and present:
        checked, failures = _unbindable(ssruntime, lib, present)
        if failures:
            shown = "\n        ".join(failures[:3])
            more = (f"\n        ... and {len(failures) - 3} more"
                    if len(failures) > 3 else "")
            problems.append(
                f"playback data is stale: {len(failures)} of {checked} packs "
                f"under game/ss_assets/ will not bind\n        {shown}{more}\n"
                f"      -> {_script('deploy-examples')}")
    return problems


def discover() -> list[tuple[str, str]]:
    """(name, path) for every tool in the suite, in a stable order."""
    names = sorted(f for f in os.listdir(_HERE)
                   if f.startswith("verify_") and f.endswith(".py"))
    names.append("m0_smoke.py")
    return [(n[:-3], os.path.join(_HERE, n)) for n in names]


def _classify(code: int, output: str) -> tuple[str, str]:
    """(verdict, note) for one finished tool.

    A tool reporting a pack missing after preflight passed is the case worth
    separating from a plain failure: the run is still red, but the reason is
    "it never ran" rather than "it disagreed with the Brain".
    """
    missing = [ln.strip().replace(_ROOT + os.sep, "") for ln in output.splitlines()
               if "SKIP" in ln and "not found" in ln]
    if missing:
        return "SKIP", missing[0]
    if code == 0:
        # Sub-case skips are legitimate (a part that does not draw in the
        # animation under test); report the count so a suite that quietly
        # narrows over time is visible.
        n = sum(1 for ln in output.splitlines() if "SKIP" in ln)
        return "PASS", f"{n} sub-case(s) skipped" if n else ""
    if code == 2:
        return "SETUP", "the tool reported its prerequisites missing"
    return "FAIL", f"exit {code}"


def main(argv: list[str]) -> int:
    only: list[str] = []
    skip: list[str] = []
    listing = verbose = False
    for item in argv[1:]:
        if item in ("-h", "--help", "help"):
            usage = (__doc__ or "").partition("Usage:")[2]
            print("Usage:" + usage.partition("\n\n")[0])
            return 0
        key, _, value = item.partition("=")
        if key == "only":
            only = [v for v in value.split(",") if v]
        elif key == "skip":
            skip = [v for v in value.split(",") if v]
        elif key == "list":
            listing = value.lower() in ("yes", "true", "1")
        elif key == "verbose":
            verbose = value.lower() in ("yes", "true", "1")
        else:
            print(f"run_tests.py: unknown arg '{item}'", file=sys.stderr)
            return 2

    tools = discover()
    if only:
        tools = [t for t in tools if any(o in t[0] for o in only)]
    if skip:
        tools = [t for t in tools if not any(s in t[0] for s in skip)]
    if not tools:
        print("run_tests.py: no tool matched", file=sys.stderr)
        return 2

    if listing:
        for name, path in tools:
            print(f"{name:28s} tools/{os.path.basename(path)}")
        return 0

    problems = preflight()
    if problems:
        print("run_tests.py: the suite cannot run yet.\n")
        for p in problems:
            print(f"  !!  {p}")
        print("\nBoth outputs are gitignored, so a fresh clone always needs them,"
              "\nand an SDK bump can leave either behind the bindings.")
        return 2

    print(f"== headless suite: {len(tools)} tool{'s' if len(tools) != 1 else ''} "
          f"({os.path.basename(sys.executable)}) ==\n")
    results: list[tuple[str, str, str, float, str]] = []
    for name, path in tools:
        started = time.monotonic()
        proc = subprocess.run([sys.executable, path], cwd=_ROOT,
                              capture_output=True, text=True)
        elapsed = time.monotonic() - started
        output = proc.stdout + proc.stderr
        verdict, note = _classify(proc.returncode, output)
        results.append((name, verdict, note, elapsed, output))
        print(f"  {verdict:5s}  {name:28s} {elapsed:5.2f}s"
              + (f"  {note}" if note else ""))
        if verbose:
            print("\n" + output.rstrip() + "\n")

    failed = [r for r in results if r[1] != "PASS"]
    if failed and not verbose:
        for name, verdict, _note, _t, output in failed:
            print(f"\n{'-' * 72}\n{verdict}: {name}\n{'-' * 72}")
            print(output.rstrip())

    passed = len(results) - len(failed)
    print(f"\n== RESULT: {passed}/{len(results)} passed ==")
    if failed:
        print("   " + ", ".join(f"{n} ({v})" for n, v, _, _, _ in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
