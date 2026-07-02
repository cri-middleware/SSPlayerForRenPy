[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

An extension library (player) for playing **[SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** animations (`.ssab`) in [Ren'Py](https://www.renpy.org/).

## 📚 Documentation
The documentation for this repository is structured for three different personas. Please refer to the section that matches your goals.

- **User**: Those who want to integrate the provided package directly into their game.
- **Customer**: Those who want to customize the behavior on the Ren'Py (Player) side without building the SDK itself.
- **SDK/Player Developer**: Those who want to develop and modify the core parts, including the native library (Rust), by building it themselves.

For detailed instructions and specifications by purpose, please refer to the following documents:
- **[Setup Guide](docs/setup.md)**: How to integrate into your game project (For Users)
- **[Asset Import](docs/import.md)**: How to convert animation data (`.sspj`)
- **[Usage](docs/usage.md)**: How to call from Ren'Py scripts
- **[Build Guide](docs/build.md)**: Environment setup and native build procedures for customization (For Customers & Developers)
- **[Limitations](docs/limitations.md)**: Support status and list of unsupported features

---

## 🎮 1. For Users: Game Integration (Quick Start)
This is an easy way to introduce the player without any burden by using the pre-built package.

Download the latest ZIP file from [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases), extract it, and copy the resulting **`spritestudio/`** folder directly into the `game/` folder of your Ren'Py project. This completes the installation.

```renpy
# Example of calling it in a game project
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
*For more details, see the [Setup Guide](docs/setup.md) and [Usage](docs/usage.md).*

## 🛠 2. For Customers: Player Customization
This is the environment setup for those who want to modify the Python code or Ren'Py scripts on the Ren'Py side, but want to use the pre-built native Rust SDK core without building it.
You don't need to clone `SpriteStudio-SDK` recursively and build it yourself; you can obtain the pre-built binaries from the official releases.

**macOS / Linux:**
```bash
# Get the submodule to use demo data (recursive is not needed)
git submodule update --init

# Download the native SDK library from Releases
scripts/download-sdk.sh

# Convert playback data for the demo
scripts/deploy-examples.sh

# Get Ren'Py SDK and launch the demo project test
scripts/fetch-renpy-sdk.sh
scripts/run-demo.sh
```

**Windows:**
```powershell
# Get the submodule to use demo data (recursive is not needed)
git submodule update --init

# Download the native SDK library from Releases
scripts\download-sdk.ps1

# Convert playback data for the demo
scripts\deploy-examples.ps1

# Get Ren'Py SDK and launch the demo project test
scripts\fetch-renpy-sdk.ps1
scripts\run-demo.ps1
```
*For more details, see the [Build Guide](docs/build.md).*

## ⚙️ 3. For SDK/Player Developers: Full Build Environment
This is for those who want to develop and contribute, including the Rust submodule (`SpriteStudio-SDK`) responsible for the core animation calculations.
Since you will be using `rustup` to build `libssconverter` and `libssruntime` yourself, you need to set up the Rust toolchain (`cargo` / `rustup`) in advance.

**macOS / Linux:**
```bash
# Clone completely, including submodules
git submodule update --init --recursive

# Build the native runtime
scripts/build-runtime.sh

# From here, you can launch the demo just like for Customers
```

**Windows:**
```powershell
# Clone completely, including submodules
git submodule update --init --recursive

# Build the native runtime
scripts\build-runtime.ps1

# From here, you can launch the demo just like for Customers
```

- By using the Python scripts in the `tools/` folder, you can perform headless behavior verification without launching Ren'Py.
- For detailed specifications and correct implementation methods, **make sure to refer to the Player porting guide in `SpriteStudio-SDK/libs/ssruntime/docs/`**.
