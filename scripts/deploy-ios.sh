#!/usr/bin/env bash
#
# Generate an Xcode project for the SSPlayer demo using Ren'Py's renios toolchain
# (launcher ios_create / ios_populate). Unlike Android (which builds a finished
# .apk) the iOS target stops at an Xcode project: Apple code signing lives in
# Xcode, so the final .ipa is produced there (Product > Archive). Requires macOS
# + Xcode. The native "Brain" for iOS is a *dynamic* xcframework
# (game/spritestudio/libs/ios/libssruntime.xcframework); ssruntime.py loads it
# via CDLL(None), which works once it is linked + embedded so dyld loads it at
# launch. This script generates the project, fetches what's needed, and STAGES the
# xcframework into the project's Frameworks/ (beside renios's MetalANGLE) so the
# project is self-contained — but it does NOT wire it into the pbxproj (no fragile
# patcher). You add it to the target ONCE via Xcode's "Embed & Sign" (the closing
# message spells it out) — the same one step a library consumer does through the
# stock launcher (see docs/export.md -> iOS Export). After that a Simulator Run
# works; only device signing is additionally left to you.
#
# This script auto-fetches the Ren'Py SDK and renios if missing. It then either
# CREATES a fresh Xcode project (first run) or POPULATES the existing one with an
# up-to-date game build (re-runs) — pick automatically, or force with a flag.
#
# Usage: scripts/deploy-ios.sh [dest_dir] [--recreate] [--open]
#   dest_dir   : Xcode project folder (default: dist/ios). The .xcodeproj lands inside.
#   --recreate : delete and re-create the project from scratch (default: reuse + populate)
#   --open     : open the generated .xcodeproj in Xcode when done
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RENPY_SDK="$ROOT_DIR/renpy-sdk"
LAUNCHER="$RENPY_SDK/launcher"
RENIOS="$RENPY_SDK/renios"
LIBS="$ROOT_DIR/game/spritestudio/libs"

# --- parse args (one positional dest + flags) -----------------------------
DEST=""; RECREATE=0; OPEN=0
for a in "$@"; do
  case "$a" in
    -h|--help|help) sed -n '/^# Usage:/,/^[^#]/p' "$0" | sed '/^[^#]/d; s/^# \{0,1\}//'; exit 0 ;;
    --recreate) RECREATE=1 ;;
    --open)     OPEN=1 ;;
    -*) echo "deploy-ios.sh: unknown flag '$a'" >&2; exit 2 ;;
    *) [ -z "$DEST" ] && DEST="$a" || { echo "deploy-ios.sh: unexpected extra arg '$a'" >&2; exit 2; } ;;
  esac
done
DEST="${DEST:-dist/ios}"
case "$DEST" in /*) : ;; *) DEST="$ROOT_DIR/$DEST" ;; esac   # absolutise

# --- prerequisites --------------------------------------------------------
# iOS packaging is macOS + Xcode only (Apple toolchain).
if [ "$(uname -s)" != "Darwin" ]; then
  echo "deploy-ios.sh: iOS packaging requires macOS with Xcode — cannot build on $(uname -s)." >&2
  exit 1
fi
command -v xcodebuild >/dev/null || {
  echo "deploy-ios.sh: 'xcodebuild' not on PATH — install Xcode and run 'xcode-select --install'." >&2
  exit 1
}
# Ren'Py SDK (fetch on demand, same as deploy-android.sh)
if [ ! -x "$RENPY_SDK/renpy.sh" ]; then
  echo "deploy-ios.sh: Ren'Py SDK not found at renpy-sdk/ — fetching it first..."
  "$ROOT_DIR/scripts/fetch-renpy-sdk.sh"
fi
# renios — the iOS support package (fetch on demand)
if [ ! -d "$RENIOS" ]; then
  echo "deploy-ios.sh: Ren'Py iOS support (renios) not found — fetching it first..."
  "$ROOT_DIR/scripts/fetch-renpy-ios.sh"
fi
# Native library — the DYNAMIC xcframework (must contain dylibs). It is not
# linked automatically; you add it to the target once via Embed & Sign (see the
# closing message). A static xcframework would link but get dead-stripped.
if [ ! -d "$LIBS/ios/libssruntime.xcframework" ] || \
   [ -z "$(find "$LIBS/ios/libssruntime.xcframework" -name '*.dylib' -print -quit 2>/dev/null)" ]; then
  echo "deploy-ios.sh: iOS native library missing, or not the dynamic xcframework:" >&2
  echo "    game/spritestudio/libs/ios/libssruntime.xcframework   (must contain *.dylib)" >&2
  echo "  Get it with scripts/download-sdk.sh (prebuilt) or" >&2
  echo "  scripts/build-runtime.sh platform=ios build=release, then re-run." >&2
  exit 1
fi

# --- create vs populate ---------------------------------------------------
# First run makes the Xcode project (ios_create); later runs just refresh the
# bundled game build in place (ios_populate). --recreate forces a clean create.
HAS_PROJECT=0
[ -d "$DEST" ] && ls -d "$DEST"/*.xcodeproj >/dev/null 2>&1 && HAS_PROJECT=1
if [ "$RECREATE" = 1 ]; then
  rm -rf "$DEST"; HAS_PROJECT=0
fi

mkdir -p "$(dirname "$DEST")"
if [ "$HAS_PROJECT" = 1 ]; then
  echo ">> populating existing Xcode project -> $DEST"
  "$RENPY_SDK/renpy.sh" "$LAUNCHER" ios_populate "$ROOT_DIR" "$DEST"
else
  echo ">> creating Xcode project -> $DEST"
  "$RENPY_SDK/renpy.sh" "$LAUNCHER" ios_create "$ROOT_DIR" "$DEST"
fi

# Generation must have produced a project.pbxproj. If only a stale .xcodeproj
# wrapper survived (classically: the project was OPEN in Xcode during a
# --recreate, so `rm -rf` and the regenerate raced), fail loudly instead of
# "done" — Xcode would just report "missing its project.pbxproj file".
if [ -z "$(ls -d "$DEST"/*.xcodeproj/project.pbxproj 2>/dev/null | head -1 || true)" ]; then
  echo "deploy-ios.sh: no project.pbxproj under $DEST after generation." >&2
  echo "  Quit Xcode (it may be holding the old project), then:" >&2
  echo "    rm -rf \"$DEST\" && scripts/deploy-ios.sh \"$DEST\"" >&2
  exit 1
fi

# --- stage the Brain into the project (you Embed & Sign it once in Xcode) -----
# Copy the dynamic xcframework next to renios's own MetalANGLE.xcframework so the
# project is self-contained. deploy-ios deliberately does NOT wire it into the
# pbxproj (no fragile patcher); you add it once in Xcode. Refreshed every run so a
# rebuilt Brain propagates, and it survives ios_populate.
XCF="$LIBS/ios/libssruntime.xcframework"
mkdir -p "$DEST/Frameworks"
rm -rf "$DEST/Frameworks/libssruntime.xcframework"
cp -R "$XCF" "$DEST/Frameworks/"

# --- report ---------------------------------------------------------------
XCODEPROJ="$(ls -d "$DEST"/*.xcodeproj 2>/dev/null | head -1 || true)"
if [ -z "$XCODEPROJ" ]; then
  echo "deploy-ios.sh: finished but no .xcodeproj found in $DEST — inspect the output above." >&2
  exit 1
fi
echo "deploy-ios.sh: done -> $XCODEPROJ"
echo "  The Brain is staged in the project: $DEST/Frameworks/libssruntime.xcframework"
echo "  One-time in Xcode — add it to the app target:"
echo "    General > Frameworks, Libraries, and Embedded Content > +  > Add Other… > Add Files…"
echo "    -> Frameworks/libssruntime.xcframework   (then set it to 'Embed & Sign')"
echo "  Persists across re-runs / ios_populate, so it really is one-time."
echo "  Then select a Simulator and Run; for device set your signing team and Archive."
if [ "$OPEN" = 1 ]; then
  echo "  Opening in Xcode..."
  open "$XCODEPROJ"
else
  echo "  Open it with:  open \"$XCODEPROJ\"   (or re-run with --open)"
fi
