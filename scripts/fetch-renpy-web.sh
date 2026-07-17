#!/usr/bin/env bash
#
# Download the Ren'Py Web export package and extract it into renpy-sdk/.
# The Ren'Py SDK must already be fetched using fetch-renpy-sdk.sh.
#
# Usage: scripts/fetch-renpy-web.sh [version]
#   version : Web package version to fetch (default: latest stable, or $RENPY_VERSION).
#             e.g. scripts/fetch-renpy-web.sh 8.3.0
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT_DIR/renpy-sdk"
BASE_URL="https://www.renpy.org/dl"
VERSION_FILE="$ROOT_DIR/scripts/RENPY_VERSION.txt"

usage() { sed -n '/^# Usage:/,/^[^#]/p' "$0" | sed '/^[^#]/d; s/^# \{0,1\}//'; }
case "${1:-}" in -h|--help|help) usage; exit 0 ;; esac

command -v curl >/dev/null || { echo "fetch-renpy-web.sh: curl not on PATH" >&2; exit 1; }
command -v unzip >/dev/null || { echo "fetch-renpy-web.sh: unzip not on PATH" >&2; exit 1; }

if [ ! -d "$DEST" ]; then
  echo "fetch-renpy-web.sh: renpy-sdk/ not found. Please run scripts/fetch-renpy-sdk.sh first." >&2
  exit 1
fi

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
  VERSION="$(curl -fsSL https://www.renpy.org/latest.html \
    | grep -oE 'renpy-[0-9]+\.[0-9]+\.[0-9]+-web\.zip' \
    | head -n1 | sed -E 's/renpy-([0-9.]+)-web\.zip/\1/')" || true
fi
if [ -z "$VERSION" ]; then
  echo "fetch-renpy-web.sh: could not resolve the latest version automatically." >&2
  echo "  pass one explicitly (scripts/fetch-renpy-web.sh 8.3.0) or set RENPY_VERSION." >&2
  exit 1
fi
echo "Ren'Py Web package version: $VERSION"

ARCHIVE="renpy-$VERSION-web.zip"
URL="$BASE_URL/$VERSION/$ARCHIVE"

# --- download + extract ---------------------------------------------------
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL ..."
curl -fL --progress-bar -o "$TMP/$ARCHIVE" "$URL"

echo "Extracting into renpy-sdk/ ..."
# The zip contains a 'web/' directory, which will land safely inside renpy-sdk/
unzip -qo "$TMP/$ARCHIVE" -d "$DEST/"

echo "fetch-renpy-web.sh: done (Ren'Py Web $VERSION)."
