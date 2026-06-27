#!/usr/bin/env bash
#
# Download the pure-Python flatbuffers runtime from GitHub and vendor it.
# Output: game/spritestudio/python/flatbuffers/

set -euo pipefail

FB_VERSION="v25.12.19"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT_DIR/game/spritestudio/python/flatbuffers"

echo "Downloading FlatBuffers $FB_VERSION python runtime..."

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl -sL "https://github.com/google/flatbuffers/archive/refs/tags/${FB_VERSION}.tar.gz" | tar xz -C "$TMP_DIR"

if [ -d "$OUT_DIR" ]; then
  rm -rf "$OUT_DIR"
fi

cp -r "$TMP_DIR/flatbuffers-${FB_VERSION#v}/python/flatbuffers" "$OUT_DIR"

echo "download-flatbuffers.sh: done. Vendored to $OUT_DIR."
