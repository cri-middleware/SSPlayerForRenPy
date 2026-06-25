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
command -v cargo >/dev/null || { echo "deploy-examples.sh: cargo (Rust) not on PATH" >&2; exit 1; }
CARGO_FLAGS="--release"; [ "$MODE" = "debug" ] && CARGO_FLAGS=""

# --- convert test projects -> game/sprites/<project> ----------------------
convert () { # <sspj-relative-to-sdk> <dest-abs>
  local sspj="$1" dest="$2"
  echo ">> converting $sspj -> ${dest#$ROOT_DIR/}"
  rm -rf "$dest"; mkdir -p "$dest"
  ( cd "$SDK_DIR" && cargo run $CARGO_FLAGS -q -p ssconverter-cli -- "$sspj" -o "$dest" )
}
convert "tests/overall/overall.sspj" "$GAME_DIR/sprites/overall"
convert "tests/Ringo/Ringo.sspj"     "$GAME_DIR/sprites/Ringo"
echo "deploy-examples.sh: done -> game/sprites/{overall,Ringo}/"
