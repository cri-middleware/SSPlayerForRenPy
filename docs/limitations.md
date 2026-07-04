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
> **Platform** — Desktop (Windows, macOS, Linux) works natively. Mobile (Android, iOS) supports native packaging. Web is supported via JS/WASM bindings.
> - The native runtime (Rust "Brain") is built for all targets — the SDK release workflow generates `macos` / `windows` / `linux` / `android` / `ios` (`.xcframework`).
> - The library loader (`ss_renpy/ssruntime.py`) already resolves these layouts (e.g. Android → `android/<abi>`, iOS falls back to static linking). What remains for **Android / iOS** is bundling the native builds and wiring up Ren'Py's mobile packaging.
> - **Web Support**:
>   Web (WASM) cannot be loaded via `ctypes`. It is integrated via a non-ctypes binding (`ssruntime_web.py`) utilizing Pyodide's `import js` feature.
>   To run in a browser, you must load the WASM module before Ren'Py (Pyodide) starts. After building your Web export, add the following script block to your `index.html`:
>   ```html
>   <script type="module">
>     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
>     window.ssruntime = ss;
>     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
>   </script>
>   ```
