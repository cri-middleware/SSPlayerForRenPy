# SpriteStudio Player for Ren'Py — AI Agent Guide

A Ren'Py integration for **SpriteStudio 7**. The Rust `libssruntime` ("Brain",
from the `SpriteStudio-SDK` submodule) computes each frame and returns a
FlatBuffers draw plan (`RenderMode::Direct`) over a C-API; this repo is the thin
Ren'Py rendering + wiring layer around it. Deep detail lives in the code
docstrings, the headless tests (§5), and the SDK porting guide (§6) — this file
is the map, not the manual.

## 1. Operating rules
- Keep changes scoped to the request. **Do not commit unless asked.**
- Read enough surrounding context (callers, invariants) before editing.
- **Never modify the `SpriteStudio-SDK` submodule** — it is the Brain. A missing
  C-API capability is an upstream request, not a local patch.
- **Do not upload/publish to external services** (artifacts, gists, hosted pages)
  without explicit per-time permission.
- **Read the porting guide (§6) before C-API / playback / render work.**

## 2. Architecture — the canonical 3-layer stack
1. **`ssruntime.py`** (`game/spritestudio/python/ss_renpy/`) — ctypes FFI to the Brain.
2. **`SSInternalPlayer`** (`ss_renpy/player.py`) — engine-independent playback
   **core**. Plays ONE animation (`set_animation` / `play` / `update(dt_ms) →
   FramePlan`); reports `finished` / `looped` as *observations only* — it never
   decides what plays next. Owns the runtime, metadata, Instance/Effect rigs, and
   events. Instance-part children are themselves parent-driven `SSInternalPlayer`s.
   Two injected seams: a `ResourceManager` (textures) and a pack reader (external
   `.ssab` bytes).
3. **`SSPlayer`** (`game/spritestudio/spritestudio.rpy`) — the Ren'Py
   Creator-Defined Displayable. Builds `renpy.Render` from the draw plan and owns
   *policy*: animation-sequence chaining (on `finished`), image attributes /
   aliases, event callbacks, and `RenPyResourceManager` injection.

**Invariants (keep these true):** playback policy (sequence chaining) lives in the
host `SSPlayer`, not the core, so Instance children can reuse the core; UV
normalization lives in the render layer (only Ren'Py knows texture sizes); every
module under `game/spritestudio/python/` must import in plain CPython (no `renpy`)
for the headless tests.

**Conventions:** the first `SSPlayer` arg is the **gamedir-relative `.ssab` path**
(e.g. `"ss_assets/Ringo/Ringo.ssab"`), not a short name; a pack's textures and
external-instance packs are **co-located** in that directory. Loading goes through
`renpy.loader.load` / `Image`, so packs work loose or inside a `.rpa` archive.

## 3. Hard constraints
- **Script roles:** `build-runtime.*` builds native binaries; `download-sdk.*`
  fetches prebuilt ones; `deploy-examples.*` builds ONLY playback data;
  `generate-runtime-code.*` regenerates the flatc bindings; `fetch-renpy-sdk.*` →
  `renpy-sdk/`; `run-demo.*` launches the demo. (all under `scripts/`)
- **Coordinates:** use the Context API (`ss_context_set_coordinate_system`). Do
  **not** hand-roll a second Y-flip.
- **Engine-independent Python:** see the §2 invariants.

## 4. Ren'Py-specific gotchas
- `ss_runtime_update(ctx, dt)` takes **milliseconds**, not seconds.
- `DrawBatch.texture_hash` is the cellmap's **`name_hash`**, not the image path.
- Ren'Py GL2 is **premultiplied-alpha**: custom mesh shaders must un-premultiply →
  do straight-space math → re-premultiply.
- Ren'Py shaders are **GLSL ES 1.00 / 120**: no integer bitwise ops, constant loop
  bounds only (fixed count + early `break`), no `PI` builtin. A declared-but-
  **unused** uniform is pruned from the program, so bind a uniform only for the
  variants whose GLSL actually references it.
- **Effect UVs** are already `0..1`; Normal/Mesh UVs are in pixels — do not
  normalize Effect UVs.
- **Asset Browser (`Shift+B`)** in developer mode previews every `.ssab`
  (animations, part tree, snippet generation). GUI rendering can't be checked
  headlessly, so it (or `scripts/run-demo.*`) is where visual sign-off happens —
  recommend it whenever a change needs a "does it look right" check.

## 5. Feature map & verification
Each engine-independent layer has a headless test in `tools/` (plain CPython, no
GUI) that checks ctypes / math / draw-plan composition. **GL2 rendering** (PMA,
mesh, blend, mask coverage+replay, `ss-*` GLSL) needs a GUI run — the user's
sign-off via `Shift+B` or `scripts/run-demo.*`.

| Feature | Where | Headless test | Doc |
|---|---|---|---|
| Playback core + timeline events | `player.py`, `events.py` | `verify_internal_player`, `verify_events` | 06 |
| Normal/Mesh geometry + PartColor | `framedata.py` (`ss.partcolor*`) | `verify_m2` | 07, 10 |
| Instance (nested animations) | `instance.py` | `verify_instance` | 08 |
| Effect (particles) | `effectplan.py`, `effect.py` (`ss.effect*`) | `verify_effect` | 08 |
| Mesh deform | `framedata._read_mesh_part` | `verify_mesh` | 08 |
| Shape (procedural polys) | `framedata._read_shape_part` | `verify_shape` | — |
| Mask / clipping | `mask.py` (`ss.mask_write`, `ss.partcolor_mask`) | `verify_mask` | 09 |
| Framebuffer blend (12 modes) | `gl_blend_func` regs in `spritestudio.rpy` | `verify_m2` | 07 |
| User shaders (SS6 `ss-*` ×13) | `framedata.read_shader`, `ss.user_*` | `verify_shader` | Godot ref |
| Resolver / snippet / smoke | `resolver.py`, `snippet.py` | `verify_resolver`, `verify_snippet`, `m0_smoke` | — |

Run all: `for t in tools/verify_*.py tools/m0_smoke.py; do python3 "$t"; done`.
Lint the whole project (compiles every `.rpy`, runs init blocks — catches shader
registration + Python errors): `renpy-sdk/renpy.sh . lint`.

**Not rendered yet:** Text / NineSlice batch kinds (draw empty); animation
blend / mixing (doc 12); Instance/Effect timeline-event kinds. Audio is
**report-only** (the host plays it). See `docs/00_limitations.ja.md`.

## 6. The porting guide (READ FIRST for Brain / render work)
The SDK ships a **Japanese** porting guide (no English build in this submodule) at
`SpriteStudio-SDK/libs/ssruntime/docs/*.ja.md`, indexed by `README.ja.md`. Most-used:

- **00** limitations · **01** intro & terms · **02** architecture (Brain vs Body)
- **05** load & init · **06** playback control + events · **07** render loop + batching
- **08** Instance / Effect / Mesh · **09** Mask · **10** Parts Color ·
  **12** animation blending · **13** special attrs (UV / Flip)
- **15** troubleshooting · **16** editor integration & conversion

**Reference ports:** `SSPlayerForGodot` (closest architecture; source of the
`ss-*` user shaders and the coverage-bitmap mask) and `SSPlayerForWeb`
(`GeometryBuilder.ts` = the render math). Tip: run the `tests/overall/overall.sspj`
packs at each step — if it matches the editor, that step is done.
