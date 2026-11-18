#!/usr/bin/env pwsh
#
# Build the native runtime libssruntime from the SpriteStudio-SDK and place it
# in the library's per-platform/arch layout. Interface: platform=/arch=/build=
# key=value arguments, the same as build-runtime.sh. For linux/windows DESKTOP
# it builds just the two cdylibs it places -- ssruntime-ffi (feature-enabled)
# and ssconverter-ffi -- with cargo directly, NOT via the SDK's release-*
# scripts, which build the whole workspace (and release-windows*.ps1 always in
# release, whatever build= says). macOS is the exception: it ships the Brain as
# a versioned, signable libssruntime.framework (App Store / notarization want a
# .framework bundle, not a bare dylib), so -- like android/ios/web -- it DOES
# delegate to the SDK's release-macos.sh, which builds the universal slices and
# wraps + codesigns the framework. (That path is always universal; no fast
# single-arch host build.)
#
#   game/spritestudio/libs/
#     macos/libssruntime.framework             (universal arm64+x86_64; + libssconverter.dylib)
#     windows/<arch>/ssruntime.dll   linux/<arch>/libssruntime.so
#     android/<abi>/libssruntime.so  ios/libssruntime.xcframework
#     web/ (wasm-pack bundle: ssruntime.js + ssruntime_bg.wasm)
#
# android/ios/web are toolchain-heavy cross builds and DO delegate to the SDK
# release scripts.
#
# Usage: scripts\build-runtime.ps1 [platform=<p>] [arch=<a>] [build=<m>] [hostbuild=<auto|false>]
#   platform : windows macos linux android ios web   (default: host)
#   arch     : x86_64 arm64 universal ...            (default: host arch)
#   build    : debug release                         (default: debug)
#   hostbuild: false to force cross even on host
#
# SDK location: $env:SSSDK, else .\SpriteStudio-SDK, else ..\SpriteStudio-SDK.

$ErrorActionPreference = "Stop"
$App = Split-Path -Leaf $PSCommandPath
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LibRoot = Join-Path $RootDir "game/spritestudio/libs"

# The block from "# Usage:" to "# SDK location", which is what the .sh twin prints.
function Show-Usage {
    $emit = $false
    foreach ($line in Get-Content $PSCommandPath) {
        if ($line -match '^# Usage:') { $emit = $true }
        if ($emit) { $line -replace '^# ?', '' }
        if ($emit -and $line -match '^# SDK location') { break }
    }
}

# Plain stderr and the code: Write-Error throws under "Stop", so an exit after
# it never runs and the caller always sees 1.
function Fail([string] $Message, [int] $Code = 1) {
    [Console]::Error.WriteLine("${App}: $Message")
    exit $Code
}

# Same host as the .sh twin works out: pwsh runs on all three, and $IsWindows
# is unset in Windows PowerShell, hence the else.
if ($IsMacOS -or $IsLinux) {
    $HOST_PLATFORM = if ($IsMacOS) { "macos" } else { "linux" }
    $HOST_ARCH = "$(& uname -m)".Trim()
    if ($HOST_ARCH -eq "aarch64") { $HOST_ARCH = "arm64" }
} else {
    $HOST_PLATFORM = "windows"
    $HOST_ARCH = if ($env:PROCESSOR_ARCHITECTURE -match "ARM64") { "arm64" } else { "x86_64" }
}

$PLATFORM = $HOST_PLATFORM; $ARCH = $HOST_ARCH; $BUILD_MODE = "debug"; $HOSTBUILD = "auto"
foreach ($item in $args) {
    switch -Regex ($item) {
        '^platform='  { $PLATFORM = $item.Substring(9).ToLower(); continue }
        '^arch='      { $ARCH = $item.Substring(5).ToLower(); continue }
        '^build='     { $BUILD_MODE = $item.Substring(6).ToLower(); continue }
        '^hostbuild=' { $HOSTBUILD = $item.Substring(10).ToLower(); continue }
        '^(-h|--help|help)$' { Show-Usage; exit 0 }
        default {
            [Console]::Error.WriteLine("${App}: unknown arg '$item'")
            Show-Usage
            exit 2
        }
    }
}
# Checked before anything is written: libs/VERSION is stamped below, and a typo
# should not cost the libraries already in place their version.
if ($PLATFORM -notin "windows", "macos", "linux", "android", "ios", "web") { Fail "unknown platform '$PLATFORM'" 2 }
if ($BUILD_MODE -notin "debug", "release") { Fail "build must be debug or release (got '$BUILD_MODE')" 2 }

# --- locate the SDK -------------------------------------------------------
$SdkDir = $env:SSSDK
if (-not $SdkDir) {
    foreach ($cand in @((Join-Path $RootDir "SpriteStudio-SDK"), (Join-Path $RootDir "../SpriteStudio-SDK"))) {
        if (Test-Path (Join-Path $cand "Cargo.toml")) { $SdkDir = (Resolve-Path $cand).Path; break }
    }
}
if (-not $SdkDir -or -not (Test-Path (Join-Path $SdkDir "Cargo.toml"))) {
    Fail "SpriteStudio-SDK not found (init the submodule or set `$env:SSSDK)"
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { Fail "cargo (Rust) not on PATH" }

$IS_HOST_BUILD = $false
if ($HOSTBUILD -ne "false" -and $PLATFORM -eq $HOST_PLATFORM -and $ARCH -eq $HOST_ARCH -and $BUILD_MODE -eq "debug") {
    $IS_HOST_BUILD = $true
}
Write-Host "Building for $PLATFORM ($ARCH) in $BUILD_MODE mode (host build: $($IS_HOST_BUILD.ToString().ToLower()))"
# Wrapped in @(): an if used as a value unrolls a one-element array into a bare
# string, which @CargoFlags would then splat one character at a time.
$CargoFlags = @(if ($BUILD_MODE -eq "release") { "--release" })

# $ErrorActionPreference does not cover native commands, so every one is
# checked: otherwise a failed build would fall through to the placement and
# copy a stale artifact.
function Invoke-Native([string] $What, [scriptblock] $Body) {
    Push-Location $SdkDir
    try { & $Body } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Fail "$What failed ($LASTEXITCODE)" }
}
# The feature-enabled ssruntime and the ssconverter cdylib. The feature list is
# quoted: a bare libc_alloc,panic-handler is a PowerShell array and reaches
# cargo as two separate arguments.
function Build-Ss([string[]] $Extra = @()) {
    Invoke-Native "cargo build (ssruntime)" { & cargo build @CargoFlags @Extra -p ssruntime-ffi --features "libc_alloc,panic-handler" }
}
function Build-Converter([string[]] $Extra = @()) {
    Invoke-Native "cargo build (ssconverter)" { & cargo build @CargoFlags @Extra -p ssconverter-ffi }
}
# The SDK's release-*.sh are bash scripts, as the .sh twin runs them.
function Invoke-SdkScript([string] $Script) {
    Invoke-Native $Script { & bash (Join-Path $SdkDir "scripts/$Script") $BUILD_MODE }
}
# Missing is fatal, as `cp` under `set -e` is in the .sh twin.
function Place([string] $Sub, [string] $Src, [string] $Name = (Split-Path -Leaf $Src)) {
    if (-not (Test-Path $Src)) { Fail "$Src was not built" }
    $dest = Join-Path $LibRoot $Sub
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item -Force $Src (Join-Path $dest $Name)
    Write-Host "   -> game/spritestudio/libs/$Sub/$Name"
}

New-Item -ItemType Directory -Force -Path $LibRoot | Out-Null
# libs/VERSION names the SDK release download-sdk installed, and what follows
# replaces libraries with this local build. Stamp it "local" first: a later
# download-sdk sees a mismatch and reinstalls instead of skipping as up to date,
# and build-release sdk=build labels its zip for what it is.
Set-Content -Path (Join-Path $LibRoot "VERSION") -Value "local"

# copy license notices alongside the libraries
if (Test-Path "$SdkDir/LICENSE.md") { Copy-Item "$SdkDir/LICENSE.md" "$LibRoot/" -Force }
if (Test-Path "$SdkDir/target/licenses/THIRD-PARTY-LICENSES.ssruntime.md") {
    Copy-Item "$SdkDir/target/licenses/THIRD-PARTY-LICENSES.ssruntime.md" "$LibRoot/" -Force
}

$T = Join-Path $SdkDir "target"
switch ($PLATFORM) {
    "macos" {
        # Delegate to the SDK's release-macos.sh: it builds both arch slices,
        # lipos the feature-enabled dylib, and wraps it into the versioned
        # libssruntime.framework (Versions/A + Info.plist + module map, @rpath
        # id), opt-in codesigning it when APPLE_SIGNING_IDENTITY is set. Always
        # universal (both arches) regardless of build=/arch=; libssconverter
        # stays a plain universal .dylib. `cp -R` preserves the framework's
        # version symlinks, which Copy-Item would follow.
        Invoke-SdkScript "release-macos.sh"
        $U = Join-Path $T "universal-apple-darwin/$BUILD_MODE"
        $dest = Join-Path $LibRoot "macos"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Remove-Item -Recurse -Force (Join-Path $dest "libssruntime.framework") -ErrorAction SilentlyContinue
        & cp -R (Join-Path $U "libssruntime.framework") "$dest/"
        if ($LASTEXITCODE -ne 0) { Fail "copying libssruntime.framework failed ($LASTEXITCODE)" }
        Place "macos" (Join-Path $U "libssconverter.dylib")
    }
    { $_ -in "linux", "windows" } {
        if ($PLATFORM -eq "linux") {
            $rt = "libssruntime.so"; $cv = "libssconverter.so"
            $triple = if ($ARCH -eq "x86_64") { "x86_64-unknown-linux-gnu" } else { "aarch64-unknown-linux-gnu" }
            # Linux arch dir uses the kernel/Rust spelling (aarch64, not arm64) --
            # matches the SDK release layout libs/linux/aarch64. arm64 accepted as
            # an alias.
            $sub = if ($ARCH -in "arm64", "aarch64") { "linux/aarch64" } else { "linux/$ARCH" }
        } else {
            $rt = "ssruntime.dll"; $cv = "ssconverter.dll"
            $triple = if ($ARCH -eq "arm64") { "aarch64-pc-windows-msvc" } else { "x86_64-pc-windows-msvc" }
            $sub = "windows/$ARCH"
        }
        if ($IS_HOST_BUILD) {
            Build-Ss; Build-Converter
            $out = Join-Path $T $BUILD_MODE
        } else {
            Build-Ss @("--target", $triple); Build-Converter @("--target", $triple)
            $out = Join-Path $T "$triple/$BUILD_MODE"
        }
        Place $sub (Join-Path $out $rt)
        Place $sub (Join-Path $out $cv)
    }

    # --- toolchain-heavy cross builds: delegate to the SDK release scripts ---
    "android" {
        Invoke-SdkScript "release-android.sh"
        # Place under the Android NDK/jniLibs ABI names (arm64-v8a/armeabi-v7a/x86_64):
        # on Android the Brain ships in the APK's lib/<abi>/ (jniLibs) and is loaded by
        # soname, so the on-disk layout mirrors the jniLibs names that deploy-android.*
        # stages from (and that download-sdk / the SDK release package produce).
        foreach ($pair in @("aarch64-linux-android:arm64-v8a", "armv7-linux-androideabi:armeabi-v7a", "x86_64-linux-android:x86_64")) {
            $tr, $abi = $pair -split ":", 2
            $so = Join-Path $T "$tr/$BUILD_MODE/libssruntime.so"
            if (Test-Path $so) { Place "android/$abi" $so }
        }
    }
    "ios" {
        Invoke-SdkScript "release-ios-xcframework.sh"
        $dest = Join-Path $LibRoot "ios"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Remove-Item -Recurse -Force (Join-Path $dest "libssruntime.xcframework") -ErrorAction SilentlyContinue
        # Ship the DYNAMIC xcframework (.framework-wrapped slices, @rpath id): a consuming
        # app adds it once with "Embed & Sign" and dyld loads it at launch, so ssruntime.py's
        # CDLL(None) resolves the Brain -- no per-symbol force_load / dead-strip
        # workarounds a *static* lib would need inside a stripped Ren'Py app.
        & cp -R (Join-Path $T "xcframework/dynamic/libssruntime.xcframework") "$dest/"
        if ($LASTEXITCODE -ne 0) { Fail "copying libssruntime.xcframework failed ($LASTEXITCODE)" }
        Write-Host "   -> game/spritestudio/libs/ios/libssruntime.xcframework"
    }
    "web" {
        # The SDK's PowerShell twin of release-web.sh, so a Windows host needs no
        # bash for this one. It does not check wasm-pack's exit status, so the
        # output is: it empties pkg/runtime-web/<mode> before building.
        Invoke-Native "release-web.ps1" { & (Join-Path $SdkDir "scripts/release-web.ps1") $BUILD_MODE }
        $webSrc = Join-Path $SdkDir "pkg/runtime-web/$BUILD_MODE"
        if (-not (Test-Path (Join-Path $webSrc "*"))) { Fail "web build produced no output at $webSrc" }
        $webDest = Join-Path $LibRoot "web"
        New-Item -ItemType Directory -Force -Path $webDest | Out-Null
        Copy-Item -Recurse -Force (Join-Path $webSrc "*") $webDest
        Write-Host "   -> game/spritestudio/libs/web/"
    }
}
Write-Host "${App}: done."
