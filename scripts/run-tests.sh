#!/usr/bin/env bash
#
# Run the headless test suite (tools/verify_*.py + tools/smoke.py) — the
# whole engine-independent layer, in plain CPython, with no Ren'Py and no GUI.
# The work is tools/run_tests.py; this picks the interpreter and forwards the
# arguments, the way deploy-examples.sh delegates to tools/cli_convert.py.
#
# Two prerequisites, both gitignored and so both missing from a fresh clone.
# The runner checks them before it starts anything and names the script that
# produces each, rather than letting the suite report green on a tree where
# nothing loaded:
#   game/spritestudio/libs/   <- build-runtime.{sh,ps1}
#   game/ss_assets/           <- deploy-examples.{sh,ps1}
#
# GL2 rendering is not covered here and cannot be: PMA, mesh, blend, mask and
# the ss-* GLSL need a GUI run — sign off via Shift+B or scripts/run-demo.*.
#
# Usage: scripts/run-tests.sh [only=<names>] [skip=<names>] [list=yes] [verbose=yes]
#   only    : comma-separated substrings; run only the tools that match
#   skip    : comma-separated substrings; skip the tools that match
#   list    : yes to list the discovered tools and exit
#   verbose : yes to stream every tool's output, not just the failing ones
#
# Exit status: 0 all passed, 1 something failed or was skipped, 2 preflight failed.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

usage() { sed -n '/^# Usage:/,/^# Exit status/p' "$0" | sed 's/^# \{0,1\}//'; }
for arg in "$@"; do
  case "$arg" in
    -h|--help|help) usage; exit 0 ;;
  esac
done

# Same interpreter resolution as deploy-examples.sh: prefer the python Ren'Py
# ships for THIS host when the SDK is present (a bare py3-* glob grabs
# py3-linux first and dies with "cannot execute binary file" on macOS), so a
# machine with only the Ren'Py SDK can still run the suite.
case "$(uname -s)" in
  Darwin) PY_DIR_GLOB="py3-mac-*" ;;
  Linux)  PY_DIR_GLOB="py3-linux-$(uname -m)*" ;;
  *)      PY_DIR_GLOB="py3-windows-*" ;;
esac
RENPY_PYTHON_DIR=$(ls -d "$ROOT_DIR"/renpy-sdk/lib/$PY_DIR_GLOB 2>/dev/null | head -n 1 || true)
if [ -n "$RENPY_PYTHON_DIR" ] && [ -x "$RENPY_PYTHON_DIR/python" ]; then
    PYTHON_CMD="$RENPY_PYTHON_DIR/python"
elif [ -n "$RENPY_PYTHON_DIR" ] && [ -x "$RENPY_PYTHON_DIR/python.exe" ]; then
    PYTHON_CMD="$RENPY_PYTHON_DIR/python.exe"
elif command -v python3 >/dev/null; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null; then
    PYTHON_CMD="python"
else
    echo "run-tests.sh: python/python3 not found in renpy-sdk or PATH" >&2; exit 2
fi

exec "$PYTHON_CMD" "$ROOT_DIR/tools/run_tests.py" "$@"
