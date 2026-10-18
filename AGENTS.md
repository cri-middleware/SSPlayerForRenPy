# SSPlayerForRenPy — AI Agent Guide

## Operating rules

*   Keep changes scoped to the requested task. Unrequested hardening is a suggestion, not a commit; a defect
    you actually hit in the code you touched is not — fix it, or say plainly why you did not.
*   Before editing, read enough surrounding context to understand callers and invariants, the ones below
    included.
*   **Anything that exists twice changes twice** — a page and its translation, a `.sh` and its `.ps1`.
    Missing one half is this family's most common defect.
*   **Never break a line between two Japanese characters**; Chrome renders the break as a space.
*   **Finish with this repository's checks**: `scripts/run-tests.sh`, and for docs the both-locale build —
    both in [CONTRIBUTING.md](./CONTRIBUTING.md). Read what a run says it verified, not its exit code —
    several checks pass, or skip themselves, without a prerequisite.
*   **Do not restate what another file owns**; the table below says which file. A fact no file owns goes
    where its staleness will be noticed.
*   **Never commit inside the `SpriteStudio-SDK` submodule.** A core change is an SDK pull request, then a
    submodule bump here.
*   **Playback and rendering semantics are the SDK's**: its [AGENTS.md](./SpriteStudio-SDK/AGENTS.md) and
    the porting guide in `SpriteStudio-SDK/libs/ssruntime/docs/`. Where the guide is silent,
    SSPlayerForWgpu decides. Do not reimplement either.
*   **Code comments never cite the porting guide** (sections, paths, quotes): it moves, and nothing checks
    the citation. Say what breaks instead.

## What this repo is

A creator-facing Ren'Py plugin for **SpriteStudio**, over two native cores from the `SpriteStudio-SDK`
submodule: `libssruntime` (the Brain) emits each frame as a FlatBuffers draw plan, and `libssconverter`
turns `.sspj` into `.ssab`. In `game/spritestudio/`, `SSInternalPlayer` (`python/ss_renpy/player.py`) is
the engine-independent core, and the `SSPlayer` displayable (`spritestudio.rpy`) builds the
`renpy.Render`; the other `*.rpy` are self-contained, dev-gated conveniences.

## Where each answer is written

| Question | File |
|---|---|
| Using it: every API | the [docs site](./docs/en/) |
| Install, convert, first frame, where to read next | [README.md](./README.md), per `SpriteStudio-SDK/MAINTAINING_PLAYERS.md` |
| What is and is not supported | [docs/en/limitations.md](./docs/en/limitations.md), the canonical list |
| Constraints, setup, the demo, tests, the docs site | [CONTRIBUTING.md](./CONTRIBUTING.md) |
| Versions and releases, maintainers only | [RELEASING.md](./RELEASING.md) |
| Plans and non-goals | [ROADMAP.md](./ROADMAP.md) |
| What a script takes | its `--help` |

## Invariants

*   **`docs/` is for creators**: it never cites a development script.
*   **Policy lives in `SSPlayer`, not the core** (sequence chaining, for one); `SSInternalPlayer` reports
    `finished` / `looped` as observations only, and UV normalization lives in the render layer.
*   **Every `python/` module imports in plain CPython, with no `renpy`**; the headless checks depend on it.
*   **The first `SSPlayer` argument is a gamedir-relative `.ssab` path.** Textures and instance sub-packs
    sit beside it, and loading goes through `renpy.loader`, so a pack works loose or inside a `.rpa`.
*   **Every Rust handle is released through `ss_*_destroy`** (the bindings do it in `__del__`); Ren'Py owns
    the textures.
*   **No per-frame allocations in the playback hot path**: consume `FramePlan` / `DrawBatch` directly,
    without building Python objects per frame.
*   **Renaming a property on `SSInternalPlayer` has no compiler to catch it.** It surfaces as an
    `AttributeError` in whichever headless tool still reads the old name, so run the suite after touching
    `game/spritestudio/python/`.
