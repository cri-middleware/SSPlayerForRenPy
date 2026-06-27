# SpriteStudio Player for Ren'Py — AI Agent Guide

## 1. Operating Rules
- Keep changes scoped to the requested task. Do not commit unless explicitly asked.
- Before editing, read enough surrounding context to understand callers and invariants.
- **Do not modify the `SpriteStudio-SDK` submodule.** It is the "Brain" of the animation system. If the C-API is missing something, it should be raised upstream.
- **Do not upload/publish to external services** (artifacts, gists, hosted pages) without explicit per-time permission.

## 2. Architecture & The Porting Guide (CRITICAL)
A Ren'Py integration for SpriteStudio 7. `libssruntime` (Rust, from the `SpriteStudio-SDK` submodule) computes animation via a C-API over Python `ctypes`. The Ren'Py Player calls `update(dt)`, reads FlatBuffers draw plans (`RenderMode::Direct`), and draws batches inside a Creator-Defined Displayable.

👉 **When implementing playback, render behavior, or using the C-API, YOU MUST READ the Player Porting Document:**
`SpriteStudio-SDK/libs/ssruntime/docs/` (Read the README and the indexed docs).
*Note: For integration instructions, usage, limitations, and build steps, refer to the `docs/` directory (`setup.md`, `usage.md`, `import.md`, `build.md`, `limitations.md`).*

## 3. Hard Constraints
- **Scripts have specific roles:** `scripts/build-runtime.*` builds native binaries, `scripts/download-sdk.*` downloads prebuilt binaries, and `scripts/deploy-examples.*` builds ONLY playback data.
- **Engine-independent Python:** Code under `game/spritestudio/python/` must run in plain CPython (no `renpy` import) to support headless testing.
- **Coordinate handling:** Use the Context API (`ss_context_set_coordinate_system`) for coordinate systems. Do not hand-roll a second Y-flip.

## 4. Gotchas
- `ss_runtime_update(ctx, delta)` takes **milliseconds** (not seconds).
- `DrawBatch.texture_hash` uses the cellmap's `name_hash` (not the image path).
- Ren'Py GL2 uses **premultiplied alpha**. Handle custom mesh shaders accordingly (un-premultiply → straight math → re-premultiply).
- **Effect UVs** are already normalized `0..1`. Normal/Mesh UVs are in pixels. Do not normalize Effect UVs.

## 5. Verification
Headless tests are available in the `tools/` directory (e.g., `m0_smoke.py`, `verify_m2.py`). Use them to verify your ctypes and math logic without needing to launch the Ren'Py GUI.
