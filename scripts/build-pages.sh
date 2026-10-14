#!/usr/bin/env bash
#
# Build the GitHub Pages site locally -- everything .github/workflows/pages.yml
# publishes, in the same order: the documentation in both locales into site/,
# then the playable Ren'Py Web demo into site/demo/.
#
#   scripts/build-pages.sh                       # docs + demo from the latest release
#   scripts/build-pages.sh serve=yes             # ... and serve site/ on :8000
#   scripts/build-pages.sh demo=build            # build the demo here instead
#   scripts/build-pages.sh demo=build sdk=build  # ... from a locally built SDK too
#   scripts/build-pages.sh demo=skip             # documentation only
#
# The demo is a release ASSET, not something pages.yml builds: release.yml
# exports it (fetch-renpy-web + deploy-examples + deploy-web) and attaches
# SSPlayerForRenPy-web-demo.zip to the release; pages.yml only downloads it.
# demo=download is that path and the default -- it is what a Pages deploy will
# actually publish. demo=build runs those release.yml steps here instead, which
# is the only way to see a demo that is not in a release yet.
#
# Ordering: the English documentation build clears site/, and both the Japanese
# site (site/ja) and the demo (site/demo) live inside it -- so the demo goes in
# last, exactly as in pages.yml. Rerunning is safe; nothing here is incremental.
#
# What this does NOT reproduce is the deploy job (actions/deploy-pages) -- there
# is no local equivalent of publishing. Serving site/ over HTTP is as close as a
# local run gets, and it is enough to check every link, both locales and the
# demo actually running in a browser.
set -euo pipefail

APP="$(basename "$0")"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# The version-less alias release.yml uploads next to the pinned zip; pages.yml
# downloads this same name.
DEMO_ASSET="SSPlayerForRenPy-web-demo.zip"
# Where deploy-web.sh writes the export before it is copied into site/demo --
# the same directory name release.yml uses, and already gitignored.
WORK_DIR="web_out"

# --- options --------------------------------------------------------------
DEMO="download"
SDK="download"
TAG=""
ZIP=""
DOCS="yes"
PREPARE="auto"
VENV=".venv"
SERVE="no"
PORT="8000"

usage () {
  echo "Usage: $APP [options]"
  echo "$APP options:"
  echo "  demo=<download|build|skip>"
  echo "                          Where site/demo comes from (default: $DEMO)"
  echo "                          download = the release asset pages.yml publishes"
  echo "                          build    = run the release.yml Web export here"
  echo "                          skip     = documentation only"
  echo "  sdk=<download|build|skip>"
  echo "                          Where the SpriteStudio SDK libs come from (default: $SDK)"
  echo "                          download = download-sdk.sh, the release pinned by"
  echo "                                     scripts/SDK_VERSION.txt (what a released"
  echo "                                     demo is built with)"
  echo "                          build    = build-runtime.sh, from the submodule sources"
  echo "                          skip     = use game/spritestudio/libs/ as it stands"
  echo "                          Only consulted for demo=build -- a downloaded demo"
  echo "                          carries its own runtime."
  echo "  tag=<vX.Y.Z>            Release to take the demo from (default: latest)."
  echo "                          demo=download only."
  echo "  zip=<path>              Use this already-downloaded $DEMO_ASSET"
  echo "                          instead of asking gh for one. demo=download only."
  echo "  docs=<yes|no>           Build the documentation (default: $DOCS). no keeps"
  echo "                          whatever site/ already holds -- handy when only the"
  echo "                          demo is being re-checked."
  echo "  prepare=<auto|yes|no>   Run prepare-docs.sh first (default: $PREPARE)."
  echo "                          auto = only when no zensical is found."
  echo "  venv=<dir>              Virtualenv for the docs toolchain, relative to the"
  echo "                          repo root (default: $VENV). Passed to prepare-docs.sh"
  echo "                          and build-docs.sh."
  echo "  serve=<yes|no>          Serve site/ over HTTP when the build is done"
  echo "                          (default: $SERVE). Foreground; Ctrl-C to stop."
  echo "  port=<n>                Port for serve=yes (default: $PORT)"
  echo "  -h | --help             Show this help"
  echo ""
  echo "Output: site/ (en) + site/ja/ (ja) + site/demo/ -- the exact tree pages.yml"
  echo "uploads. The documentation builds are --strict, so a broken internal link or a"
  echo "nav entry pointing at a missing page fails the build here rather than on a"
  echo "release publish."
  echo ""
  echo "The demo needs a real HTTP server (a browser cannot ES-module import from"
  echo "file://), so open it through serve=yes, not by double-clicking the file."
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
        # Lower-cased where the option is an enum; tag=/zip=/venv=/port= are not.
        demo)    DEMO="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        sdk)     SDK="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        tag)     TAG="$value" ;;
        zip)     ZIP="$value" ;;
        docs)    DOCS="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        prepare) PREPARE="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        venv)    VENV="$value" ;;
        serve)   SERVE="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
        port)    PORT="$value" ;;
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

case "$DEMO" in
  download|build|skip) ;;
  *) echo "$APP: demo must be download, build or skip (got '$DEMO')" >&2; exit 2 ;;
esac
case "$SDK" in
  download|build|skip) ;;
  *) echo "$APP: sdk must be download, build or skip (got '$SDK')" >&2; exit 2 ;;
esac
case "$DOCS" in yes|no) ;; *) echo "$APP: docs must be yes or no (got '$DOCS')" >&2; exit 2 ;; esac
case "$PREPARE" in auto|yes|no) ;; *) echo "$APP: prepare must be auto, yes or no (got '$PREPARE')" >&2; exit 2 ;; esac
case "$SERVE" in yes|no) ;; *) echo "$APP: serve must be yes or no (got '$SERVE')" >&2; exit 2 ;; esac
case "$PORT" in ''|*[!0-9]*) echo "$APP: port must be a number (got '$PORT')" >&2; exit 2 ;; esac

# tag=/zip= describe where a downloaded demo comes from, so they are meaningless
# — and, silently ignored, misleading — anywhere else.
if [ "$DEMO" != "download" ]; then
  if [ -n "$TAG" ]; then echo "$APP: tag= applies to demo=download (got demo=$DEMO)" >&2; exit 2; fi
  if [ -n "$ZIP" ]; then echo "$APP: zip= applies to demo=download (got demo=$DEMO)" >&2; exit 2; fi
fi
if [ -n "$TAG" ] && [ -n "$ZIP" ]; then
  echo "$APP: tag= and zip= are alternatives — zip= is already a specific build" >&2
  exit 2
fi

SDK_NOTE=""
[ "$DEMO" = "build" ] || SDK_NOTE=" (unused: demo=$DEMO)"
SERVE_NOTE=""
[ "$SERVE" = "no" ] || SERVE_NOTE=" (port $PORT)"

echo "options"
echo "  demo    => $DEMO${TAG:+ (tag $TAG)}${ZIP:+ (zip $ZIP)}"
echo "  sdk     => $SDK$SDK_NOTE"
echo "  docs    => $DOCS"
echo "  prepare => $PREPARE"
echo "  venv    => $VENV"
echo "  serve   => $SERVE$SERVE_NOTE"
echo ""

# Every script here resolves its own paths from the repo root, and site/ is
# written relative to it, so run from there however this was invoked.
cd "$ROOT_DIR"

SITE_DIR="$ROOT_DIR/site"
DEMO_DIR="$SITE_DIR/demo"

TMP_DIR=""
cleanup () {
  if [ -n "$TMP_DIR" ]; then rm -rf "$TMP_DIR"; fi
}
trap cleanup EXIT

step () {
  echo ""
  echo ">> $*"
  "$@"
}

# --- documentation toolchain ----------------------------------------------
# Same probe as build-docs.sh: a venv laid out either way, else PATH (which is
# how a run with no venv at all still works).
have_zensical () {
  local venv_bin="$ROOT_DIR/$VENV/bin"
  [ -d "$ROOT_DIR/$VENV/Scripts" ] && venv_bin="$ROOT_DIR/$VENV/Scripts"
  [ -x "$venv_bin/zensical" ] || [ -x "$venv_bin/zensical.exe" ] \
    || command -v zensical > /dev/null 2>&1
}

if [ "$DOCS" = "yes" ]; then
  case "$PREPARE" in
    yes)
      step ./scripts/prepare-docs.sh venv="$VENV"
      ;;
    auto)
      if have_zensical; then
        echo "$APP: zensical already available; skipping prepare-docs.sh (prepare=yes forces it)"
      else
        step ./scripts/prepare-docs.sh venv="$VENV"
      fi
      ;;
    no) ;;
  esac

  # Both locales, English first — build-docs.sh owns that order.
  step ./scripts/build-docs.sh venv="$VENV"
else
  echo "$APP: docs=no — site/ keeps whatever the last build left there"
fi

# --- demo: download the release asset (what pages.yml does) ----------------
download_demo () {
  local src="$ZIP"

  command -v unzip > /dev/null 2>&1 || { echo "$APP: unzip not on PATH" >&2; exit 1; }

  if [ -n "$src" ]; then
    [ -f "$src" ] || { echo "$APP: no such file: $src" >&2; exit 1; }
    echo ""
    echo ">> using $src"
  else
    command -v gh > /dev/null 2>&1 || {
      echo "$APP: gh (GitHub CLI) not on PATH — install it, pass zip=<path> to a" >&2
      echo "$APP: downloaded $DEMO_ASSET, or build the demo with demo=build" >&2
      exit 1
    }
    TMP_DIR="$(mktemp -d)"
    echo ""
    if [ -n "$TAG" ]; then
      echo ">> gh release download $TAG --pattern $DEMO_ASSET"
      gh release download "$TAG" --pattern "$DEMO_ASSET" --dir "$TMP_DIR" || demo_download_failed
    else
      echo ">> gh release download (latest) --pattern $DEMO_ASSET"
      gh release download --pattern "$DEMO_ASSET" --dir "$TMP_DIR" || demo_download_failed
    fi
    src="$TMP_DIR/$DEMO_ASSET"
  fi

  echo ">> unpacking into site/demo/"
  rm -rf "$DEMO_DIR"
  mkdir -p "$DEMO_DIR"
  unzip -q "$src" -d "$DEMO_DIR"
}

# Reached from pages.yml as well as from a working tree, so it says what is wrong
# rather than assuming the reader can just build the demo instead — on the Pages
# runner they cannot.
demo_download_failed () {
  echo "" >&2
  echo "$APP: could not download $DEMO_ASSET from ${TAG:-the latest release}." >&2
  echo "$APP: release.yml attaches that asset, so it exists only on releases that" >&2
  echo "$APP: workflow produced — check the release actually carries it." >&2
  echo "$APP: In a working tree, '$APP demo=build' runs the same export steps instead" >&2
  echo "$APP: (that needs the SpriteStudio-SDK submodule, which pages.yml never checks out)." >&2
  exit 1
}

# --- demo: build it here (what release.yml does) ---------------------------
build_demo () {
  case "$SDK" in
    download)
      step ./scripts/download-sdk.sh || {
        echo "" >&2
        echo "$APP: download-sdk.sh failed — the libs it fetches come from the" >&2
        echo "$APP: SpriteStudio-SDK release pinned by scripts/SDK_VERSION.txt." >&2
        echo "$APP: To build them from the submodule instead: $APP demo=build sdk=build" >&2
        exit 1
      }
      ;;
    build)
      # Two builds, because the export needs two different things: the wasm
      # runtime the demo loads in the browser, and a host libssconverter for
      # deploy-examples.sh below. build=release for both, to match the libs
      # download-sdk.sh would have fetched.
      step ./scripts/build-runtime.sh platform=web build=release
      step ./scripts/build-runtime.sh build=release
      ;;
    skip) ;;
  esac

  if [ ! -f "$ROOT_DIR/game/spritestudio/libs/web/ssruntime.js" ]; then
    echo "$APP: no web runtime under game/spritestudio/libs/web/ — rerun with" >&2
    echo "$APP: sdk=download (or sdk=build) rather than sdk=$SDK" >&2
    exit 1
  fi

  # Fetch the Ren'Py SDK only when it is missing: fetch-renpy-sdk.sh wipes
  # renpy-sdk/ and re-downloads the whole thing, taking the Web support with it,
  # which would then have to be re-fetched too. CI starts from an empty runner
  # and so always fetches; a working tree usually has both already.
  if [ ! -x "$ROOT_DIR/renpy-sdk/renpy.sh" ]; then
    step ./scripts/fetch-renpy-sdk.sh
  else
    echo "$APP: renpy-sdk/ present; not re-fetching (it would be wiped and redownloaded)"
  fi
  if [ ! -d "$ROOT_DIR/renpy-sdk/web" ]; then
    step ./scripts/fetch-renpy-web.sh
  else
    echo "$APP: renpy-sdk/web present; not re-fetching"
  fi

  # The exporter packs game/ as it stands, so the playback data has to exist
  # before the export runs — same order as release.yml. web_out/ is emptied
  # first: the exporter overwrites what it produces but removes nothing, so a
  # file an earlier export swept in would otherwise ride along into site/demo
  # forever. CI gets that for free from a fresh runner.
  step ./scripts/deploy-examples.sh
  rm -rf "$ROOT_DIR/$WORK_DIR"
  step ./scripts/deploy-web.sh "$WORK_DIR"

  echo ""
  echo ">> copying $WORK_DIR/ into site/demo/"
  rm -rf "$DEMO_DIR"
  mkdir -p "$DEMO_DIR"
  cp -R "$ROOT_DIR/$WORK_DIR/." "$DEMO_DIR/"
}

case "$DEMO" in
  download) download_demo ;;
  build)    build_demo ;;
  skip)
    echo ""
    echo "$APP: demo=skip — site/demo is not part of this build"
    ;;
esac

# --- what landed ----------------------------------------------------------
echo ""
echo "$APP: done -> site/"
report () { # <path> <label>
  if [ -e "$ROOT_DIR/$1" ]; then
    echo "  $2: $1"
  else
    echo "  $2: MISSING ($1)"
  fi
}
report "site/index.html" "en  "
report "site/ja/index.html" "ja  "
if [ "$DEMO" != "skip" ]; then
  report "site/demo/index.html" "demo"
fi

# --- serve ----------------------------------------------------------------
PYTHON_CMD="python3"
command -v "$PYTHON_CMD" > /dev/null 2>&1 || PYTHON_CMD="python"

echo ""
if [ "$SERVE" = "yes" ]; then
  command -v "$PYTHON_CMD" > /dev/null 2>&1 || {
    echo "$APP: no python on PATH to serve with — use any static server on site/" >&2
    exit 1
  }
  echo "$APP: http://localhost:$PORT/  (docs)"
  echo "$APP: http://localhost:$PORT/ja/  (Japanese)"
  echo "$APP: http://localhost:$PORT/demo/  (Web demo)"
  echo "$APP: Ctrl-C to stop"
  echo ""
  # Python's http.server already serves .js as text/javascript and .wasm as
  # application/wasm, which is all the demo needs; any static server will do.
  exec "$PYTHON_CMD" -m http.server "$PORT" -d site
else
  echo "$APP: serve it (the demo needs HTTP, not file://):"
  echo "$APP:   $APP serve=yes"
  echo "$APP:   $PYTHON_CMD -m http.server $PORT -d site"
fi
