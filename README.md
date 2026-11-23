[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**Give your visual novel editor-crafted 2D animation — in just a few lines of script, no video files.**

▶️ **[Try the live demo in your browser](https://cri-middleware.github.io/SSPlayerForRenPy/demo/)** — the bundled SpriteStudio animations running in Ren'Py Web.

An extension (player) that plays **[SpriteStudio](https://www.webtech.co.jp/eng/spritestudio/)** animations (`.ssab`) directly in [Ren'Py](https://www.renpy.org/). Animate the sprite art you already use (PNG / WebP) in a dedicated editor, then drop the finished animation into your project — with none of the long, complex ATL or heavy video files it would normally take.

## ✨ Why use SpriteStudio with Ren'Py?

- **Bring your sprites to life — by eye, not by numbers.** Breathing and blinking, swaying hair and clothes, flashy slash or magic effects are built visually in a dedicated editor (SpriteStudio), with bone rigs, mesh deformation, and particles. Instead of typing each part's position, rotation, and timing into ATL and reloading to check, you pose the parts on the canvas and time them on a timeline with easing curves, so the person who draws the character can animate it too. Ren'Py just plays the result.
- **Lip flap that follows your dialogue.** One `SSCharacter` line defines the image and the speaker together: the sprite plays its talk animation while a line is on screen and returns to idle when it ends — no per-line code.
- **Use it like any other image.** `show ringo wait1` works with no `image` statement, and switching to another animation is one more `show`, just like changing an expression. ATL and `Transform` still position, slide, zoom, or fade it, and the Interactive Director lists it. For a blend instead of a cut, `ss_crossfade()` fades into the next animation, and layered tracks add a blink or a wave on top.
- **A lightweight alternative to video.** Openings, living backgrounds, effect cut-ins — wherever you'd play a `Movie` — run as animation instead: it scales freely, loops seamlessly, changes on your script's cue, and moves at your display's refresh rate rather than a frame rate baked into a video. However smoothly it moves, the file stays the same size: it holds the artwork and the motion, not every frame.
- **A seamless edit-to-runtime loop.** The **Auto Importer** watches `SpriteStudio_Source/` during development: arm it with one **Shift+R**, then just save in SpriteStudio — only the changed project is re-converted, and the running game reloads itself to show it. No manual export step.

## 📚 Documentation

For detailed specifications, import procedures, and API references, please visit the documentation site.

- [**Documentation site (hosted)**](https://cri-middleware.github.io/SSPlayerForRenPy/)
- [**Documentation (English)**](./docs/en/index.md)
- [**ドキュメント (日本語)**](./docs/ja/index.md)
- [**For AI assistants**](https://cri-middleware.github.io/SSPlayerForRenPy/llms.txt) — these docs as Markdown: `llms.txt` indexes the pages and `llms-full.txt` holds all of them in one file; the installed player carries the same pages in `game/spritestudio/`
- [**SpriteStudio Docs (portal)**](https://cri-middleware.github.io/SpriteStudio-Docs/) — the SDK and every official player in one place, with a [plugin](https://cri-middleware.github.io/SpriteStudio-Docs/ai/) that tells your coding assistant about SpriteStudio

---

## 🚀 Quick Start

**Using it in your game?** Read on — drop the folder in, convert your `.sspj`, show it.
Everything after that (events, per-part overrides, `SSCharacter`) is the same path further in,
in the [documentation](./docs/en/index.md).
**Working on the Player, or the Rust core under it?** [CONTRIBUTING.md](./CONTRIBUTING.md), the [Build Guide](docs/en/development/build.md) — which also covers using a changed copy in a game and checking it in Ren'Py — and [How the Player Is Put Together](docs/en/development/architecture.md) for the layers and why.

You need **Ren'Py 8.x** (the Python 3 line), and a project made in **SpriteStudio 7.6 or later**.

1. **Install**: Download [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip)
   (a stable link to the latest release; [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases)
   has every version), extract it, and copy the `spritestudio/` folder inside into your project's
   `game/` folder.
2. **Convert**: Make a `SpriteStudio_Source/` folder in your project's root, beside `game/`, and
   copy your SpriteStudio project into it — the whole folder, not the `.sspj` alone. Select the
   project in the Ren'Py launcher and press **Launch Project**: before the game starts, the project is converted into
   `game/ss_assets/<project>/`. (The launcher starts games in developer mode, which the
   converter needs; a game you ship never converts.)

   ```
   MyGame/
   ├── game/
   │   ├── spritestudio/          ← the folder from the ZIP, as it is
   │   │   ├── spritestudio.rpy
   │   │   ├── libs/
   │   │   ├── python/
   │   │   └── …
   │   ├── ss_assets/
   │   │   └── Ringo/             ← converted when the game launches
   │   │       ├── Ringo.ssab
   │   │       ├── Ringo.png
   │   │       └── …
   │   └── script.rpy
   └── SpriteStudio_Source/
       └── Ringo/                 ← your project folder, copied whole
           ├── Ringo.sspj
           ├── Ringo.png
           └── …
   ```

3. **Show**: Every converted pack is already an image, named after its `.ssab` in lower case,
   with its animations as attributes. In `game/script.rpy`, put `show ringo wait1` where a new project
   has `show eileen happy`:

   ```renpy
   label start:

       scene bg room

       show ringo wait1
   ```

   Not sure of a name? Press **Shift+B** in the running game: the SpriteStudio Browser lists every pack
   and animation, plays them, and copies a snippet to paste.

No `.sspj` of your own yet? SpriteStudio's [official sample data](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/) works as-is — the page is in Japanese, the downloads are not. [Ringo](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/#ringo) is a good character to start with. To make your own, you use SpriteStudio itself — see [its site](https://www.webtech.co.jp/eng/spritestudio/).

**Read next:** [Usage Guide](docs/en/usage.md) · [Asset Import](docs/en/import.md) — including
[hot reload](docs/en/import.md#hot-reload) after editing in SpriteStudio, and the converters that
work without Ren'Py running · [Limitations & Scope](docs/en/limitations.md)

## 🔗 Related Repositories

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/) — the documentation portal for the SDK and every official player
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — the core SDK providing `libssruntime` and `libssconverter`
- [SSConverter GUI](https://github.com/cri-middleware/SSConverterGUI) — desktop GUI for converting `.sspj` to `.ssab` without a player

## 📄 License

This project and its output are provided under the [LICENSE.md](LICENSE.md) (BSD-3-Clause).

For the licenses of the bundled `SpriteStudio-SDK` and other third-party libraries used in this project, please refer to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
