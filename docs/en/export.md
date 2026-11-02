# 📦 Exporting your Game

How to export a game that uses the SpriteStudio Player for Ren'Py. This covers
only the steps this player adds; for the generic build mechanics it links to
Ren'Py's own documentation.

> This page is for **game authors** exporting their own project with the stock
> Ren'Py launcher. If you are working inside this repository (building the demo
> or the native libraries), the developer helper scripts that automate each
> export below are documented in the [Build Guide](development/build.md).

Common to every platform: `game/spritestudio/libs/` already holds the player's
native library for every platform. Ren'Py packages the ones a desktop or Web build needs with
your game; for Android and iOS you place it once by hand, as below. Your
**assets** are your game's own content, so classify them in your own
`options.rpy`: `build.classify('**.ssab', 'all')`, `build.classify('**.ssqb', 'all')`
for sequence packs, and `'**.wav'` / `'**.mp3'` if your animations play SS Audio
events. The Web export in particular drops unknown extensions unless you do.

## Desktop Export (Windows / macOS / Linux)

Standard Ren'Py [Build Distributions](https://www.renpy.org/doc/html/build.html) —
nothing to add for this player. For distribution, code-sign and notarize per
Ren'Py's docs (unsigned `.dylib`s are blocked by Gatekeeper).

**Optional — pack assets into a `.rpa`:** register the archive *before* your
`**.ssab` / audio classify rules, since `build.classify` uses the first rule that
matches:

```renpy
init python:
    build.archive("ssdata", "all")
    build.classify("game/ss_assets/**", "ssdata")
    build.classify('**.ssab', 'all')
    build.classify('**.ssqb', 'all')
```

## Android Export

Standard Ren'Py [RAPT](https://www.renpy.org/doc/html/android.html). Set up RAPT
and run **Install SDK**, **Configure** (sets the package name), and **Generate
Keys** once from the launcher's **Android** screen, per Ren'Py's docs. Then:

1. **Copy the native library into RAPT, once.** Android loads native libraries
   only from the app's own library folder, so copy each ABI's `.so` from
   `game/spritestudio/libs/android/<abi>/libssruntime.so` into your Ren'Py SDK:

   ```
   <renpy-sdk>/rapt/prototype/renpyandroid/src/main/jniLibs/<abi>/libssruntime.so
   ```

   The ABIs are `arm64-v8a` (most 64-bit devices), `armeabi-v7a` (older phones)
   and `x86_64` (emulators).
2. **Build** an `.aab` (for Play upload) or an `.apk`.

## iOS Export

Standard Ren'Py [renios](https://www.renpy.org/doc/html/ios.html): it generates an
**Xcode project** (the `.ipa` is built from Xcode). **macOS + Xcode required.**

1. **Generate the Xcode project** — from Ren'Py's launcher (**iOS** → **Create Xcode
   Project**), or the equivalent `<renpy> launcher ios_create . <xcode-project-dir>`
   CLI command.
2. **Embed the native library, once** — in Xcode: app target → **General** →
   **Frameworks, Libraries, and Embedded Content** → **+** → *Add Files…* →
   `game/spritestudio/libs/ios/libssruntime.xcframework` → **Embed & Sign**. It
   stays through later `ios_populate` runs.
3. **Build** — pick a **Simulator** and **Run** (no signing), or set your signing
   team and **Product > Archive** for a device `.ipa`.

## Web Export

Standard Ren'Py [Web export](https://www.renpy.org/doc/html/web.html) — nothing to
add for this player: the WebAssembly build in `game/spritestudio/libs/web/` ships
inside `game.zip` and loads when the game starts. It uses **WebAssembly SIMD**, so
the target browser must support it — see [Limitations](limitations.md).

**Testing:** serve over HTTP (not `file://`) — Ren'Py's own web server does. After
re-exporting, **unregister the cached service worker / clear site data**, or the
browser serves the old build.
