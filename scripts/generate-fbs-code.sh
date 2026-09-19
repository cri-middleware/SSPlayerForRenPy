#!/usr/bin/env bash
#
# Generate Python flatbuffers bindings from the SpriteStudio-SDK schemas.
# Output: game/spritestudio/python/ss/

set -euo pipefail

HELP_APP="$(basename "$0")"
usage () {
    cat <<USAGE
Usage: ${HELP_APP} [--help]
  flatc --python over the SDK's .fbs schemas, into game/spritestudio/python/ss/.
  Needs flatc. The old bindings are removed first.
USAGE
}

for arg in "$@"; do
  case "$arg" in
    -h|--help|help) usage; exit 0 ;;
    *) echo "${HELP_APP}: unknown argument '${arg}'" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SDK_DIR="${SSSDK:-}"
if [ -z "$SDK_DIR" ]; then
  for cand in "$ROOT_DIR/SpriteStudio-SDK" "$ROOT_DIR/../SpriteStudio-SDK"; do
    if [ -f "$cand/Cargo.toml" ]; then SDK_DIR="$(cd "$cand" && pwd)"; break; fi
  done
fi

if [ -z "$SDK_DIR" ] || [ ! -f "$SDK_DIR/Cargo.toml" ]; then
  echo "generate-fbs-code.sh: SpriteStudio-SDK not found." >&2
  exit 1
fi

command -v flatc >/dev/null || { echo "generate-fbs-code.sh: flatc not on PATH" >&2; exit 1; }

OUT_DIR="$ROOT_DIR/game/spritestudio/python"
echo "Generating Python bindings to $OUT_DIR/ss ..."

# Remove old bindings
rm -rf "$OUT_DIR/ss"

# Run flatc
flatc --python -o "$OUT_DIR" \
    "$SDK_DIR/libs/ssab/fbs/ssab.fbs" \
    "$SDK_DIR/libs/ssab/fbs/ssqb.fbs" \
    "$SDK_DIR/libs/ssruntime/fbs/effect_draw_plan.fbs" \
    "$SDK_DIR/libs/ssruntime/fbs/framedata.fbs"

echo "generate-fbs-code.sh: done."
