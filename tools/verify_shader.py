#!/usr/bin/env python3
"""Headless check for the user-shader effect core (SS6 ``ss-*`` family).

Exercises the engine-independent half of the user-shader feature without a GUI
(the GLSL itself — sepia / outline / hsb / blur / wave / circle / spot / … —
still needs a real GL2 run; use the Asset Browser, Shift+B, on
``overall/Shader.ssab``). Four layers:

  * **struct sanity** — that the bulk ``PartState`` decode record
    (:data:`ss_renpy.framedata._PS_REC`, now carrying the ``shader`` short) still
    matches ``PartState.SizeOf()`` so the fast path stays enabled;
  * **hash catalog** — that the render layer's name→id_hash map (built with the
    Brain's own ``ss_runtime_hash_string``) covers every ``ss-*`` variant and
    every ``id_hash`` the ``overall/Shader.ssab`` showcase actually emits — i.e.
    the dispatch in ``spritestudio.rpy`` will recognise all of them;
  * **core surface** — that :func:`ss_renpy.framedata.iter_draw_plan` /
    :func:`ss_renpy.instance.collect_ordered` stamp each shadered part's
    ``MeshPart`` with the right ``shader_id_hash`` + a finite 8-float
    ``shader_params``, and that a non-shadered part reports ``0`` / ``()``;
  * **CPU twins** — property checks on Python reproductions of a few
    pure-function variants (sepia / bmask / hsb / step), the same way
    ``ss_renpy.mask.mask_passes`` twins the mask-replay GLSL. These guard the
    formula's gross behaviour (passthrough / grayscale / discard / darken), not
    pixel-exact output (that is the GPU pass).

Plain CPython — no Ren'Py.

Usage:  python tools/verify_shader.py [pack.ssab ...]
"""

from __future__ import annotations

import math
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import ssruntime, framedata  # noqa: E402
from ss_renpy.instance import collect_ordered, display_frame  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402
from ss.runtime.PartState import PartState  # noqa: E402

# The 13 SS6 variants ported in spritestudio.rpy (keep in sync with
# _SS_USER_NAME_MAP there). Default / TestStub are not user effects.
SHADER_NAMES = [
    "ss-sepia", "ss-outline", "ss-bmask", "ss-hsb", "ss-step", "ss-move",
    "ss-wave", "ss-noise", "ss-blur", "ss-pix", "ss-scatter", "ss-circle",
    "ss-spot",
]


def _check(cond, msg, fails):
    if not cond:
        print("    FAIL:", msg)
        fails.append(msg)
    return cond


# --------------------------------------------------------------------------
# 1. struct sanity (the fast-path record grew a `shader` field)
# --------------------------------------------------------------------------
def check_struct() -> bool:
    fails: list = []
    size = struct.calcsize(framedata._PS_REC.format)
    print("### struct: calcsize(_PS_REC)=%d  _PS_SIZE=%d  PartState.SizeOf=%d"
          % (size, framedata._PS_SIZE, PartState.SizeOf()))
    _check(size == framedata._PS_SIZE == PartState.SizeOf(),
           "bulk PartState record size mismatch (fast path would disable / "
           "misread the shader field)", fails)
    print("### struct", "PASS" if not fails else "FAIL")
    return not fails


# --------------------------------------------------------------------------
# 2/3. hash catalog + core surface on a real pack
# --------------------------------------------------------------------------
def check_pack(lib, path: str, anim=None, expect_shaders=True) -> bool:
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    name = os.path.basename(path)
    part_names = {p.index: p.name for p in meta.parts()}
    fails: list = []

    # Catalog the render layer would build (Brain's own fnv1a → variant).
    catalog = {lib.ss_runtime_hash_string(n.encode("utf-8")): n
               for n in SHADER_NAMES}
    print("### %s  catalog=%d distinct hashes" % (name, len(catalog)))
    _check(len(catalog) == len(SHADER_NAMES),
           "two ss-* names hash to the same id (dispatch collision)", fails)

    rt = ssruntime.SSRuntime(lib)
    try:
        rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                     origin=ssruntime.ORIGIN_CENTER)
        rt.load_ssab_bytes(data)
        a0 = anim or meta.animation_names()[0]
        if not rt.setup_animation(a0):
            print("    FAIL: setup_animation(%r)" % a0)
            return False
        rt.set_loop(-1)
        rt.play()
        fps = rt.fps or 30
        dt = 1.0 / fps
        total = max(1, meta.animations()[0].total_frame)

        used_hashes: set[int] = set()
        shadered_meshes = 0
        plain_meshes = 0
        bad_params = 0        # shadered part w/o a finite 8-float params tuple
        bad_plain = 0         # non-shadered part with non-empty params
        unknown = set()       # emitted id_hash absent from the catalog

        for fr in range(total + 1):
            f = rt.update(dt)
            fb = rt.get_frame_data(display_frame(f, False))
            if not fb:
                continue
            fd = framedata.parse(fb)
            items = collect_ordered(rt, fd, None, None, f, dt, rt.is_looped,
                                    False)
            for tag, mp in items:
                if tag != "mesh":
                    continue
                if mp.shader_id_hash:
                    shadered_meshes += 1
                    used_hashes.add(mp.shader_id_hash)
                    if mp.shader_id_hash not in catalog:
                        unknown.add(mp.shader_id_hash)
                    p = mp.shader_params
                    if (len(p) != 8
                            or any(not math.isfinite(v) for v in p)):
                        bad_params += 1
                else:
                    plain_meshes += 1
                    if mp.shader_params:
                        bad_plain += 1

        seen_names = sorted(catalog[h] for h in used_hashes if h in catalog)
        missing = [n for n in SHADER_NAMES
                   if lib.ss_runtime_hash_string(n.encode()) not in used_hashes]
        print("    shadered meshes=%d  plain meshes=%d  distinct variants=%d"
              % (shadered_meshes, plain_meshes, len(used_hashes)))
        print("    variants seen: %s" % (", ".join(seen_names) or "(none)"))
        if missing:
            print("    (not exercised by this pack: %s)" % ", ".join(missing))

        _check(not unknown,
               "id_hash(es) emitted that the catalog does not cover: %s"
               % ["0x%08x" % h for h in unknown], fails)
        _check(bad_params == 0,
               "%d shadered part(s) had a bad shader_params tuple" % bad_params,
               fails)
        _check(bad_plain == 0,
               "%d non-shadered part(s) carried shader_params" % bad_plain,
               fails)
        if expect_shaders:
            _check(shadered_meshes > 0,
                   "no shadered MeshPart surfaced (core is not reading "
                   "PartState.shader)", fails)
            # On the official showcase, expect the full family.
            if os.path.basename(path) == "Shader.ssab":
                _check(not missing,
                       "Shader.ssab did not exercise every ss-* variant "
                       "(missing: %s)" % ", ".join(missing), fails)
        else:
            # Negative pack: the core must NOT invent shaders where none exist.
            _check(shadered_meshes == 0,
                   "%d part(s) spuriously reported a shader on a pack with none"
                   % shadered_meshes, fails)
            _check(plain_meshes > 0, "no geometry to check the plain invariant",
                   fails)
        print("### %s" % name, "PASS" if not fails else "FAIL")
        return not fails
    finally:
        rt.close()


# --------------------------------------------------------------------------
# 4. CPU twins — Python reproductions of a few pure-function variants, checked
#    for gross semantic properties (mirrors the GLSL in spritestudio.rpy).
# --------------------------------------------------------------------------
def _mix(a, b, t):
    return a * (1.0 - t) + b * t


def _step(edge, x):
    return 0.0 if x < edge else 1.0


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def sepia(rgb, fPower):
    w = (0.298912, 0.586611, 0.114478)
    gray = sum(rgb[i] * w[i] for i in range(3))
    grey = (gray, gray, gray)
    sep = tuple(gray * c for c in (1.07, 0.74, 0.43))
    s = _step(fPower, 0.0)   # 1.0 when fPower <= 0
    toned = tuple(_mix(sep[i], grey[i], s) for i in range(3))
    return tuple(_mix(rgb[i], toned[i], abs(fPower)) for i in range(3))


def bmask_keeps(rgb, fB):
    b = abs(_step(fB, 0.0) - max(rgb))
    return not (b <= abs(fB))


def _rgb_to_hsb(r, g, b, a):
    K = (0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0)
    s = _step(b, g)
    p = tuple(_mix(A, B, s) for A, B in
              zip((b, g, K[3], K[2]), (g, b, K[0], K[1])))
    s2 = _step(p[0], r)
    q = tuple(_mix(A, B, s2) for A, B in
              zip((p[0], p[1], p[3], r), (r, p[1], p[2], p[0])))
    d = q[0] - min(q[3], q[1])
    e = 1.0e-10
    return (abs(q[2] + (q[3] - q[1]) / (6.0 * d + e)), d / (q[0] + e), q[0], a)


def _hsb_to_rgb(h, s, v, a):
    K = (1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0)
    p = [abs((((h + k) % 1.0) * 6.0) - K[3]) for k in (K[0], K[1], K[2])]
    return tuple(v * _mix(K[0], _clamp(p[i] - K[0], 0.0, 1.0), s)
                 for i in range(3)) + (a,)


def hsb(rgb, fHue, fSat, fBri):
    h, s, v, a = _rgb_to_hsb(rgb[0], rgb[1], rgb[2], 1.0)
    h += fHue
    s = _clamp(s + fSat, 0.0, 1.0)
    v = _clamp(v + fBri, 0.0, 1.0)
    h = h + 1.0 if h < 0.0 else (h - 1.0 if h > 1.0 else h)
    return _hsb_to_rgb(h, s, v, a)


def step_fx(rgb, fThreshold, fStage, fColor):
    d = 1.0 + 255.0 * abs(fStage)
    e = 1.0e-10
    t = abs(fThreshold)
    b = abs(_step(fThreshold, 0.0) - max(rgb))
    r = _clamp(math.floor((b - t) / (t + e) * 256.0 / d) * d / 256.0, 0.0, 1.0)
    c = _step(t, b) * r
    return tuple(_mix(c, rgb[i] * c, fColor) for i in range(3))


def check_cpu_twins() -> bool:
    fails: list = []
    eq = lambda a, b: abs(a - b) < 1e-4
    grey = lambda c: eq(c[0], c[1]) and eq(c[1], c[2])

    # sepia: fPower 0 = passthrough; <0 = grayscale; >0 = warm (r>g>b on grey).
    mid = (0.5, 0.4, 0.2)
    _check(all(eq(a, b) for a, b in zip(sepia(mid, 0.0), mid)),
           "sepia(fPower=0) is not passthrough", fails)
    _check(grey(sepia(mid, -1.0)), "sepia(fPower<0) is not grayscale", fails)
    warm = sepia((0.5, 0.5, 0.5), 1.0)
    _check(warm[0] > warm[1] > warm[2], "sepia(fPower>0) is not warm-toned",
           fails)

    # bmask: positive brightness masks dark, keeps bright.
    _check(bmask_keeps((1.0, 1.0, 1.0), 0.188), "bmask should keep white", fails)
    _check(not bmask_keeps((0.0, 0.0, 0.0), 0.188),
           "bmask should discard black", fails)

    # hsb: brightness -1 => black; saturation -1 => grayscale.
    _check(all(eq(c, 0.0) for c in hsb((0.8, 0.2, 0.4), 0.0, 0.0, -1.0)[:3]),
           "hsb(fBri=-1) is not black", fails)
    _check(grey(hsb((0.8, 0.2, 0.4), 0.0, -1.0, 0.0)),
           "hsb(fSat=-1) is not grayscale", fails)

    # step: finite + in-range for a representative 2-value config.
    v = step_fx((0.7, 0.3, 0.5), 0.482, 1.0, 0.5)
    _check(all(math.isfinite(c) for c in v), "step produced non-finite output",
           fails)

    print("### cpu twins", "PASS" if not fails else "FAIL")
    return not fails


def main(argv) -> int:
    if len(argv) > 1:
        targets = [(t, None, True) for t in argv[1:]]
    else:
        targets = [
            (os.path.join(_GAME, "ss_assets", "overall", "Shader.ssab"),
             None, True),
            # Negative pack (no user shaders): the core must report all-plain.
            (os.path.join(_GAME, "ss_assets", "overall", "Basic.ssab"),
             None, False),
        ]
    lib = ssruntime.load_library()
    print("== User-shader (ss-*) verification ==\n")
    allok = check_struct()
    print()
    allok &= check_cpu_twins()
    print()
    for path, anim, expect in targets:
        allok &= check_pack(lib, path, anim, expect_shaders=expect)
        print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
