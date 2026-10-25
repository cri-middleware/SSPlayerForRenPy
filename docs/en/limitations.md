# ⚠️ Limitations & Scope

Restrictions and unimplemented features of the current SpriteStudio Player for Ren'Py. (For the list of what *is* supported, see the usage docs.)

This page covers what is specific to **this** player. The constraints that come from the shared runtime and therefore apply to every official player — `independent=true` parts under reverse playback and seeking, seeking not firing the events it skips, no reverse audio, unvalidated `.ssab` input — are documented once in the portal: **[Shared Limitations](https://cri-middleware.github.io/SpriteStudio-Docs/sdk/limitations/)**.

## Not Yet Implemented

> [!WARNING]
> - **Text / NineSlice parts** — not rendered (they draw empty).

## Partially Supported

> [!WARNING]
> - **Blend modes** — blending goes through Ren'Py's `config.gl_blend_func`, so modes with no GL equivalent (Division, Overlay) fall back to Mix.
> - **Atlases past the display's texture limit** — a texture larger than `config.max_texture_size` (4096x4096 by default, and never more than the GPU allows) is loaded as a grid of tiles, which no mesh can sample. Parts on such an atlas are drawn through the simpler transform path instead — the shape is right, but mesh deformation and UV transforms are not applied — and Effect particles on one are skipped; a line in `log.txt` names the atlas. Re-export the pack with a smaller atlas, or raise `config.max_texture_size` in `options.rpy`, which also enlarges the framebuffer Ren'Py allocates (4096 to 8192 takes it from 64MB to 256MB of VRAM).
> - **Whole-part color tint on Mesh / Instance parts** — `parts_color` is applied per-vertex on Normal / Shape parts; a whole-part tint on Mesh parts is currently approximated (alpha only).
> - **Masks on Effect particles** — mask / clipping applies to Normal, Mesh, and Shape parts; particles emitted by Effect parts are drawn unclipped even where the editor clips them.
> - **At most 96 masks at once in one animation** — counting both mask parts and parts that write a clipping mask, and the animations it plays through Instance parts: an instance's masks count again every time the instance is placed. A hidden mask, or one whose mask value is 0, does not count. Past 96 the ones drawn last are ignored, and a line in `log.txt` says so. Up to 24 masks are drawn at full resolution; past that the mask edges get coarser rather than using more memory.
> - **Part overrides inside Instance parts** — a color / cell / visibility override reaches the parts of the animation you call it on, not the parts inside an Instance part (that nested child animation runs as a separate player). Force-hiding the Instance part itself does stop its contents from being drawn.
> - **Animation mixing** ([crossfade and layering](usage.md#mixing-animations)) — the track stack is not saved: a loaded save brings the player back on track 0's animation at its saved frame, without the other tracks or a fade in flight. Switching animation through an image attribute (`show ringo walk`) cuts rather than cross-fades; call `ss_crossfade()` on a player you keep in a variable for that. Across a crossfade on track 0, an Instance or Effect part that both animations key on the same frame may carry on with the outgoing animation's settings for it.
> - **Part tracking (following a part)** — a child pinned to a part always draws **in front of** the whole sprite and cannot be inserted between parts. A mirrored (negative-scale) part is not mirrored on the child either, because a part's scale is reported as a magnitude — the position and the angle stay exact, but a purely horizontal mirror reaches the child as a 180° rotation ([details](usage.md#mirrored-parts)). Only the parts of the pack the player itself is playing can be targeted, not the parts inside an Instance part.
> - **Buttons** ([`SSButton`](buttons.md)) — a Ren'Py button has no state for the mouse being held down on it, so neither does `SSButton`, and a selected button shows as it would unselected. `parts` names the parts of the pack the player itself plays, not the parts inside an Instance part.

## Audio Playback

> [!NOTE]
> For ordinary use — playing forward and showing / hiding the sprite normally — audio just works: it plays on the `sfx` mixer, so player volume and mute apply. Only these edge cases have caveats:
>
> - **No reverse audio.** When an animation runs backward (a reverse direction, or a ping-pong return leg), its sounds are skipped — audio cannot be played in reverse. A negative speed is not one of those cases: speed is a multiplier, and a negative one stops the playhead rather than turning it around, as does `0`.
> - **Seeking does not scrub audio.** A sound fires only when the playhead crosses its frame during playback; jumping the frame (`ss_set_frame_no`) neither scrubs nor re-fires skipped sounds.
> - **Sound outlives the playback that started it.** `ss_pause()` and `ss_stop()` end the *animation*, not the sound — SpriteStudio has no infinite loop (`loop_num` is a play count), so every sound ends on its own, and one that outlasts its animation is the animation data's business. Call `ss_stop_audio()` where you do want silence.
> - **Stopping a hand-managed player.** `hide` / `scene` stops its sound at once. If instead you keep an `SSPlayer` in a variable and replace it yourself, call `ss_stop_audio()` to stop immediately — otherwise it is auto-stopped within ~0.25s of leaving the screen.
> - **Ship the sound files** alongside the `.ssab` (they resolve relative to it, like textures); a missing file is skipped.

## Performance & Platform

> [!NOTE]
> **Performance** — Your frame rate may be affected by animations with an extremely high mesh vertex count, or by many particle effects overlapping at once.

> [!WARNING]
> **Platform** — All targets are supported: Desktop (Windows / macOS / Linux), Android, iOS, and Web. See the [export guide](export.md) for how to export to each; the platform-specific constraints to be aware of are:
>
> - **Android** loads native code only from the app's own library folder, so the player's `.so` is copied into RAPT once by hand before the first Android build ([Android Export](export.md#android-export)).
> - **iOS** requires macOS + Xcode, and the player's library is embedded into the app target once by hand ([iOS Export](export.md#ios-export)).
> - **Web** needs a browser with **WebAssembly SIMD** (Chrome / Edge 91+, Firefox 89+, Safari 16.4+): the player's WebAssembly build is compiled with SIMD instructions and will **not run on browsers without it**. Treat SIMD support as a browser requirement for your distribution.
