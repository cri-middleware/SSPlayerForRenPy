[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**Give your visual novel editor-crafted 2D animation — in just a few lines of script, no video files.**

An extension (player) that plays **[OPTPiX SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** animations (`.ssab`) directly in [Ren'Py](https://www.renpy.org/). Animate the sprite art you already use (PNG / WebP) in a dedicated editor, then drop the finished animation into your project — with none of the long, complex ATL or heavy video files it would normally take.

## ✨ Why SpriteStudio Player?

- **Bring your sprites to life.** Breathing and blinking, swaying hair and clothes, flashy slash or magic effects — you build the motion visually in a dedicated editor (SpriteStudio 7) and the player just plays it. With bone rigs, mesh deformation, and particles, there's no long, complex ATL to hand-write.
- **A lightweight alternative to video.** Where Ren'Py productions reach for video — a `Movie` playing a `.webm`, `.ogv`, or `.mp4` for animated openings, living backgrounds, effect cut-ins — this runs as lightweight native playback: it scales freely at runtime, loops seamlessly, and reacts to your game instead of just playing back.
- **Still composes with ATL & `Transform`.** `SSPlayer` is a standard Ren'Py Displayable, so you keep ATL where it shines — position, slide, zoom, or fade the whole animated sprite exactly like any other image.
- **Smooth motion, not locked to a frame rate.** **Sub-frame interpolation** renders each frame at the exact display time. Unlike video baked at a fixed frame rate, motion follows your display's refresh rate and playback speed for smoother movement.
- **A seamless edit-to-runtime loop.** The **Auto Importer** watches `SpriteStudio_Source/` during development: edit a `.sspj`, reload Ren'Py (**Shift+R**), and only the changed project is re-converted automatically and shows up live in your game — no manual export step.

## 📚 Documentation

For detailed specifications, import procedures, and API references, please visit our MkDocs documentation site.

- [**Documentation (English)**](./docs/index.md)
- [**ドキュメント (日本語)**](./docs/ja/index.md)

### Quick Links
- [Setup Guide](docs/setup.md)
- [Asset Import](docs/import.md)
- [Usage & Control](docs/usage.md)
- [Build Guide](docs/build.md)

---

## 🎮 1. Quick Start

### Setup

This is the easiest way to integrate the player using a pre-built package.

Download the latest ZIP file from [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases). Extract it, and simply copy the resulting **`spritestudio/`** folder directly into the `game/` folder of your Ren'Py project. That's it!

```renpy
# Example usage in a Ren'Py script
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
*For details, see the [Setup Guide](docs/setup.md) and [Usage & Control](docs/usage.md).*

### Verifying It Works

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
*For details, see the [Build Guide](docs/build.md).*

## ⚙️ 2. Full Build Environment (For SDK/Player Developers)
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

- Run `scripts/build-runtime.*` in place of the `scripts/download-sdk.*` step from Verifying It Works — this builds the core yourself instead of fetching the pre-built one. The following `fetch-renpy-sdk` / `deploy-examples` / `run-demo` steps are the same as in [Verifying It Works](#-1-quick-start).

## 📄 License

This project and its output are provided under the [LICENSE.md](LICENSE.md) (BSD-3-Clause).

For the licenses of the bundled `SpriteStudio-SDK` and other third-party libraries used in this project, please refer to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
