# 🚀 Setup Guide

This document provides instructions for **Users**. It explains how to integrate the package directly into your game project.
If you want to customize the player, please refer to the [Build Guide](build.md).

## 1. Requirements
- **Ren'Py**: Version 8.x series (Python 3 based) is required.

## 2. Placing the Library
Download the latest package — [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip) (stable link, always the latest release; to pick a specific version, see [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases)). Extract it, and copy the **`spritestudio/`** folder inside it directly into your project's `game/` directory.

> **Internal Structure**: This folder contains all the Python scripts (e.g., `spritestudio.rpy`) and native libraries for each platform (Windows / macOS / Linux, Android, iOS and Web), plus this documentation as Markdown (`README.md`, `docs/`) for the release it came from, readable offline. `spritestudio.rpy` leaves the documentation out of the games you build.

## 3. Placing Playback Data (`.ssab`)
Animation projects (`.sspj`) created in SpriteStudio are played as `.ssab`, the runtime format every SpriteStudio Player reads.

Put the project in `SpriteStudio_Source/`, beside `game/`, and press **Launch Project** in the Ren'Py launcher: the Auto Importer converts it into `game/ss_assets/<project>/` before the game starts.

To convert without Ren'Py running, use **SSConverter GUI** (a desktop app you drop the project onto), **`ssconverter-cli`** (for batch scripts and CI) or **`ssconverter-web`** (in the browser, with nothing to install).

For more details, please refer to **[Asset Import](import.md)**.

The setup is now complete. For how to actually call it in your game, please see [usage.md](usage.md).

## 4. Updating / Removing the Library

**When you update, delete the whole `game/spritestudio/` folder first — never copy a new version over an old one.**

Ren'Py compiles each `.rpy` into a `.rpyc` beside it and keeps running that `.rpyc` even after the `.rpy` is gone. Copying over an old install therefore leaves the previous version's scripts alive next to the new ones, and mixes old native libraries and old generated Python under `python/` with the new ones — the resulting errors are hard to trace back to the update.

1. Delete `game/spritestudio/` from your project.
2. Extract the new `SSPlayerForRenPy.zip` and copy its `spritestudio/` folder into `game/`.
3. Launch your game in developer mode and check the startup log line (or call `ss_diagnostics()` from the console, **Shift+O**) — see [Usage & Control](usage.md).

Your content is untouched by this: converted `.ssab` data (e.g. `game/ss_assets/`) and your `SpriteStudio_Source/` projects live outside this folder.

**To remove the player**, delete `game/spritestudio/` — the folder carries its own packaging rules, so nothing is left behind inside it. Anything you added yourself stays and can be removed when you no longer need it: the `.ssab` classification lines in your `options.rpy` (see [Exporting your Game](export.md)), your converted data, and your `SSPlayer(...)` calls.
