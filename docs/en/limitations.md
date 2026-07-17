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
> - **Masks on Effect particles** — mask / clipping applies to Normal, Mesh, and Shape parts; particles emitted by Effect parts are drawn unclipped even where the editor clips them.

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
> **Platform** — All targets are supported: Desktop (Windows / macOS / Linux), Android, iOS, and Web. See the [export guide](export.md) for how to export to each; the platform-specific constraints to be aware of are:
> - **Android** ships the Brain as a native library in the APK's `lib/<abi>/`; Android only loads native code from there, not from the packaged game data, so the `.so` must be placed in the app's jniLibs — a step the SSPlayer Android export flow handles, but a plain launcher build needs done once by hand.
> - **iOS** requires macOS + Xcode, and the Brain library must be embedded into the app target once by hand — Ren'Py has no hook to auto-link third-party native code.
> - **Web** (Pyodide/WASM) can't load the Brain through `ctypes`, so it uses a JS/WASM binding that Ren'Py's exporter doesn't bundle on its own — every Web export needs an extra manual step to load the WASM module before the game starts.
