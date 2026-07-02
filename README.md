[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

An extension library (player) for playing **[SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** animations (`.ssab`) in [Ren'Py](https://www.renpy.org/).

With this player, Ren'Py users are freed from writing long, complex ATL (Animation and Transformation Language) or custom animation logic. You can easily integrate highly expressive 2D animations crafted in the dedicated editor—such as smoothly moving character sprites, dynamic UI, and effects—into your project with just a few lines of script. It delivers lightweight, native performance without relying on heavy video files.

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
