# SSPlayer for Ren'Py

Play **SpriteStudio 7** animations (`.ssab`) inside [Ren'Py](https://www.renpy.org/).

Animation math (keyframe interpolation, world transforms, playback state) is done
by the prebuilt native runtime **`libssruntime`** ("Brain", from the
[SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK)); this repo
is the Ren'Py **Player** ("Body") — a thin `ctypes` + Creator-Defined Displayable
layer. The authoritative porting reference is the SDK's
`libs/ssruntime/docs/` guide.

Status: **M1** — Normal parts render (position / rotation / scale / flip / alpha,
Mix blend). See [Scope](#scope--limits).

## The library vs. the demo

This repo is one Ren'Py project that **contains the library and a demo that uses it**:

- **`game/spritestudio/`** — *the library*. A self-contained, drop-in folder.
- **`game/script.rpy` + `game/sprites/`** — *the demo* that consumes it.

### Use it in your own game

Copy the **`game/spritestudio/`** folder into your project's `game/` directory.
That's it — the `.rpy` inside auto-loads and defines `SpriteStudioDisplayable`:

```renpy
# show a .ssab (placed anywhere under your game/, here game/sprites/)
screen demo():
    add SpriteStudioDisplayable("Basic.ssab", sprites_subdir="sprites") xalign 0.5 yalign 0.5
```

If you put the folder somewhere other than `game/spritestudio/`, set
`spritestudio_root` in an earlier `init` block (see top of `spritestudio.rpy`).

## Layout

```
SpriteStudio-SDK/              # git submodule (the Brain + converter + porting guide)
game/
  script.rpy                   # demo entry (←/→ cycle test packs)
  sprites/                     # demo playback data — gitignored, see deploy-examples.*
  spritestudio/                # ★ THE LIBRARY (copy this into any game/)
    spritestudio.rpy           #   Creator-Defined Displayable + init + sys.path
    python/                    #   engine-independent Python (no renpy import)
      ss_renpy/                #     ssruntime.py (ctypes FFI), framedata.py, ssab_meta.py
      ss/                      #     flatc-generated FlatBuffers bindings (ss.runtime / ss.format)
      flatbuffers/             #     vendored pure-Python flatbuffers runtime
    libs/                      #   native libs — gitignored, see build-runtime.*
      macos/libssruntime.dylib            # universal (arm64 + x86_64)
      windows/<arch>/ssruntime.dll
      linux/<arch>/libssruntime.so
      # reserved (built but Ren'Py-side integration is separate): android/<abi>/, ios/, web/
scripts/                       # build-runtime.{sh,ps1}, deploy-examples.{sh,ps1}
tools/                         # headless dev tools (plain CPython, no Ren'Py)
```

`game/spritestudio/libs/` and `game/sprites/` are **build artifacts** (gitignored);
the scripts below regenerate them from the SDK submodule.

## Setup

```bash
# 1. get the SDK submodule (the Brain + converter + porting docs)
git submodule update --init --recursive

# 2. build the native runtime  -> game/spritestudio/libs/<platform>/<arch>/
scripts/build-runtime.sh                 # host, debug (fast dev build)
scripts/build-runtime.sh build=release    # release (macOS => universal arm64+x86_64)

# 3. convert the demo's playback data -> game/sprites/
scripts/deploy-examples.sh
```

Requires the Rust toolchain (`cargo`) and `flatc` (only if regenerating bindings).
Two responsibilities, two scripts: **`build-runtime.*` = the native binary**,
**`deploy-examples.* = the playback data`**.

### Multi-platform builds

`build-runtime.*` mirrors SSPlayerForUnity's interface:

```bash
scripts/build-runtime.sh platform=<windows|macos|linux|android|ios|web> arch=<x86_64|arm64|...> build=<debug|release>
```

Desktop (Windows / macOS / Linux × x86_64 / arm64) is the **wired, ctypes-loaded**
path. `android/`, `ios/`, `web/` slots exist and the SDK can build them, but the
Ren'Py-side integration (RAPT / renios / renpyweb) is a separate, future effort —
those binaries are not loaded yet.

## Run the demo in Ren'Py

No Ren'Py SDK ships here. To see it on screen:

1. Install the **Ren'Py SDK** (8.x) and open the launcher.
2. Either point the launcher's projects directory at this repo, or **Create New
   Project** and copy this repo's `game/` contents into it (the new project
   supplies the `gui`/`screens` scaffolding; our `script.rpy` replaces its start).
3. **Launch Project**. `Basic.ssab` plays centered; **←/→** switch packs, **Esc** quits.

> **Orientation knobs** (top of `game/spritestudio/spritestudio.rpy`): Ren'Py's
> rotate/zoom sign conventions could not be verified here without running it. If
> the animation is mirrored or rotates the wrong way, flip exactly one of
> `SS_ROTATE_SIGN` / `SS_MIRROR_AXIS` and relaunch. The geometry math is verified
> (see below); only Ren'Py's `Transform` convention is the open variable.

## Scope & limits

M1 renders the **Normal** draw-batch kind: position, rotation, non-uniform scale,
H/V flip, per-part alpha, Mix blend, and parent/child hierarchy (the runtime
pre-bakes world matrices in `RenderMode::Direct`).

- **Approximated:** sheared / free-quad-deformed cells render as an unsheared box
  (logged via `renpy.log` with the px error) — full fidelity needs **M2** (model-
  based mesh).
- **Not yet:** other blend modes (Add/Mul/...), `parts_color` vertex colors, and
  the Mesh / Effect / Mask / Shape / Instance / Text / NineSlice kinds.

## Verification (no GUI needed)

A dev venv (`.venv`, with `flatbuffers` + `Pillow`) drives headless tools:

```bash
python3 tools/m0_smoke.py [anim.ssab]      # M0: prove the ctypes <-> Brain wiring
python3 tools/analyze.py  [dir|ssab ...]   # displayability audit per pack/kind
./.venv/bin/python tools/render_png.py game/sprites/overall/Basic.ssab  # software-render to out/
```

`render_png.py` rasterizes the **exact** M1 geometry (same `build_normal_quads`
the CDD runs), so you can eyeball it against the SS editor without Ren'Py.

## Gotchas (the cold-start guide is wrong on these; the porting guide is right)

- `ss_runtime_update(ctx, delta)` takes **milliseconds** (cold-start §5/§6.2 say
  seconds). `SSRuntime.update()` takes seconds and converts.
- `DrawBatch.texture_hash` = FNV1a of the **cellmap name** (not the image path);
  resolve textures by `cellmap.name_hash`.
- `parts_color`'s alpha is **pre-composed** by the runtime — don't re-multiply by
  `PartState.alpha` for parts that have it (relevant at M2).
- Don't reimplement FNV-1a — call `ss_runtime_hash_string`.

Authoritative reference: `SpriteStudio-SDK/libs/ssruntime/docs/` (README → 16).
