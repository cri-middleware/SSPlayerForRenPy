#!/bin/bash
set -e
BASEDIR=$(dirname $0)
ROOTDIR=$(cd "$BASEDIR/.." && pwd -P)
TARGET_DIR="${ROOTDIR}/game/spritestudio/libs"
VERSION_FILE="${ROOTDIR}/SDK_VERSION.txt"
CURRENT_VERSION_FILE="${TARGET_DIR}/VERSION"

TARGET_VERSION=$(cat "$VERSION_FILE" | tr -d '\r\n')

if [ -f "$CURRENT_VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$CURRENT_VERSION_FILE" | tr -d '\n')
    if [ "$CURRENT_VERSION" = "$TARGET_VERSION" ]; then
        echo "SDK $TARGET_VERSION is already up to date. Skipping download."
        exit 0
    fi
fi

# Note: The zip file name should match what is actually published on the SpriteStudio-SDK releases.
URL="https://github.com/cri-middleware/SpriteStudio-SDK/releases/download/${TARGET_VERSION}/spritestudio7-sdk-dynamic-libs.zip"
ZIP_FILE="${TARGET_DIR}/sdk.zip"

echo "Target SDK Version: ${TARGET_VERSION}"
echo "Download URL: ${URL}"
echo "Downloading SDK..."
mkdir -p "$TARGET_DIR"
curl -fL -o "$ZIP_FILE" "$URL"

echo "Extracting SDK..."
unzip -q -o "$ZIP_FILE" -d "${TARGET_DIR}/"
rm "$ZIP_FILE"

echo "$TARGET_VERSION" > "$CURRENT_VERSION_FILE"

echo "Done."
