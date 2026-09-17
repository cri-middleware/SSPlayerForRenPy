# 🎭 SpriteStudio Player for Ren'Py

A plugin (player) to play animations created in [SpriteStudio](https://www.webtech.co.jp/spritestudio/) on the [Ren'Py](https://www.renpy.org/) visual novel engine. The playback process is powered by `libssruntime` provided by the [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK).

!!! tip "Try it in your browser"
    [▶️ Run the sample project](demo/) — a Ren'Py Web build published alongside this
    documentation. Nothing to install.
    _Coming soon_: the demo ships with the first release, so the link 404s until then.

!!! tip "No SpriteStudio data of your own yet?"
    The [official sample data](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/) works as-is — that page is
    Japanese only, but the downloads themselves are language-neutral.
    [Ringo](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/#ringo) is a good character sample, and
    [Particle](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/#Perticle_sample) is a good one if you want effects.

## Table of Contents

This documentation is structured by user purpose.

- **User Guide**
    - [Setup Guide](setup.md): How to integrate the player into your game project.
    - [Asset Import](import.md): How to convert `.sspj` animation data.
    - [Usage Guide](usage.md): How to call and control animations from Ren'Py scripts.
    - [Exporting your Game](export.md): How to export to each platform (desktop / mobile / web) with the stock Ren'Py tooling.
- **Developer Guide**
    - [Build Guide](build.md): Setting up a custom environment and building the native library.
    - [Limitations](limitations.md): List of supported and unsupported features.

## Key Features

This player is designed to bring the full expressive power of SpriteStudio to the Ren'Py engine.

*   **Eliminate Complex ATL:** You no longer need to write long, complex ATL (Animation and Transformation Language) blocks in Ren'Py. Animations crafted in the editor can be played with just a few lines of script.
*   **Full Feature Support:** It fully supports advanced SpriteStudio features out of the box, including bone hierarchies, meshes & deformations, and particle effects.
*   **High-Speed Native Processing:** Powered by `libssruntime` (Rust) and deeply integrated with Ren'Py's rendering pipeline, it renders animations lightweight and fast without relying on heavy video files.
*   **Transparency & Blending:** Supports seamless fading and additive blending for effects, enabling the rich visual presentation essential for modern visual novels.
*   **Dynamic Costume Changes:** Swap the texture an animation samples from at runtime, so a single asset can drive color variations, costume changes, and facial expressions from a line of script.

## Related Repositories

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/) — the documentation portal for the SDK and its official players.
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — the SDK itself, providing `libssruntime` / `libssconverter`.
- [SSConverterGUI](https://github.com/cri-middleware/SSConverterGUI) — a standalone desktop GUI for converting `.sspj` without a player.
