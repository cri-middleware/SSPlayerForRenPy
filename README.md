[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**Give your visual novel editor-crafted 2D animation — in just a few lines of script, no video files.**

An extension (player) that plays **[OPTPiX SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** animations (`.ssab`) directly in [Ren'Py](https://www.renpy.org/). Animate the sprite art you already use (PNG / WebP) in a dedicated editor, then drop the finished animation into your project — with none of the long, complex ATL or heavy video files it would normally take.

## ✨ Why SpriteStudio Player?

- **Editor-crafted animation, not hand-written ATL.** SpriteStudio 7 is a dedicated editor for **raster-based 2D animation** — bone hierarchies, mesh deformation, particle effects. You build the motion visually and the player just plays it, so there's no long, complex ATL (Animation and Transformation Language) to hand-write for the animation itself.
- **A lightweight alternative to video.** Where Ren'Py productions reach for video — a `Movie` playing a `.webm`, `.ogv`, or `.mp4` for animated openings, living backgrounds, effect cut-ins — this runs as lightweight native playback: it scales freely at runtime, loops seamlessly, and reacts to your game instead of just playing back. No bloated video files.
- **Uses the art you already have (PNG / WebP).** Textures load through Ren'Py's standard image pipeline, so PNG and WebP work exactly like every other image in your project.
- **Still composes with ATL & `Transform`.** `SSPlayer` is a standard Ren'Py Displayable, so you keep ATL where it shines — position, slide, zoom, or fade the whole animated sprite exactly like any other image.

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

## 🎮 1. Quick Start (For Users)

This is the easiest way to integrate the player using a pre-built package.

Download the latest ZIP file from [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases). Extract it, and simply copy the resulting **`spritestudio/`** folder directly into the `game/` folder of your Ren'Py project. That's it!

```renpy
# Example usage in a Ren'Py script
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
*For details, see the [Setup Guide](docs/setup.md) and [Usage & Control](docs/usage.md).*

## 🛠 2. Customizing the Player (For Customers)
If you want to modify the Ren'Py scripts or Python code but prefer to use the pre-built native Rust SDK core, follow these steps to set up your environment.

**macOS / Linux:**
```bash
git submodule update --init
scripts/download-sdk.sh
scripts/deploy-examples.sh
scripts/fetch-renpy-sdk.sh
scripts/run-demo.sh
```

**Windows:**
```powershell
git submodule update --init
scripts\download-sdk.ps1
scripts\deploy-examples.ps1
scripts\fetch-renpy-sdk.ps1
scripts\run-demo.ps1
```
*For details, see the [Build Guide](docs/build.md).*

## ⚙️ 3. Full Build Environment (For SDK/Player Developers)
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
*For detailed specifications, be sure to read the Player Porting Guide located in `SpriteStudio-SDK/libs/ssruntime/docs/`.*

## 📄 License

This project and its output are provided under the [LICENSE.md](LICENSE.md) (BSD-3-Clause).

For the licenses of the bundled `SpriteStudio-SDK` and other third-party libraries used in this project, please refer to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
