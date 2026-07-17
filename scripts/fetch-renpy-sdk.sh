#!/usr/bin/env bash
#
# Download the Ren'Py SDK and extract it into a gitignored renpy-sdk/ at the
# project root, so the project can be launched / visually verified. The Ren'Py
# SDK is NOT in this repo (it renders to a GUI), so this fetches it on demand.
#
# This is a SEPARATE job from the other scripts (keep them decoupled):
#   build-runtime.*   -> the native libssruntime    (game/spritestudio/libs/)
#   deploy-examples.* -> the .ssab playback data     (game/ss_assets/)
#   fetch-renpy-sdk.* -> the Ren'Py editor/runtime   (renpy-sdk/, gitignored)
#
# Usage: scripts/fetch-renpy-sdk.sh [version]
#   version : SDK version to fetch (default: latest stable, or $RENPY_VERSION).
#             e.g. scripts/fetch-renpy-sdk.sh 8.5.3
#
# Afterwards, launch the project with:
#   renpy-sdk/renpy.sh .
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT_DIR/renpy-sdk"
BASE_URL="https://www.renpy.org/dl"
VERSION_FILE="$ROOT_DIR/scripts/RENPY_VERSION.txt"

usage() { sed -n '/^# Usage:/,/^[^#]/p' "$0" | sed '/^[^#]/d; s/^# \{0,1\}//'; }
case "${1:-}" in -h|--help|help) usage; exit 0 ;; esac

command -v curl >/dev/null || { echo "fetch-renpy-sdk.sh: curl not on PATH" >&2; exit 1; }

# --- resolve version ------------------------------------------------------
# priority: CLI arg > $RENPY_VERSION > scripts/RENPY_VERSION.txt (the pin all
# fetch-renpy-* scripts share) > latest stable resolved from latest.html.
VERSION="${1:-${RENPY_VERSION:-}}"
if [ -z "$VERSION" ] && [ -f "$VERSION_FILE" ]; then
  VERSION="$(tr -d ' \t\r\n' < "$VERSION_FILE")"
  [ -n "$VERSION" ] && echo "Using pinned version from scripts/RENPY_VERSION.txt: $VERSION"
fi
if [ -z "$VERSION" ]; then
  echo "Resolving latest stable Ren'Py version..."
  # latest.html links the current SDK archives; pull the version out of the
  # renpy-<x.y.z>-sdk filename it references.
  VERSION="$(curl -fsSL https://www.renpy.org/latest.html \
    | grep -oE 'renpy-[0-9]+\.[0-9]+\.[0-9]+-sdk' \
    | head -n1 | sed -E 's/renpy-([0-9.]+)-sdk/\1/')" || true
fi
if [ -z "$VERSION" ]; then
  echo "fetch-renpy-sdk.sh: could not resolve the latest version automatically." >&2
  echo "  pass one explicitly (scripts/fetch-renpy-sdk.sh 8.5.3) or set RENPY_VERSION." >&2
  exit 1
fi
echo "Ren'Py SDK version: $VERSION"

# --- pick the per-OS archive ----------------------------------------------
# The SDK tarball is platform-agnostic (bundles every platform's runtime under
# lib/), so macOS and Linux both use the .tar.bz2; Linux ARM uses the sdkarm
# build. On Windows use the .ps1 (Expand-Archive of the .zip).
case "${OSTYPE:-}" in
  msys*|cygwin*|win*)
    echo "fetch-renpy-sdk.sh: on Windows run scripts\\fetch-renpy-sdk.ps1 instead." >&2; exit 2 ;;
  darwin*) ARCHIVE="renpy-$VERSION-sdk.tar.bz2" ;;
  *)
    a="$(uname -m)"
    if [ "$a" = "aarch64" ] || [ "$a" = "arm64" ]; then
      ARCHIVE="renpy-$VERSION-sdkarm.tar.bz2"
    else
      ARCHIVE="renpy-$VERSION-sdk.tar.bz2"
    fi ;;
esac
URL="$BASE_URL/$VERSION/$ARCHIVE"

# --- download + extract ---------------------------------------------------
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL ..."
curl -fL --progress-bar -o "$TMP/$ARCHIVE" "$URL"

echo "Extracting into renpy-sdk/ ..."
rm -rf "$DEST"; mkdir -p "$DEST"
# the archive has a single top-level renpy-<ver>-sdk/ dir; strip it so the
# launcher lands at renpy-sdk/renpy.sh.
tar -xjf "$TMP/$ARCHIVE" -C "$DEST" --strip-components=1

# --- report ---------------------------------------------------------------
echo "fetch-renpy-sdk.sh: done (Ren'Py $VERSION)."
if [ -f "$DEST/renpy.sh" ]; then
  echo "   launch the project:  renpy-sdk/renpy.sh ."
else
  echo "   note: renpy.sh not found at renpy-sdk/ — inspect the extracted tree." >&2
fi
