#!/usr/bin/env bash
#
# Build the release: the drop-in `spritestudio/` folder a creator pastes into
# their Ren'Py project, the playable Web demo, and the checksums over both.
#
#   scripts/build-release.sh                  # both assets
#   scripts/build-release.sh demo=skip        # the plugin zip only, much faster
#   scripts/build-release.sh sdk=build        # compile the libs from the submodule
#   scripts/build-release.sh out=/tmp/rel     # somewhere else
#
# release.yml's release job runs this script for the assets it uploads, so CI
# and a local run cannot drift. The workflow keeps only what is GitHub's -- the
# checkout, the artifact upload and the Release itself.
#
# Both assets ship, so both are built here. The Web demo is not a side product:
# pages.yml publishes it as the playable demo by downloading it off the Release,
# so a release without it leaves the site pointing at the previous one. It is
# also the expensive half -- it fetches the Ren'Py SDK and runs a full Web
# export -- which is what demo=skip is for while iterating on the plugin zip.
#
# This is the phase AFTER it has been decided what is being released: the tag
# comes from the checkout, not from an option. What this does NOT do is bump
# __version__ or tag anything. Those are decisions, and a script that made them
# would have to guess which.
#
# The two checks are the ones that have actually bitten:
#
#   The tag must match __version__. A Release called v1.2.3 carrying
#   SSPlayerForRenPy-1.2.4.zip is worse than no release, and nothing downstream
#   would notice.
#
#   The macOS framework must still be a bundle. libs/macos/libssruntime.framework
#   is versioned -- Versions/Current and the bundle-root aliases are symlinks --
#   and zip FOLLOWS symlinks unless told not to, flattening it into plain copies.
#   That invalidates its code signature (`codesign --verify` says "bundle format
#   is ambiguous"), so a game bundling the extracted framework can no longer be
#   signed or notarised. Consumers get that framework only through this zip, and
#   the working tree here always has the real symlinks, so a flattened bundle
#   would ship unnoticed.
set -euo pipefail

APP="$(basename "$0")"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# --- options --------------------------------------------------------------

OUT="release-dist"
SDK="download"
DEMO="build"
VERIFY="yes"
CLEAN="yes"

usage () {
  echo "Usage: $APP [options]"
  echo "$APP options:"
  echo "  out=<dir>               Where the zips and SHA256SUMS land (default: $OUT)."
  echo "                          Relative paths resolve against the current directory."
  echo "  sdk=<download|build|skip>"
  echo "                          Where the SpriteStudio SDK libs come from (default:"
  echo "                          $SDK). download = download-sdk.sh, the version pinned"
  echo "                          by scripts/SDK_VERSION.txt (what CI uses). build ="
  echo "                          build-runtime.sh, from the submodule sources -- this"
  echo "                          host's platform only, so never a release. skip = use"
  echo "                          game/spritestudio/libs/ as it stands."
  echo "  demo=<build|skip>       Whether to build the Web demo (default: $DEMO)."
  echo "                          build fetches the Ren'Py SDK and runs the Web export,"
  echo "                          which is most of the wall clock here. skip leaves the"
  echo "                          demo out -- fine while iterating on the plugin zip,"
  echo "                          never for a release: pages.yml publishes the demo by"
  echo "                          downloading it off the Release."
  echo "  verify=<yes|no>         Re-open the finished zips and check them (default:"
  echo "                          $VERIFY)."
  echo "  clean=<yes|no>          Delete <out> before building (default: $CLEAN)."
    echo "  in= skip=               Accepted and ignored here. The family's build-release"
  echo "                          scripts share out= clean= verify= in= sdk= skip=,"
  echo "                          so one command line drives all of them."
echo "  -h | --help             Show this help"
  echo ""
  echo "Output: <out>/ holds SSPlayerForRenPy-<version>.zip, the Web demo zip, the"
  echo "version-less alias of each (the stable releases/latest/download/ names the"
  echo "README, the docs and pages.yml use), and SHA256SUMS over all four."
  echo ""
  echo "There is no option for which release this is: the tag comes from the checkout"
  echo "this runs in (the ref the workflow was dispatched from, or 'git checkout <tag>'"
  echo "locally), and it must match __version__."
}

while [ $# -gt 0 ]; do
  item="$1"
  shift

  case "$item" in
    -h|--help|help)
      usage
      exit 0
      ;;
    *=*)
      key="${item%%=*}"
      value="${item#*=}"
      case "$key" in
        out)    OUT="$value" ;;
        # Lower-cased where the option is a keyword; out= is a path.
        sdk)    SDK="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        demo)   DEMO="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        verify) VERIFY="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        clean)  CLEAN="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        # Accepted so one command line drives build-release in every repository
        # of the family; this one has no use for them.
        in|skip) echo "$APP: ${key}= does not apply here; ignored" >&2 ;;
        *)
          echo "$APP: unknown option '$key' (see $APP --help)" >&2
          exit 2
          ;;
      esac
      ;;
    *)
      echo "$APP: unknown argument '$item' (options are key=value; see $APP --help)" >&2
      exit 2
      ;;
  esac
done

case "$SDK"    in download|build|skip) ;; *) echo "$APP: sdk must be download, build or skip (got '$SDK')" >&2; exit 2 ;; esac
case "$DEMO"   in build|skip) ;;         *) echo "$APP: demo must be build or skip (got '$DEMO')" >&2; exit 2 ;; esac
case "$VERIFY" in yes|no) ;;             *) echo "$APP: verify must be yes or no (got '$VERIFY')" >&2; exit 2 ;; esac
case "$CLEAN"  in yes|no) ;;             *) echo "$APP: clean must be yes or no (got '$CLEAN')" >&2; exit 2 ;; esac

# Resolve against the invoking directory, before anything cds away from it.
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

PKG_DIR="$ROOT_DIR/game/spritestudio"
if [ "$OUT" = "/" ] || [ "$OUT" = "$ROOT_DIR" ] || [ "$OUT" = "$PKG_DIR" ]; then
  echo "$APP: refusing to use '$OUT' as out= (it is deleted when clean=yes)" >&2
  exit 2
fi

cd "$ROOT_DIR"

# --- what this release is called ------------------------------------------
#
# A release is a tag: one is pushed, and the workflow is then dispatched from
# it. Reading the ref here is reading that decision, not making it.
VERSION="$(./scripts/release-version.sh)"
MANIFEST_TAG="v${VERSION}"

if [ "${GITHUB_REF_TYPE:-}" = "tag" ] && [ -n "${GITHUB_REF_NAME:-}" ]; then
  TAG="$GITHUB_REF_NAME"
  TAG_SOURCE="GITHUB_REF_NAME -- the ref this release was dispatched from"
elif TAG="$(git -C "$ROOT_DIR" describe --exact-match --match 'v[0-9]*' --tags HEAD 2>/dev/null)"; then
  TAG_SOURCE="the release tag HEAD is checked out at"
else
  TAG=""
  TAG_SOURCE="HEAD is not on a release tag, so this is a build, not a release"
fi

ARTIFACT="SSPlayerForRenPy-${VERSION}.zip"
DEMO_ZIP="SSPlayerForRenPy-web-demo-${VERSION}.zip"
# Version-less aliases: the README, the docs and pages.yml all fetch through
# releases/latest/download/<name>, a URL that must not change when the version
# does. Byte-identical copies under a stable name.
ALIAS="SSPlayerForRenPy.zip"
DEMO_ALIAS="SSPlayerForRenPy-web-demo.zip"

echo "options"
echo "  out      => $OUT"
echo "  sdk      => $SDK"
echo "  demo     => $DEMO"
echo "  verify   => $VERIFY"
echo "  clean    => $CLEAN"
echo "  version  => $VERSION"
echo "  tag      => ${TAG:-(none)}"
echo "              ($TAG_SOURCE)"

# A tag that disagrees with the shipped __version__ is not a warning: the
# Release would be called one thing and carry a zip called another, and the
# version inside the drop-in folder a creator ends up with is the zip's.
if [ -n "$TAG" ] && [ "$TAG" != "$MANIFEST_TAG" ]; then
  echo "" >&2
  echo "$APP: tag $TAG does not match __version__ ($MANIFEST_TAG)." >&2
  echo "$APP: bump ss_renpy.__version__, or retag -- the assets would be named $ARTIFACT." >&2
  exit 1
fi

# --- preflight ------------------------------------------------------------

if [ ! -d "$PKG_DIR" ]; then
  echo "$APP: game/spritestudio not found -- is this the SSPlayerForRenPy repo?" >&2
  exit 1
fi

for tool in zip unzip; do
  command -v "$tool" > /dev/null 2>&1 || {
    echo "$APP: $tool not found -- it is what packages the archives" >&2
    exit 1
  }
done

# The runners have sha256sum (coreutils); macOS ships shasum instead. Both write
# the same `<hash>  <name>` lines and both take -c, so SHA256SUMS is identical
# either way.
if command -v sha256sum > /dev/null 2>&1; then
  sha256 () { sha256sum "$@"; }
elif command -v shasum > /dev/null 2>&1; then
  sha256 () { shasum -a 256 "$@"; }
else
  echo "$APP: neither sha256sum nor shasum found -- one of them writes SHA256SUMS" >&2
  exit 1
fi

step () {
  echo ""
  echo ">> $*"
}

FAILED=""
fail () {
  FAILED="${FAILED}
  $1"
}

if [ "$CLEAN" = "yes" ]; then
  rm -rf "$OUT"
fi
mkdir -p "$OUT"

# --- the native libraries --------------------------------------------------
case "$SDK" in
  download)
    step "installing the pinned SDK native libraries"
    ./scripts/download-sdk.sh
    ;;
  build)
    step "building the SDK native libraries from source (THIS HOST ONLY)"
    echo "   Other platforms are left as they were, so what lands in the zip is"
    echo "   whatever is in game/spritestudio/libs. Never a release."
    ./scripts/build-runtime.sh
    ;;
  skip)
    step "sdk=skip -- keeping game/spritestudio/libs as it stands"
    ;;
esac

if [ ! -f "$PKG_DIR/libs/VERSION" ]; then
  echo "$APP: game/spritestudio/libs/VERSION is missing -- the SDK libs are not installed" >&2
  echo "$APP: run scripts/download-sdk.sh, or pass sdk=download" >&2
  exit 1
fi
echo "   libs/VERSION => $(tr -d ' \r\n' < "$PKG_DIR/libs/VERSION")"

# --- the plugin zip --------------------------------------------------------
step "packaging game/spritestudio -> $ARTIFACT"

# The licence documents ride inside the drop-in folder so they travel with every
# copy: the vendored FlatBuffers runtime is Apache-2.0, which requires the
# licence text to accompany redistribution. They are copies of the repo-root
# originals, so they are removed again afterwards however this exits -- leaving
# them behind would put two untracked files in game/spritestudio that only a
# release run ever creates.
cleanup_docs () {
  rm -f "$PKG_DIR/LICENSE.md" "$PKG_DIR/LICENSE.ja.md" "$PKG_DIR/THIRD_PARTY_NOTICES.md"
}
trap cleanup_docs EXIT
cp "$ROOT_DIR/LICENSE.md" "$ROOT_DIR/LICENSE.ja.md" "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$PKG_DIR/"

# `spritestudio` at the archive root, so a creator drops it straight into their
# project's game/ directory. -y stores symlinks AS symlinks -- see the header;
# without it the macOS framework is flattened and can never be signed again.
# -X drops the extra file attributes, keeping the archive reproducible.
( cd "$ROOT_DIR/game" && zip -qr -X -y "$OUT/$ARTIFACT" spritestudio \
    -x '*.rpyc' '*/__pycache__/*' '*/.DS_Store' )
cp "$OUT/$ARTIFACT" "$OUT/$ALIAS"
echo "   $ARTIFACT"
echo "   $ALIAS  (stable releases/latest/download/ name)"

# --- the Web demo ----------------------------------------------------------
if [ "$DEMO" = "build" ]; then
  step "building the Web demo -> $DEMO_ZIP"
  # The Ren'Py SDK plus its Web support, then the animation data the demo plays,
  # then the export itself. deploy-examples must run before deploy-web: the
  # exporter packs game/ as it stands.
  ./scripts/fetch-renpy-sdk.sh
  ./scripts/fetch-renpy-web.sh
  ./scripts/deploy-examples.sh
  ./scripts/deploy-web.sh web_out
  ( cd "$ROOT_DIR/web_out" && zip -qr -X "$OUT/$DEMO_ZIP" . -x '*/.DS_Store' )
  cp "$OUT/$DEMO_ZIP" "$OUT/$DEMO_ALIAS"
  echo "   $DEMO_ZIP"
  echo "   $DEMO_ALIAS  (stable name pages.yml downloads)"
else
  step "demo=skip -- no Web demo in this build"
  echo "   pages.yml publishes the demo by downloading it off the Release, so a"
  echo "   release built this way would leave the site on the previous one."
fi

# --- checksums -------------------------------------------------------------
# Covers the aliases too: they are byte-identical copies, but they download
# separately, so a consumer verifying one needs its line.
step "writing SHA256SUMS"
( cd "$OUT" && sha256 ./*.zip | sed 's|\./||' > SHA256SUMS )
echo "   $(wc -l < "$OUT/SHA256SUMS" | tr -d ' ') archives"

# --- verify ----------------------------------------------------------------
if [ "$VERIFY" = "yes" ]; then
  step "verifying $OUT"

  # The macOS framework is still a bundle. This is the regression guard for the
  # -y above, and the only place it can be checked: the repo's own working tree
  # always has the real symlinks, so nothing before the zip can tell.
  CHECK="$ROOT_DIR/build/release-zipcheck"
  rm -rf "$CHECK"
  mkdir -p "$CHECK"
  unzip -qq "$OUT/$ARTIFACT" -d "$CHECK"
  FW="$CHECK/spritestudio/libs/macos/libssruntime.framework"
  if [ ! -d "$FW" ]; then
    fail "$ARTIFACT has no libs/macos/libssruntime.framework"
  else
    for link in "$FW/Versions/Current" "$FW/libssruntime"; do
      if [ ! -L "$link" ]; then
        fail "${link#"$CHECK"/} is not a symlink -- the macOS framework was flattened (zip needs -y)"
      fi
    done
    [ -n "$FAILED" ] || echo "   macOS framework: version symlinks intact"
  fi

  # The drop-in folder has to work with no scripts/, no SDK and no build, so the
  # things a creator's project reaches for have to be inside it.
  for f in spritestudio/LICENSE.md spritestudio/LICENSE.ja.md spritestudio/THIRD_PARTY_NOTICES.md \
           spritestudio/libs/VERSION spritestudio/python/ss_renpy/__init__.py; do
    [ -e "$CHECK/$f" ] || fail "$ARTIFACT is missing $f"
  done

  # The version inside the folder is the one the archive is named after. This is
  # the same check as the tag one above, from the other end: it catches a zip
  # built from a tree whose __init__.py was edited after the name was computed.
  PACKED="$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' \
    "$CHECK/spritestudio/python/ss_renpy/__init__.py" 2>/dev/null || true)"
  if [ "$PACKED" != "$VERSION" ]; then
    fail "$ARTIFACT contains __version__ $PACKED, expected $VERSION"
  fi

  # Compiled bytecode and caches are excluded on purpose: .rpyc files built
  # against this Ren'Py would be stale in a creator's project.
  if unzip -Z1 "$OUT/$ARTIFACT" | grep -qE '\.rpyc$|/__pycache__/'; then
    fail "$ARTIFACT contains .rpyc or __pycache__ (the -x patterns did not hold)"
  fi

  rm -rf "$CHECK"

  if [ "$DEMO" = "build" ]; then
    # A Ren'Py Web export the browser can actually start.
    for f in index.html game.zip; do
      unzip -Z1 "$OUT/$DEMO_ZIP" | grep -qx "$f" || fail "$DEMO_ZIP has no $f"
    done
    # The Brain is read out of game.zip at startup (ssruntime_web.load_library),
    # so the export plays only if both runtime files were packed into it.
    DEMO_CHECK="$ROOT_DIR/build/release-democheck"
    rm -rf "$DEMO_CHECK"
    if unzip -q "$OUT/$DEMO_ZIP" game.zip -d "$DEMO_CHECK"; then
      for f in ssruntime.js ssruntime_bg.wasm; do
        unzip -Z1 "$DEMO_CHECK/game.zip" | grep -qx "game/spritestudio/libs/web/$f" \
          || fail "$DEMO_ZIP: game.zip has no spritestudio/libs/web/$f"
      done
    fi
    rm -rf "$DEMO_CHECK"
    [ -n "$FAILED" ] || echo "   Web demo: index.html, and game.zip with the runtime"
  fi

  # Each alias is the same bytes as the zip it stands in for.
  cmp -s "$OUT/$ARTIFACT" "$OUT/$ALIAS" || fail "$ALIAS is not identical to $ARTIFACT"
  if [ "$DEMO" = "build" ]; then
    cmp -s "$OUT/$DEMO_ZIP" "$OUT/$DEMO_ALIAS" || fail "$DEMO_ALIAS is not identical to $DEMO_ZIP"
  fi

  ( cd "$OUT" && sha256 -c SHA256SUMS > /dev/null ) || fail "SHA256SUMS does not verify"

  if [ -n "$FAILED" ]; then
    echo "" >&2
    echo "$APP: the release in $OUT is not shippable:$FAILED" >&2
    exit 1
  fi
  echo "   aliases identical, SHA256SUMS verified"
  echo "   all checks passed"
else
  step "verify=no -- the archives are not checked"
fi

# --- done ------------------------------------------------------------------
echo ""
echo "$APP: done -> $OUT  (${TAG:-$MANIFEST_TAG})"
echo ""
( cd "$OUT" && ls -l ./*.zip SHA256SUMS | sed 's|^|  |' )
echo ""
echo "$APP: this is what release.yml attaches to the draft Release."
echo "$APP: try the plugin before shipping it -- unzip into a Ren'Py project's game/:"
echo "  unzip -o $OUT/$ARTIFACT -d <your-renpy-project>/game/"
