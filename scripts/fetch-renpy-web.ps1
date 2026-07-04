#!/usr/bin/env pwsh
#
# Download the Ren'Py Web export package and extract it into renpy-sdk\.
# The Ren'Py SDK must already be fetched using fetch-renpy-sdk.ps1.
#
# Usage: scripts\fetch-renpy-web.ps1 [version]
#   version : Web package version to fetch (default: latest stable, or $env:RENPY_VERSION).
#             e.g. scripts\fetch-renpy-web.ps1 8.3.0

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Dest = Join-Path $RootDir "renpy-sdk"
$BaseUrl = "https://www.renpy.org/dl"

if ($Args.Count -ge 1 -and ($Args[0] -in @("-h", "--help", "help"))) {
    Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:', '^#   ' | ForEach-Object { $_.Line -replace '^# ?', '' }
    exit 0
}

if (-not (Test-Path $Dest)) {
    Write-Error "fetch-renpy-web.ps1: renpy-sdk\ not found. Please run scripts\fetch-renpy-sdk.ps1 first."
    exit 1
}

# --- resolve version ------------------------------------------------------
$Version = if ($Args.Count -ge 1) { $Args[0] } elseif ($env:RENPY_VERSION) { $env:RENPY_VERSION } else { "" }
if (-not $Version) {
    Write-Host "Resolving latest stable Ren'Py version..."
    $html = (Invoke-WebRequest -Uri "https://www.renpy.org/latest.html" -UseBasicParsing).Content
    $m = [regex]::Match($html, 'renpy-([0-9]+\.[0-9]+\.[0-9]+)-web\.zip')
    if ($m.Success) { $Version = $m.Groups[1].Value }
}
if (-not $Version) {
    Write-Error "fetch-renpy-web.ps1: could not resolve the latest version automatically. Pass one explicitly (scripts\fetch-renpy-web.ps1 8.3.0) or set `$env:RENPY_VERSION."
    exit 1
}
Write-Host "Ren'Py Web package version: $Version"

# --- download + extract ---------------------------------------------------
$Archive = "renpy-$Version-web.zip"
$Url = "$BaseUrl/$Version/$Archive"
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("renpy-web-" + [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
try {
    $ZipPath = Join-Path $Tmp $Archive
    Write-Host "Downloading $Url ..."
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

    Write-Host "Extracting into renpy-sdk\ ..."
    Expand-Archive -Path $ZipPath -DestinationPath $Dest -Force
}
finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}

Write-Host "fetch-renpy-web.ps1: done (Ren'Py Web $Version)."
