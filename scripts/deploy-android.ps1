#!/usr/bin/env pwsh
#
# Build a signed Android package (APK by default, or an AAB with -Bundle) of the
# SSPlayer demo using Ren'Py's RAPT toolchain (launcher android_build). The native
# "Brain" .so must land in the APK's lib\<abi>\ (jniLibs) — the only place Android's
# linker will dlopen from — so this script stages game\spritestudio\libs\android\<abi>\
# into RAPT's jniLibs before building; ssruntime.py then loads it by soname at
# runtime (abi: arm64-v8a / armeabi-v7a / x86_64, the NDK names).
#
# This script auto-fetches the Ren'Py SDK and RAPT if missing, but it does NOT
# perform the three INTERACTIVE one-time setup steps (do them once in the launcher
# GUI:  renpy-sdk\renpy.exe renpy-sdk\launcher  -> Android):
#   * Install SDK  : downloads the Android SDK/NDK/JDK into renpy-sdk\rapt\Sdk\
#   * Configure    : sets the package name / app name in android.json (required)
#   * Generate Keys: creates android.keystore (+ bundle.keystore) used to sign
# RAPT itself (the packaging tool) is fetched by scripts\fetch-renpy-android.ps1.
#
# Usage: scripts\deploy-android.ps1 [dest_dir] [-Bundle] [-Install] [-Launch]
#   dest_dir  : output folder (default: dist)
#   -Bundle   : build an .aab App Bundle (Play upload) instead of a Universal .apk
#   -Install  : adb-install onto a connected device after the build
#   -Launch   : install then launch on the device (implies -Install)

[CmdletBinding()]
param(
    [string]$Dest = "dist",
    [switch]$Bundle,
    [switch]$Install,
    [switch]$Launch,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RenpySdk = Join-Path $RootDir "renpy-sdk"
$Launcher = Join-Path $RenpySdk "launcher"
$Rapt = Join-Path $RenpySdk "rapt"
$Libs = Join-Path $RootDir "game/spritestudio/libs"

if ($Help) {
    Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:', '^#   ' | ForEach-Object { $_.Line -replace '^# ?', '' }
    exit 0
}
if (-not [System.IO.Path]::IsPathRooted($Dest)) { $Dest = Join-Path $RootDir $Dest }

# --- prerequisites --------------------------------------------------------
# Ren'Py SDK (fetch on demand, same as deploy-desktop.ps1)
$Renpy = Join-Path $RenpySdk "renpy.exe"
if (-not (Test-Path $Renpy)) {
    Write-Host "deploy-android.ps1: renpy.exe not found in renpy-sdk\ — fetching the SDK first..."
    & (Join-Path $RootDir "scripts/fetch-renpy-sdk.ps1")
}
# The top-level renpy.exe is a GUI-subsystem binary: launched from a console it
# prints nothing, doesn't block, and returns exit 0 immediately — so android_build
# would silently do nothing. Drive Ren'Py through the console python instead
# (same trick as run-demo.ps1) so we get output, blocking, and a real exit code.
$PythonExe = Join-Path $RenpySdk "lib/py3-windows-x86_64/python.exe"
$RenpyPy   = Join-Path $RenpySdk "renpy.py"
if (Test-Path $PythonExe) {
    $RenpyExe = $PythonExe; $RenpyPre = @($RenpyPy)
} else {
    $RenpyExe = $Renpy;     $RenpyPre = @()
}
# RAPT — the Android packaging tool (fetch on demand)
if (-not (Test-Path (Join-Path $Rapt "android.py"))) {
    Write-Host "deploy-android.ps1: Ren'Py Android support (RAPT) not found — fetching it first..."
    & (Join-Path $RootDir "scripts/fetch-renpy-android.ps1")
}
# Android SDK/NDK installed by RAPT's "Install SDK" (adb is its sentinel)
if (-not (Test-Path (Join-Path $Rapt "Sdk/platform-tools/adb.exe"))) {
    Write-Error @"
deploy-android.ps1: Android SDK not installed (no renpy-sdk\rapt\Sdk\platform-tools\adb.exe).
  Run it once, interactively, from the launcher GUI:
    renpy-sdk\renpy.exe renpy-sdk\launcher    ->  Android  ->  Install SDK
"@
    exit 1
}
# Signing keys (android.keystore in the project root; bundle.keystore for -Bundle)
if ((-not (Test-Path (Join-Path $RootDir "android.keystore"))) -or ($Bundle -and -not (Test-Path (Join-Path $RootDir "bundle.keystore")))) {
    $need = if ($Bundle) { "android.keystore + bundle.keystore" } else { "android.keystore" }
    Write-Error @"
deploy-android.ps1: signing key(s) missing in the project root ($need).
  Generate them once from the launcher GUI:
    renpy-sdk\renpy.exe renpy-sdk\launcher    ->  Android  ->  Generate Keys
"@
    exit 1
}
# App configuration (package name in android.json). RAPT's build refuses to run
# ("Run configure before attempting to build the app.") when package is unset.
$Cfg = Join-Path $RootDir "android.json"
$Pkg = if (Test-Path $Cfg) { (Get-Content $Cfg -Raw | ConvertFrom-Json).package } else { $null }
if (-not $Pkg) {
    Write-Error @"
deploy-android.ps1: app not configured (no package name in android.json).
  Configure it once from the launcher GUI:
    renpy-sdk\renpy.exe renpy-sdk\launcher    ->  Android  ->  Configure
"@
    exit 1
}
# Native library for the primary device ABI (arm64-v8a); armeabi-v7a/x86_64 optional.
if (-not (Test-Path (Join-Path $Libs "android/arm64-v8a/libssruntime.so"))) {
    Write-Error @"
deploy-android.ps1: native library missing for Android:
    game\spritestudio\libs\android\arm64-v8a\libssruntime.so
  Without it the app builds but SSPlayer fails at load. Get it with
  scripts\download-sdk.ps1 (prebuilt) or scripts\build-runtime.ps1 platform=android build=release, then re-run.
"@
    exit 1
}
foreach ($abi in @("armeabi-v7a", "x86_64")) {
    if (-not (Test-Path (Join-Path $Libs "android/$abi/libssruntime.so"))) {
        Write-Warning "deploy-android.ps1: no libs\android\$abi\libssruntime.so; the app will not run on $abi devices/emulators."
    }
}

# Stage the Brain into RAPT's jniLibs so RAPT bundles it into the APK's lib\<abi>\.
# Android's linker only dlopen()s native libs the installer extracted to the app's
# read-only nativeLibraryDir (W^X since API 29) — i.e. libs shipped in lib\<abi>\.
# RAPT sources jniLibs from prototype\renpyandroid\src\main\jniLibs\<abi>\ (copied
# into every build), so mirror our per-ABI .so there. Consumers building via the
# stock launcher must do this copy once by hand — see docs/export.md (Android).
$JniLibs = Join-Path $Rapt "prototype/renpyandroid/src/main/jniLibs"
foreach ($abi in @("arm64-v8a", "armeabi-v7a", "x86_64")) {
    $so = Join-Path $Libs "android/$abi/libssruntime.so"
    if (Test-Path $so) {
        $d = Join-Path $JniLibs $abi; New-Item -ItemType Directory -Force -Path $d | Out-Null
        Copy-Item $so (Join-Path $d "libssruntime.so") -Force
        Write-Host "deploy-android.ps1: staged Brain -> jniLibs\$abi\libssruntime.so"
    }
}

# --- build ----------------------------------------------------------------
$Pass = @()
if ($Bundle)  { $Pass += "--bundle" }
if ($Install) { $Pass += "--install" }
if ($Launch)  { $Pass += "--launch" }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$kind = if ($Bundle) { "App Bundle (.aab)" } else { "package (.apk)" }
Write-Host ">> building Android $kind -> $Dest"
& $RenpyExe @RenpyPre $Launcher android_build $RootDir --dest $Dest @Pass
if ($LASTEXITCODE -ne 0) { Write-Error "deploy-android.ps1: android_build failed ($LASTEXITCODE)"; exit 1 }

# --- report ---------------------------------------------------------------
$Out = Get-ChildItem -Path $Dest -Include *.aab, *.apk -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($Out) {
    $Adb = Join-Path $Rapt "Sdk/platform-tools/adb.exe"
    Write-Host "deploy-android.ps1: done -> $($Out.FullName)"
    Write-Host "  Install on a connected device:  & `"$Adb`" install -r `"$($Out.FullName)`""
    Write-Host "  (or re-run with -Install / -Launch to have RAPT do it.)"
} else {
    Write-Error "deploy-android.ps1: build finished but no .apk/.aab found in $Dest — inspect the output above."
    exit 1
}
