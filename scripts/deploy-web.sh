#!/usr/bin/env bash
#
# Build the Ren'Py Web export of this project, with the stock exporter and
# nothing applied afterwards: the Brain's wasm module ships inside game.zip and
# SSPlayer loads it from there at startup, so the export plays as it comes out.
#
# Prereqs: Ren'Py SDK in renpy-sdk/ (fetch-renpy-sdk.sh) with Web support
# (fetch-renpy-web.sh), and the web runtime under game/spritestudio/libs/web/
# (download-sdk.sh / build-runtime.sh).
#
# Usage: scripts/deploy-web.sh [dest_dir]
#   dest_dir : output folder (default: web_out)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RENPY_SDK="$ROOT_DIR/renpy-sdk"
LAUNCHER="$RENPY_SDK/launcher"
WEB_ASSETS="$ROOT_DIR/game/spritestudio/libs/web"

DEST="${1:-web_out}"
case "$DEST" in -h|--help|help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;; esac
case "$DEST" in /*) : ;; *) DEST="$ROOT_DIR/$DEST" ;; esac   # absolutise

# --- prerequisites --------------------------------------------------------
[ -x "$RENPY_SDK/renpy.sh" ] || { echo "deploy-web.sh: renpy-sdk/ not found — run scripts/fetch-renpy-sdk.sh first." >&2; exit 1; }
[ -d "$RENPY_SDK/web" ]      || { echo "deploy-web.sh: Ren'Py Web support not found — run scripts/fetch-renpy-web.sh first." >&2; exit 1; }
[ -f "$WEB_ASSETS/ssruntime.js" ] && [ -f "$WEB_ASSETS/ssruntime_bg.wasm" ] || {
  echo "deploy-web.sh: web runtime missing under game/spritestudio/libs/web/ — run scripts/download-sdk.sh first." >&2; exit 1; }

# --- run the Web export ----------------------------------------------------
echo ">> building Web export -> $DEST"
"$RENPY_SDK/renpy.sh" "$LAUNCHER" web_build "$ROOT_DIR" --dest "$DEST"

[ -f "$DEST/index.html" ] || { echo "deploy-web.sh: export did not produce $DEST/index.html" >&2; exit 1; }

echo "deploy-web.sh: done -> $DEST"
echo "  Serve it over HTTP (not file://), as any Ren'Py Web export."
