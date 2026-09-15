# SpriteStudio Player for Ren'Py — AI Agent Guide

A shipping, creator-facing plugin that plays **SpriteStudio** in Ren'Py. Two native cores from the `SpriteStudio-SDK` submodule do the work: `libssruntime` (the "Brain") computes each frame as a FlatBuffers draw plan over a C-API, and `libssconverter` turns a `.sspj` project into a runtime `.ssab` pack. This repo is the Ren'Py layer and the creator ergonomics around them.

## Operating rules

*   Keep changes scoped to the request; do not commit unless asked.
*   Read enough context (callers, invariants) before editing; if a read was truncated, read the rest first. Match the style of touched files.
*   **Ren'Py is an external dependency** (`renpy-sdk/`) — do not patch it. Use its public API and the `SS_*` environment knobs.
*   **Consumer model:** the drop-in `game/spritestudio/` has to work with no `scripts/`, no `tools/` and no SDK, under the stock launcher. Judge creator-facing changes from that side, and keep `docs/` user-facing — never cite a dev script there.
*   **Brain / render work: read `SpriteStudio-SDK/AGENTS.md` first**, then the porting guide under `SpriteStudio-SDK/libs/ssruntime/docs/` (numbered dirs, EN `.md` + JA `.ja.md`, indexed by `README.md`). Reference ports: `SSPlayerForGodot` (closest — source of the `ss-*` shaders and the coverage-bitmap mask) and `SSPlayerForWeb` (`GeometryBuilder.ts` is the render math).
*   Priorities: asset import (`.sspj → .ssab`), creator ergonomics, export (desktop / Android / iOS / Web + `.rpa`), docs — then render internals, which are mature and bug-fix territory.

## Architecture

Three layers under `game/spritestudio/`. `python/ss_renpy/ssruntime.py` routes to `ssruntime_native.py` (ctypes FFI to the Brain) or `ssruntime_web.py` (Pyodide, `sys.platform == "emscripten"`). `player.py`'s `SSInternalPlayer` is the engine-independent core: it plays ONE animation via `update(dt_ms) → FramePlan` and reports `finished` / `looped` as observations only. The `SSPlayer` displayable (`spritestudio.rpy`) builds the `renpy.Render` and owns policy — sequence chaining, image attributes, callbacks, resource injection.

The sibling `*.rpy` are the drop-in ergonomics, each self-contained, dev-gated and droppable: `ss_character.rpy` (`SSCharacter`, a one-line talking sprite), `ss_helpers.rpy` (`ss_play_once` / `ss_duration`), `ss_browser.rpy` (Asset Browser, `Shift+B`), `ss_diagnostics.rpy`, and `auto_importer.rpy` (dev-only: `SpriteStudio_Source/` → `game/ss_assets/` through `ss_renpy/converter.py` → `libssconverter`). `ssab_meta.py` parses the static `.ssab` metadata the Brain does not surface; `resolver.py` is the zero-config pack index.

| Path | Role | Ships to creators? |
|---|---|---|
| `game/spritestudio/python/ss_renpy/` | Engine-independent playback + import core. | yes |
| `game/spritestudio/*.rpy` | `SSPlayer` displayable + drop-in ergonomics. | yes |
| `game/spritestudio/{libs/<platform>,python/{ss,flatbuffers}}` | Native libs + FlatBuffers bindings. | yes |
| `game/*.rpy`, `game/tl/` | Demo game + JA translation. | no |
| `docs/`, `mkdocs*.yml`, `overrides/` | Bilingual user docs. | no |
| `scripts/`, `tools/` | Build / deploy wrappers; headless tests + utilities. | no |
| `SpriteStudio-SDK/` | Submodule: both cores + the porting guide. | no |

## Hard constraints

*   **Policy lives in `SSPlayer`, not the core** (sequence chaining), and UV normalization lives in the render layer. Every `python/` module must import in plain CPython with no `renpy` — the headless tools depend on it.
*   The first `SSPlayer` argument is a gamedir-relative `.ssab` path; textures and instance sub-packs sit beside it, and loading goes through `renpy.loader`, so it works loose or inside a `.rpa`.
*   **FFI:** release every Rust handle via `ss_*_destroy` (the bindings do it on `__del__`). Textures are the exception — Ren'Py owns them.
*   **Hot path:** no per-frame Python allocations; consume `FramePlan` / `DrawBatch` directly. `_prewarm_textures` staggers uploads, `SS_PROFILE=1` logs the split.
*   **Coordinates:** use `ss_runtime_set_coordinate_system`; never add a second Y-flip.
*   **Versions:** `ss_renpy.__version__` (`game/spritestudio/python/ss_renpy/__init__.py`, PEP 440, e.g. `7.0.0b1`) is the package version and the single source of truth — it ships inside the folder creators get, and the release reads it for the tag and the zip name. It is independent of the SDK. `scripts/SDK_VERSION.txt` and `scripts/RENPY_VERSION.txt` pin the other two, and `libs/<platform>/` must match the SDK pin (bump → re-run `download-sdk`, often `generate-runtime-code`).
*   **Scripts** are `scripts/*.sh` with `.ps1` twins, `key=value` options and `--help`: `build-runtime` / `download-sdk`, `download-flatbuffers` + `generate-runtime-code`, `deploy-examples`, `run-demo`, `run-tests`, `fetch-renpy-*`, `deploy-{desktop,android,ios,web}` (iOS is POSIX-only), `prepare-docs` / `build-docs` / `build-pages`, `build-release` / `release-version`.

## Documentation site

`docs/` is a bilingual [Zensical](https://zensical.org) site ordered `setup → import → usage → export` (plus `build` and `limitations`). `limitations.md` is the canonical supported / unsupported list. Every page exists as both `docs/en/<path>` and `docs/ja/<path>`; there is no fallback locale, so a page missing from one side is a nav entry pointing at nothing.

Each locale builds from its own config — `mkdocs.yml` → `site/`, `mkdocs.ja.yml` → `site/ja/`, both inheriting `mkdocs.base.yml`. **A YAML sequence must be defined in exactly one of the three files:** Zensical's `INHERIT` *concatenates* sequences where MkDocs replaces them, so a `nav` in the base as well as a locale config renders the English navigation followed by the Japanese one. Shared sequences (`theme.palette`, `theme.features`, `plugins`, `markdown_extensions`, `extra.alternate`, `extra_css`) live in the base and nowhere else; `nav` and `extra.social` live in the locale configs and never in the base. What is not simply written twice:

*   **`overrides/main.html`** (`theme.custom_dir`) emits the Open Graph / Twitter Card tags the theme omits, and repairs the page title: Zensical never sets `page.is_homepage`, which its own `base.html` branches on, so the landing page would title itself twice over. One template serves both locales — localize through a per-locale config value, never a branch in the template — and it is kept in sync with the copies in SpriteStudio-Docs and the sibling players, `twitter:site` included.
*   **`overrides/partials/alternate.html`** rebuilds the header language selector so switching language keeps the reader on the same page, driven by `extra.alternate[].link` (a locale subpath, not a URL) plus `extra.site_root_prefix`. Known gap: the `<link rel="alternate" hreflang>` tags in `<head>` still point at each locale root — they sit inside the theme's `site_meta` block, and overriding that means copying thirty lines Zensical may change.
*   **`site_url` is per locale**, the ja one keeping its `ja/` suffix — `page.canonical_url`, and therefore `og:url`, is built from it. Each locale also owns its `assets/`: a shared `docs/assets/` would sit outside both `docs_dir`s.
*   **Asset paths are source-relative** (`assets/…` from these top-level pages) and identical in both locales, raw `<video>` / `<img>` `src` included — Zensical resolves those the same way it resolves a Markdown link.
*   **The demo link on `index.md` is the one path that differs** — `demo/` in English, `../demo/` in Japanese, the English pages sitting at the site root and the Japanese ones a level down. It is site-relative on purpose: `site/demo/` is not a page of this site, and an absolute URL would be wrong in a local `serve=yes` preview and on a fork's Pages. `--strict` passes because neither href resolves to a documentation page. The READMEs keep the absolute URL — GitHub has no site for a relative one to resolve against.
*   **Footer social icons are defined twice**, in `mkdocs.yml` and `mkdocs.ja.yml` (translated labels, same icons and links). Add or reorder an icon in both, or the footers diverge.
*   **There is deliberately no `edit_uri`**, so no "edit this page" button renders: it is a branch name nothing validates, and it had drifted wrong in three of the five player repos. Do not reintroduce it.
*   **Callouts** are parsed natively: a list inside a `> [!NOTE]` block needs a blank `>` line before it or it renders as literal text, and `[!IMPORTANT]` is not a built-in admonition type — `docs/*/stylesheets/extra.css` styles it. Also avoid `src="…"` / `href="…"` inside an inline code span, which Zensical rewrites as if it were a real link; use a fenced block, which it leaves alone.

`mkdocs.base.yml` sets `strict: true`, so a broken link fails the build. `serve` validates nothing, and nothing builds the docs on a pull request (`pages.yml` runs on `release: published` and dispatch), so the local build is the only gate — and **both locales have to be built**, English first because it clears `site/`, which contains `site/ja`. Building only English is the easy mistake: it leaves a stale `site/ja` behind, so a Japanese page you just broke still looks fine.

```bash
scripts/prepare-docs.sh              # once: .venv + the pins in docs/requirements.txt
scripts/build-docs.sh                # the gate: English then Japanese, both --strict
scripts/build-pages.sh serve=yes     # + the released Web demo -> http://localhost:8000/
```

`build-pages.sh` is the whole published site, and `pages.yml`'s build job **is** this script (`prepare=no docs=yes demo=download tag=…`, every option spelled out so a publish cannot change because a default did). `demo=download` needs `gh` and a Release carrying `SSPlayerForRenPy-web-demo.zip`; `zip=<path>` feeds one by hand, and `demo=build` runs the export here instead — the only option until that first Release exists. `sdk=` picks `download-sdk` or `build-runtime` and is consulted for `demo=build` only, since a downloaded demo brings its own runtime. An existing `renpy-sdk/` is never re-fetched. Note `game/options.rpy` excludes `site/**`: the docs build copies the screencasts into `site/*/assets/`, and Ren'Py classifies `**.webm` into every package.

## Verification

Every engine-independent layer has a headless `tools/` check in plain CPython. **GL2 rendering** (PMA, mesh, blend, mask, `ss-*` GLSL) has no headless check — sign it off in a GUI run, via `Shift+B` or `scripts/run-demo.*`.

| Layer | Tools |
|---|---|
| Playback core, events (`player.py`, `events.py`) | `verify_internal_player`, `verify_events` |
| Geometry / mesh / PartColor (`framedata.py`) | `verify_m2`, `verify_mesh` |
| Instance / effect / shape, slot stepping | `verify_instance`, `verify_effect`, `verify_shape`, `verify_hidden` |
| Mask, clipping (`mask.py`) | `verify_mask` |
| Part overrides, skinned-part query, user shaders | `verify_override`, `verify_skinned`, `verify_shader` |
| `.ssab` identifier gate, resolver, snippet, smoke | `verify_ssab_guard`, `verify_resolver`, `verify_snippet`, `m0_smoke` |
| The test doubles themselves, against production call sites | `verify_doubles` |

**Run them through `scripts/run-tests.sh`** (`only=mask,events`, `skip=`, `list=yes`, `verbose=yes`), because a bare loop over the tools reports green on a tree where nothing loaded. Both prerequisites are gitignored, so a fresh clone has neither — `game/spritestudio/libs/` (`build-runtime` / `download-sdk`) and `game/ss_assets/` (`deploy-examples`) — and a tool that cannot find its pack prints `SKIP` and **exits 0**. The runner checks both up front, refuses to start a partial suite, and treats a `SKIP` that survives that preflight as a failure. Sub-case skips ("this part does not draw in this animation") are counted beside the `PASS`, not failed. Nothing runs the suite on a pull request, and `release.yml`'s dispatch-only test job loops over the tools itself rather than calling the runner, so this is the gate: run it after touching anything under `game/spritestudio/python/`. Renaming a property on `SSInternalPlayer` is the case to watch — no compiler catches the call sites, so it surfaces only as an `AttributeError` from whichever tool still reads the old name. Lint with `renpy-sdk/renpy.sh . lint`.

Outside the suite: `tools/analyze.py` (DrawBatchKind audit), `cli_convert.py` (shell `.sspj → .ssab`), `ss_stamp_import.py` (stamp the auto-importer marker over an out-of-band pack), and `render_png.py` / `render_mask_png.py` (software raster, not GL2 — the only two that need Pillow). **Not rendered:** Text / NineSlice, animation blending, nested Instance / Effect timeline events. **Audio** is played by `SSPlayer` (`sfx` mixer, round-robin, `ss_stop_audio`; muted in reverse). See `docs/*/limitations.md`.

## Releases

A release is a tag, pushed first and built second: push `v$__version__`, then dispatch **Release** from that tag with `upload_release=true`. The tag names the Release, and `upload_release=true` from anything else fails the run rather than silently producing none; the default dispatch (`upload_release=false`) is a QA build and creates no Release. What comes out is a draft — a human reviews the assets and the generated notes and publishes from the UI. A beta is still published as the *latest* release, since `releases/latest/download/…` is the link the README and the docs hand out, and that only resolves for a non-prerelease.

`scripts/build-release.sh` is the release — `release.yml`'s job **is** this script (`sdk=download demo=build out=release-dist verify=yes clean=yes`, every option spelled out so a release cannot change because a default did), so CI and a local run cannot drift. It produces the version-pinned plugin zip and Web demo zip, a version-less alias of each, and `SHA256SUMS` over all four.

```bash
scripts/build-release.sh              # both assets
scripts/build-release.sh demo=skip    # the plugin zip only, much faster
```

`demo=skip` is for iterating on the plugin zip, never for a release: `pages.yml` publishes the playable demo by downloading it off the Release, so a release without it leaves the site on the previous one. The `.ps1` twin produces a byte-identical archive from the same inputs, and both need `zip` on PATH — `Compress-Archive` cannot store symlinks at all.

Two checks earn their place. The tag must agree with `ss_renpy.__version__` — a Release called `v1.2.3` carrying `SSPlayerForRenPy-1.2.4.zip` is worse than no release. And **the macOS framework must still be a bundle**: `libs/macos/libssruntime.framework` is versioned, its `Versions/Current` and bundle-root aliases are symlinks, and `zip` follows symlinks unless given `-y`. Flattening them invalidates the code signature (`codesign --verify` → "bundle format is ambiguous"), so a game bundling the extracted framework can no longer be signed or notarised. Consumers get that framework only through this zip, and the working tree here always has the real symlinks, so a flattened bundle would ship unnoticed. The script unpacks the finished archive and asserts they survived.
