[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**Give your visual novel editor-crafted 2D animation — in just a few lines of script, no video files.**

▶️ **[Try the live demo in your browser](https://cri-middleware.github.io/SSPlayerForRenPy/demo/)** — the bundled SpriteStudio animations running in Ren'Py Web.

An extension (player) that plays **[SpriteStudio](https://www.webtech.co.jp/spritestudio/)** animations (`.ssab`) directly in [Ren'Py](https://www.renpy.org/). Animate the sprite art you already use (PNG / WebP) in a dedicated editor, then drop the finished animation into your project — with none of the long, complex ATL or heavy video files it would normally take.

## ✨ Why use SpriteStudio with Ren'Py?

- **Bring your sprites to life.** Breathing and blinking, swaying hair and clothes, flashy slash or magic effects — you build the motion visually in a dedicated editor (SpriteStudio), and Ren'Py just plays it. With bone rigs, mesh deformation, and particles, there's no long, complex ATL to hand-write.
- **Lip flap that follows your dialogue.** One `SSCharacter` line defines the image and the speaker together: the sprite plays its talk animation while a line is on screen and returns to idle when it ends — no per-line code.
- **Use it like any other image.** `show ringo wait1` works with no `image` statement, and switching to another animation is one more `show`, just like changing an expression. ATL and `Transform` still position, slide, zoom, or fade it, and the Interactive Director lists it.
- **A lightweight alternative to video.** Openings, living backgrounds, effect cut-ins — wherever you'd play a `Movie` — run as animation instead: it scales freely, loops seamlessly, changes on your script's cue, and moves at your display's refresh rate rather than a frame rate baked into a video. The bundled Ringo, every animation plus its texture, is under 300 KB.
- **A seamless edit-to-runtime loop.** The **Auto Importer** watches `SpriteStudio_Source/` during development: arm it with one **Shift+R**, then just save in SpriteStudio — only the changed project is re-converted, and the running game reloads itself to show it. No manual export step.

## 📚 Documentation

For detailed specifications, import procedures, and API references, please visit our MkDocs documentation site.

- [**Documentation site (hosted)**](https://cri-middleware.github.io/SSPlayerForRenPy/)
- [**Documentation (English)**](./docs/en/index.md)
- [**ドキュメント (日本語)**](./docs/ja/index.md)
- [**For AI assistants**](https://cri-middleware.github.io/SSPlayerForRenPy/llms.txt) — these docs as Markdown: `llms.txt` indexes the pages and `llms-full.txt` holds all of them in one file
- [**SpriteStudio Docs (portal)**](https://cri-middleware.github.io/SpriteStudio-Docs/) — the SDK and every official player in one place

### Quick Links
- [Setup Guide](docs/en/setup.md)
- [Asset Import](docs/en/import.md)
- [Usage & Control](docs/en/usage.md)
- [Limitations & Scope](docs/en/limitations.md)

---

## 🚀 1. Quick Start

**Using it in your game?** Read on — drop the folder in, convert your `.sspj`, add one line.
Everything after that (events, per-part overrides, `SSCharacter`) is the same path further in,
in the [documentation](./docs/en/index.md).
**Working on the Player, or the Rust core under it?** [Section 2](#%EF%B8%8F-2-full-build-environment-for-sdk--player-developers).

### Setup

Needs **Ren'Py 8.x** (the Python 3 line), and animations authored in **SpriteStudio 7.5 or later**.

This is the easiest way to integrate the player using a pre-built package.

Download the latest package — [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip) (stable link, always the latest release; to pick a specific version, see [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases)). Extract it, and simply copy the resulting **`spritestudio/`** folder directly into the `game/` folder of your Ren'Py project. That's it!

```renpy
# Example usage in a Ren'Py script
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
*For details, see the [Setup Guide](docs/en/setup.md) and [Usage & Control](docs/en/usage.md).*

**Your own animation gets in the same way.** Drop the SpriteStudio project into `SpriteStudio_Source/`
and the Auto Importer converts it on the next reload — which, with [hot reload](docs/en/import.md#hot-reload)
armed (one **Shift+R**), happens by itself. There is no manual export step.
[Asset Import](docs/en/import.md) also covers the two routes that do not need Ren'Py running:
SSConverter GUI on the desktop, and `ssconverter-cli` in CI.

### See it running from a checkout

> This is a checkout, not part of the setup above — you do not need it to use the package.

Run the bundled demo to confirm the player works correctly. The scripts below fetch the pre-built native Rust SDK core and launch the demo (no need to build the core yourself).

**macOS / Linux (`*.sh`):**
```bash
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
scripts/download-sdk.sh
scripts/fetch-renpy-sdk.sh
scripts/deploy-examples.sh
scripts/run-demo.sh
```

**Windows (`*.ps1`):**
```powershell
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
scripts\download-sdk.ps1
scripts\fetch-renpy-sdk.ps1
scripts\deploy-examples.ps1
scripts\run-demo.ps1
```

*Note: `deploy-examples` and `run-demo` use the Python binary bundled with the Ren'Py SDK.*
*For details, see the [Build Guide](docs/en/build.md).*

## ⚙️ 2. Full Build Environment (For SDK / Player Developers)
If you want to develop and contribute to the core animation module (`SpriteStudio-SDK`), follow these steps.

**macOS / Linux:**
```bash
git submodule update --init --recursive
scripts/build-runtime.sh
```

**Windows:**
```powershell
git submodule update --init --recursive
scripts\build-runtime.ps1
```

- Run `scripts/build-runtime.*` in place of the `scripts/download-sdk.*` step in [See it running from a checkout](#see-it-running-from-a-checkout) — this builds the core yourself instead of fetching the pre-built one. The following `fetch-renpy-sdk` / `deploy-examples` / `run-demo` steps are the same as there.

## 🔗 Related Repositories

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/) — the documentation portal for the SDK and every official player
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — the core SDK providing `libssruntime` and `libssconverter`
- [SSConverter GUI](https://github.com/cri-middleware/SSConverterGUI) — desktop GUI for converting `.sspj` to `.ssab` without a player

## 📄 License

This project and its output are provided under the [LICENSE.md](LICENSE.md) (BSD-3-Clause).

For the licenses of the bundled `SpriteStudio-SDK` and other third-party libraries used in this project, please refer to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
