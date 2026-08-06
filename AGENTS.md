# SpriteStudio Player for Ren'Py — AI Agent Guide

A **shipping, creator-facing plugin** that plays **SpriteStudio 7** in Ren'Py. Two
native cores from the `SpriteStudio-SDK` submodule do the work: `libssruntime` (the
"Brain") computes each frame as a FlatBuffers draw plan over a C-API; `libssconverter`
turns a `.sspj` project into a runtime `.ssab` pack. This repo is the Ren'Py layer +
creator ergonomics around them. This file is the map; detail lives in code docstrings,
the tests (§5), the docs (§4), and the SDK porting guide (§6).

## 1. Operating rules
- Keep changes scoped to the request; don't commit unless asked.
- Read enough context (callers, invariants) before editing; if a read was truncated,
  read the rest first. Match the style of touched files.
- **Ren'Py** is an external dependency (`renpy-sdk/`) — don't patch it; use its public
  API and the `SS_*` knobs.
- **SDK alignment:** when modifying core playback logic, refer to
  `SpriteStudio-SDK/AGENTS.md` for Rust runtime constraints.
- **Consumer model:** the drop-in `game/spritestudio/` must work without
  `scripts/`/`tools/`/SDK and under the stock launcher — judge creator-facing changes
  from that side (§2), and keep user docs (§4) user-facing.

## 2. Layout & priorities
Dev + demo project; only the drop-in **`game/spritestudio/`** ships to creators (pasted
into a stock Ren'Py project — no `scripts/`, SDK, or build). Priorities: (a) asset
import (`.sspj → .ssab`), (b) creator ergonomics, (c) export (desktop/Android/iOS/Web
+ `.rpa`), (d) docs, then (e) render internals (mature, bug-fix territory).

| Path | Role | Ships? |
|---|---|---|
| `game/spritestudio/python/ss_renpy/` | Engine-independent playback + import core (§3). | yes |
| `game/spritestudio/*.rpy` | `SSPlayer` displayable + drop-in ergonomics (§3). | yes |
| `game/spritestudio/{libs/<platform>,python/{ss,flatbuffers}}` | Native libs + FlatBuffers bindings. | yes |
| `game/*.rpy`, `game/tl/` | Demo game + JA translation. | no |
| `docs/`, `mkdocs*.yml` | Bilingual user docs (§4). | no |
| `scripts/`, `tools/` | Build/deploy wrappers (§3); headless tests + utils (§5). | no |
| `SpriteStudio-SDK/` | Submodule: both cores + porting guide (§6). | no |
| `game/spritestudio/python/ss_renpy/__init__.py` (`__version__`), `scripts/SDK_VERSION.txt`, `scripts/RENPY_VERSION.txt` | Pin package-release / SDK / Ren'Py versions (§3). | no |

## 3. Architecture & constraints
**3-layer stack** (under `game/spritestudio/`): `python/ss_renpy/ssruntime.py` routes to
`ssruntime_native.py` (ctypes FFI to the Brain) or `ssruntime_web.py` (Pyodide,
`sys.platform=="emscripten"`); `player.py`'s `SSInternalPlayer` is the engine-independent
core (plays ONE animation via `update(dt_ms)→FramePlan`, reports `finished`/`looped` as
observations only); the `SSPlayer` displayable (`spritestudio.rpy`) builds `renpy.Render`
and owns policy (sequence chaining, image attributes, callbacks, resource injection).

**Drop-in ergonomics** — sibling `*.rpy`, each self-contained/dev-gated/droppable:
`ss_character.rpy` (`SSCharacter` one-line talking sprite), `ss_helpers.rpy`
(`ss_play_once`/`ss_duration`), `ss_browser.rpy` (Asset Browser, `Shift+B`),
`ss_diagnostics.rpy`, `auto_importer.rpy` (dev-only: `SpriteStudio_Source/` →
`game/ss_assets/` via `ss_renpy/converter.py` → `libssconverter`). `ssab_meta.py` parses
static `.ssab` metadata the Brain doesn't surface; `resolver.py` = zero-config pack index.

**Invariants & constraints:**
- Policy (sequence chaining) lives in `SSPlayer`, not the core; UV normalization lives in
  the render layer. Every `python/` module must import in plain CPython (no `renpy`).
- First `SSPlayer` arg = gamedir-relative `.ssab` path; textures + instance sub-packs
  co-located; loading via `renpy.loader` (works loose or in `.rpa`).
- `ss_renpy.__version__` (in `game/spritestudio/python/ss_renpy/__init__.py`) is the package
  version — the single source of truth, shipped inside the distributed `spritestudio/` folder and
  read by the release workflow for the tag and zip name (independent of the SDK; PEP 440 form, e.g.
  `7.0.0b1`). `scripts/SDK_VERSION.txt` / `scripts/RENPY_VERSION.txt`
  pin versions; `libs/<platform>/` must match `scripts/SDK_VERSION.txt` (bump → re-run `download-sdk`,
  often `generate-runtime-code`).
- **FFI:** release every Rust handle via `ss_*_destroy` (bindings do it on `__del__`);
  textures are the exception — Ren'Py owns them.
- **Hot path:** no per-frame Python allocs; consume `FramePlan`/`DrawBatch` directly;
  `_prewarm_textures` staggers uploads; `SS_PROFILE=1` logs the split.
- **Coordinates:** use `ss_context_set_coordinate_system`; don't add a second Y-flip.
- **Scripts** (`scripts/`, `*.sh`/`*.ps1`): `build-runtime`/`download-sdk`,
  `download-flatbuffers`+`generate-runtime-code`, `deploy-examples`, `run-demo`,
  `fetch-renpy-*`, `deploy-{desktop,android,ios,web}`.

## 4. Docs
`docs/` = [Zensical](https://zensical.org) bilingual, ordered `setup → import → usage →
export` (+ `build`/`limitations` for devs). **User-facing** — don't cite dev scripts.
`limitations.md` is the canonical supported/unsupported list; keep `en/`/`ja/` in sync.

Zensical has no multi-locale build, so **each locale is built from its own config**:
`mkdocs.yml` builds `docs/en` to `site/`, `mkdocs.ja.yml` builds `docs/ja` to `site/ja/`,
and both inherit the shared settings from `mkdocs.base.yml`. There is no fallback locale
any more, so a page missing from one side is a nav entry pointing at nothing. Each locale
also owns its `assets/` — there is no shared `docs/assets/`, it would sit outside both
`docs_dir`s — which is why the paths are now identical in both languages rather than the
`ja/` side needing an extra `../`.

**The three-config split has one rule: a YAML sequence must be defined in exactly one of
the three files.** Zensical's `INHERIT` *concatenates* parent and child sequences where
MkDocs replaces them — put `nav` in the base as well as a locale config and the Japanese
site renders the English navigation followed by the Japanese one. Shared sequences
(`theme.palette`, `theme.features`, `plugins`, `markdown_extensions`, `extra.alternate`,
`extra_css`) live in `mkdocs.base.yml` and nowhere else; `nav` and `extra.social` live in
the locale configs and never in the base.

Things that do **not** follow the "everything twice" rule, or that changed with the
migration — check before duplicating:

*   **`overrides/main.html`** (`theme.custom_dir`) emits the Open Graph / Twitter Card tags the theme omits, **and repairs the page title**: Zensical never sets `page.is_homepage`, which its own `base.html` branches on, so the landing page would title itself "SpriteStudio Player for Ren'Py - SpriteStudio Player for Ren'Py". The override derives the flag from `page.url` and overrides the `htmltitle` block. **One template serves both locales** — everything is read from whichever locale config is building. Localize by adding a per-locale config override, never by branching in the template. Keep it in sync with the copies in SpriteStudio-Docs and the sibling player repos.
*   **`overrides/partials/alternate.html`** rebuilds the header language selector so switching language keeps you on the same page. `mkdocs-static-i18n` used to rewrite those links per page; nothing does once the locales are separate builds, and the stock partial would send every reader to the other locale's home page. Driven by `extra.alternate[].link` (a locale subpath, not a URL) plus `extra.site_root_prefix` in each locale config. Known gap: the `<link rel="alternate" hreflang>` tags in `<head>` still point at each locale root — they sit inside the theme's `site_meta` block, and overriding that would mean copying thirty lines Zensical may change.
*   **`site_url` is per locale** and the ja one keeps its `ja/` suffix — `page.canonical_url`, and therefore `og:url`, is built from it.
*   **Asset paths are source-relative** (`assets/…` from these top-level pages), including inside raw `<video>` / `<img>` HTML. Zensical resolves raw HTML `src` the same way it resolves Markdown links; MkDocs passed it through untouched. That difference is the one place where a MkDocs fallback build produces wrong output.
*   **Footer social icons are defined twice** — in `mkdocs.yml` and `mkdocs.ja.yml` (translated labels, same icons and links). Add or reorder an icon in both, or the two footers diverge. Keep `twitter:site` in `overrides/main.html` in sync with the X link.
*   **There is deliberately no `edit_uri`**, so no "edit this page" button renders. It is a branch name nothing validates, and it had drifted wrong in three of the five player repos. Do not reintroduce it.

`mkdocs.base.yml` sets `strict: true`, so a plain `build` fails on a broken link. `serve` validates nothing — `zensical serve --strict` is accepted and currently does nothing. Nothing builds the docs on a pull request either (`pages.yml` runs on `release: published` and dispatch), so the local build is the only gate, and **both locales have to be built** — English first, because it clears `site/`, which contains `site/ja`:

```bash
.venv/bin/zensical build --strict
.venv/bin/zensical build -f mkdocs.ja.yml --strict
```

Building only English is the easy mistake: it leaves a stale `site/ja` behind, so a Japanese page you just broke still looks fine.

Two things to know about callouts, which Zensical parses natively now that `mkdocs-callouts` is gone: a list inside a `> [!NOTE]` block needs a blank `>` line before it or it renders as literal text, and `[!IMPORTANT]` is not a built-in admonition type — `docs/*/stylesheets/extra.css` styles it to keep the appearance it had. Also **avoid `src="…"` / `href="…"` inside an inline code span**: Zensical rewrites paths there as if they were real links, corrupting the example. Use a fenced block, which it leaves alone.

## 5. Verification
Each engine-independent layer has a headless `tools/` test (plain CPython); **GL2
rendering** (PMA, mesh, blend, mask, `ss-*` GLSL) needs a GUI run — sign off via
`Shift+B` or `scripts/run-demo.*`. Run all:
`for t in tools/verify_*.py tools/m0_smoke.py; do python3 "$t"; done`.

| Layer | Where | Test |
|---|---|---|
| Playback core + events | `player.py`, `events.py` | `verify_internal_player`, `verify_events` |
| Geometry/Mesh + PartColor | `framedata.py` | `verify_m2`, `verify_mesh` |
| Instance / Effect / Shape | `instance.py`, `effect*.py`, `framedata.py` | `verify_instance`, `verify_effect`, `verify_shape` |
| Mask / clipping | `mask.py` | `verify_mask` |
| Part overrides (colour/cell/visibility) | `player.py`, `ssruntime_*.py` | `verify_override` |
| User shaders (SS6 `ss-*`) | `framedata.read_shader` | `verify_shader` |
| Resolver / snippet / smoke | `resolver.py`, `snippet.py` | `verify_resolver`, `verify_snippet`, `m0_smoke` |

Also: `tools/analyze.py` (DrawBatchKind audit), `cli_convert.py` (shell `.sspj→.ssab`),
`render_png.py`/`render_mask_png.py` (software raster, not GL2). Lint:
`renpy-sdk/renpy.sh . lint`. **Not rendered:** Text/NineSlice; animation blend; nested
Instance/Effect timeline events. **Audio** is played by `SSPlayer` (`sfx` mixer,
round-robin, `ss_stop_audio`; reverse muted). See `docs/*/limitations.md`.

## 6. Porting guide (READ FIRST for Brain / render work)
Start at **`SpriteStudio-SDK/AGENTS.md`**, then the porting guide under
`SpriteStudio-SDK/libs/ssruntime/docs/` — numbered dirs (`10_introduction` …
`60_tooling`), EN `.md` + JA `.ja.md`, indexed by `README.md`. **Reference ports:**
`SSPlayerForGodot` (closest; source of the `ss-*` shaders + coverage-bitmap mask) and
`SSPlayerForWeb` (`GeometryBuilder.ts` = render math).
