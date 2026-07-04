#!/usr/bin/env bash
#
# Convert the SpriteStudio test projects into playback data under game/sprites/
# (.ssab + referenced textures, via ssconverter-cli). Ren'Py counterpart of
# SSPlayerForWeb's deploy-examples.
#
# Scope: ONLY the playback data. The native libssruntime binary is the job of
# scripts/build-runtime.{sh,ps1}, not this script.
#   game/sprites/             <- deploy-examples.{sh,ps1}   (this script)
#   game/spritestudio/libs/   <- build-runtime.{sh,ps1}
# Both are gitignored.
#
# Usage: scripts/deploy-examples.sh [release|debug]   (ssconverter-cli build mode; default release)
#
# SDK location: $SSSDK, else ./SpriteStudio-SDK (submodule), else ../SpriteStudio-SDK.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GAME_DIR="$ROOT_DIR/game"

MODE="release"
for arg in "$@"; do
  case "$arg" in
    release|debug) MODE="$arg" ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "deploy-examples.sh: unknown arg '$arg'" >&2; exit 2 ;;
  esac
done

# --- locate the SDK -------------------------------------------------------
SDK_DIR="${SSSDK:-}"
if [ -z "$SDK_DIR" ]; then
  for cand in "$ROOT_DIR/SpriteStudio-SDK" "$ROOT_DIR/../SpriteStudio-SDK"; do
    if [ -f "$cand/Cargo.toml" ]; then SDK_DIR="$(cd "$cand" && pwd)"; break; fi
  done
fi
if [ -z "$SDK_DIR" ] || [ ! -f "$SDK_DIR/Cargo.toml" ]; then
  echo "deploy-examples.sh: SpriteStudio-SDK not found (init the submodule or set SSSDK)" >&2
  exit 1
fi
PYTHON_CMD=""
RENPY_PYTHON_DIR=$(ls -d "$ROOT_DIR/renpy-sdk/lib/py3-"* 2>/dev/null | head -n 1 || true)
if [ -n "$RENPY_PYTHON_DIR" ] && [ -x "$RENPY_PYTHON_DIR/python" ]; then
    PYTHON_CMD="$RENPY_PYTHON_DIR/python"
elif [ -n "$RENPY_PYTHON_DIR" ] && [ -x "$RENPY_PYTHON_DIR/python.exe" ]; then
    PYTHON_CMD="$RENPY_PYTHON_DIR/python.exe"
elif command -v python3 >/dev/null; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null; then
    PYTHON_CMD="python"
else
    echo "deploy-examples.sh: python/python3 not found in renpy-sdk or PATH" >&2; exit 1
fi

# --- convert test projects -> SpriteStudio_Source/ -> game/ss_assets/<project> ---
SOURCE_DIR="$ROOT_DIR/SpriteStudio_Source"
mkdir -p "$SOURCE_DIR"

convert () { # <test-folder-relative-to-sdk> <project-name> <dest-abs>
  local test_folder="$1" project_name="$2" dest="$3"
  echo ">> copying $test_folder to SpriteStudio_Source/$project_name and converting..."
  
  local src_dir="$SDK_DIR/$test_folder"
  local work_dir="$SOURCE_DIR/$project_name"
  
  rm -rf "$work_dir"; mkdir -p "$work_dir"
  cp -R "$src_dir/"* "$work_dir/"
  
  rm -rf "$dest"; mkdir -p "$dest"
  "$PYTHON_CMD" "$ROOT_DIR/tools/cli_convert.py" "$work_dir/$project_name.sspj" "$dest"
}

convert "tests/overall" "overall" "$GAME_DIR/ss_assets/overall"
convert "tests/Ringo" "Ringo" "$GAME_DIR/ss_assets/Ringo"
convert "tests/ParticleEffect" "ParticleEffect" "$GAME_DIR/ss_assets/ParticleEffect"
echo "deploy-examples.sh: done -> game/ss_assets/{overall,Ringo,ParticleEffect}/"
