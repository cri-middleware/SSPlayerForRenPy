# SpriteStudio Player for Ren'Py — AI Agent Guide

A **shipping, creator-facing plugin** that plays **SpriteStudio 7** in Ren'Py. Two
native cores from the `SpriteStudio-SDK` submodule do the work: `libssruntime` (the
"Brain") computes each frame as a FlatBuffers draw plan over a C-API; `libssconverter`
turns a `.sspj` project into a runtime `.ssab` pack. This repo is the Ren'Py layer +
creator ergonomics around them. This file is the map; detail lives in code docstrings,
the tests (§5), the docs (§4), and the SDK porting guide (§6).

## 1. Operating rules
- Keep changes scoped to the request; don't commit unless asked.
- Read enough context (callers, invariants) before editing; if a read was truncated,
  read the rest first. Match the style of touched files.
- **Ren'Py** is an external dependency (`renpy-sdk/`) — don't patch it; use its public
  API and the `SS_*` knobs.
- **SDK alignment:** when modifying core playback logic, refer to
  `SpriteStudio-SDK/AGENTS.md` for Rust runtime constraints.
- **Consumer model:** the drop-in `game/spritestudio/` must work without
  `scripts/`/`tools/`/SDK and under the stock launcher — judge creator-facing changes
  from that side (§2), and keep user docs (§4) user-facing.

## 2. Layout & priorities
Dev + demo project; only the drop-in **`game/spritestudio/`** ships to creators (pasted
into a stock Ren'Py project — no `scripts/`, SDK, or build). Priorities: (a) asset
import (`.sspj → .ssab`), (b) creator ergonomics, (c) export (desktop/Android/iOS/Web
+ `.rpa`), (d) docs, then (e) render internals (mature, bug-fix territory).

| Path | Role | Ships? |
|---|---|---|
| `game/spritestudio/python/ss_renpy/` | Engine-independent playback + import core (§3). | yes |
| `game/spritestudio/*.rpy` | `SSPlayer` displayable + drop-in ergonomics (§3). | yes |
| `game/spritestudio/{libs/<platform>,python/{ss,flatbuffers}}` | Native libs + FlatBuffers bindings. | yes |
| `game/*.rpy`, `game/tl/` | Demo game + JA translation. | no |
| `docs/`, `mkdocs.yml` | Bilingual user docs (§4). | no |
| `scripts/`, `tools/` | Build/deploy wrappers (§3); headless tests + utils (§5). | no |
| `SpriteStudio-SDK/` | Submodule: both cores + porting guide (§6). | no |
| `game/spritestudio/python/ss_renpy/__init__.py` (`__version__`), `scripts/SDK_VERSION.txt`, `scripts/RENPY_VERSION.txt` | Pin package-release / SDK / Ren'Py versions (§3). | no |

## 3. Architecture & constraints
**3-layer stack** (under `game/spritestudio/`): `python/ss_renpy/ssruntime.py` routes to
`ssruntime_native.py` (ctypes FFI to the Brain) or `ssruntime_web.py` (Pyodide,
`sys.platform=="emscripten"`); `player.py`'s `SSInternalPlayer` is the engine-independent
core (plays ONE animation via `update(dt_ms)→FramePlan`, reports `finished`/`looped` as
observations only); the `SSPlayer` displayable (`spritestudio.rpy`) builds `renpy.Render`
and owns policy (sequence chaining, image attributes, callbacks, resource injection).

**Drop-in ergonomics** — sibling `*.rpy`, each self-contained/dev-gated/droppable:
`ss_character.rpy` (`SSCharacter` one-line talking sprite), `ss_helpers.rpy`
(`ss_play_once`/`ss_duration`), `ss_browser.rpy` (Asset Browser, `Shift+B`),
`ss_diagnostics.rpy`, `auto_importer.rpy` (dev-only: `SpriteStudio_Source/` →
`game/ss_assets/` via `ss_renpy/converter.py` → `libssconverter`). `ssab_meta.py` parses
static `.ssab` metadata the Brain doesn't surface; `resolver.py` = zero-config pack index.

**Invariants & constraints:**
- Policy (sequence chaining) lives in `SSPlayer`, not the core; UV normalization lives in
  the render layer. Every `python/` module must import in plain CPython (no `renpy`).
- First `SSPlayer` arg = gamedir-relative `.ssab` path; textures + instance sub-packs
  co-located; loading via `renpy.loader` (works loose or in `.rpa`).
- `ss_renpy.__version__` (in `game/spritestudio/python/ss_renpy/__init__.py`) is the package
  version — the single source of truth, shipped inside the distributed `spritestudio/` folder and
  read by the release workflow for the tag and zip name (independent of the SDK; PEP 440 form, e.g.
  `7.0.0b1`). `scripts/SDK_VERSION.txt` / `scripts/RENPY_VERSION.txt`
  pin versions; `libs/<platform>/` must match `scripts/SDK_VERSION.txt` (bump → re-run `download-sdk`,
  often `generate-runtime-code`).
- **FFI:** release every Rust handle via `ss_*_destroy` (bindings do it on `__del__`);
  textures are the exception — Ren'Py owns them.
- **Hot path:** no per-frame Python allocs; consume `FramePlan`/`DrawBatch` directly;
  `_prewarm_textures` staggers uploads; `SS_PROFILE=1` logs the split.
- **Coordinates:** use `ss_context_set_coordinate_system`; don't add a second Y-flip.
- **Scripts** (`scripts/`, `*.sh`/`*.ps1`): `build-runtime`/`download-sdk`,
  `download-flatbuffers`+`generate-runtime-code`, `deploy-examples`, `run-demo`,
  `fetch-renpy-*`, `deploy-{desktop,android,ios,web}`.

## 4. Docs
`docs/` = MkDocs Material bilingual (`en/` default + `ja/` + shared `assets/`), ordered
`setup → import → usage → export` (+ `build`/`limitations` for devs). **User-facing** —
don't cite dev scripts. `limitations.md` is the canonical supported/unsupported list;
keep `en/`/`ja/` in sync (`ja/` asset paths need one extra `../`).

## 5. Verification
Each engine-independent layer has a headless `tools/` test (plain CPython); **GL2
rendering** (PMA, mesh, blend, mask, `ss-*` GLSL) needs a GUI run — sign off via
`Shift+B` or `scripts/run-demo.*`. Run all:
`for t in tools/verify_*.py tools/m0_smoke.py; do python3 "$t"; done`.

| Layer | Where | Test |
|---|---|---|
| Playback core + events | `player.py`, `events.py` | `verify_internal_player`, `verify_events` |
| Geometry/Mesh + PartColor | `framedata.py` | `verify_m2`, `verify_mesh` |
| Instance / Effect / Shape | `instance.py`, `effect*.py`, `framedata.py` | `verify_instance`, `verify_effect`, `verify_shape` |
| Mask / clipping | `mask.py` | `verify_mask` |
| Part overrides (colour/cell/visibility) | `player.py`, `ssruntime_*.py` | `verify_override` |
| User shaders (SS6 `ss-*`) | `framedata.read_shader` | `verify_shader` |
| Resolver / snippet / smoke | `resolver.py`, `snippet.py` | `verify_resolver`, `verify_snippet`, `m0_smoke` |

Also: `tools/analyze.py` (DrawBatchKind audit), `cli_convert.py` (shell `.sspj→.ssab`),
`render_png.py`/`render_mask_png.py` (software raster, not GL2). Lint:
`renpy-sdk/renpy.sh . lint`. **Not rendered:** Text/NineSlice; animation blend; nested
Instance/Effect timeline events. **Audio** is played by `SSPlayer` (`sfx` mixer,
round-robin, `ss_stop_audio`; reverse muted). See `docs/*/limitations.md`.

## 6. Porting guide (READ FIRST for Brain / render work)
Start at **`SpriteStudio-SDK/AGENTS.md`**, then the porting guide under
`SpriteStudio-SDK/libs/ssruntime/docs/` — numbered dirs (`10_introduction` …
`60_tooling`), EN `.md` + JA `.ja.md`, indexed by `README.md`. **Reference ports:**
`SSPlayerForGodot` (closest; source of the `ss-*` shaders + coverage-bitmap mask) and
`SSPlayerForWeb` (`GeometryBuilder.ts` = render math).
