#!/usr/bin/env bash
#
# Print the package version -- what a release of this plugin should be tagged as.
#
#   scripts/release-version.sh          # 7.0.0b1
#   v$(scripts/release-version.sh)      # v7.0.0b1  -- the git tag
#
# It is `__version__` in game/spritestudio/python/ss_renpy/__init__.py, and
# nothing else. That file ships inside the drop-in folder, so it is the version
# a creator actually has in their project -- which is why it, and not
# scripts/SDK_VERSION.txt or scripts/RENPY_VERSION.txt, is what a release is
# named after. Those two pin dependencies and move on their own schedule.
#
# The tag is what names a release -- release.yml is dispatched from a v* tag and
# takes the name from that ref. This is what the tag *must* be: build-release.sh
# refuses a tag that disagrees, because a Release called v1.2.3 carrying
# SSPlayerForRenPy-1.2.4.zip is worse than no release at all.
set -euo pipefail

APP="$(basename "$0")"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

case "${1:-}" in
  -h|--help|help)
    echo "Usage: $APP"
    echo "Prints __version__ from game/spritestudio/python/ss_renpy/__init__.py"
    echo "(no leading 'v')."
    exit 0
    ;;
  "") ;;
  *)
    echo "$APP: unexpected argument '$1' (see $APP --help)" >&2
    exit 2
    ;;
esac

INIT="$ROOT_DIR/game/spritestudio/python/ss_renpy/__init__.py"
if [ ! -f "$INIT" ]; then
  echo "$APP: $INIT not found -- is this the SSPlayerForRenPy repo?" >&2
  exit 1
fi

VERSION="$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' "$INIT")"

if [ -z "$VERSION" ]; then
  echo "$APP: no __version__ in ${INIT#"$ROOT_DIR"/}" >&2
  exit 1
fi

printf '%s\n' "$VERSION"
