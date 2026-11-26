# 🎭 SpriteStudio Player for Ren'Py

A plugin (player) to play animations created in [SpriteStudio](https://www.webtech.co.jp/eng/spritestudio/) on the [Ren'Py](https://www.renpy.org/) visual novel engine. Put a SpriteStudio project in your game, press **Launch Project** in the Ren'Py launcher, and show the animation with a `show` line.

!!! tip "Try it in your browser"
    [▶️ Run the sample project](demo/) — a Ren'Py Web build published alongside this
    documentation. Nothing to install.

!!! tip "No SpriteStudio data of your own yet?"
    The [official sample data](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/) works as-is — that page is
    Japanese only, but the downloads themselves are language-neutral.
    [Ringo](https://www.webtech.co.jp/spritestudio/ss6user/download/OPTPiX_SpriteStudio_Ringo_Sample_20220121.zip) is a good character sample, and
    [Particle](https://www.webtech.co.jp/spritestudio/ss6user/download/OPTPiX_SpriteStudio_ParticleEffect_Sample_20191025.zip) is a good one if you want effects.
    To make your own, you use SpriteStudio itself — see [its site](https://www.webtech.co.jp/eng/spritestudio/).

## Table of Contents

This documentation is structured by user purpose.

- **User Guide**
    - [Setup Guide](setup.md): How to integrate the player into your game project.
    - [Asset Import](import.md): How to convert `.sspj` animation data.
    - [Usage Guide](usage.md): How to call and control animations from Ren'Py scripts.
    - [Buttons](buttons.md): How to make an animation a button, with a state for idle, hover and insensitive.
    - [Exporting your Game](export.md): How to export to each platform (desktop / mobile / web) with the stock Ren'Py tooling.
    - [Limitations](limitations.md): What is not supported, or supported only in part.
- **For Player & SDK Developers**
    - [Build Guide](development/build.md): Setting up a custom environment, building the native library, using a changed copy in a game, and checking it in Ren'Py.
    - [How the Player Is Put Together](development/architecture.md): The layers, where each platform loads the native library from, and why the player is built the way it is.

## Key Features

- **Bring your sprites to life — by eye, not by numbers.** Breathing and blinking, swaying hair and clothes, flashy slash or magic effects are built visually in a dedicated editor (SpriteStudio), with bone rigs, mesh deformation, and particles. Instead of typing each part's position, rotation, and timing into ATL and reloading to check, you pose the parts on the canvas and time them on a timeline with easing curves, so the person who draws the character can animate it too. Ren'Py just plays the result.
- **Lip flap that follows your dialogue.** One `SSCharacter` line defines the image and the speaker together: the sprite plays its talk animation while a line is on screen and returns to idle when it ends — no per-line code.
- **Use it like any other image.** `show ringo wait1` works with no `image` statement, and switching to another animation is one more `show`, just like changing an expression. ATL and `Transform` still position, slide, zoom, or fade it, and the Interactive Director lists it. For a blend instead of a cut, `ss_crossfade()` fades into the next animation, layered tracks add a blink or a wave on top ([mixing animations](usage.md#mixing-animations)), and runtime overrides swap textures or part states for costumes and expressions.
- **A lightweight alternative to video.** Openings, living backgrounds, effect cut-ins — wherever you'd play a `Movie` — run as animation instead: it scales freely, loops seamlessly, changes on your script's cue, and moves at your display's refresh rate rather than a frame rate baked into a video. However smoothly it moves, the file stays the same size: it holds the artwork and the motion, not every frame.
- **A seamless edit-to-runtime loop.** The **Auto Importer** watches `SpriteStudio_Source/` during development: arm it with one **Shift+R**, then just save in SpriteStudio — only the changed project is re-converted, and the running game reloads itself to show it ([hot reload](import.md#hot-reload)). No manual export step.

## Related Repositories

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/) — the documentation portal for the SDK and its official players.
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — the SDK itself, providing `libssruntime` / `libssconverter`.
- [SSConverterGUI](https://github.com/cri-middleware/SSConverterGUI) — a standalone desktop GUI for converting `.sspj` without a player.
