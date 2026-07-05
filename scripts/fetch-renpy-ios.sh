#!/usr/bin/env bash
#
# Download the Ren'Py iOS support package (renios) and extract it into
# renpy-sdk/. This is the extra download the iOS target needs, the same way the
# Android target needs fetch-renpy-android.sh (RAPT) and Web needs
# fetch-renpy-web.sh. The Ren'Py SDK must already be fetched using
# fetch-renpy-sdk.sh; the launcher looks for renios at renpy-sdk/renios/.
#
# Note: renios only lets Ren'Py *generate* an Xcode project. Building the .ipa
# itself needs macOS + Xcode (with your Apple signing / provisioning set up in
# Xcode). Those steps are not scripted — Xcode owns code signing. After fetching,
# generate the project with scripts/deploy-ios.sh and open it in Xcode.
#
# Usage: scripts/fetch-renpy-ios.sh [version]
#   version : renios package version to fetch (default: latest stable, or $RENPY_VERSION).
#             e.g. scripts/fetch-renpy-ios.sh 8.3.0
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT_DIR/renpy-sdk"
BASE_URL="https://www.renpy.org/dl"
VERSION_FILE="$ROOT_DIR/scripts/RENPY_VERSION.txt"

usage() { sed -n '/^# Usage:/,/^[^#]/p' "$0" | sed '/^[^#]/d; s/^# \{0,1\}//'; }
case "${1:-}" in -h|--help|help) usage; exit 0 ;; esac

command -v curl >/dev/null || { echo "fetch-renpy-ios.sh: curl not on PATH" >&2; exit 1; }
command -v unzip >/dev/null || { echo "fetch-renpy-ios.sh: unzip not on PATH" >&2; exit 1; }

if [ ! -d "$DEST" ]; then
  echo "fetch-renpy-ios.sh: renpy-sdk/ not found. Please run scripts/fetch-renpy-sdk.sh first." >&2
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
    | grep -oE 'renpy-[0-9]+\.[0-9]+\.[0-9]+-renios\.zip' \
    | head -n1 | sed -E 's/renpy-([0-9.]+)-renios\.zip/\1/')" || true
fi
if [ -z "$VERSION" ]; then
  echo "fetch-renpy-ios.sh: could not resolve the latest version automatically." >&2
  echo "  pass one explicitly (scripts/fetch-renpy-ios.sh 8.3.0) or set RENPY_VERSION." >&2
  exit 1
fi
echo "Ren'Py renios (iOS) package version: $VERSION"

ARCHIVE="renpy-$VERSION-renios.zip"
URL="$BASE_URL/$VERSION/$ARCHIVE"

# --- download + extract ---------------------------------------------------
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL ..."
curl -fL --progress-bar -o "$TMP/$ARCHIVE" "$URL"

echo "Extracting into renpy-sdk/ ..."
# The zip contains a 'renios/' directory, which will land safely inside renpy-sdk/
unzip -qo "$TMP/$ARCHIVE" -d "$DEST/"

echo "fetch-renpy-ios.sh: done (Ren'Py renios $VERSION)."
echo "  Next — generate the Xcode project (needs macOS + Xcode):"
echo "    scripts/deploy-ios.sh"
echo "  then open the generated .xcodeproj in Xcode to sign and build the .ipa."
