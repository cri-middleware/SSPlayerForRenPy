# Build & Customization Guide

This is a guide for developers who wish to modify and customize the code in this repository.
Set up one of the following two environments depending on your goals:

- **Customer**: Those who want to customize only the Python/Ren'Py code on the Ren'Py side, without building the SDK core (native library).
- **SDK/Player Developer**: Those who want to do a full build, including the native libraries (`libssruntime`, `libssconverter`), to modify core specifications.

---

## 1. For Customers: Player Customization Environment
Because you don't need to build the Rust-based native libraries, you can set up a customization environment very easily.

### 1.1 Prerequisites
- **Python (3.x)**: Required to run the demo data conversion script (`deploy-examples.sh`) and the Ren'Py SDK fetch script.

### 1.2 Repository Setup
Initialize the submodules to obtain test data for the demo. Since the native build environment is not needed here, do **not** use the `--recursive` option.
```bash
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init
```

### 1.3 Downloading the Native Library
Automatically download and place the pre-built binaries from the SDK release.
**macOS / Linux:**
```bash
scripts/download-sdk.sh
```
**Windows:**
```powershell
scripts\download-sdk.ps1
```

### 1.4 Launching the Demo and Development Iteration
Convert the animation data included in the demo project, and start Ren'Py to verify behavior.
**macOS / Linux (`*.sh`):**
```bash
# Get Ren'Py SDK
scripts/fetch-renpy-sdk.sh

# Convert playback data for the demo and launch the demo project test
scripts/deploy-examples.sh
scripts/run-demo.sh
```
**Windows (`*.ps1`):**
```powershell
# Get Ren'Py SDK
scripts\fetch-renpy-sdk.ps1

# Convert playback data for the demo and launch the demo project test
scripts\deploy-examples.ps1
scripts\run-demo.ps1
```

*Note: `deploy-examples` and `run-demo` use the Python binary bundled with the Ren'Py SDK.*

**How to Iterate:**
After modifying the Python code (`game/spritestudio/python/`) or Ren'Py scripts (`game/*.rpy`) on the Ren'Py side, the changes will be reflected just by re-running `run-demo.sh`.

---

## 2. For SDK/Player Developers: Full Build Environment
These steps are for those who want to build and modify from scratch, including the Rust-based `SpriteStudio-SDK` code.

### 2.1 Prerequisites
1. **Python (3.x)**: For tools and various scripts.
2. **Rust Environment (`rustup`)**: Mandatory for building the runtime library from source code. Please install it from the official site ([rustup.rs](https://rustup.rs/)).
3. **`flatc` (FlatBuffers Compiler)**: Only needed if you are rebuilding the binding definitions (auto-generation) of the playback data.

### 2.2 Complete Setup of Repository and Submodules
To fetch all dependent crates, initialize the submodules with `--recursive`.
```bash
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
```

### 2.3 Building the Native Library
Modify and build the C/Rust code. The result will be output to `game/spritestudio/libs/`.
**macOS / Linux:**
```bash
scripts/build-runtime.sh
```
**Windows:**
```powershell
scripts\build-runtime.ps1
```
*If you want to perform a release build, specify arguments like `build=release` (for details, refer to the script contents).*

### 2.4 Launching the Demo and Development Iteration
Perform data conversion and demo launch just like for Customers.
**How to Iterate:**
When you modify the native library (`SpriteStudio-SDK/libs/`) side, run `build-runtime.sh` again to update the binaries, then launch `run-demo.sh`.

### 2.5 Updating FlatBuffers Bindings (On Schema Change)
When changes are made to the FlatBuffers schema (`.fbs` file) on the `SpriteStudio-SDK` side, you need to regenerate the read code (bindings) for the Python side. This task requires the `flatc` compiler installed and accessible in your local environment path.

**macOS / Linux:**
```bash
scripts/generate-runtime-code.sh
```
**Windows:**
```powershell
scripts\generate-runtime-code.ps1
```
*Running this will automatically regenerate and overwrite the Python code under `game/spritestudio/python/ss/`.*
*If you want to update the pure Python runtime library itself (`game/spritestudio/python/flatbuffers/`), please run `scripts/download-flatbuffers.*` to re-vendor it.*

### 2.6 SDK Development Rules
- Since `SpriteStudio-SDK` represents core specifications, do not force unreasonable workarounds for the convenience of the Player (Ren'Py side). If a specification change is needed, please raise it as an issue on the SDK repository itself.
