#!/usr/bin/env pwsh
#
# Download the Ren'Py SDK and extract it into a gitignored renpy-sdk\ at the
# project root, so the project can be launched / visually verified. Windows
# counterpart of scripts/fetch-renpy-sdk.sh (uses the .zip + Expand-Archive).
#
# This is a SEPARATE job from the other scripts (keep them decoupled):
#   build-runtime.*   -> the native libssruntime    (game\spritestudio\libs\)
#   deploy-examples.* -> the .ssab playback data     (game\sprites\)
#   fetch-renpy-sdk.* -> the Ren'Py editor/runtime   (renpy-sdk\, gitignored)
#
# Usage: scripts\fetch-renpy-sdk.ps1 [version]
#   version : SDK version to fetch (default: latest stable, or $env:RENPY_VERSION).
#             e.g. scripts\fetch-renpy-sdk.ps1 8.5.3
#
# Afterwards, launch the project with:
#   renpy-sdk\renpy.exe .

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Dest = Join-Path $RootDir "renpy-sdk"
$BaseUrl = "https://www.renpy.org/dl"

if ($Args.Count -ge 1 -and ($Args[0] -in @("-h", "--help", "help"))) {
    Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:', '^#   ' | ForEach-Object { $_.Line -replace '^# ?', '' }
    exit 0
}

# --- resolve version ------------------------------------------------------
$Version = if ($Args.Count -ge 1) { $Args[0] } elseif ($env:RENPY_VERSION) { $env:RENPY_VERSION } else { "" }
if (-not $Version) {
    Write-Host "Resolving latest stable Ren'Py version..."
    $html = (Invoke-WebRequest -Uri "https://www.renpy.org/latest.html" -UseBasicParsing).Content
    $m = [regex]::Match($html, 'renpy-([0-9]+\.[0-9]+\.[0-9]+)-sdk')
    if ($m.Success) { $Version = $m.Groups[1].Value }
}
if (-not $Version) {
    Write-Error "fetch-renpy-sdk.ps1: could not resolve the latest version automatically. Pass one explicitly (scripts\fetch-renpy-sdk.ps1 8.5.3) or set `$env:RENPY_VERSION."
    exit 1
}
Write-Host "Ren'Py SDK version: $Version"

# --- download + extract ---------------------------------------------------
$Archive = "renpy-$Version-sdk.zip"
$Url = "$BaseUrl/$Version/$Archive"
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("renpy-sdk-" + [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
try {
    $ZipPath = Join-Path $Tmp $Archive
    Write-Host "Downloading $Url ..."
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

    Write-Host "Extracting into renpy-sdk\ ..."
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    Expand-Archive -Path $ZipPath -DestinationPath $Tmp -Force
    # the archive has a single top-level renpy-<ver>-sdk\ dir; move its contents
    # up so the launcher lands at renpy-sdk\renpy.exe.
    $Inner = Join-Path $Tmp "renpy-$Version-sdk"
    if (Test-Path $Inner) { Move-Item -Path $Inner -Destination $Dest }
    else { New-Item -ItemType Directory -Force -Path $Dest | Out-Null; Move-Item -Path (Join-Path $Tmp "*") -Destination $Dest -Exclude $Archive }
}
finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}

# --- report ---------------------------------------------------------------
Write-Host "fetch-renpy-sdk.ps1: done (Ren'Py $Version)."
if (Test-Path (Join-Path $Dest "renpy.exe")) {
    Write-Host "   launch the project:  renpy-sdk\renpy.exe ."
}
else {
    Write-Warning "renpy.exe not found at renpy-sdk\ - inspect the extracted tree."
}
