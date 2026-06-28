# SpriteStudio Player for Ren'Py — AI Agent Guide

## 1. Operating Rules
- Keep changes scoped to the requested task. Do not commit unless explicitly asked.
- Before editing, read enough surrounding context to understand callers and invariants.
- **Do not modify the `SpriteStudio-SDK` submodule.** It is the "Brain" of the animation system. If the C-API is missing something, it should be raised upstream.
- **Do not upload/publish to external services** (artifacts, gists, hosted pages) without explicit per-time permission.

## 2. Architecture & The Porting Guide (CRITICAL)
A Ren'Py integration for SpriteStudio 7. `libssruntime` (Rust, from the `SpriteStudio-SDK` submodule) computes animation via a C-API over Python `ctypes`, returning FlatBuffers draw plans (`RenderMode::Direct`).

The player is a **canonical 3-layer stack**:
- **`ssruntime`** (`game/spritestudio/python/ss_renpy/ssruntime.py`) — ctypes FFI to the Brain.
- **`SSInternalPlayer`** (`python/ss_renpy/player.py`) — engine-independent playback **core**. Plays ONE animation (`set_animation` / `play` / `update(dt_ms) -> FramePlan`); reports `FramePlan.finished`/`looped` as *observations only* — it never decides what to play next. Owns the runtime, metadata, Instance/Effect rigs and events. **Instance-part children are themselves parent-driven `SSInternalPlayer`s.** Depends on two injected seams: a `ResourceManager` (textures) and a pack reader (external `.ssab` bytes).
- **`SSPlayer`** (`game/spritestudio/spritestudio.rpy`) — the Ren'Py Creator-Defined Displayable. Wraps the core, builds `renpy.Render` from the draw plan, and owns *policy*: animation-sequence chaining (on `FramePlan.finished`), image attributes / aliases, event callbacks, and injecting a `RenPyResourceManager`.

Conventions:
- `SSPlayer("ss_assets/Ringo/Ringo.ssab", ...)` — first arg is the **`.ssab` path** (gamedir-relative), NOT a short name. A pack's textures and external-instance packs are **co-located** in the same directory.
- `.ssab` loads via `renpy.loader.load` (browser discovery enumerates via `renpy.list_files`), so packs work loose **or inside a `.rpa` archive**; textures load via `Image` (also archive-safe).
- UV normalization stays in the **render layer** (needs texture pixel sizes only Ren'Py has); the core's draw plan carries raw UVs.

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
- **Playback policy lives in the host.** Animation-sequence chaining happens in `SSPlayer` (on `FramePlan.finished`); `SSInternalPlayer` only *reports* edges and plays one animation. Keep it that way so Instance children can reuse the core. UV normalization likewise stays in the render layer (it needs texture sizes).

## 5. Verification
Headless tests in `tools/` exercise the engine-independent layers without launching the GUI: `m0_smoke.py`, `verify_internal_player.py` (the playback core: set_animation → play → update + the finished edge), `verify_instance.py`, `verify_effect.py`, `verify_mesh.py`, `verify_m2.py`, `verify_events.py`, `verify_resolver.py`, `verify_snippet.py`. Run these to verify ctypes / math / draw-plan composition. Actual GL2 rendering (premultiplied alpha / mesh / blend) and the dev asset browser (**Shift+B**) still require a GUI run.
