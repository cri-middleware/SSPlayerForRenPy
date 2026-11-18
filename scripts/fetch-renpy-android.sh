#!/usr/bin/env bash
#
# Download the Ren'Py Android support package (RAPT — the Ren'Py Android
# Packaging Tool) and extract it into renpy-sdk/. This is the extra download the
# Android target needs, the same way the Web target needs fetch-renpy-web.sh.
# The Ren'Py SDK must already be fetched using fetch-renpy-sdk.sh.
#
# Note: RAPT itself does NOT include the Android SDK / NDK / JDK, nor the signing
# keys. Those steps are interactive, so do them once from the launcher GUI:
#     renpy-sdk/renpy.sh renpy-sdk/launcher   ->  Android
#       -> "Install SDK"   (downloads the SDK/NDK/JDK into rapt/Sdk/)
#       -> "Generate Keys" (creates android.keystore to sign the package)
#       -> "Configure"     (package/app name in android.json)
# After that, build with scripts/deploy-android.sh.
#
# Usage: scripts/fetch-renpy-android.sh [version]
#   version : RAPT package version to fetch (default: $RENPY_VERSION, else the pin in
#             scripts/RENPY_VERSION.txt, else the latest stable).
#             e.g. scripts/fetch-renpy-android.sh 8.3.0
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT_DIR/renpy-sdk"
BASE_URL="https://www.renpy.org/dl"
VERSION_FILE="$ROOT_DIR/scripts/RENPY_VERSION.txt"

usage() { sed -n '/^# Usage:/,/^[^#]/p' "$0" | sed '/^[^#]/d; s/^# \{0,1\}//'; }
VERSION_ARG=""
for a in "$@"; do
  case "$a" in
    -h|--help|help) usage; exit 0 ;;
    -*) echo "fetch-renpy-android.sh: unknown flag '$a'" >&2; exit 2 ;;
    *) [ -z "$VERSION_ARG" ] || { echo "fetch-renpy-android.sh: unexpected extra arg '$a'" >&2; exit 2; }; VERSION_ARG="$a" ;;
  esac
done

command -v curl >/dev/null || { echo "fetch-renpy-android.sh: curl not on PATH" >&2; exit 1; }
command -v unzip >/dev/null || { echo "fetch-renpy-android.sh: unzip not on PATH" >&2; exit 1; }

if [ ! -d "$DEST" ]; then
  echo "fetch-renpy-android.sh: renpy-sdk/ not found. Please run scripts/fetch-renpy-sdk.sh first." >&2
  exit 1
fi

# --- resolve version ------------------------------------------------------
# priority: CLI arg > $RENPY_VERSION > scripts/RENPY_VERSION.txt (the pin all
# fetch-renpy-* scripts share) > latest stable resolved from latest.html.
VERSION="${VERSION_ARG:-${RENPY_VERSION:-}}"
if [ -z "$VERSION" ] && [ -f "$VERSION_FILE" ]; then
  VERSION="$(tr -d ' \t\r\n' < "$VERSION_FILE")"
  [ -n "$VERSION" ] && echo "Using pinned version from scripts/RENPY_VERSION.txt: $VERSION"
fi
if [ -z "$VERSION" ]; then
  echo "Resolving latest stable Ren'Py version..."
  VERSION="$(curl -fsSL https://www.renpy.org/latest.html \
    | grep -oE 'renpy-[0-9]+\.[0-9]+\.[0-9]+-rapt\.zip' \
    | head -n1 | sed -E 's/renpy-([0-9.]+)-rapt\.zip/\1/')" || true
fi
if [ -z "$VERSION" ]; then
  echo "fetch-renpy-android.sh: could not resolve the latest version automatically." >&2
  echo "  pass one explicitly (scripts/fetch-renpy-android.sh 8.3.0) or set RENPY_VERSION." >&2
  exit 1
fi
echo "Ren'Py RAPT (Android) package version: $VERSION"

ARCHIVE="renpy-$VERSION-rapt.zip"
URL="$BASE_URL/$VERSION/$ARCHIVE"

# --- download + extract ---------------------------------------------------
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL ..."
curl -fL --progress-bar -o "$TMP/$ARCHIVE" "$URL"

echo "Extracting into renpy-sdk/ ..."
# The zip contains a 'rapt/' directory, which will land safely inside renpy-sdk/
unzip -qo "$TMP/$ARCHIVE" -d "$DEST/"

echo "fetch-renpy-android.sh: done (Ren'Py RAPT $VERSION)."
echo "  Next (once, interactive) in the launcher GUI -> Android:"
echo "    renpy-sdk/renpy.sh renpy-sdk/launcher"
echo "    -> 'Install SDK'  (Android SDK/NDK/JDK)  and  'Generate Keys' (signing)"
echo "  Then build:  scripts/deploy-android.sh"
