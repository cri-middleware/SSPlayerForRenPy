# Limitations & Scope

Restrictions and unimplemented features of the current SpriteStudio Player for Ren'Py. (For the list of what *is* supported, see the usage docs.)

## Not Yet Implemented

> [!WARNING]
> - **Text / NineSlice parts** — not rendered (they draw empty).
> - **Animation blending / mixing** — cross-fade or weighted mixing between animations.
> - **Nested timeline-event kinds inside Instance / Effect parts** — only the root animation's UserData / Signal / Audio events are surfaced.

## Partially Supported

> [!WARNING]
> - **Blend modes** — blending goes through Ren'Py's `config.gl_blend_func`, so modes with no GL equivalent (Division, Overlay) fall back to Mix.
> - **Whole-part color tint on Mesh / Instance parts** — `parts_color` is applied per-vertex on Normal / Shape parts; a whole-part tint on Mesh parts is currently approximated (alpha only).

## Audio Playback

> [!NOTE]
> For ordinary use — playing forward and showing / hiding the sprite normally — audio just works: it plays on the `sfx` mixer, so player volume and mute apply. Only these edge cases have caveats:
> - **No reverse audio.** When an animation runs backward (reverse direction or negative speed), its sounds are skipped — audio cannot be played in reverse.
> - **Seeking does not scrub audio.** A sound fires only when the playhead crosses its frame during playback; jumping the frame (`ss_set_frame`) neither scrubs nor re-fires skipped sounds.
> - **Stopping a hand-managed player.** `hide` / `scene` stops its sound at once. If instead you keep an `SSPlayer` in a variable and replace it yourself, call `ss_stop_audio()` (or `ss_stop()`) to stop immediately — otherwise it is auto-stopped within ~0.25s of leaving the screen.
> - **Ship the sound files** alongside the `.ssab` (they resolve relative to it, like textures); a missing file is skipped.

## Performance & Platform

> [!NOTE]
> **Performance** — Because rendering is routed through `ctypes` and Creator-Defined Displayables, your frame rate may be affected by animations with an extremely high mesh vertex count, or by many particle effects overlapping at once.

> [!WARNING]
> **Platforms** — Desktop (Windows, macOS, Linux) works today. Mobile is close, and Web needs a separate integration:
> - The native runtime (the Rust "Brain") builds for every target — the SDK release workflow produces `macos`, `windows/x86_64`, `linux/x86_64`, `android/{arm64,arm32,x86_64}`, `ios` (`.xcframework`), and `web` (WASM).
> - The library loader (`ss_renpy/ssruntime.py`) already resolves all of those layouts (Android → `android/<abi>`; iOS falls back to the statically-linked app image). What remains for **Android / iOS** is bundling the native build and wiring Ren'Py's mobile packaging (for iOS, linking the `.xcframework` into the Xcode project).
> - **Web** cannot use this path at all — a WASM runtime is not loadable through `ctypes`, so it needs a separate (non-ctypes) integration.
