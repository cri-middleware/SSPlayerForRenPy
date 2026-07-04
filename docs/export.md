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

* **Packaging `.ssab`, `.wav` and `.mp3` Files**
   By default during web exports, Ren'Py only includes specific file extensions (like `.png` or `.ogg`) in the output archive (`game.zip`).
   This library already defines `build.classify('**.ssab', 'all')`, `build.classify('**.wav', 'all')` and `build.classify('**.mp3', 'all')` within `spritestudio.rpy`. Because of this, developers do not need to manually edit their `options.rpy`; the necessary assets will automatically be packaged correctly.

## Mobile (Android / iOS) & Desktop

*(To be added later)*
