# 🛠️ Build Guide

This is a guide for developers who wish to modify and customize the code in this repository:
building it, using a changed copy in a game, and checking it in Ren'Py. How the player is put
together, and why, is on [How the Player Is Put Together](architecture.md).

> **Just want to use the player in your own game?** You don't need this guide —
> see the [Setup Guide](../setup.md) and [Usage](../usage.md). This page is for working
> *inside this repository*: customizing the player code or rebuilding the native
> libraries. (The "Customer" role below still means a developer — one who edits
> only the Ren'Py-side code — not an end user.)

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
4. **`wasm-opt` (Binaryen)**: Required if you are building the Web (WASM) target.

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
*If you want to perform a release build, specify arguments like `build=release` (`--help` lists every option).*

### 2.4 Launching the Demo and Development Iteration
Perform data conversion and demo launch just like for Customers.
**How to Iterate:**
When you modify the native library (`SpriteStudio-SDK/libs/`) side, run `build-runtime.sh` again to update the binaries, then launch `run-demo.sh`.

### 2.5 Updating FlatBuffers Bindings (On Schema Change)
When changes are made to the FlatBuffers schema (`.fbs` file) on the `SpriteStudio-SDK` side, you need to regenerate the read code (bindings) for the Python side. This task requires the `flatc` compiler installed and accessible in your local environment path.

**macOS / Linux:**
```bash
scripts/generate-fbs-code.sh
```
**Windows:**
```powershell
scripts\generate-fbs-code.ps1
```
*Running this will automatically regenerate and overwrite the Python code under `game/spritestudio/python/ss/`.*
*If you want to update the pure Python runtime library itself (`game/spritestudio/python/flatbuffers/`), please run `scripts/download-flatbuffers.*` to re-vendor it.*

### 2.6 SDK Development Rules
- Since `SpriteStudio-SDK` represents core specifications, do not force unreasonable workarounds for the convenience of the Player (Ren'Py side). If a specification change is needed, please raise it as an issue on the SDK repository itself.

---

## 3. Building Platform Exports (Helper Scripts)

The repository ships helper scripts under `scripts/` that run a full platform
export of the demo and apply any SSPlayer-specific post-steps automatically — the
developer-side counterpart of the manual instructions in the
[Export Guide](../export.md). They drive the Ren'Py SDK fetched above.

> These scripts are for working **inside this repository**. A game author
> exporting their own project uses the stock Ren'Py launcher instead — see the
> [Export Guide](../export.md).

### 3.1 Prerequisites
- The native library for the **target** platform placed under
  `game/spritestudio/libs/` — `scripts/download-sdk.*` (prebuilt) or
  `scripts/build-runtime.*` (source). Desktop / mobile / web each need their own,
  e.g. `build-runtime.* platform=android build=release`, `platform=ios`,
  `platform=web`.
- The Ren'Py SDK (`scripts/fetch-renpy-sdk.*`); the desktop, Android and iOS deploy
  scripts fetch it on demand if it is missing, and `deploy-web.*` asks you to run it first.
- Platform-specific toolchains, one-time:
    - **Android**: `scripts/fetch-renpy-android.*` (RAPT), then **Install SDK**,
      **Configure** (sets the package name in `android.json` — required), and
      **Generate Keys** once from the launcher GUI (→ Android).
    - **iOS**: `scripts/fetch-renpy-ios.sh` (renios; macOS-only).
    - **Web**: `scripts/fetch-renpy-web.*` (Ren'Py Web support).

### 3.2 Export Commands

**macOS / Linux (`*.sh`):**
```bash
scripts/deploy-desktop.sh [dest_dir]                       # host-OS desktop app (mac / linux)
scripts/deploy-android.sh [dest_dir] [--bundle] [--install] [--launch]
scripts/deploy-ios.sh     [dest_dir] [--recreate] [--open] # generates an Xcode project (macOS only)
scripts/deploy-web.sh     [dest_dir]                       # the stock Web export; nothing to apply after it
```

**Windows (`*.ps1`):**
```powershell
scripts\deploy-desktop.ps1 [dest_dir]                      # win desktop app
scripts\deploy-android.ps1 [dest_dir] [--bundle] [--install] [--launch]
scripts\deploy-web.ps1     [dest_dir]
# (iOS export is macOS-only; there is no deploy-ios.ps1)
```

- **Desktop**: builds for the host OS (`.sh`: mac / linux; `.ps1`: win) and unpacks
  a ready-to-run app. Only the platform whose native library is present can be
  built to run.
- **Android**: `--bundle` → `.aab` (Play upload); `--install` / `--launch` push and
  start on a connected device via `adb`.
- **iOS**: generates / refreshes the Xcode project; the Brain still needs the
  one-time **Embed & Sign** in Xcode (see the [Export Guide](../export.md)).
- **Web**: the stock Web export, with nothing applied after it; serve the output over
  HTTP with the right MIME types.

Why each platform needs what these scripts do (the per-ABI `.so`, the dynamic iOS
xcframework) is in [Where the Native Library Loads From](architecture.md#where-the-native-library-loads-from);
the `.rpa` ordering is in the [Export Guide](../export.md).

---

## 4. Using a Changed Player

A game takes the player as one folder, so a checkout gets into a game the way a release does:

1. Put the native libraries in place: `scripts/download-sdk.*` for the released ones, or
   `scripts/build-runtime.*` after changing the SDK ([2.3](#23-building-the-native-library);
   `platform=` builds Android, iOS and the Web).
2. In the game, delete `game/spritestudio/`, then copy the checkout's `game/spritestudio/` in.
   Delete first: Ren'Py keeps running a `.rpyc` whose `.rpy` is gone.

To hand the change to someone else, build the zip a release publishes:
`scripts/build-release.sh demo=skip` writes `release-dist/SSPlayerForRenPy-<version>.zip`
from the checkout, with the libraries `sdk=` picks (`--help` lists them). It installs as the
[Setup Guide](../setup.md) describes.

---

## 5. Checking Against the Real Host

`scripts/run-tests.sh` covers the engine-independent core in plain CPython; CONTRIBUTING has
its rules. What it cannot cover — drawing, the displayable, the launcher, the exports — is
checked by running Ren'Py, and all of it can run from a script.

### 5.1 Where Ren'Py's Labels Come From

The guides name the launcher's screens and the in-game developer tools as Ren'Py shows them.
The English strings are the `_("…")` calls in `renpy-sdk/launcher/game/*.rpy` (the launcher)
and `renpy-sdk/renpy/common/` (the in-game tools); the Japanese ones are the `old` / `new`
pairs in `renpy-sdk/launcher/game/tl/japanese/`. **Create Xcode Project**, for one, is
`ios.rpy` in English and 「Xcode プロジェクト作成」 in `tl/japanese/launcher.rpy`.

### 5.2 Drawing, Without a Person at the Keyboard

GL2 drawing has no headless check. A throwaway script can still run it from launch to a
screenshot. Save this as `game/zz_check.rpy`, and delete it and its `.rpyc` afterwards:

```renpy
init python:
    import os as _check_os
    if _check_os.environ.get("SS_CHECK_PACK"):
        config.label_overrides["start"] = "zz_check"
        config.log = "zz_check_log.txt"

label zz_check:
    scene expression Solid("#202020")
    $ _p = SSPlayer(_check_os.environ["SS_CHECK_PACK"], size=(1280, 720))
    show expression _p as check:
        xalign 0.5 yalign 0.5
    pause 1.5
    python:
        renpy.screenshot(_check_os.environ["SS_CHECK_SHOT"])
        renpy.quit()
```

Run it with
`RENPY_SKIP_MAIN_MENU=1 SS_CHECK_PACK=ss_assets/Ringo/Ringo.ssab SS_CHECK_SHOT=<png> renpy-sdk/renpy.sh .`.

- Without `RENPY_SKIP_MAIN_MENU`, the main menu waits and `label_overrides` never applies.
- An exception leaves Ren'Py on its error screen. Watch for `traceback.txt`, bound the run
  (`perl -e 'alarm 60; exec @ARGV' renpy-sdk/renpy.sh .`), and write results to a file: a
  killed process loses its buffered output.
- The player's own reports (`[SSPlayer] …`) are printed, so they reach `log.txt` and the console in any
  project. `renpy.log` writes nothing unless `config.log` is set.
- A `modal True` screen, such as the Shift+B browser, never returns from `renpy.pause`. Step
  through it from a high-`zorder` screen's `timer … repeat True`, and wait in the label with
  `$ ui.interact()`.
- Cause interaction with real input: `renpy.test.testmouse`'s `move_mouse`, `press_mouse` and
  `release_mouse`, at positions read from `renpy.display.focus.focus_list`. Rewriting a
  displayable's state to imitate a drag skips the path Ren'Py really takes.
- What needs init code but no drawing — `SSPlayer`'s constructor, `_duplicate`, loading, the
  importer — runs under lint, which executes init blocks: an `init 999 python:` in a
  throwaway `game/zz_*.rpy`, then `renpy-sdk/renpy.sh . lint --error-code`.
- The demo's own scripts (`game/*.rpy` outside `spritestudio/`) are under no test and no lint
  check. After renaming an `ss_*` method, search them by hand.

### 5.3 The Web Build

Build it with `scripts/deploy-web.sh <dir>`, serve it over HTTP (`python3 -m http.server <port>`)
and open it in Chrome; in headless Chrome, drive it over the DevTools protocol.

- Ren'Py Web is CPython compiled with emscripten, not Pyodide.
- Use a new port for every build: `http.server` sends no `Cache-Control`, so an old build can
  come back.
- Startup takes a minute or two. `window.ss_runtime_state` reads `ready` once the bridge has
  loaded the wasm, and `renpy_exec("…")` runs Python in the game from the page.
- The first click on the canvas after each screen change goes to focus.
- A JavaScript exception stops Ren'Py's loop without a word: `renpy_exec` stops returning and
  the CPU goes idle. Read the exception from the protocol's `Runtime.exceptionThrown`.

### 5.4 Android and iOS

`scripts/deploy-android.*` builds through RAPT, which needs JDK 21: point `JAVA_HOME` at one,
or `android_build` fails with "Java version is wrong". `scripts/deploy-ios.sh` generates the
Xcode project and stages the xcframework; after the one **Embed & Sign**, a Simulator run
needs no signing.

### 5.5 Measuring the Hot Path

Time `update()` on a headless `SSInternalPlayer` over the packs in `game/ss_assets/`. Compare
inside one directory, swapping the `.py` under test round-robin for three rounds or more and
taking each pack's minimum: the same code timed in another checkout of the repository can
differ by about 13%. What pays off is moving work from the interpreter into C — one
`struct.unpack` for a whole vector, `list.extend` instead of a loop of `append`, invariants
hoisted out of vertex loops. When `.rpy` code is slow, check cProfile for
`renpy/revertable.py` first: a list built in a `.rpy` file is a `RevertableList`, whose every
change is recorded for rollback and which Ren'Py's mesh reads back item by item.

---
