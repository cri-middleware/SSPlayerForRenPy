# 📦 Exporting your Game

How to export a game that uses the SpriteStudio Player for Ren'Py. This covers
only what is **SSPlayer-specific**; for the generic build mechanics it links to
Ren'Py's own documentation.

> This page is for **game authors** exporting their own project with the stock
> Ren'Py launcher. If you are working inside this repository (building the demo
> or the native libraries), the developer helper scripts that automate each
> export below are documented in the [Build Guide](build.md).

Common to every platform: the native "Brain" library must be present under
`game/spritestudio/libs/<platform-arch>/` for the platform you build — Ren'Py
bundles it into the package and `ssruntime.py` resolves it at runtime. Shipping
your **assets** is your game's responsibility (they are your content, not the
library's): classify your `.ssab` packs (and `.ssqb` sequence packs, if any) —
and, for SS Audio timeline events, the uncompressed `.wav` / `.mp3` — in your own
`options.rpy`. The Web export in particular drops unknown extensions unless you
do. Add `build.classify('**.ssab', 'all')` and `'**.ssqb'` (plus `'**.wav'` /
`'**.mp3'` if you use audio); the demo does this in `game/options.rpy`.

## Desktop Export (Windows / macOS / Linux)

Standard Ren'Py [Build Distributions](https://www.renpy.org/doc/html/build.html) —
no SSPlayer-specific post-steps.

> **⚠️ Each platform needs its own native library** under `game/spritestudio/libs/`:
> `macos/libssruntime.framework`, `windows/x86_64/ssruntime.dll`,
> `linux/x86_64/libssruntime.so`. Ren'Py bundles it and `ssruntime.py` resolves it
> at runtime. Without the library for the platform you build, the package builds
> but SSPlayer throws at load.

`build.name` must be set in your `options.rpy` (the demo does), or the `.app`
won't launch. For distribution, code-sign / notarize per Ren'Py's docs (unsigned
`.dylib`s are Gatekeeper-blocked).

**Optional — pack assets into a `.rpa`:** register the archive *before* your
`**.ssab` / audio classify rules so those assets route into it (build.classify is
first-match-wins); the demo's `options.rpy` shows this with a
`ss_pack_assets_into_rpa` toggle you can follow.

## Android Export

Standard Ren'Py [RAPT](https://www.renpy.org/doc/html/android.html). Set up RAPT
and run **Install SDK**, **Configure** (sets the package name), and **Generate
Keys** once from the launcher GUI (→ Android), per Ren'Py's docs.

> **⚠️ The Brain must be a native library in the APK's `lib/<abi>/` (jniLibs).**
> Android's linker only `dlopen()`s native libs the installer extracted to the
> app's read-only `nativeLibraryDir` (W^X since API 29) — a `.so` under the game
> assets or in app-writable storage will NOT load. `ssruntime.py` loads it by
> soname (`libssruntime.so`) at runtime. Ship one per ABI, under the **NDK ABI
> names**: `libs/android/arm64-v8a/libssruntime.so` (most 64-bit devices),
> `armeabi-v7a/` (old phones), `x86_64/` (emulators).
>
> RAPT has no game-tree hook for native code, so copy each `.so` once, by
> hand, into your Ren'Py SDK's RAPT jniLibs (the same kind of one-time manual
> step iOS needs):
>
> ```
> <renpy-sdk>/rapt/prototype/renpyandroid/src/main/jniLibs/<abi>/libssruntime.so
> ```

You can build either an `.aab` (for Play upload) or an `.apk`.

## iOS Export

Standard Ren'Py [renios](https://www.renpy.org/doc/html/ios.html): it generates an
**Xcode project** (the `.ipa` is built from Xcode). **macOS + Xcode required.**

> **⚠️ The Brain is a *dynamic* `libssruntime.xcframework`, added to the app target
> as "Embed & Sign".** `ssruntime.py` loads it via ctypes `CDLL(None)`, so it must
> be a loaded image; Embed & Sign links it (dyld loads it at launch) and signs it
> into the bundle — the same treatment renios gives `MetalANGLE.xcframework`. A
> *static* xcframework links but gets dead-stripped → `CDLL(None)` fails at
> runtime, so use the dynamic one. Its slices are `.framework` bundles (not bare
> dylibs), so Embed & Sign passes App Store bundle-structure validation.

1. **Generate the Xcode project** — from Ren'Py's launcher (→ iOS → create the
   Xcode project), or the equivalent `<renpy> launcher ios_create . <xcode-project-dir>`
   CLI command.
2. **Embed the Brain, once** — in Xcode: app target → **General** → **Frameworks,
   Libraries, and Embedded Content** → **+** → *Add Files…* →
   `game/spritestudio/libs/ios/libssruntime.xcframework` → **Embed & Sign**. Ren'Py
   has no hook to auto-link third-party native code, so this one manual step is
   unavoidable; it persists across `ios_populate` re-runs.
3. **Build** — pick a **Simulator** and **Run** (no signing), or set your signing
   team and **Product > Archive** for a device `.ipa`.

## Web Export

Standard Ren'Py [Web export](https://www.renpy.org/doc/html/web.html)
(Pyodide/WASM). SSPlayer auto-switches to a non-ctypes JS binding
(`ssruntime_web.py`) — no code changes needed.

> **⚠️ A raw Web export will NOT run.** The renderer needs a separate WASM module
> (`ssruntime.js` / `ssruntime_bg.wasm`) that Ren'Py's exporter doesn't know about,
> so **every export needs the two post-steps below**. Ren'Py regenerates
> `index.html` and repacks `game.zip` on every run, so **re-apply them after each
> export**. Without them the console throws
> `Cannot read properties of undefined (reading 'SSRuntimeContext')`.

After a `web_build` export:

1. **Edit `index.html`** — add this **before** the `<script src="renpy-pre.js">`
   tag so the WASM bindings load before the game starts:
   ```html
   <script type="module">
     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
     window.ssruntime = ss;
     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
   </script>
   ```
2. **Copy the WASM assets as real files** — `ssruntime.js` and `ssruntime_bg.wasm`
   from `game/spritestudio/libs/web/` into the same path in the output (e.g.
   `web_out/game/spritestudio/libs/web/`). The export zips `game/` into `game.zip`,
   so the browser can't `import` them from inside it; the step-1 path must match.

**Testing:** serve over HTTP (not `file://`) with correct MIME types (`.js` →
`application/javascript`, `.wasm` → `application/wasm`) — Ren'Py's own web server
does this. After re-exporting, **unregister the cached service worker / clear site
data**, or the browser serves the old build.
