# SpriteStudio Player for Ren'Py — AI Agent Guide

A shipping, creator-facing plugin that plays **SpriteStudio** in Ren'Py. Two native cores from the
`SpriteStudio-SDK` submodule do the work: `libssruntime` (the "Brain") computes each frame as a
FlatBuffers draw plan over a C-API, and `libssconverter` turns a `.sspj` project into a runtime
`.ssab` pack. This repository is the Ren'Py layer and the creator ergonomics around them.

## Operating rules

*   Keep changes scoped to the request; do not commit, push or open PRs unless asked.
*   Read enough context (callers, invariants) before editing; if a read was truncated, read the
    rest first. Match the style of the file you touch.
*   Validate with `scripts/run-tests.sh` and, for docs, the both-locale build — see
    [CONTRIBUTING.md](./CONTRIBUTING.md). Nothing runs either on a pull request.
*   **Ren'Py is an external dependency** (`renpy-sdk/`) — do not patch it. Use its public API and
    the `SS_*` environment knobs.
*   **Brain and render work: read [the SDK's AGENTS.md](./SpriteStudio-SDK/AGENTS.md) first**, then
    the porting guide under `SpriteStudio-SDK/libs/ssruntime/docs/`. The reference ports are
    SSPlayerForGodot (closest — source of the `ss-*` shaders and the coverage-bitmap mask) and
    SSPlayerForWeb (`GeometryBuilder.ts` is the render math).

## What this repo is

Three layers under `game/spritestudio/`. `python/ss_renpy/ssruntime.py` routes to
`ssruntime_native.py` (ctypes FFI to the Brain) or `ssruntime_web.py` (Pyodide). `player.py`'s
`SSInternalPlayer` is the engine-independent core: it plays one animation through
`update(dt_ms) → FramePlan` and reports `finished` / `looped` as observations only. The `SSPlayer`
displayable in `spritestudio.rpy` builds the `renpy.Render` and owns policy — sequence chaining,
image attributes, callbacks, resource injection. The sibling `*.rpy` are the drop-in ergonomics,
each self-contained and dev-gated.

| Path | Role | Ships to creators? |
|---|---|---|
| `game/spritestudio/python/ss_renpy/` | Engine-independent playback and import core. | yes |
| `game/spritestudio/*.rpy` | The `SSPlayer` displayable and the drop-in ergonomics. | yes |
| `game/spritestudio/{libs/<platform>,python/{ss,flatbuffers}}` | Native libs and FlatBuffers bindings. | yes |
| `game/*.rpy`, `game/tl/` | Demo game and its JA translation. | no |
| `docs/`, `mkdocs*.yml`, `overrides/` | The bilingual user documentation. | no |
| `scripts/`, `tools/` | Build and deploy wrappers; headless checks and utilities. | no |

## Where each answer is written

| Question | File |
|---|---|
| What the plugin does, and how a creator uses it | [README.md](./README.md), the [docs site](./docs/en/) |
| What is supported and what is not | [docs/en/limitations.md](./docs/en/limitations.md), the canonical list |
| How to set up, run the demo, test and document | [CONTRIBUTING.md](./CONTRIBUTING.md) |
| How the site is built and a release is cut | [RELEASING.md](./RELEASING.md), maintainers only |
| What to build next, and what is out of scope | [ROADMAP.md](./ROADMAP.md) |
| What each script does and takes | that script's `--help` |

Do not restate those here. This file is for what an agent would otherwise break silently.

## Invariants

*   **The consumer gets `game/spritestudio/` and nothing else.** It has to work with no `scripts/`,
    no `tools/` and no SDK, under the stock launcher. Judge every creator-facing change from that
    side, and keep `docs/` user-facing — never cite a dev script there.
*   **Policy lives in `SSPlayer`, not the core** (sequence chaining is the example), and UV
    normalization lives in the render layer. **Every `python/` module must import in plain CPython
    with no `renpy`** — the headless checks depend on it.
*   **The first `SSPlayer` argument is a gamedir-relative `.ssab` path**; textures and instance
    sub-packs sit beside it, and loading goes through `renpy.loader`, so it works loose or inside
    a `.rpa`.
*   **Release every Rust handle** via `ss_*_destroy` (the bindings do it on `__del__`). Textures
    are the exception — Ren'Py owns them.
*   **No per-frame Python allocations.** Consume `FramePlan` / `DrawBatch` directly.
    `_prewarm_textures` staggers uploads and `SS_PROFILE=1` logs the split.
*   **Use `ss_runtime_set_coordinate_system`; never add a second Y-flip.**
*   **`ss_renpy.__version__` is the single source of truth** for the package version (PEP 440, in
    `game/spritestudio/python/ss_renpy/__init__.py`). It ships inside the folder creators get and
    is independent of the SDK. `scripts/SDK_VERSION.txt` and `scripts/RENPY_VERSION.txt` pin the
    other two, and `libs/<platform>/` must match the SDK pin — bumping it means re-running
    `download-sdk`, and often `generate-fbs-code`.
*   **Renaming a property on `SSInternalPlayer` has no compiler to catch the call sites.** It
    surfaces only as an `AttributeError` from whichever headless tool still reads the old name, so
    run the suite after touching anything under `game/spritestudio/python/`.
*   **Not rendered**, and not to be presented as working: Text and NineSlice parts, animation
    blending, and nested Instance / Effect timeline events. Audio is played by `SSPlayer` on the
    `sfx` mixer, round-robin, and is muted in reverse.
