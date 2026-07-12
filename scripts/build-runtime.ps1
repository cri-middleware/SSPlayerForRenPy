#!/usr/bin/env pwsh
#
# Build the native runtime libssruntime from the SpriteStudio-SDK and place it
# in the library's per-platform/arch layout. Windows counterpart of
# scripts/build-runtime.sh; modeled on SSPlayerForUnity's build-runtime.ps1
# (same platform=/arch=/build= interface), adapted to the Ren'Py layout:
#
#   game\spritestudio\libs\
#     windows\x86_64\ssruntime.dll   windows\arm64\ssruntime.dll
#     macos\libssruntime.framework  linux\<arch>\libssruntime.so  (when cross-built)
#     android\<abi>\libssruntime.so  ios\libssruntime.xcframework  web\libssruntime.a
#
# Usage: scripts\build-runtime.ps1 [platform=<p>] [arch=<a>] [build=<m>] [hostbuild=<auto|false>]
#   platform : windows macos linux android ios web   (default: windows)
#   arch     : x86_64 arm64 ...                       (default: host arch)
#   build    : debug release                          (default: debug)
#
# SDK location: $env:SSSDK, else .\SpriteStudio-SDK, else ..\SpriteStudio-SDK.

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LibRoot = Join-Path $RootDir "game\spritestudio\libs"

$rawArch = (Get-Item Env:PROCESSOR_ARCHITECTURE -ErrorAction SilentlyContinue).Value
$HOST_ARCH = if ($rawArch -match "ARM64") { "arm64" } else { "x86_64" }
$HOST_PLATFORM = "windows"

$PLATFORM = $HOST_PLATFORM; $ARCH = $HOST_ARCH; $BUILD_MODE = "debug"; $HOSTBUILD = "auto"
foreach ($item in $Args) {
    if ($item -match "=") {
        $kv = $item -split "=", 2
        switch ($kv[0]) {
            "platform"  { $PLATFORM = $kv[1].ToLower() }
            "arch"      { $ARCH = $kv[1].ToLower() }
            "build"     { $BUILD_MODE = $kv[1].ToLower() }
            "hostbuild" { $HOSTBUILD = $kv[1].ToLower() }
        }
    } elseif ($item -match "help" -or $item -eq "-h") {
        Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:','^#   ' | ForEach-Object { $_.Line -replace '^# ?','' }
        exit 0
    }
}

# --- locate the SDK -------------------------------------------------------
$SdkDir = $env:SSSDK
if (-not $SdkDir) {
    foreach ($cand in @((Join-Path $RootDir "SpriteStudio-SDK"), (Join-Path $RootDir "..\SpriteStudio-SDK"))) {
        if (Test-Path (Join-Path $cand "Cargo.toml")) { $SdkDir = (Resolve-Path $cand).Path; break }
    }
}
if (-not $SdkDir -or -not (Test-Path (Join-Path $SdkDir "Cargo.toml"))) {
    Write-Error "SpriteStudio-SDK not found. Set `$env:SSSDK or place it at .\SpriteStudio-SDK"
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { Write-Error "cargo (Rust) not on PATH" }

$IS_HOST_BUILD = $false
if ($HOSTBUILD -ne "false" -and $PLATFORM -eq $HOST_PLATFORM -and $ARCH -eq $HOST_ARCH -and $BUILD_MODE -eq "debug") {
    $IS_HOST_BUILD = $true
}
Write-Host "Building for $PLATFORM ($ARCH) in $BUILD_MODE mode (host build: $IS_HOST_BUILD)"
$CargoFlags = if ($BUILD_MODE -eq "release") { @("--release") } else { @() }

# --- 1. build phase -------------------------------------------------------
$SrcDir = ""
Push-Location $SdkDir
try {
    if ($IS_HOST_BUILD) {
        cargo build $CargoFlags -p ssruntime --features libc_alloc,panic-handler
        cargo build $CargoFlags -p ssconverter
        $SrcDir = "target/$BUILD_MODE"
    } else {
        switch ($PLATFORM) {
            "windows" {
                $script = if ($ARCH -eq "arm64") { "./scripts/release-windows-arm64.ps1" } else { "./scripts/release-windows.ps1" }
                & $script $BUILD_MODE
                $SrcDir = if ($ARCH -eq "arm64") { "target/aarch64-pc-windows-msvc/$BUILD_MODE" } else { "target/x86_64-pc-windows-msvc/$BUILD_MODE" }
            }
            "macos"   { & sh ./scripts/release-macos.sh $BUILD_MODE; $SrcDir = "target/universal-apple-darwin/$BUILD_MODE" }
            "linux"   { & sh ./scripts/release-linux.sh $BUILD_MODE; $SrcDir = "target/$BUILD_MODE" }
            "android" { & sh ./scripts/release-android.sh $BUILD_MODE; $SrcDir = "" }
            "ios"     { & sh ./scripts/release-ios-xcframework.sh $BUILD_MODE; $SrcDir = "" }
            "web" {
                & "$SdkDir/scripts/release-web.ps1" "$BUILD_MODE"
                $SrcDir = "web_skip"
            }
            default   { Write-Error "unknown platform '$PLATFORM'" }
        }
    }
} finally { Pop-Location }

# --- 1.5 licenses (mirror Unity) ------------------------------------------
New-Item -ItemType Directory -Force -Path $LibRoot | Out-Null
if (Test-Path "$SdkDir/LICENSE.md") { Copy-Item "$SdkDir/LICENSE.md" "$LibRoot/" -Force }
if (Test-Path "$SdkDir/target/licenses/THIRD-PARTY-LICENSES.ssruntime.md") {
    Copy-Item "$SdkDir/target/licenses/THIRD-PARTY-LICENSES.ssruntime.md" "$LibRoot/" -Force
}

# --- 2. placement ---------------------------------------------------------
switch ($PLATFORM) {
    "web" {
        # release-web.ps1 emits the wasm-pack bundle to pkg\runtime-web\<mode>;
        # place its contents into game\spritestudio\libs\web\ (mirrors build-runtime.sh).
        $webSrc  = Join-Path $SdkDir "pkg/runtime-web/$BUILD_MODE"
        $webDest = Join-Path $LibRoot "web"
        if (-not (Test-Path (Join-Path $webSrc "*"))) {
            Write-Error "build-runtime.ps1: web build produced no output at $webSrc"
        }
        New-Item -ItemType Directory -Force -Path $webDest | Out-Null
        Copy-Item -Recurse -Force (Join-Path $webSrc "*") $webDest
        Write-Host "   -> game\spritestudio\libs\web\"
    }
    "ios" {
        $dest = Join-Path $LibRoot "ios"; New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Remove-Item -Recurse -Force "$dest/libssruntime.xcframework" -ErrorAction SilentlyContinue
        # DYNAMIC xcframework (bare dylibs, @rpath id): added once with "Embed &
        # Sign", dyld loads it at launch so ssruntime.py's CDLL(None) resolves the
        # Brain — no force_load / dead-strip workarounds a static lib would need.
        Copy-Item -Recurse -Force "$SdkDir/target/xcframework/dynamic/libssruntime.xcframework" "$dest/"
        Write-Host "   -> game\spritestudio\libs\ios\libssruntime.xcframework"
    }
    "android" {
        # Use the Android NDK/jniLibs ABI names (arm64-v8a/armeabi-v7a/x86_64):
        # on Android the Brain ships in the APK's lib\<abi>\ (jniLibs) and is loaded
        # by soname, so the on-disk layout mirrors the jniLibs names that
        # deploy-android.* stages from (and that download-sdk / the SDK produce).
        foreach ($t in @(@{triple="aarch64-linux-android";abi="arm64-v8a"},
                         @{triple="armv7-linux-androideabi";abi="armeabi-v7a"},
                         @{triple="x86_64-linux-android";abi="x86_64"})) {
            $src = "$SdkDir/target/$($t.triple)/$BUILD_MODE/libssruntime.so"
            if (Test-Path $src) {
                $d = Join-Path $LibRoot "android/$($t.abi)"; New-Item -ItemType Directory -Force -Path $d | Out-Null
                Copy-Item $src "$d/libssruntime.so" -Force
                Write-Host "   -> game\spritestudio\libs\android\$($t.abi)\libssruntime.so"
            }
        }
    }
    "macos" {
        # macOS ships the Brain as a versioned libssruntime.framework, built +
        # wrapped (and opt-in codesigned) by release-macos.sh, delegated above.
        # Copy the whole bundle; libssconverter stays a plain universal .dylib.
        $dest = Join-Path $LibRoot "macos"; New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Remove-Item -Recurse -Force (Join-Path $dest "libssruntime.framework") -ErrorAction SilentlyContinue
        Copy-Item -Recurse -Force (Join-Path $SdkDir "$SrcDir/libssruntime.framework") "$dest/"
        Write-Host "   -> game\spritestudio\libs\macos\libssruntime.framework"
        $cvSrc = Join-Path $SdkDir "$SrcDir/libssconverter.dylib"
        if (Test-Path $cvSrc) {
            Copy-Item $cvSrc (Join-Path $dest "libssconverter.dylib") -Force
            Write-Host "   -> game\spritestudio\libs\macos\libssconverter.dylib"
        }
    }
    default {
        switch ($PLATFORM) {
            "linux" { $sub = "linux/$(if ($ARCH -eq 'arm64' -or $ARCH -eq 'aarch64') { 'aarch64' } else { $ARCH })";      $name = "libssruntime.so";    $cname = "libssconverter.so" }
            "windows" { $sub = "windows/$ARCH";  $name = "ssruntime.dll";      $cname = "ssconverter.dll" }
        }
        $dest = Join-Path $LibRoot $sub; New-Item -ItemType Directory -Force -Path $dest | Out-Null
        $src = Join-Path $SdkDir "$SrcDir/$name"
        if (-not (Test-Path $src) -and $PLATFORM -eq "windows") { $src = Join-Path $SdkDir "$SrcDir/libssruntime.dll" }
        Copy-Item $src (Join-Path $dest $name) -Force
        Write-Host "   -> game\spritestudio\libs\$sub\$name"
        
        if ($cname -ne "") {
            $csrc = Join-Path $SdkDir "$SrcDir/$cname"
            if (-not (Test-Path $csrc) -and $PLATFORM -eq "windows") { $csrc = Join-Path $SdkDir "$SrcDir/libssconverter.dll" }
            if (Test-Path $csrc) {
                Copy-Item $csrc (Join-Path $dest $cname) -Force
                Write-Host "   -> game\spritestudio\libs\$sub\$cname"
            }
        }
    }
}
Write-Host "build-runtime.ps1: done."
