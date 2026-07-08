# Setup Guide

This document provides instructions for **Users**. It explains how to integrate the package directly into your game project.
If you want to customize the player, please refer to the [Build Guide](build.md).

## 1. Requirements
- **Ren'Py**: Version 8.x series (Python 3 based) is required.

## 2. Placing the Library
Download the latest package — [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip) (stable link, always the latest release; to pick a specific version, see [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases)). Extract it, and copy the **`spritestudio/`** folder inside it directly into your project's `game/` directory.

> **Internal Structure**: This folder contains all the Python scripts (e.g., `spritestudio.rpy`) and native libraries for each OS (Windows / macOS / Linux).

## 3. Placing Playback Data (`.ssab`)
Animation projects (`.sspj`) created in SpriteStudio must be converted to Ren'Py format (`.ssab`) before placement.

There are two ways to convert them. Choose according to your project's development style:
- **Auto Importer:** An easy way that automatically converts data when Ren'Py starts up.
- **CLI Convert:** A way to convert in bulk using external batch scripts or CI.

For more details, please refer to **[Asset Import](import.md)**.

The setup is now complete. For how to actually call it in your game, please see [usage.md](usage.md).
