#!/usr/bin/env bash
#
# Launch the SSPlayer demo in the downloaded Ren'Py SDK. Convenience wrapper
# around `renpy-sdk/renpy.sh <project-root>`; fetches the SDK first if it is not
# present yet (scripts/fetch-renpy-sdk.sh).
#
# Usage: scripts/run-demo.sh
#
# Equivalent manual command (from the project root):
#   renpy-sdk/renpy.sh .
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHER="$ROOT_DIR/renpy-sdk/renpy.sh"

if [ ! -f "$LAUNCHER" ]; then
  echo "run-demo.sh: Ren'Py SDK not found at renpy-sdk/ — fetching it first..."
  "$ROOT_DIR/scripts/fetch-renpy-sdk.sh"
fi

echo "Launching the SSPlayer demo: $LAUNCHER $ROOT_DIR"
exec "$LAUNCHER" "$ROOT_DIR"
