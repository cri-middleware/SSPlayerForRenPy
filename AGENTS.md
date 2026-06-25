# SpriteStudio Player for Ren'Py — AI Agent Guide

## Operating rules

- Keep changes scoped to the requested task.
- Do not commit unless the user explicitly asks.
- Before editing, read enough surrounding context to understand callers and invariants.
- Follow existing code style in touched files (Python: stdlib + ctypes only in the
  library layer; `.rpy`: Ren'Py-idiomatic).
- **Do not upload/publish to external services** (artifacts, gists, hosted pages)
  without explicit per-time permission. Produce local files and report their paths.
- **SDK alignment:** the authoritative porting reference is
  `SpriteStudio-SDK/libs/ssruntime/docs/` (README → 16). Read it before
  implementing playback/render behavior — the repo-root `renpy-cold-start.ja.md`
  is a quickstart and is wrong on a couple of points (see Gotchas).
- **Do not modify the `SpriteStudio-SDK` submodule** — it is the Brain. If the
  C-API is missing something, raise it upstream rather than working around it.

## Architecture in one paragraph

A Ren'Py integration for SpriteStudio 7. `libssruntime` (Rust, from the
`SpriteStudio-SDK` submodule) does all animation computation and is called over a
C-API via Python `ctypes`. Each frame the Player calls `update(dt)` then
`get_frame_data`, reads SoA buffers (world matrices, local vertices/UVs, cell
meta) plus a FlatBuffers draw plan (`RenderMode::Direct`), and draws the batches
inside a Creator-Defined Displayable's `render()`. The library is shipped as a
drop-in `game/spritestudio/` folder; `.ssab` playback data and the native lib are
build artifacts regenerated from the SDK by `scripts/`.

## Key components

| Path | Role |
|---|---|
| `game/spritestudio/spritestudio.rpy` | The Creator-Defined Displayable (`SpriteStudioDisplayable`) + `init` (sys.path, native lib load) + user playback API. The only Ren'Py-coupled file. |
| `game/spritestudio/python/ss_renpy/ssruntime.py` | ctypes FFI to `libssruntime`. Signatures transcribed from `libs/ssruntime/target/ssruntime.h`. No `renpy` import. Per-platform/arch lib resolution. |
| `game/spritestudio/python/ss_renpy/framedata.py` | Walk the FrameData draw plan; build Normal-part world quads; `decompose_quad` (world matrix → center/rotate/scale/mirror for blit+Transform). |
| `game/spritestudio/python/ss_renpy/ssab_meta.py` | Parse static `.ssab` metadata the runtime does not surface (animation names, cellmap → image path, `texture_hash` map). |
| `game/spritestudio/python/ss/` | flatc-generated FlatBuffers bindings (`ss.runtime` = framedata, `ss.format` = ssab). Regenerate from the submodule `.fbs`. |
| `game/spritestudio/python/flatbuffers/` | Vendored pure-Python flatbuffers runtime. |
| `game/spritestudio/libs/<platform>/<arch>/` | Native `libssruntime` per platform (gitignored; `build-runtime.*`). |
| `game/script.rpy`, `game/sprites/` | The demo and its playback data (NOT part of the library). |
| `SpriteStudio-SDK/` | Submodule: the Rust runtime, converter, and porting guide. |
| `scripts/` | `build-runtime.{sh,ps1}` (native binary), `deploy-examples.{sh,ps1}` (playback data). |
| `tools/` | Headless dev tools (plain CPython): `m0_smoke.py`, `analyze.py`, `render_png.py`. |

## Hard constraints

- **Two scripts, two jobs:** `build-runtime.*` produces ONLY the native binary
  (`game/spritestudio/libs/...`); `deploy-examples.*` produces ONLY playback data
  (`game/sprites/...`). Keep them decoupled.
- **Library is engine-independent except `spritestudio.rpy`:** everything under
  `python/` must run under plain CPython (the headless tools rely on this). Do not
  import `renpy` there.
- **SoA lifetime:** pointers from the runtime are valid only until the next Brain
  call. Build geometry immediately after `get_frame_data`; never retain raw buffers
  across frames.
- **Resource/Context lifetime:** a bound resource must outlive its context. The
  `SSRuntime` wrapper destroys context then resource. Copy resource strategy is
  the default for v1.
- **Coordinate handling via the Context API only** (`ss_context_set_coordinate_system`
  = Y-Down, origin, unit). Do not hand-roll a second Y-flip — the runtime already
  applied it (double-flip trap).
- **Hashing:** never reimplement FNV-1a; use `ss_runtime_hash_string` (or the
  hashes already stored in the `.ssab`).
- **Platform/arch layout:** keep `ssruntime.platform_subdir()` and the build
  scripts' output dirs in agreement (`macos/`, `windows/<arch>`, `linux/<arch>`,
  `android/<abi>`, `ios/`, `web/`).

## Verification

| Task | Command |
|---|---|
| Build native runtime | `scripts/build-runtime.sh` (POSIX) / `scripts\build-runtime.ps1` (Win) |
| Convert demo playback data | `scripts/deploy-examples.sh` / `scripts\deploy-examples.ps1` |
| M0 wiring smoke test | `python3 tools/m0_smoke.py` (expects `draw_batches > 0`) |
| Displayability audit | `python3 tools/analyze.py` |
| Software-render a pack | `./.venv/bin/python tools/render_png.py <anim.ssab>` → `out/` |
| In Ren'Py (visual) | The Ren'Py SDK is not in this repo and renders to a GUI; **ask the user to launch the project** to verify on-screen behavior. |

## Gotchas

- `ss_runtime_update(ctx, delta)` takes **milliseconds**, not seconds (the
  cold-start guide §5/§6.2 are wrong). `SSRuntime.update()` takes seconds, converts.
- `DrawBatch.texture_hash` keys on `cellmap.name_hash` (not the image-path hash).
- `parts_color`'s alpha is pre-composed; don't re-multiply by `PartState.alpha`.
