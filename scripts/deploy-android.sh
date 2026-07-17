#!/usr/bin/env bash
#
# Build a signed Android package (APK by default, or an AAB with --bundle) of the
# SSPlayer demo using Ren'Py's RAPT toolchain (launcher android_build). The native
# "Brain" .so must land in the APK's lib/<abi>/ (jniLibs) — the only place Android's
# linker will dlopen from — so this script stages game/spritestudio/libs/android/<abi>/
# into RAPT's jniLibs before building; ssruntime.py then loads it by soname at
# runtime (abi ∈ arm64-v8a / armeabi-v7a / x86_64, the NDK names).
#
# This script auto-fetches the Ren'Py SDK and RAPT if missing, but it does NOT
# perform the three INTERACTIVE one-time setup steps (do them once in the launcher
# GUI:  renpy-sdk/renpy.sh renpy-sdk/launcher  -> Android):
#   * Install SDK  : downloads the Android SDK/NDK/JDK into renpy-sdk/rapt/Sdk/
#   * Configure    : sets the package name / app name in android.json (required)
#   * Generate Keys: creates android.keystore (+ bundle.keystore) used to sign
# RAPT itself (the packaging tool) is fetched by scripts/fetch-renpy-android.sh.
#
# Usage: scripts/deploy-android.sh [dest_dir] [--bundle] [--install] [--launch]
#   dest_dir  : output folder (default: dist)
#   --bundle  : build an .aab App Bundle (Play upload) instead of a Universal .apk
#   --install : adb-install onto a connected device after the build
#   --launch  : install then launch on the device (implies --install)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RENPY_SDK="$ROOT_DIR/renpy-sdk"
LAUNCHER="$RENPY_SDK/launcher"
RAPT="$RENPY_SDK/rapt"
LIBS="$ROOT_DIR/game/spritestudio/libs"

# --- parse args (one positional dest + passthrough flags) -----------------
DEST=""; BUNDLE=0; PASS=()
for a in "$@"; do
  case "$a" in
    -h|--help|help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --bundle)  BUNDLE=1; PASS+=(--bundle) ;;
    --install) PASS+=(--install) ;;
    --launch)  PASS+=(--launch) ;;
    -*) echo "deploy-android.sh: unknown flag '$a'" >&2; exit 2 ;;
    *) [ -z "$DEST" ] && DEST="$a" || { echo "deploy-android.sh: unexpected extra arg '$a'" >&2; exit 2; } ;;
  esac
done
DEST="${DEST:-dist}"
case "$DEST" in /*) : ;; *) DEST="$ROOT_DIR/$DEST" ;; esac   # absolutise

# --- prerequisites --------------------------------------------------------
# Ren'Py SDK (fetch on demand, same as deploy-desktop.sh)
if [ ! -x "$RENPY_SDK/renpy.sh" ]; then
  echo "deploy-android.sh: Ren'Py SDK not found at renpy-sdk/ — fetching it first..."
  "$ROOT_DIR/scripts/fetch-renpy-sdk.sh"
fi
# RAPT — the Android packaging tool (fetch on demand)
if [ ! -f "$RAPT/android.py" ]; then
  echo "deploy-android.sh: Ren'Py Android support (RAPT) not found — fetching it first..."
  "$ROOT_DIR/scripts/fetch-renpy-android.sh"
fi
# Android SDK/NDK installed by RAPT's "Install SDK" (adb is its sentinel)
if [ ! -x "$RAPT/Sdk/platform-tools/adb" ]; then
  echo "deploy-android.sh: Android SDK not installed (no renpy-sdk/rapt/Sdk/platform-tools/adb)." >&2
  echo "  Run it once, interactively, from the launcher GUI:" >&2
  echo "    renpy-sdk/renpy.sh renpy-sdk/launcher    ->  Android  ->  Install SDK" >&2
  exit 1
fi
# Signing keys (android.keystore in the project root; bundle.keystore for --bundle)
if [ ! -f "$ROOT_DIR/android.keystore" ] || { [ "$BUNDLE" = 1 ] && [ ! -f "$ROOT_DIR/bundle.keystore" ]; }; then
  echo "deploy-android.sh: signing key(s) missing in the project root (android.keystore$([ "$BUNDLE" = 1 ] && echo ' + bundle.keystore'))." >&2
  echo "  Generate them once from the launcher GUI:" >&2
  echo "    renpy-sdk/renpy.sh renpy-sdk/launcher    ->  Android  ->  Generate Keys" >&2
  exit 1
fi
# App configuration (package name in android.json). RAPT's build refuses to run
# ("Run configure before attempting to build the app.") when package is unset.
if [ ! -f "$ROOT_DIR/android.json" ] || grep -Eq '"package"[[:space:]]*:[[:space:]]*null' "$ROOT_DIR/android.json"; then
  echo "deploy-android.sh: app not configured (no package name in android.json)." >&2
  echo "  Configure it once from the launcher GUI:" >&2
  echo "    renpy-sdk/renpy.sh renpy-sdk/launcher    ->  Android  ->  Configure" >&2
  exit 1
fi
# Native library for the primary device ABI (arm64-v8a). armeabi-v7a/x86_64 are
# optional (older phones / emulators); warn but do not block if they are absent.
if [ ! -f "$LIBS/android/arm64-v8a/libssruntime.so" ]; then
  echo "deploy-android.sh: native library missing for Android:" >&2
  echo "    game/spritestudio/libs/android/arm64-v8a/libssruntime.so" >&2
  echo "  Without it the app builds but SSPlayer fails at load. Get it with" >&2
  echo "  scripts/download-sdk.sh (prebuilt) or scripts/build-runtime.sh platform=android build=release, then re-run." >&2
  exit 1
fi
for abi in armeabi-v7a x86_64; do
  [ -f "$LIBS/android/$abi/libssruntime.so" ] || \
    echo "deploy-android.sh: note — no libs/android/$abi/libssruntime.so; the app will not run on $abi devices/emulators." >&2
done

# Stage the Brain into RAPT's jniLibs so RAPT bundles it into the APK's lib/<abi>/.
# Android's linker only dlopen()s native libs the installer extracted to the app's
# read-only nativeLibraryDir (W^X since API 29) — i.e. libs shipped in lib/<abi>/.
# RAPT sources jniLibs from prototype/renpyandroid/src/main/jniLibs/<abi>/ (copied
# into every build), so mirror our per-ABI .so there. Consumers building via the
# stock launcher must do this copy once by hand — see docs/en/export.md (Android Export).
JNILIBS="$RAPT/prototype/renpyandroid/src/main/jniLibs"
for abi in arm64-v8a armeabi-v7a x86_64; do
  so="$LIBS/android/$abi/libssruntime.so"
  [ -f "$so" ] || continue
  mkdir -p "$JNILIBS/$abi"
  cp -f "$so" "$JNILIBS/$abi/libssruntime.so"
  echo "deploy-android.sh: staged Brain -> jniLibs/$abi/libssruntime.so"
done

# --- build ----------------------------------------------------------------
mkdir -p "$DEST"
echo ">> building Android $([ "$BUNDLE" = 1 ] && echo 'App Bundle (.aab)' || echo 'package (.apk)') -> $DEST"
"$RENPY_SDK/renpy.sh" "$LAUNCHER" android_build "$ROOT_DIR" --dest "$DEST" ${PASS[@]+"${PASS[@]}"}

# --- report ---------------------------------------------------------------
OUT="$(ls -t "$DEST"/*.aab "$DEST"/*.apk 2>/dev/null | head -1 || true)"
if [ -n "$OUT" ]; then
  echo "deploy-android.sh: done -> $OUT"
  echo "  Install on a connected device:  \"$RAPT/Sdk/platform-tools/adb\" install -r \"$OUT\""
  echo "  (or re-run with --install / --launch to have RAPT do it.)"
else
  echo "deploy-android.sh: build finished but no .apk/.aab found in $DEST — inspect the output above." >&2
  exit 1
fi
