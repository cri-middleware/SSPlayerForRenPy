#!/usr/bin/env python3
"""Headless check of the Doll fixture: Instance and Effect parts in one character.

``tests/Doll`` (deployed to ``game/ss_assets/Doll/``) is the only fixture whose
Instance parts play *another* pack: each body pack (``Action01_Body``,
``Action02_Body``) has two Instance parts playing the ``Eye`` pack's ``Wait``,
beside Effect parts that run ``Effect01`` / ``Effect02``. Each body pack also
has a ``Wait`` of its own, four times as long as the Eye's, so a child resolved
against the wrong pack still finds a ``Wait`` and plays; the geometry check
below is what tells the two apart.

Every animation of every Doll pack is stepped ``TICKS`` ticks, one frame each,
through ``SSInternalPlayer``, and checked for:

  * cross-pack resolution — every Instance part has a child built from the pack
    it names, playing the animation it names over that animation's frames;
  * instance children drawing — on every tick its part shows, a child draws
    what a standalone player of the referenced pack draws at the frame the slot
    computed, placed in the root's plan by the Instance part's world matrix, and
    over the run it plays every frame of its animation;
  * effect parts stepping — every slot steps once a tick, drawn exactly on the
    ticks its part shows, with particles on every one of them that move from
    tick to tick, and the root's plan carries exactly the batches it returned;
  * clean playback — ``update()`` swallows exceptions, so a tick that comes
    back empty or falls back to Normal parts only is a failure; every position
    and colour is finite, every texture resolves to a file, every mesh UV lies
    on its atlas, and the head plays every frame of the section and loops.

And one check off the deployed data: the Eye pack the body packs reach across
to, patched in memory to one schema version behind the runtime's, must be
refused by the native bridge, naming both versions, before its bytes reach
``ss_resource_create_*`` — the check binds through a library whose constructors
only count calls, so a regressed gate fails here instead of parsing the pack.
A body pack handed that Eye, or one without ``Wait``, plays on without its
eyes, and its ``instance_problems`` must name each part left without a child
and why.

Plain CPython — no Ren'Py.

Usage:  python tools/verify_doll.py [doll_dir]   (default: game/ss_assets/Doll)
"""

from __future__ import annotations

import math
import os
import struct
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy import framedata, ssruntime  # noqa: E402
from ss_renpy.player import SSInternalPlayer  # noqa: E402
from ss_renpy.resource import RecordingResourceManager, filesystem_pack_reader  # noqa: E402
from ss_renpy.ssab_meta import SsabMeta  # noqa: E402
from ss.format.SsAnimeBinary import SsAnimeBinary  # noqa: E402

TICKS = 300
_PACKS = ("Action01_Body", "Action02_Body", "Eye")


def _sig(positions) -> tuple:
    """A vertex list as a hashable, rounding-tolerant key."""
    return tuple(round(c, 3) for xy in positions for c in xy)


def _png_size(path: str):
    """(width, height) from a PNG's IHDR, or None for anything else."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


class _Report:
    """Collects failures, printing the first of each kind and counting the rest
    so a defect hit on every tick stays one line."""

    def __init__(self):
        self.counts: Counter = Counter()

    def fail(self, kind: str, detail: str = "") -> None:
        self.counts[kind] += 1
        if self.counts[kind] == 1:
            print(f"    FAIL: {kind}" + (f" ({detail})" if detail else ""))

    def close(self) -> bool:
        for kind, n in self.counts.items():
            if n > 1:
                print(f"    FAIL: {kind}: {n} times in all")
        return not self.counts


class _Taps:
    """Per-tick records of what the player's rigs did, by wrapping them on the
    instance (the player itself is unchanged). Cleared before every tick."""

    def __init__(self, p: SSInternalPlayer):
        self.child = {}        # instance part index -> (child frame, child-space meshes)
        self.fx_drawn = {}     # effect part index -> batches its drawn step returned
        self.fx_steps = Counter()
        self.fallbacks = 0     # the full draw walk raised; Normal parts only

        if p._instances is not None:
            for index, ch in p._instances._children.items():
                ch.sub.render_at = self._child_tap(index, ch.sub.render_at)
        if p._effects is not None:
            collect, idle = p._effects.collect, p._effects.step_idle

            def collect_tap(index, *a, **k):
                out = collect(index, *a, **k)
                self.fx_steps[index] += 1
                self.fx_drawn[index] = out
                return out

            def idle_tap(index, *a, **k):
                self.fx_steps[index] += 1
                return idle(index, *a, **k)

            p._effects.collect, p._effects.step_idle = collect_tap, idle_tap
        plain = p._plain_items

        def plain_tap(*a, **k):
            self.fallbacks += 1
            return plain(*a, **k)

        p._plain_items = plain_tap

    def _child_tap(self, index, render_at):
        def tap(frame_no, *a, **k):
            out = render_at(frame_no, *a, **k)
            self.child[index] = (frame_no, [m for t, m in out if t == "mesh"])
            return out
        return tap

    def clear(self) -> None:
        self.child.clear()
        self.fx_drawn.clear()
        self.fx_steps.clear()
        self.fallbacks = 0


def _resolve_children(p, meta, folder, lib, rep):
    """Check every Instance part's child; return ``{part index: reference}``,
    a standalone player of the pack + animation the part names."""
    refs = {}
    parts = meta.instance_parts()
    if not parts:
        return refs
    externals = {e.anime_pack_name for e in meta.external_instances()}
    children = p._instances._children if p._instances is not None else {}
    own = {a.name: a for a in meta.animations()}
    for part in parts:
        want = f"{part.ref_anime_pack}/{part.ref_anime_name}"
        if part.ref_anime_pack == meta.name or part.ref_anime_pack not in externals:
            rep.fail(f"{part.name!r} does not reference an external pack", want)
            continue
        ch = children.get(part.index)
        if ch is None:
            rep.fail(f"{part.name!r} has no child: {want} did not resolve "
                     "(missing, or refused by the runtime)")
            continue
        if (ch.sub.meta.name, ch.sub.current_animation) != (
                part.ref_anime_pack, part.ref_anime_name):
            rep.fail(f"{part.name!r} child plays the wrong animation",
                     f"{ch.sub.meta.name}/{ch.sub.current_animation}, want {want}")
            continue
        ref_data = open(os.path.join(folder, part.ref_anime_pack + ".ssab"), "rb").read()
        ref_anim = {a.name: a for a in SsabMeta(ref_data).animations()}[part.ref_anime_name]
        if (ch.sub.start_frame, ch.sub.end_frame) != (ref_anim.start_frame,
                                                      ref_anim.end_frame):
            rep.fail(f"{part.name!r} child section",
                     f"{ch.sub.start_frame}..{ch.sub.end_frame}, "
                     f"{want} is {ref_anim.start_frame}..{ref_anim.end_frame}")
            continue
        ref = SSInternalPlayer(ref_data, lib=lib, base_dir=p.base_dir,
                               resource_manager=RecordingResourceManager())
        if not ref.set_animation(part.ref_anime_name):
            rep.fail(f"standalone {want} did not set up")
            ref.close()
            continue
        refs[part.index] = (part, ref, ref_anim)
        same = own.get(part.ref_anime_name)
        print(f"    instance {part.name!r} (part {part.index}) -> {want}, "
              f"frames {ref_anim.start_frame}..{ref_anim.end_frame}"
              + (f" (this pack's own {part.ref_anime_name!r} is "
                 f"{same.start_frame}..{same.end_frame})" if same else ""))
    return refs


def _check_effect_parts(p, meta, rep):
    """The Effect parts' slots exist and reference an effect this pack embeds."""
    embedded = {e.name_hash: e.name for e in meta.effects()}
    slots = p._effects._slots if p._effects is not None else {}
    for part in meta.effect_parts():
        name = embedded.get(part.ref_effect_name_hash)
        if name is None:
            rep.fail(f"effect part {part.name!r} references no embedded effect",
                     f"hash {part.ref_effect_name_hash}")
        elif not slots.get(part.index):
            rep.fail(f"effect part {part.name!r} has no slot ({name})")
        else:
            print(f"    effect {part.name!r} (part {part.index}) -> {name}")


def _check_animation(p, anim, taps, refs, atlases, rep) -> None:
    if not p.set_animation(anim.name):
        rep.fail(f"set_animation({anim.name!r})")
        return
    p.set_loop_count(-1)
    p.play()
    fps = p.frame_rate or anim.fps or 30
    dt_ms = 1000.0 / fps
    frames = set(range(p.start_frame, p.end_frame + 1))
    fx_parts = list(p._effects.part_indices()) if p._effects is not None else []

    seen, loops, meshes, quads = set(), 0, 0, 0
    child_frames = {i: set() for i in refs}
    child_ticks = Counter()
    fx_ticks = Counter()
    last_fx = {}               # effect part -> geometry of its previous drawn tick
    for tick in range(TICKS):
        taps.clear()
        plan = p.update(dt_ms)
        if not plan.items:
            rep.fail("update() returned no items (it swallows exceptions)",
                     f"{anim.name} tick {tick}")
            continue
        if taps.fallbacks:
            rep.fail("the draw walk raised and fell back to Normal parts only",
                     f"{anim.name} tick {tick}")
        seen.add(int(math.floor(plan.frame_no)))
        loops += bool(plan.looped)
        hidden = plan.hidden_parts or set()

        root = Counter()
        n_fx = 0
        for tag, item in plan.items:
            for (x, y) in item.positions:
                if not (math.isfinite(x) and math.isfinite(y)):
                    rep.fail("non-finite position", f"{anim.name} tick {tick}")
                    break
            if tag == "fx":
                n_fx += 1
                continue
            meshes += 1
            root[_sig(item.positions)] += 1
            path = p.texture_path(item.texture_hash)
            size = atlases.get(path)
            if size is None:
                rep.fail("mesh texture does not resolve to a PNG",
                         f"hash {item.texture_hash} -> {path!r}")
                continue
            w, h = size
            if not all(-1e-3 <= u <= w + 1e-3 and -1e-3 <= v <= h + 1e-3
                       for (u, v) in item.uvs):
                rep.fail("mesh UV off its atlas",
                         f"part {item.part_index}, atlas {w}x{h}")

        # Instance children: drawn whenever the part shows, as the referenced
        # pack draws itself at that frame, and placed by the part's matrix.
        for index, (part, ref, _ref_anim) in refs.items():
            got = taps.child.get(index)
            if index in hidden:
                continue
            if got is None or not got[1]:
                rep.fail(f"instance {part.name!r} drew nothing while shown",
                         f"{anim.name} tick {tick}")
                continue
            child_frame, child_meshes = got
            child_ticks[index] += 1
            child_frames[index].add(int(math.floor(child_frame)))
            want = sorted(_sig(m.positions) for t, m in
                          ref.render_at(child_frame, False, dt_ms / 1000.0)
                          if t == "mesh")
            if sorted(_sig(m.positions) for m in child_meshes) != want:
                rep.fail(f"instance {part.name!r} child geometry differs from "
                         f"standalone {part.ref_anime_pack}/{part.ref_anime_name}",
                         f"{anim.name} tick {tick}, child frame {child_frame}")
            matrix = plan.world_matrices[index * 16:index * 16 + 16]
            for m in child_meshes:
                placed = _sig(framedata.transform_mesh_part(m, matrix).positions)
                if root[placed] < 1:
                    rep.fail(f"instance {part.name!r} child mesh is not in the "
                             "root plan at the part's matrix",
                             f"{anim.name} tick {tick}")
                    break

        # Effect parts: one step a tick, drawn exactly when the part shows.
        drawn_batches = 0
        for index in fx_parts:
            if taps.fx_steps[index] != 1:
                rep.fail("effect slot did not step exactly once",
                         f"part {index}, {taps.fx_steps[index]} steps, "
                         f"{anim.name} tick {tick}")
            batches = taps.fx_drawn.get(index)
            if (batches is not None) != (index not in hidden):
                rep.fail("effect drawn state disagrees with the part's "
                         "visibility", f"part {index}, {anim.name} tick {tick}")
            if batches is None:
                last_fx.pop(index, None)
                continue
            drawn_batches += len(batches)
            n = sum(len(b.positions) // 4 for b in batches)
            if n == 0:
                rep.fail("shown effect produced no particles",
                         f"part {index}, {anim.name} tick {tick}")
                continue
            fx_ticks[index] += 1
            quads += n
            for b in batches:
                if p.texture_path(b.cellmap_hash) not in atlases:
                    rep.fail("effect cellmap does not resolve",
                             f"hash {b.cellmap_hash}")
                if not all(math.isfinite(c) for col in b.colors for c in col):
                    rep.fail("non-finite effect colour", f"part {index}")
            geometry = tuple(_sig(b.positions) for b in batches)
            if last_fx.get(index) == geometry:
                rep.fail("effect particles did not move between ticks",
                         f"part {index}, {anim.name} tick {tick}")
            last_fx[index] = geometry
        if n_fx != drawn_batches:
            rep.fail("root plan's effect batches differ from the slots' output",
                     f"{n_fx} in the plan, {drawn_batches} stepped, "
                     f"{anim.name} tick {tick}")

    if seen != frames:
        rep.fail(f"{anim.name}: head missed frames",
                 f"{sorted(frames - seen)[:8]}")
    n_frames = len(frames)
    if not TICKS // n_frames - 1 <= loops <= TICKS // n_frames:
        rep.fail(f"{anim.name}: loop count",
                 f"{loops} over {TICKS} ticks of a {n_frames}-frame section")
    for index, (part, _ref, ref_anim) in refs.items():
        want = set(range(ref_anim.start_frame, ref_anim.end_frame + 1))
        if child_ticks[index] and child_frames[index] != want:
            rep.fail(f"{anim.name}: instance {part.name!r} child missed frames",
                     f"{sorted(want - child_frames[index])[:8]}")
    print(f"    {anim.name:<8} frames {p.start_frame}..{p.end_frame}  loops={loops}  "
          f"meshes/tick={meshes / TICKS:.1f}  "
          f"child ticks={dict(child_ticks)}  fx ticks={dict(fx_ticks)}  "
          f"particle quads={quads}")


def check_pack(lib, folder: str, name: str) -> bool:
    path = os.path.join(folder, name + ".ssab")
    data = open(path, "rb").read()
    meta = SsabMeta(data)
    print(f"### {name}.ssab  animations={meta.animation_names()}  "
          f"instance_parts={len(meta.instance_parts())}  "
          f"effect_parts={len(meta.effect_parts())}")
    rep = _Report()
    base_dir = os.path.relpath(folder, _GAME).replace("\\", "/")
    try:
        p = SSInternalPlayer(data, lib=lib, base_dir=base_dir,
                             resource_manager=RecordingResourceManager(),
                             pack_reader=filesystem_pack_reader(folder))
    except Exception as e:  # noqa: BLE001 — the reason is the report
        print(f"    FAIL: the pack does not load: {e}")
        return False
    refs = {}
    try:
        refs = _resolve_children(p, meta, folder, lib, rep)
        _check_effect_parts(p, meta, rep)
        # Every image the player knows, keyed by the path a hash resolves to.
        atlases = {}
        for image in set(p._texmap.values()):
            full = os.path.join(_GAME, base_dir, image)
            size = _png_size(full) if os.path.exists(full) else None
            if size is not None:
                atlases[f"{base_dir}/{image}"] = size
        taps = _Taps(p)
        for anim in meta.animations():
            _check_animation(p, anim, taps, refs, atlases, rep)
    finally:
        for _part, ref, _anim in refs.values():
            ref.close()
        p.close()
    ok = rep.close()
    if ok:
        print("    -> PASS")
    return ok


class _NoCreate:
    """``lib`` with ``ss_resource_create_*`` replaced by a counter that returns
    NULL: a pack that gets past the bridge's checks fails this tool rather than
    reaching a runtime that does not validate it."""

    def __init__(self, lib):
        self._lib = lib
        self.reached = 0

    def __getattr__(self, name):
        if name.startswith("ss_resource_create"):
            def create(*_args):
                self.reached += 1
                return None
            return create
        return getattr(self._lib, name)


def _at_version(data: bytes, version: int):
    """``data`` with its schema version field set to ``version``, or None when
    the pack carries no such field."""
    data = bytearray(data)
    root = SsAnimeBinary.GetRootAs(bytes(data), 0)
    field = root._tab.Offset(4)          # the version field, as Version() reads it
    if not field:
        return None
    struct.pack_into("<I", data, root._tab.Pos + field, version)
    return bytes(data)


def check_stale_reference(lib, folder: str) -> bool:
    print("### Eye.ssab one schema version behind (patched in memory)")
    reads = int(lib.ss_runtime_ssab_schema_version())
    data = _at_version(open(os.path.join(folder, "Eye.ssab"), "rb").read(),
                       reads - 1)
    if data is None:
        print("    FAIL: Eye.ssab carries no schema version field")
        return False
    guard = _NoCreate(lib)
    rt = ssruntime.SSRuntime(guard)
    err = None
    try:
        rt.load_ssab_bytes(data)
    except RuntimeError as e:
        err = str(e)
    finally:
        rt.close()
    ok = True
    if guard.reached:
        print("    FAIL: the stale pack reached ss_resource_create_*")
        ok = False
    if (err is None or f"schema version {reads - 1} " not in err
            or f"reads version {reads}." not in err):
        print(f"    FAIL: the refusal does not name both versions: {err!r}")
        ok = False
    if ok:
        print(f"    refused: {err}\n    -> PASS")
    return ok


def check_unbuilt_children(lib, folder: str) -> bool:
    """A body pack whose Eye will not build plays on without its eyes, and
    nothing on screen says why, so the root has to: ``instance_problems`` names
    each Instance part left without a child, what it plays, and the reason."""
    print("### Action01_Body with an Eye that will not build")
    body = open(os.path.join(folder, "Action01_Body.ssab"), "rb").read()
    eye = open(os.path.join(folder, "Eye.ssab"), "rb").read()
    parts = sorted(p.name for p in SsabMeta(body).instance_parts())
    reads = int(lib.ss_runtime_ssab_schema_version())
    ringo = os.path.join(_GAME, "ss_assets", "Ringo", "Ringo.ssab")
    base_dir = os.path.relpath(folder, _GAME).replace("\\", "/")
    cases = (
        ("Eye as deployed", eye, None),
        ("Eye one schema version behind", _at_version(eye, reads - 1),
         f"schema version {reads - 1} "),
        # Ringo has no `Wait`; the bytes stand in for an Eye re-exported without it.
        ("an Eye with no Wait", open(ringo, "rb").read(),
         "that pack has no animation 'Wait'"),
    )
    ok = True
    for label, eye_bytes, reason in cases:
        p = SSInternalPlayer(body, lib=lib, base_dir=base_dir,
                             resource_manager=RecordingResourceManager(),
                             pack_reader=lambda name, d=eye_bytes:
                             d if name == "Eye" else b"")
        try:
            got = p.instance_problems
        finally:
            p.close()
        if reason is None:
            if got:
                print(f"    FAIL: {label}: reported {got}"); ok = False
            continue
        named = sorted(part for part in parts
                       if any(f"{part!r} (playing Eye/Wait)" in m for m in got))
        if len(got) != len(parts) or named != parts \
                or not all(reason in m for m in got):
            print(f"    FAIL: {label}: want one message per part {parts} "
                  f"saying {reason!r}, got {got}"); ok = False
        else:
            print(f"    {label}: {got[0]}")
    print("    ->", "PASS" if ok else "FAIL")
    return ok


def main(argv) -> int:
    folder = argv[1] if len(argv) > 1 else os.path.join(_GAME, "ss_assets", "Doll")
    for name in _PACKS:
        path = os.path.join(folder, name + ".ssab")
        if not os.path.exists(path):
            print(f"SKIP: {path} not found (run scripts/deploy-examples.* first)")
            return 0
    lib = ssruntime.load_library()
    print("== Doll verification (cross-pack Instance + Effect) ==\n")
    allok = True
    for name in _PACKS:
        allok &= check_pack(lib, folder, name)
        print()
    allok &= check_stale_reference(lib, folder)
    print()
    allok &= check_unbuilt_children(lib, folder)
    print()
    print("== RESULT:", "ALL PASS" if allok else "FAILURES PRESENT", "==")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
