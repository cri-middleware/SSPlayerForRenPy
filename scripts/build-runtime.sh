#!/usr/bin/env bash
#
# Build the native runtime libssruntime from the SpriteStudio-SDK and place it
# in the library's per-platform/arch layout. Interface mirrors SSPlayerForUnity's
# build-runtime.sh (platform=/arch=/build=), but for DESKTOP we build only the
# feature-enabled `ssruntime` cdylib directly (NOT via the SDK release-*.sh,
# which also build the whole workspace + ssconverter — wasteful here). macOS
# universal = one build per arch + lipo (2 compiles, not 4).
#
#   game/spritestudio/libs/
#     macos/libssruntime.dylib                 (universal arm64+x86_64 on build=release)
#     windows/<arch>/ssruntime.dll   linux/<arch>/libssruntime.so
#     android/<abi>/libssruntime.so  ios/libssruntime.xcframework  web/libssruntime.a
#
# android/ios/web are toolchain-heavy cross builds and DO delegate to the SDK
# release scripts (reserved path; Ren'Py-side integration is separate).
#
# Usage: scripts/build-runtime.sh [platform=<p>] [arch=<a>] [build=<m>] [hostbuild=<auto|false>]
#   platform : windows macos linux android ios web   (default: host)
#   arch     : x86_64 arm64 universal ...            (default: host arch)
#   build    : debug release                         (default: debug)
#   hostbuild: false to force cross even on host
#
# SDK location: $SSSDK, else ./SpriteStudio-SDK, else ../SpriteStudio-SDK.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LIB_ROOT="$ROOT_DIR/game/spritestudio/libs"

usage() { sed -n '/^# Usage:/,/^# SDK location/p' "$0" | sed 's/^# \{0,1\}//'; }

case "${OSTYPE:-}" in
  msys*|cygwin*|win*) HOST_PLATFORM=windows ;;
  darwin*)            HOST_PLATFORM=macos ;;
  *)                  HOST_PLATFORM=linux ;;
esac
HOST_ARCH="$(uname -m)"; [ "$HOST_ARCH" = "aarch64" ] && HOST_ARCH=arm64

PLATFORM="$HOST_PLATFORM"; ARCH="$HOST_ARCH"; BUILD_MODE="debug"; HOSTBUILD="auto"
for item in "$@"; do
  case "$item" in
    platform=*)  PLATFORM="${item#*=}" ;;
    arch=*)      ARCH="${item#*=}" ;;
    build=*)     BUILD_MODE="${item#*=}" ;;
    hostbuild=*) HOSTBUILD="${item#*=}" ;;
    -h|--help|help) usage; exit 0 ;;
    *) echo "build-runtime.sh: unknown arg '$item'" >&2; usage; exit 2 ;;
  esac
done

# --- locate the SDK -------------------------------------------------------
SDK_DIR="${SSSDK:-}"
if [ -z "$SDK_DIR" ]; then
  for cand in "$ROOT_DIR/SpriteStudio-SDK" "$ROOT_DIR/../SpriteStudio-SDK"; do
    if [ -f "$cand/Cargo.toml" ]; then SDK_DIR="$(cd "$cand" && pwd)"; break; fi
  done
fi
if [ -z "$SDK_DIR" ] || [ ! -f "$SDK_DIR/Cargo.toml" ]; then
  echo "build-runtime.sh: SpriteStudio-SDK not found (init the submodule or set SSSDK)" >&2
  exit 1
fi
command -v cargo >/dev/null || { echo "build-runtime.sh: cargo (Rust) not on PATH" >&2; exit 1; }

IS_HOST_BUILD=false
if [ "$HOSTBUILD" != "false" ] && [ "$PLATFORM" = "$HOST_PLATFORM" ] \
   && [ "$ARCH" = "$HOST_ARCH" ] && [ "$BUILD_MODE" = "debug" ]; then
  IS_HOST_BUILD=true
fi
echo "Building for $PLATFORM ($ARCH) in $BUILD_MODE mode (host build: $IS_HOST_BUILD)"
CARGO_FLAGS=""; [ "$BUILD_MODE" = "release" ] && CARGO_FLAGS="--release"

# build the feature-enabled ssruntime cdylib (optionally for a --target triple)
build_ss() { ( cd "$SDK_DIR" && cargo build $CARGO_FLAGS "$@" -p ssruntime --features libc_alloc,panic-handler ); }
place() { mkdir -p "$LIB_ROOT/$1"; cp "$2" "$LIB_ROOT/$1/${3:-$(basename "$2")}"; echo "   -> game/spritestudio/libs/$1/${3:-$(basename "$2")}"; }

# licenses (mirror Unity)
mkdir -p "$LIB_ROOT"
[ -f "$SDK_DIR/LICENSE.md" ] && cp "$SDK_DIR/LICENSE.md" "$LIB_ROOT/"
[ -f "$SDK_DIR/target/licenses/THIRD-PARTY-LICENSES.ssruntime.md" ] && \
  cp "$SDK_DIR/target/licenses/THIRD-PARTY-LICENSES.ssruntime.md" "$LIB_ROOT/"

T="$SDK_DIR/target"
case "$PLATFORM" in
  macos)
    if [ "$IS_HOST_BUILD" = true ]; then
      build_ss
      place macos "$T/$BUILD_MODE/libssruntime.dylib"
      echo "   (host-arch debug build; use build=release for a universal dylib)"
    else
      # universal: build each arch's ssruntime once, then lipo (2 compiles)
      build_ss --target aarch64-apple-darwin
      build_ss --target x86_64-apple-darwin
      mkdir -p "$LIB_ROOT/macos"
      lipo -create "$T/aarch64-apple-darwin/$BUILD_MODE/libssruntime.dylib" \
                   "$T/x86_64-apple-darwin/$BUILD_MODE/libssruntime.dylib" \
                   -output "$LIB_ROOT/macos/libssruntime.dylib"
      echo "   -> game/spritestudio/libs/macos/libssruntime.dylib (universal arm64+x86_64)"
    fi ;;
  linux)
    if [ "$IS_HOST_BUILD" = true ]; then build_ss; src="$T/$BUILD_MODE/libssruntime.so"
    else triple=$([ "$ARCH" = x86_64 ] && echo x86_64-unknown-linux-gnu || echo aarch64-unknown-linux-gnu)
         build_ss --target "$triple"; src="$T/$triple/$BUILD_MODE/libssruntime.so"; fi
    place "linux/$ARCH" "$src" ;;
  windows)
    if [ "$IS_HOST_BUILD" = true ]; then build_ss; src="$T/$BUILD_MODE/ssruntime.dll"
    else triple=$([ "$ARCH" = arm64 ] && echo aarch64-pc-windows-msvc || echo x86_64-pc-windows-msvc)
         build_ss --target "$triple"; src="$T/$triple/$BUILD_MODE/ssruntime.dll"; fi
    place "windows/$ARCH" "$src" ;;

  # --- toolchain-heavy cross builds: delegate to the SDK release scripts ---
  android)
    bash "$SDK_DIR/scripts/release-android.sh" "$BUILD_MODE"
    for pair in "aarch64-linux-android:arm64-v8a" "armv7-linux-androideabi:armeabi-v7a" "x86_64-linux-android:x86_64"; do
      tr="${pair%%:*}"; abi="${pair##*:}"
      [ -f "$T/$tr/$BUILD_MODE/libssruntime.so" ] && place "android/$abi" "$T/$tr/$BUILD_MODE/libssruntime.so"
    done ;;
  ios)
    bash "$SDK_DIR/scripts/release-ios-xcframework.sh" "$BUILD_MODE"
    mkdir -p "$LIB_ROOT/ios"; rm -rf "$LIB_ROOT/ios/libssruntime.xcframework"
    cp -R "$T/xcframework/static/libssruntime.xcframework" "$LIB_ROOT/ios/"
    echo "   -> game/spritestudio/libs/ios/libssruntime.xcframework" ;;
  web)
    bash "$SDK_DIR/scripts/release-emscripten.sh" "$BUILD_MODE"
    place web "$T/wasm32-unknown-unknown/$BUILD_MODE/libssruntime.a" ;;
  *) echo "build-runtime.sh: unknown platform '$PLATFORM'" >&2; exit 2 ;;
esac
echo "build-runtime.sh: done."
