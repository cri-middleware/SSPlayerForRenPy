#!/bin/bash
set -e
HELP_APP="$(basename "$0")"
usage () {
    cat <<USAGE
Usage: ${HELP_APP} [--help]
  Install the SpriteStudio-SDK release pinned by scripts/SDK_VERSION.txt into
  game/spritestudio/libs/. Skips the download when that version is already in place.
USAGE
}

for arg in "$@"; do
  case "$arg" in
    -h|--help|help) usage; exit 0 ;;
    *) echo "${HELP_APP}: unknown argument '${arg}'" >&2; usage >&2; exit 2 ;;
  esac
done

BASEDIR=$(dirname "$0")
SCRIPTDIR=$(cd "$BASEDIR" && pwd -P)
ROOTDIR=$(cd "$BASEDIR/.." && pwd -P)
TARGET_DIR="${ROOTDIR}/game/spritestudio/libs"
VERSION_FILE="${SCRIPTDIR}/SDK_VERSION.txt"
CURRENT_VERSION_FILE="${TARGET_DIR}/VERSION"
# Downloaded zips are cached here (gitignored) so a re-run that needs the same
# version reuses them instead of re-downloading tens of MB.
CACHE_DIR="${SCRIPTDIR}/.sdk-cache"

TARGET_VERSION=$(tr -d '\r\n' < "$VERSION_FILE")

if [ -f "$CURRENT_VERSION_FILE" ]; then
    CURRENT_VERSION=$(tr -d '\r\n' < "$CURRENT_VERSION_FILE")
    if [ "$CURRENT_VERSION" = "$TARGET_VERSION" ]; then
        echo "SDK $TARGET_VERSION is already up to date. Skipping download."
        exit 0
    fi
fi

BASE_URL="https://github.com/cri-middleware/SpriteStudio-SDK/releases/download/${TARGET_VERSION}"
# RenPy consumes two archives: the native dynamic libraries, and the combined
# web archive — from which only the SIMD runtime-web/ bundle (ssruntime.js +
# ssruntime_bg.wasm) is needed for the Web export target, the same files
# build-runtime.sh copies from pkg/runtime-web/.
DYNAMIC_ASSET="spritestudio-sdk-dynamic-libs.zip"
WEB_ASSET="spritestudio-sdk-web-libs.zip"
SUMS_FILE="${CACHE_DIR}/SHA256SUMS"

echo "Target SDK Version: ${TARGET_VERSION}"
mkdir -p "$CACHE_DIR"

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

# Fetch the checksum manifest (small): it both verifies integrity and decides
# whether an already-cached zip can be reused without re-downloading.
echo "Downloading checksum manifest: ${BASE_URL}/SHA256SUMS"
curl -fL -o "$SUMS_FILE" "${BASE_URL}/SHA256SUMS"

# ensure_cached_zip <asset-name>: leave a checksum-verified copy of the asset in
# CACHE_DIR (reusing it when already valid, else downloading) and echo its path.
# Progress goes to stderr so only the path is captured by the caller.
ensure_cached_zip() {
    local asset="$1" file="${CACHE_DIR}/$1" expected
    expected=$(awk -v n="$asset" '$2 == n {print $1}' "$SUMS_FILE")
    if [ -z "$expected" ]; then
        echo "ERROR: no checksum entry for ${asset} in SHA256SUMS" >&2
        exit 1
    fi
    if [ -f "$file" ] && [ "$(sha256_of "$file")" = "$expected" ]; then
        echo "Reusing cached ${asset}" >&2
    else
        echo "Downloading ${BASE_URL}/${asset}" >&2
        curl -fL -o "$file" "${BASE_URL}/${asset}"
        if [ "$(sha256_of "$file")" != "$expected" ]; then
            echo "ERROR: checksum mismatch for ${asset}" >&2
            rm -f "$file"
            exit 1
        fi
    fi
    echo "$file"
}

DYNAMIC_ZIP=$(ensure_cached_zip "$DYNAMIC_ASSET")
WEB_ZIP=$(ensure_cached_zip "$WEB_ASSET")

echo "Extracting SDK..."
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Native dynamic libraries: the archive is a flat tree (libs/, include/,
# bindings/, VERSION, …). RenPy needs only the native libs + license notices at
# game/spritestudio/libs/<platform>/, so extract to a temp and move libs/* +
# licenses into place — include/ and bindings/ are unused here.
unzip -q -o "$DYNAMIC_ZIP" -d "$TMP_DIR"
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
mv "$TMP_DIR"/libs/* "$TARGET_DIR"/
cp "$TMP_DIR"/LICENSE.md "$TARGET_DIR"/ 2>/dev/null || true
cp "$TMP_DIR"/THIRD-PARTY-LICENSES.*.md "$TARGET_DIR"/ 2>/dev/null || true

# Web runtime: the combined web archive holds runtime-web/, runtime-web-nosimd/
# and converter-web/ as subdirs; RenPy needs only the SIMD runtime-web/ bundle.
# Extract just that subdir with junked paths so ssruntime.js + ssruntime_bg.wasm
# land directly in game/spritestudio/libs/web/ — the same files build-runtime.sh
# copies from pkg/runtime-web/ and deploy-web.sh serves. 'runtime-web/*' does not
# match 'runtime-web-nosimd/*' (different literal prefix).
mkdir -p "$TARGET_DIR/web"
unzip -q -o -j "$WEB_ZIP" 'runtime-web/*' -d "$TARGET_DIR/web"

echo "$TARGET_VERSION" > "$CURRENT_VERSION_FILE"

echo "Done."
