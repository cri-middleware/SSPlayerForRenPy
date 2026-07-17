#!/usr/bin/env bash
#
# Build a runnable desktop distribution of the SSPlayer demo for the HOST OS,
# using Ren'Py's standard "Build Distributions". Unlike the Web target, the
# desktop target needs NO post-export steps: the native "Brain" library under
# game/spritestudio/libs/ is bundled automatically and resolved at runtime.
#
# This .sh handles the Unix desktops; for a Windows .exe run deploy-desktop.ps1:
#   macOS (Darwin) -> mac package   -> an unpacked, double-clickable <name>.app
#   Linux          -> linux package -> an unpacked <name>-linux-x86_64/ folder
#                                       (run its <name>.sh)
#
# The native library for the host platform must be present under
# game/spritestudio/libs/ first (macos/libssruntime.framework on macOS,
# linux/x86_64/libssruntime.so on Linux) — get it with
# scripts/download-sdk.sh (prebuilt) or scripts/build-runtime.sh
# (from source).
#
# Usage: scripts/deploy-desktop.sh [dest_dir]
#   dest_dir : output folder (default: dist)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RENPY_SDK="$ROOT_DIR/renpy-sdk"
LAUNCHER="$RENPY_SDK/launcher"
LIBS="$ROOT_DIR/game/spritestudio/libs"

DEST="${1:-dist}"
case "$DEST" in -h|--help|help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;; esac
case "$DEST" in /*) : ;; *) DEST="$ROOT_DIR/$DEST" ;; esac   # absolutise

# --- host platform -> Ren'Py package + the native lib it requires ---------
case "$(uname -s)" in
  Darwin) PKG=mac;   FORMAT=app-zip; LIB_REL="macos/libssruntime.framework" ;;
  Linux)  PKG=linux; FORMAT=tar.bz2; LIB_REL="linux/x86_64/libssruntime.so" ;;
  *) echo "deploy-desktop.sh: unsupported host '$(uname -s)'. For Windows, run scripts\\deploy-desktop.ps1." >&2; exit 1 ;;
esac

# --- prerequisites --------------------------------------------------------
if [ ! -x "$RENPY_SDK/renpy.sh" ]; then
  echo "deploy-desktop.sh: Ren'Py SDK not found at renpy-sdk/ — fetching it first..."
  "$ROOT_DIR/scripts/fetch-renpy-sdk.sh"
fi
if [ ! -e "$LIBS/$LIB_REL" ]; then   # -e: the macOS Brain is a .framework directory, not a file
  echo "deploy-desktop.sh: native library missing for the $PKG package:" >&2
  echo "    game/spritestudio/libs/$LIB_REL" >&2
  echo "  Without it the app builds but SSPlayer fails at load. Get it with" >&2
  echo "  scripts/download-sdk.sh (prebuilt) or scripts/build-runtime.sh, then re-run." >&2
  exit 1
fi

# --- build ----------------------------------------------------------------
echo ">> building $PKG desktop distribution -> $DEST"
"$RENPY_SDK/renpy.sh" "$LAUNCHER" distribute "$ROOT_DIR" \
  --package "$PKG" --format "$FORMAT" --no-update --destination "$DEST"

# --- unpack so the result is immediately runnable -------------------------
if [ "$PKG" = mac ]; then
  ARCHIVE="$(find "$DEST" -maxdepth 1 -name '*-mac.zip' | head -1)"
  [ -n "$ARCHIVE" ] || { echo "deploy-desktop.sh: expected *-mac.zip in $DEST" >&2; exit 1; }
  echo ">> unpacking $(basename "$ARCHIVE")"
  ( cd "$DEST" && unzip -o -q "$ARCHIVE" )
  APP="$(find "$DEST" -maxdepth 1 -name '*.app' | head -1)"
  echo "deploy-desktop.sh: done -> $APP"
  echo "  Run it:  open \"$APP\""
else
  # Ren'Py's "linux" package produces <name>-<version>-linux.tar.bz2 (no arch
  # suffix — see the itch channel map in renpy/common/00build.rpy).
  ARCHIVE="$(find "$DEST" -maxdepth 1 -name '*-linux.tar.bz2' | head -1)"
  [ -n "$ARCHIVE" ] || { echo "deploy-desktop.sh: expected *-linux.tar.bz2 in $DEST" >&2; exit 1; }
  echo ">> unpacking $(basename "$ARCHIVE")"
  tar -xjf "$ARCHIVE" -C "$DEST"
  DIR="$(find "$DEST" -maxdepth 1 -type d -name '*-linux' | head -1)"
  echo "deploy-desktop.sh: done -> $DIR"
  echo "  Run it:  \"$DIR\"/*.sh"
fi
