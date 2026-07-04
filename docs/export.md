# Exporting your Game

This guide describes how to export games incorporating the SpriteStudio Player for Ren'Py to various platforms.

## Web Export

You can output a web-playable game using Ren'Py's standard Web export feature (Pyodide/WASM).
This library automatically uses a non-ctypes JS binding (`ssruntime_web.py`) internally, so no Python code changes are required.

> **⚠️ A raw Ren'Py Web export will NOT run on its own.**
> The Web renderer loads a separate WASM module (`ssruntime.js` / `ssruntime_bg.wasm`).
> Ren'Py's exporter does not know about it, so **every export requires two manual
> post-steps** — editing `index.html` (§3) and placing the WASM assets as real
> files (§4). Without them the browser console throws
> `Cannot read properties of undefined (reading 'SSRuntimeContext')`
> (i.e. `window.ssruntime` was never loaded) and nothing renders.
> The exporter **regenerates `index.html` and repacks `game.zip` on every run**,
> so these two steps must be **re-applied after each export**.

### Automated build (recommended)

Use the helper script, which runs the export and applies both post-steps (§3 and
§4) for you. It is idempotent, so it is safe to re-run:

```bash
scripts/deploy-web.sh [dest_dir]      # default dest: web_out
# Windows:
scripts\deploy-web.ps1 [dest_dir]
```

Then serve `dest_dir` over HTTP (see [Testing](#testing) below). If you prefer to
do it by hand, follow the manual steps instead.

### Manual steps

1. **Setup the Web Build Environment**
   Install the necessary Ren'Py packages for Web export.
   (Download from the Ren'Py Launcher or run `scripts/fetch-renpy-web.sh` in the project.)

2. **Run the Export**
   From the Ren'Py Launcher, go to the "Web (Beta)" menu and select "Build Web Application" to run the export.
   (For CLI, run `./renpy.sh launcher web_build <project_dir> --dest <out>`.)

3. **⚠️ Required: Add the JS/WASM Load Script to `index.html`**
   Open the generated `index.html` in the output folder and add the following code
   **before** Ren'Py's initialization (immediately before the
   `<script src="renpy-pre.js"></script>` tag).
   This loads the WASM bindings that do SSPlayer rendering *before* the game starts.
   **This edit is mandatory and is lost on every re-export — re-add it each time.**

   ```html
   <script type="module">
     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
     window.ssruntime = ss;
     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
   </script>
   ```

4. **⚠️ Required: Deploy Web Assets (`ssruntime.js` / `ssruntime_bg.wasm`)**
   The export process zips the `game` directory into `game.zip`, so a browser's
   ES-module `import` in `index.html` **cannot** read the runtime from inside it.
   Therefore you must **copy** `ssruntime.js` and `ssruntime_bg.wasm` from
   `game/spritestudio/libs/web/` into the same path in the output folder as **real
   files** (e.g., `web_out/game/spritestudio/libs/web/`). The import path in §3
   must match this location exactly.

### Testing

* **Serve over HTTP, not `file://`.** ES modules and WASM will not load from the
  filesystem. Any static server works, but it must send the right MIME types:
  `.js` → `application/javascript`, `.wasm` → `application/wasm`. Ren'Py's own web
  server (`renpy.sh launcher web_build <dir> --launch`, or the launcher's
  "Web (Beta)" page) already does this.
* **Clear the Service Worker when re-testing.** A Ren'Py web build registers a
  service worker that caches `game.zip`. After a re-export the browser may serve
  the *old* build. In DevTools → Application, **Unregister** the service worker
  and **Clear site data**, then hard-reload (or use a private window).

### Implementation Details

* **Packaging `.ssab` and audio (`.wav` / `.mp3`) Files**
   By default during web exports, Ren'Py only includes specific file extensions (like `.png` or `.ogg`) in the output archive (`game.zip`).
   The library defines `build.classify('**.ssab', 'all')` in `spritestudio.rpy`, so your SpriteStudio packs are always included — no `options.rpy` edit needed for those.
   **Uncompressed audio is the game's call, not the library's:** if your game plays SpriteStudio **Audio** timeline events from `.wav` / `.mp3` files, add `build.classify('**.wav', 'all')` and `build.classify('**.mp3', 'all')` to your own `options.rpy` (this demo does exactly that — see `game/options.rpy`). Otherwise the web builder drops them.

## Desktop Export (Windows / macOS / Linux)

Desktop export uses Ren'Py's standard **Build Distributions** feature. Unlike the
Web target, **no post-export steps are required**: the native "Brain" library
(`libssruntime.dylib` / `ssruntime.dll` / `libssruntime.so`) lives *inside*
`game/`, so Ren'Py bundles it into the app automatically and `ssruntime.py`
resolves it at runtime from `game/spritestudio/libs/<platform-arch>/` — the same
layout used during development.

Assets are handled too: `spritestudio.rpy` declares `build.classify('**.ssab',
'all')`, so your `.ssab` packs (and their co-located textures) are packaged
without touching `options.rpy`. Uncompressed **audio** (`.wav` / `.mp3`) is the
game's responsibility — classify it in your own `options.rpy` if you use SS Audio
events (the demo does; see `game/options.rpy`).

> **⚠️ Each target platform needs its own native library.**
> The Brain is a compiled binary, so a package can only *run* on a platform whose
> library is present under `game/spritestudio/libs/`:
>
> | Package | Needs | Path |
> |---|---|---|
> | `mac`   | `libssruntime.dylib` (universal) | `libs/macos/` |
> | `win`   | `ssruntime.dll`      | `libs/windows/x86_64/` |
> | `linux` | `libssruntime.so`    | `libs/linux/x86_64/` |
>
> **This repository currently ships only the macOS library.** A `win`/`linux`
> package built without the matching binary still *builds*, but SSPlayer throws at
> load time (the resolved `.dll`/`.so` path does not exist). Obtain the other
> platforms' libraries first with `scripts/download-sdk.*` (prebuilt) or
> `scripts/build-runtime.*` (from source), then re-run the export.

### Automated build (recommended)

Use the helper script, which builds the package matching your **host OS** and
unpacks it into a ready-to-run app. It is idempotent, so it is safe to re-run:

```bash
scripts/deploy-desktop.sh [dest_dir]     # default dest: dist
#   macOS -> dist/<name>.app         (double-click / `open`)
#   Linux -> dist/<name>-linux-x86_64/ (run its <name>.sh)
# Windows (.exe):
scripts\deploy-desktop.ps1 [dest_dir]    # -> dist\<name>-win\<name>.exe
```

The script errors out with a hint if the native library for the host platform is
missing. Because only the macOS library ships here, run the `.sh` **on a Mac** for
a working build out of the box.

### Manual build

From the project root (builds the `mac` package; swap `--package` for `win` /
`linux` on those hosts):

```bash
renpy-sdk/renpy.sh renpy-sdk/launcher distribute . \
  --package mac --format app-zip --no-update --destination dist
```

Or from the Ren'Py Launcher GUI: select the project → **Build Distributions** →
tick **Macintosh** → **Build**.

The result is `dist/<name>-mac.zip` containing a self-contained `.app`. The native
library lands at
`<name>.app/Contents/Resources/autorun/game/spritestudio/libs/macos/libssruntime.dylib`,
and the app loads it with no further wiring.

> **⚠️ `build.name` must be set, or the app won't launch.** With no `build.name`,
> Ren'Py leaves `CFBundleExecutable` (and the `Contents/MacOS/` launcher binary)
> empty, producing a degenerate `-mac.zip` whose `.app` cannot start. This demo's
> `options.rpy` already sets `define build.name = "SSPlayerForRenPy"`; your own
> game must set its own (e.g. `define build.name = "MyGame"` → `MyGame-1.0`).

### macOS distribution note

A locally built `.app` runs fine on your own machine. If you **distribute** it
(users download it), macOS Gatekeeper quarantines the unsigned `.dylib` and the
app is blocked. For release you must **code-sign and notarize** the app (Ren'Py's
launcher supports passing a signed app via `--macapp`; see Ren'Py's
"Signing a Mac App" documentation).

### Packaging details

`spritestudio.rpy` keeps desktop builds lean automatically (via `build.classify`),
so you should not need to touch `options.rpy`:

* **Only the target platform's native library ships.** Each `libs/<platform>/`
  subtree is tagged with its Ren'Py platform (`macos/`→`mac`, `windows/x86_64/`→
  `windows`, `linux/x86_64/`→`linux`, …), so a `mac` build carries just the
  `.dylib` — not the Windows `.dll`, Linux `.so`, or Web `.wasm`.
* **The converter (`libssconverter.*`) is never bundled.** It is an import- /
  dev-time tool (`auto_importer`, gated on `config.developer`); a shipped game
  never loads it.
* Stale `__pycache__` is dropped. (This repo's own developer cruft — `renpy-sdk/`,
  `SpriteStudio-SDK/`, `scripts/`, `docs/`, `dist/`, root `*.md` / `*.txt`, … — is
  excluded from the *demo's* build by `game/options.rpy`, not by the library, so a
  downstream game that vendors `game/spritestudio/` is never affected by it.)

**Optional — pack assets into a `.rpa` archive.** Ren'Py ships game files loose
by default. To bundle them into a single archive instead, declare an archive and
classify the assets into it. SSPlayer loads packs through `renpy.loader.load`, so
they work identically loose or archived. Because `build.classify` is
first-match-wins by registration order, register the archive pattern *before* the
library's `**.ssab`→`all` (init −10) — i.e. at an earlier init priority:

```renpy
init -20 python:
    build.archive("ssdata", "all")
    build.classify("game/ss_assets/**", "ssdata")   # -> game/ssdata.rpa
```

The demo's `options.rpy` already does this behind a `ss_pack_assets_into_rpa`
toggle (set it `False` to distribute the assets loose).

## Android Export

Android export uses Ren'Py's standard **RAPT** toolchain (the Ren'Py Android
Packaging Tool). Like the desktop target and unlike Web, **no post-export steps
are required**: the native "Brain" `.so` under
`game/spritestudio/libs/android/<arch>/` is bundled into the app and
`ssruntime.py` loads it at runtime.

> **⚠️ Android needs its own native libraries, one per ABI.**
> The Brain is a compiled binary, so the app only runs on an ABI whose `.so` is
> present. They go under the SDK's **arch tokens** (`arm64` / `arm32` / `x86_64`),
> **not** the Android ABI names (`arm64-v8a` / `armeabi-v7a`) — this path is a
> ctypes load path inside `game/`, not the APK's `lib/<abi>/`:
>
> | Device | Path |
> |---|---|
> | 64-bit phones/tablets (most) | `libs/android/arm64/libssruntime.so` |
> | Older 32-bit phones          | `libs/android/arm32/libssruntime.so` |
> | x86_64 emulators             | `libs/android/x86_64/libssruntime.so` |
>
> Get them with `scripts/build-runtime.* platform=android build=release` (from
> source; needs the Android NDK toolchain) or `scripts/download-sdk.*` (prebuilt).

### One-time setup

1. **Fetch RAPT** — the extra download the Android target needs (like Web needs
   `fetch-renpy-web.*`):
   ```bash
   scripts/fetch-renpy-android.sh          # Windows: scripts\fetch-renpy-android.ps1
   ```
2. **Install the Android SDK & generate signing keys** — both are interactive, so
   do them once from the launcher GUI:
   ```bash
   renpy-sdk/renpy.sh renpy-sdk/launcher   # -> Android
   ```
   * **Install SDK** — downloads the Android SDK / NDK / JDK into `renpy-sdk/rapt/Sdk/`.
   * **Generate Keys** — creates `android.keystore` (and `bundle.keystore`) in the
     project root, used to sign the package.

### Automated build (recommended)

Use the helper script, which checks the prerequisites above and runs the export.
It auto-fetches the Ren'Py SDK and RAPT if missing:

```bash
scripts/deploy-android.sh [dest_dir] [--bundle] [--install] [--launch]   # default dest: dist
# Windows:
scripts\deploy-android.ps1 [dest_dir] [-Bundle] [-Install] [-Launch]
```

* `--bundle` builds an `.aab` App Bundle (for Play upload) instead of a Universal
  `.apk`; `--install` / `--launch` push and start it on a connected device (`adb`).

### Manual build

```bash
renpy-sdk/renpy.sh renpy-sdk/launcher android_build . --dest dist
```

Or from the launcher GUI: select the project → **Android** → **Build**. As with
desktop, `build.name` must be set (this demo's `options.rpy` already does).

## iOS Export

*(To be added later — requires building the iOS native library
(`libssruntime.xcframework`) and placing it under `game/spritestudio/libs/ios/`;
`scripts/build-runtime.* platform=ios` produces it.)*
