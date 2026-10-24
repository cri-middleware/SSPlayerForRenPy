#!/usr/bin/env python3
"""Headless check of the Ren'Py Web bridge (``ss_renpy.ssruntime_web``), no browser.

The web bridge drives the Brain's wasm-bindgen build by eval'ing JS source that
it builds with Python string formatting, and no other tool runs it. Its defects
surface only in a web export, as a frame that aborts rather than an exception:
a Python value spliced into the source raw (``True`` / ``None`` / ``nan`` are
undefined identifiers in JS), and a JS throw — a rejected pack, an enum value
the binding refuses — that escapes its script, since the Python side of the
emscripten boundary cannot catch it.

So this installs a fake ``emscripten`` module, which records every script and
answers the few reads the bridge parses, and checks:

  1. **API parity**: ``_WebRuntime`` against ``_NativeRuntime``, with the same
     public names, the same property / method split, the same signatures
     (parameter names, kinds, defaults) and the same Instance step-result
     fields. ``SSInternalPlayer`` runs on either unchanged, so a name one of
     them lacks is an ``AttributeError`` on that platform alone. Intentional
     differences sit in ``_NATIVE_ONLY`` / ``_WEB_ONLY``, each with its reason.
  2. **Generated scripts**: every public method that takes an argument is called
     with awkward values (``True``, ``None``, ``nan``, ``1e-7``, negatives,
     names with quotes and backslashes). A value the native bridge's ctypes
     argtypes reject must raise in Python before any script is sent; any other
     must give scripts with no Python literal in them, balanced brackets and
     strings, a name that decodes back to itself, and 0 or 1 wherever the
     binding takes an enum — folded the way the C-API reads a stray value.
  3. **A rejected pack**: when the JS side refuses a pack, ``load_ssab_bytes``
     raises RuntimeError with the reason and leaves the previous resource bound.
  4. **A refused section**: when the JS side refuses a playback section,
     ``set_animation_section`` returns False, as native does.

With ``node`` on PATH, every recorded script, in order, is then compiled and run
against a small stand-in for the wasm-bindgen objects, whose enum setters,
section setter and pack constructor throw as the real ones do: that is what
shows the load script catching the throw and returning the reason, and the
section script returning 0. Without ``node`` that sub-step is reported as a
sub-case skip.

What this does NOT cover: the real glue and Brain (no web build is loaded), the
emscripten heap behind the addresses the bridge hands JS (the stand-in heap is
empty), and anything a browser adds. A web export still signs those off.

Plain CPython: no Ren'Py, no runtime library, no asset pack.

Usage:  python tools/verify_web_bridge.py
"""

from __future__ import annotations

import inspect
import json
import math
import os
import re
import shutil
import subprocess
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()


class FakeEmscripten(types.ModuleType):
    """Ren'Py's ``emscripten`` module, minus the browser.

    Every script is recorded with the label of the call that sent it. A read
    answers with the value of the first ``answers`` needle the script contains,
    else 0 / ''.
    """

    def __init__(self):
        super().__init__("emscripten")
        self.scripts: list[tuple[str, str]] = []
        self.answers: dict[str, object] = {}
        self.label = "?"

    def _record(self, script, default):
        self.scripts.append((self.label, script))
        for needle, value in self.answers.items():
            if needle in script:
                return value
        return default

    def run_script(self, script):
        self._record(script, None)

    def run_script_int(self, script):
        return int(self._record(script, 0))

    def run_script_string(self, script):
        return str(self._record(script, ""))

    def sleep(self, ms):
        pass


_FAKE = FakeEmscripten()
# The reads the bridge parses: a frame's lengths (frame + 13 SoA buffers) and
# an Instance step's five fields and the slot's speed.
_FAKE.answers["window.ss_frame("] = ",".join(["0"] * 14)
_FAKE.answers["window.ss_instance_step("] = "0,0,0,0,0,1"
sys.modules["emscripten"] = _FAKE

from ss_renpy import ssruntime_native, ssruntime_web  # noqa: E402

_ok = True


def check(label, cond, detail=""):
    global _ok
    print(f"    {'PASS' if cond else 'FAIL'}  {label}"
          + (f"\n          {detail}" if detail and not cond else ""))
    _ok = _ok and bool(cond)


# --- 1. API parity ----------------------------------------------------------

# Names one bridge has and the other lacks on purpose, each with its reason.
# An entry that no longer differs fails too, so the list cannot go stale.
_NATIVE_ONLY = {
    "lib": "the ctypes CDLL; the web module lives on window, with no Python handle",
}
_WEB_ONLY: dict[str, str] = {}


def _public(cls) -> dict:
    names = [k for k in dir(cls) if not k.startswith("_")]
    names += [k for k in ("__enter__", "__exit__") if hasattr(cls, k)]
    return {k: inspect.getattr_static(cls, k) for k in names}


def _kind(obj) -> str:
    return "property" if isinstance(obj, property) else (
        "method" if callable(obj) else type(obj).__name__)


def _params(fn, *, keyword_only=True):
    """(name, kind, default) per parameter: annotations differ and do not matter."""
    ps = inspect.signature(fn).parameters.values()
    if not keyword_only:
        ps = [p for p in ps if p.kind is not p.KEYWORD_ONLY]
    return [(p.name, p.kind.name, p.default) for p in ps]


def check_parity():
    native, web = ssruntime_native._NativeRuntime, ssruntime_web._WebRuntime
    print("### API parity: _WebRuntime vs _NativeRuntime")
    n, w = _public(native), _public(web)
    missing_web = sorted(set(n) - set(w) - set(_NATIVE_ONLY))
    missing_native = sorted(set(w) - set(n) - set(_WEB_ONLY))
    stale = sorted(k for k in _NATIVE_ONLY if k in w) + sorted(k for k in _WEB_ONLY if k in n)
    check(f"the same {len(set(n) & set(w))} public names "
          f"(allowed: {', '.join(sorted(_NATIVE_ONLY)) or '-'} native only, "
          f"{', '.join(sorted(_WEB_ONLY)) or '-'} web only)",
          not (missing_web or missing_native or stale),
          f"web lacks {missing_web}; native lacks {missing_native}; "
          f"allow-list entries that no longer differ: {stale}")

    both = sorted(set(n) & set(w))
    kinds = [k for k in both if _kind(n[k]) != _kind(w[k])]
    check("each is a property on both or a method on both", not kinds,
          ", ".join(f"{k}: native {_kind(n[k])}, web {_kind(w[k])}" for k in kinds))

    sigs = [k for k in both if _kind(n[k]) == _kind(w[k]) == "method"
            and _params(n[k]) != _params(w[k])]
    check("signatures agree (parameter names, kinds, defaults)", not sigs,
          "; ".join(f"{k}: native {inspect.signature(n[k])}, "
                    f"web {inspect.signature(w[k])}" for k in sigs))

    native_fields = {f for f, _ in ssruntime_native.ss_instance_step_result._fields_}
    web_fields = set(ssruntime_web._InstanceStepResult.__slots__)
    check("an Instance step result carries the native struct's fields",
          native_fields == web_fields, f"native {sorted(native_fields)}, web {sorted(web_fields)}")

    # The keyword-only parameters differ by design: native's `log` routes the
    # Brain's log callback, which the wasm build does not expose, and web's
    # `timeout` bounds the asynchronous module import.
    check("load_library takes the same positional parameters",
          _params(ssruntime_native.load_library, keyword_only=False)
          == _params(ssruntime_web.load_library, keyword_only=False))


# --- 2. generated scripts ---------------------------------------------------

# What a parameter takes: a benign `base` for when another parameter is under
# test, the awkward values that must coerce into a script (`ok`), and those
# the native bridge's ctypes argtypes reject, which must raise in Python
# before a script is sent (`raises`).
_I = dict(base=0, ok=(True, False, 0, -1, 7, 2.9, -2.9, 2**31, 2**40),
          raises=(None, math.nan, math.inf))
_F = dict(base=0.0, ok=(True, False, 0, -2.5, 1e-7, -1e-7, 1e300,
                        math.nan, math.inf, -math.inf),
          raises=(None,))
_B = dict(base=False, ok=(True, False, None, 0, 1, "", "yes"), raises=())
_S = dict(base="wait",
          ok=("wait", "", 'say "hi"', "it's", "back\\slash", "\\", "line\nbreak",
              "</script>", "\u2028\u2029", "\ud800", "日本語", "${x}",
              "' + x + '", "None", "True"),
          raises=(None, b"wait", 3))
_C = dict(base=[0, 0, 0, 0],
          ok=([0, 1, 2, 3], (True, False, -1, 2**33 + 5), [0xFFFFFFFF] * 4, [1, 2]),
          raises=(None, [None, 0, 0, 0]))
# A slot / event / context handle: only ever what the bridge itself handed out.
# Native passes None on as a null pointer, so no value of it must raise.
_H = dict(base=1, ok=(1, 7, True), raises=())

_CALLS = {
    "configure": dict(render_mode=_I, coordinate_system=_I, origin=_I, unit=_I),
    "setup_animation": dict(name=_S),
    "set_loop_count": dict(loop_count=_I),
    "set_speed_scale": dict(rate=_F),
    "set_frame_no": dict(frame=_F),
    "play_with_start_frame": dict(frame=_F),
    "set_frame_rate": dict(fps=_I),
    "set_animation_section": dict(start=_I, end=_I),
    "set_playback_direction": dict(direction=_I, style=_I),
    "set_skip_frames": dict(skip=_B),
    "update": dict(dt_seconds=_F),
    "update_ms": dict(dt_ms=_F),
    "get_frame_data": dict(frame_no=_F),
    "get_frame_data_view": dict(frame_no=_F),
    "passed_event_index": dict(i=_I),
    "passed_event_source_handle": dict(i=_I),
    "set_track_animation": dict(track=_I, name=_S),
    "clear_track": dict(track=_I),
    "set_track_alpha": dict(track=_I, alpha=_F),
    "track_alpha": dict(track=_I),
    "set_track_blend": dict(track=_I, blend=_I),
    "track_blend": dict(track=_I),
    "set_track_sync": dict(track=_I, sync=_I),
    "track_sync": dict(track=_I),
    "set_track_frame": dict(track=_I, frame=_F),
    "track_frame": dict(track=_I),
    "set_track_speed": dict(track=_I, speed=_F),
    "track_speed": dict(track=_I),
    "set_track_frame_rate": dict(track=_I, fps=_I),
    "track_frame_rate": dict(track=_I),
    "set_track_skip_frames": dict(track=_I, skip=_B),
    "track_skip_frames": dict(track=_I),
    "set_track_playback_direction": dict(track=_I, direction=_I, style=_I),
    "track_playback_direction": dict(track=_I),
    "track_playback_style": dict(track=_I),
    "set_track_loop_count": dict(track=_I, count=_I),
    "track_loop_count": dict(track=_I),
    "is_track_finished": dict(track=_I),
    "track_just_looped": dict(track=_I),
    "set_track_outgoing_event_threshold": dict(track=_I, threshold=_F),
    "track_outgoing_event_threshold": dict(track=_I),
    "crossfade": dict(track=_I, name=_S, duration_ms=_F),
    "fade_track": dict(track=_I, target_alpha=_F, duration_ms=_F),
    "track_fade_progress": dict(track=_I),
    "cancel_track_fade": dict(track=_I),
    "track_main_source": dict(track=_I),
    "add_track_source": dict(track=_I, name=_S, weight=_F),
    "set_source_weight": dict(handle=_I, weight=_F),
    "source_weight": dict(handle=_I),
    "set_source_frame": dict(handle=_I, frame=_F),
    "source_frame": dict(handle=_I),
    "set_source_event_threshold": dict(handle=_I, threshold=_F),
    "source_event_threshold": dict(handle=_I),
    "source_animation_index": dict(handle=_I),
    "find_part_index": dict(part_name=_S),
    "set_part_visibility_override": dict(part=_I, force=_I, cascade=_B),
    "clear_part_visibility_override": dict(part=_I),
    "set_part_color_override": dict(part=_I, blend_op=_I, rgba=_I, priority=_I),
    "set_part_color_override_corners": dict(part=_I, blend_op=_I, corners_rgba=_C,
                                            priority=_I),
    "clear_part_color_override": dict(part=_I),
    "set_part_cell_override": dict(part=_I, cellmap_name_hash=_I, cell_name_hash=_I,
                                   priority=_I),
    "clear_part_cell_override": dict(part=_I),
    "instance_slot_destroy": dict(slot=_H),
    "instance_slot_reset": dict(slot=_H),
    "instance_slot_step": dict(slot=_H, ev=_H, child_ctx=_H, parent_frame=_F,
                               delta_seconds=_F, parent_looped=_B),
    "instance_slot_is_independent": dict(slot=_H),
    "instance_slot_get_speed": dict(slot=_H),
    "effect_slot_create": dict(effect_name_hash=_I, seed=_I),
    "effect_slot_destroy": dict(slot=_H),
    "effect_slot_reset": dict(slot=_H),
    "effect_slot_step": dict(slot=_H, ev=_H, parent_frame=_F, delta_seconds=_F,
                             fps=_F, parent_looped=_B, y_flip=_B, vert_stride=_I,
                             draw=_B),
    "effect_slot_step_view": dict(slot=_H, ev=_H, parent_frame=_F, delta_seconds=_F,
                                  fps=_F, parent_looped=_B, y_flip=_B, vert_stride=_I,
                                  draw=_B),
    "effect_slot_is_independent": dict(slot=_H),
}
# Public methods that take an argument but are not driven above, and why.
# A new one that is in neither table fails, so it cannot go unchecked.
_NOT_CALLED = {
    "load_ssab_bytes": "section 3 drives it, with an accepted and a rejected pack",
    "load_ssab_file": "opens a file, then hands its bytes to load_ssab_bytes",
    "active_event_instance": "sends no script: hands the part index on to the step",
    "active_effect_event": "sends no script: hands the part index on to the step",
}

# The wasm-bindgen enum parameters, by method: their positions in the call.
# The generated glue throws on any other value than 0 or 1.
_ENUM_ARGS = {
    "set_coordinate_system": [0], "set_origin": [0], "set_unit": [0],
    "set_playback_direction": [0, 1], "set_track_playback_direction": [1, 2],
}
_ENUM_CALL = re.compile(r"\.(%s)\(([^()]*)\)" % "|".join(_ENUM_ARGS))
_PY_LITERAL = re.compile(r"\b(True|False|None|nan|inf)\b")
# An unformatted placeholder, or the source of an f-string missing its prefix.
_PY_LEFTOVER = re.compile(r"%[sdr]|\bself\b")


def _scan(src):
    """``(code, double_quoted, error)``: ``src`` with every string literal and
    comment blanked out, the raw double-quoted literals, and what is malformed."""
    code, quoted, i, n = [], [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n" and c != "`":
                    return "".join(code), quoted, "a line break inside a string literal"
                j += 1
            if j >= n:
                return "".join(code), quoted, "an unterminated string literal"
            if c == '"':
                quoted.append(src[i:j + 1])
            code.append(" ")
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                return "".join(code), quoted, "an unterminated comment"
            i = j + 2
        else:
            code.append(c)
            i += 1
    return "".join(code), quoted, None


def _balanced(code) -> bool:
    stack = []
    for c in code:
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack.pop() != "([{"[")]}".index(c)]:
                return False
    return not stack


def _strings(src) -> list:
    """The double-quoted literals of ``src``, decoded."""
    decoded = []
    for q in _scan(src)[1]:
        try:
            decoded.append(json.loads(q))
        except ValueError:
            pass
    return decoded


def _lint(src) -> list[str]:
    """What is wrong with one script."""
    code, _, error = _scan(src)
    if error:
        return [error]
    problems = [f"a Python literal: {m.group(0)}" for m in _PY_LITERAL.finditer(code)]
    problems += [f"Python left in the source: {m.group(0)}"
                 for m in _PY_LEFTOVER.finditer(code)]
    if not _balanced(code):
        problems.append("unbalanced brackets")
    for m in _ENUM_CALL.finditer(code):
        args = [a.strip() for a in m.group(2).split(",")]
        bad = [args[i] for i in _ENUM_ARGS[m.group(1)] if args[i] not in ("0", "1")]
        if bad:
            problems.append(f"{m.group(1)} given {', '.join(bad)} for an enum")
    return problems


def _close(rt):
    """Close ``rt`` now, so its script lands in order: left to ``__del__``, it
    would land whenever the collector got to it."""
    _FAKE.label = "close()"
    rt.close()


def _runtime():
    """A web runtime with a pack bound (an Effect slot needs one)."""
    _FAKE.label = "_WebRuntime() + load_ssab_bytes"
    rt = ssruntime_web._WebRuntime()
    rt.load_ssab_bytes(b"pack")
    return rt


def check_scripts():
    print(f"### generated scripts: {len(_CALLS)} methods, awkward values")
    rt = _runtime()
    web = ssruntime_web._WebRuntime
    takes_args = sorted(k for k, v in _public(web).items()
                        if _kind(v) == "method" and not k.startswith("_")
                        and len(inspect.signature(v).parameters) > 1)
    uncovered = [k for k in takes_args if k not in _CALLS and k not in _NOT_CALLED]
    check("every public method that takes an argument is driven or excused",
          not uncovered, f"neither in _CALLS nor _NOT_CALLED: {uncovered}")

    for method, params in _CALLS.items():
        fn = getattr(rt, method, None)
        if fn is None:
            check(f"{method}: exists", False)
            continue
        declared = [p for p in inspect.signature(fn).parameters]
        if sorted(declared) != sorted(params):
            check(f"{method}: the table names its parameters", False,
                  f"declared {declared}, table {sorted(params)}")
            continue
        base = {p: kind["base"] for p, kind in params.items()}
        problems, coerced, refused = [], 0, 0
        for p, kind in params.items():
            for v in kind["ok"]:
                _FAKE.label = f"{method}({p}={ascii(v)})"
                start = len(_FAKE.scripts)
                try:
                    getattr(rt, method)(**dict(base, **{p: v}))
                except Exception as e:  # noqa: BLE001
                    problems.append(f"{_FAKE.label} raised {type(e).__name__}: {e}")
                    continue
                coerced += 1
                sent = [src for _, src in _FAKE.scripts[start:]]
                for src in sent:
                    problems += [f"{_FAKE.label}: {why}" for why in _lint(src)]
                if kind is _S and not any(v in _strings(src) for src in sent):
                    problems.append(f"{_FAKE.label}: no string literal decodes to it")
            for v in kind["raises"]:
                _FAKE.label = f"{method}({p}={ascii(v)})"
                start = len(_FAKE.scripts)
                try:
                    getattr(rt, method)(**dict(base, **{p: v}))
                    problems.append(f"{_FAKE.label} was accepted, where native raises")
                except Exception:  # noqa: BLE001
                    refused += 1
                if len(_FAKE.scripts) > start:
                    problems.append(f"{_FAKE.label} sent a script")
        check(f"{method}: {coerced} value(s) coerced"
              + (f", {refused} refused in Python" if refused else ""),
              not problems, "\n          ".join(problems[:6])
              + (f"\n          ... and {len(problems) - 6} more" if len(problems) > 6 else ""))
    _close(rt)


# The C-API's reading of a value that is neither 0 nor 1: coordinate system,
# origin and unit take 1 as the second variant and anything else as the first;
# a direction or a style takes any non-zero as backward / ping-pong.
_FOLDS = (
    ("configure", dict(coordinate_system=2), "set_coordinate_system(0)"),
    ("configure", dict(coordinate_system=True), "set_coordinate_system(1)"),
    ("configure", dict(origin=-1), "set_origin(0)"),
    ("configure", dict(unit=1), "set_unit(1)"),
    ("set_playback_direction", dict(direction=2, style=-1), "set_playback_direction(1, 1)"),
    ("set_playback_direction", dict(direction=False, style=0), "set_playback_direction(0, 0)"),
    ("set_track_playback_direction", dict(track=0, direction=-3, style=7),
     "set_track_playback_direction(0, 1, 1)"),
)


def check_folds():
    print("### enum values fold as the C-API reads them")
    rt = _runtime()
    for method, kwargs, want in _FOLDS:
        _FAKE.label = f"{method}({kwargs})"
        start = len(_FAKE.scripts)
        getattr(rt, method)(**kwargs)
        sent = " ".join(src for _, src in _FAKE.scripts[start:])
        check(f"{method}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())}) "
              f"-> {want}", want in sent)
    _close(rt)


# --- 3. a rejected pack -----------------------------------------------------

_REASON = "SSAB schema version mismatch: expected 7, found 6"
_LOAD = "SSRuntimeResource("
# Expected node results, by script index: what the script returns.
_EXPECT: dict[int, str] = {}


def _load(rt, label, answer, *, js_setup=None):
    """Load a pack with the fake answering ``answer``; ``js_setup`` is what
    the node stand-in must be told first so that it answers the same."""
    if js_setup:
        _FAKE.label = f"{label}: stand-in setup"
        _FAKE.run_script(js_setup)
    _FAKE.label = label
    _FAKE.answers[_LOAD] = answer
    start = len(_FAKE.scripts)
    try:
        rt.load_ssab_bytes(b"pack")
        return None, _FAKE.scripts[start:]
    except Exception as e:  # noqa: BLE001
        return e, _FAKE.scripts[start:]
    finally:
        _FAKE.answers[_LOAD] = ""
        _EXPECT[len(_FAKE.scripts) - 1] = answer


def check_rejected_pack():
    print("### a pack the JS side rejects")
    _FAKE.label = "_WebRuntime()"
    rt = ssruntime_web._WebRuntime()

    err, sent = _load(rt, "load: accepted", "")
    check("an accepted pack binds", err is None and rt.resource,
          f"raised {err!r}" if err else "no resource")
    check("a load is one script, with no emscripten FS round-trip",
          len(sent) == 1 and not any("FS." in s or "temp_ssab" in s for _, s in sent),
          f"{len(sent)} script(s)")
    check("no copy of the pack is held on the Python side",
          not any(isinstance(v, (bytes, bytearray)) and v == b"pack"
                  for v in vars(rt).values()))

    rejected = "ss_resource_create failed: " + _REASON
    err, _ = _load(rt, "load: rejected", rejected,
                   js_setup="window.ss_test_reject = %s;" % json.dumps(_REASON))
    check("load_ssab_bytes raises RuntimeError with the Brain's reason",
          isinstance(err, RuntimeError) and _REASON in str(err)
          and str(err).startswith("ss_resource_create failed"), repr(err))
    check("the previous resource stays bound", bool(rt.resource))

    err, _ = _load(rt, "load: unbindable", "ss_runtime_bind_resource failed",
                   js_setup="window.ss_test_reject = null;"
                            " window.ss_test_unbindable = true;")
    check("a refused bind raises RuntimeError, as native does",
          isinstance(err, RuntimeError) and "ss_runtime_bind_resource failed" in str(err),
          repr(err))
    _FAKE.label = "stand-in reset"
    _FAKE.run_script("window.ss_test_unbindable = false;")
    _close(rt)


# --- 4. a refused section --------------------------------------------------

_SECTION = "set_animation_section("


def check_refused_section():
    print("### a section the JS side refuses")
    rt = _runtime()
    for label, start, end, want in (("section: refused", 10, 5, "0"),
                                    ("section: accepted", 5, 10, "1")):
        _FAKE.label = label
        _FAKE.answers[_SECTION] = want
        try:
            got = rt.set_animation_section(start, end)
        finally:
            del _FAKE.answers[_SECTION]
            _EXPECT[len(_FAKE.scripts) - 1] = want
        check(f"set_animation_section({start}, {end}) returns {want == '1'}",
              got is (want == "1"), f"returned {got!r}")
    _close(rt)


# --- every recorded script --------------------------------------------------

def check_all_linted():
    """The constructor and load scripts too, which no call above lints."""
    print("### every script sent")
    bad = [f"{label}: {why}" for label, src in _FAKE.scripts for why in _lint(src)]
    check(f"all {len(_FAKE.scripts)} scripts pass the lint", not bad,
          "\n          ".join(bad[:8]))


# --- the recorded scripts under node ----------------------------------------

# Every script runs in one context, in the order it was sent. The stand-in for
# a wasm-bindgen object answers 0 from every method, except the few whose result
# a script dereferences; an enum argument other than 0 or 1 throws, as the
# generated glue does, and so does the pack constructor once told to reject,
# and set_animation_section given an end before its start (the stand-in knows
# no last frame, so any two ends from 0 up count as inside the animation).
_NODE_DRIVER = r"""
const vm = require('vm');
const {enums, scripts} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const sb = {};
sb.window = sb;
function stub() {
  return new Proxy({}, {get(_, k) {
    if (typeof k !== 'string') return undefined;
    if (k === 'bind_resource') return () => !sb.ss_test_unbindable;
    if (k.startsWith('get_active_')) return () => ({free() {}});
    if (k === 'set_animation_section') return (s, e) => {
      if (s >= 0 && e >= 0 && e < s) throw 'Invalid parameter';
      return 0;
    };
    return (...a) => {
      for (const i of (Object.prototype.hasOwnProperty.call(enums, k) ? enums[k] : []))
        if (a[i] !== 0 && a[i] !== 1) throw new Error('invalid enum value passed');
      return 0;
    };
  }});
}
// A stand-in under every id, since the fake handed out ids the JS never made.
function table() {
  return new Proxy({}, {get(t, k) {
    if (typeof k === 'string' && !(k in t)) t[k] = stub();
    return t[k];
  }});
}
Object.assign(sb, {
  ss_ctxs: table(), ss_resources: table(), ss_instances: table(), ss_effects: table(),
  ssruntime: {
    SSRuntimeContext: function () { return stub(); },
    SSRuntimeResource: function (bytes) {
      if (!(bytes instanceof Uint8Array)) throw new TypeError('expected a Uint8Array');
      if (sb.ss_test_reject) throw sb.ss_test_reject;
      return stub();
    },
    SSRuntimeInstanceSlot: {create: () => stub()},
    SSRuntimeEffectSlot: {create: () => stub()},
  },
  ssruntime_wasm: {memory: {buffer: new ArrayBuffer(64)}},
  Module: {HEAPU8: new Uint8Array(64), HEAPF64: new Float64Array(8)},
});
vm.createContext(sb);
process.stdout.write(JSON.stringify(scripts.map((src) => {
  try {
    // A script's completion value may be a stand-in object: only a
    // primitive is a value the bridge reads back.
    const v = vm.runInContext(src, sb);
    return {ok: true, value: v === null || typeof v === 'object' || typeof v === 'function'
                              || v === undefined ? null : String(v)};
  } catch (e) {
    return {ok: false, error: e instanceof Error ? e.name + ': ' + e.message : String(e)};
  }
})));
"""


def check_under_node():
    print("### the recorded scripts under node")
    node = shutil.which("node")
    if node is None:
        print("    SKIP  node is not on PATH: the scripts were linted, not run")
        return
    scripts = list(_FAKE.scripts)
    payload = json.dumps({"enums": _ENUM_ARGS, "scripts": [s for _, s in scripts]})
    try:
        proc = subprocess.run([node, "-e", _NODE_DRIVER], input=payload,
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        check("node ran the driver", False, f"{e!r}")
        return
    try:
        results = json.loads(proc.stdout)
    except ValueError:
        check("node ran the driver", False,
              f"exit {proc.returncode}: {proc.stderr.strip()[-400:]}")
        return
    if len(results) != len(scripts):
        check("node ran every script", False, proc.stderr.strip()[-400:])
        return
    thrown = [f"{scripts[i][0]}: {r['error']}"
              for i, r in enumerate(results) if not r["ok"]]
    check(f"all {len(results)} scripts compile and run without a throw", not thrown,
          "\n          ".join(thrown[:8])
          + (f"\n          ... and {len(thrown) - 8} more" if len(thrown) > 8 else ""))
    for i, want in sorted(_EXPECT.items()):
        got = results[i].get("value")
        check(f"{scripts[i][0]}: the script returns {ascii(want or '')}",
              got == want, f"returned {ascii(got)}")


def main(argv) -> int:
    print("== web bridge verification (fake emscripten) ==\n")
    if ssruntime_web.emscripten is not _FAKE:
        print("    FAIL  ss_renpy.ssruntime_web did not pick up the fake emscripten")
        return 1
    check_parity()
    check_scripts()
    check_folds()
    check_rejected_pack()
    check_refused_section()
    check_all_linted()
    check_under_node()
    print("\n== RESULT:", "ALL PASS" if _ok else "FAILURES PRESENT", "==")
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
