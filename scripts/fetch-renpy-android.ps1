#!/usr/bin/env pwsh
#
# Download the Ren'Py Android support package (RAPT — the Ren'Py Android
# Packaging Tool) and extract it into renpy-sdk\. This is the extra download the
# Android target needs, the same way the Web target needs fetch-renpy-web.ps1.
# The Ren'Py SDK must already be fetched using fetch-renpy-sdk.ps1.
#
# Note: RAPT itself does NOT include the Android SDK / NDK / JDK, nor the signing
# keys. Those steps are interactive, so do them once from the launcher GUI:
#     renpy-sdk\renpy.exe renpy-sdk\launcher   ->  Android
#       -> "Install SDK"   (downloads the SDK/NDK/JDK into rapt\Sdk\)
#       -> "Generate Keys" (creates android.keystore to sign the package)
#       -> "Configure"     (package/app name in android.json)
# After that, build with scripts\deploy-android.ps1.
#
# Usage: scripts\fetch-renpy-android.ps1 [version]
#   version : RAPT package version to fetch (default: $env:RENPY_VERSION, else the pin in
#             scripts\RENPY_VERSION.txt, else the latest stable).
#             e.g. scripts\fetch-renpy-android.ps1 8.3.0

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Dest = Join-Path $RootDir "renpy-sdk"
$BaseUrl = "https://www.renpy.org/dl"
$VersionFile = Join-Path $RootDir "scripts/RENPY_VERSION.txt"

# From "# Usage:" to the end of the header, which is what the .sh twin prints.
function Show-Usage {
    $emit = $false
    foreach ($line in Get-Content $PSCommandPath) {
        if ($line -match '^# Usage:') { $emit = $true }
        if (-not $emit) { continue }
        if ($line -notmatch '^#') { break }
        $line -replace '^# ?', ''
    }
}

$VersionArg = ""
foreach ($a in $args) {
    switch -Regex -CaseSensitive ($a) {
        '^(-h|--help|help)$' { Show-Usage; exit 0 }
        '^-' { [Console]::Error.WriteLine("fetch-renpy-android.ps1: unknown flag '$a'"); exit 2 }
        default {
            if ($VersionArg) { [Console]::Error.WriteLine("fetch-renpy-android.ps1: unexpected extra arg '$a'"); exit 2 }
            $VersionArg = $a
        }
    }
}

if (-not (Test-Path $Dest)) {
    Write-Error "fetch-renpy-android.ps1: renpy-sdk\ not found. Please run scripts\fetch-renpy-sdk.ps1 first."
    exit 1
}

# --- resolve version ------------------------------------------------------
# priority: CLI arg > $env:RENPY_VERSION > scripts\RENPY_VERSION.txt (the pin all
# fetch-renpy-* scripts share) > latest stable resolved from latest.html.
$Version = if ($VersionArg) { $VersionArg } elseif ($env:RENPY_VERSION) { $env:RENPY_VERSION } else { "" }
if (-not $Version -and (Test-Path $VersionFile)) {
    $Version = (Get-Content $VersionFile -Raw).Trim()
    if ($Version) { Write-Host "Using pinned version from scripts\RENPY_VERSION.txt: $Version" }
}
if (-not $Version) {
    Write-Host "Resolving latest stable Ren'Py version..."
    $ProgressPreference = 'SilentlyContinue'
    $html = (Invoke-WebRequest -Uri "https://www.renpy.org/latest.html" -UseBasicParsing).Content
    $ProgressPreference = 'Continue'
    $m = [regex]::Match($html, 'renpy-([0-9]+\.[0-9]+\.[0-9]+)-rapt\.zip')
    if ($m.Success) { $Version = $m.Groups[1].Value }
}
if (-not $Version) {
    Write-Error "fetch-renpy-android.ps1: could not resolve the latest version automatically. Pass one explicitly (scripts\fetch-renpy-android.ps1 8.3.0) or set `$env:RENPY_VERSION."
    exit 1
}
Write-Host "Ren'Py RAPT (Android) package version: $Version"

# --- download + extract ---------------------------------------------------
$Archive = "renpy-$Version-rapt.zip"
$Url = "$BaseUrl/$Version/$Archive"
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("renpy-rapt-" + [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
try {
    $ZipPath = Join-Path $Tmp $Archive
    Write-Host "Downloading $Url ..."
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing
    $ProgressPreference = 'Continue'

    Write-Host "Extracting into renpy-sdk\ ..."
    $global:ProgressPreference = 'SilentlyContinue'
    Expand-Archive -Path $ZipPath -DestinationPath $Dest -Force
    $global:ProgressPreference = 'Continue'
}
finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}

Write-Host "fetch-renpy-android.ps1: done (Ren'Py RAPT $Version)."
Write-Host "  Next (once, interactive) in the launcher GUI -> Android:"
Write-Host "    renpy-sdk\renpy.exe renpy-sdk\launcher"
Write-Host "    -> 'Install SDK'  (Android SDK/NDK/JDK)  and  'Generate Keys' (signing)"
Write-Host "  Then build:  scripts\deploy-android.ps1"
