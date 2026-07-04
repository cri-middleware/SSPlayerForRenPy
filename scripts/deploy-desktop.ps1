#!/usr/bin/env pwsh
#
# Build a runnable Windows desktop distribution (.exe) of the SSPlayer demo,
# using Ren'Py's standard "Build Distributions". Unlike the Web target, the
# desktop target needs NO post-export steps: the native "Brain" library under
# game\spritestudio\libs\ is bundled automatically and resolved at runtime.
#
# This .ps1 targets Windows -> win package -> an unpacked <name>-win\ folder
# containing <name>.exe. For a macOS .app or a Linux folder, run
# scripts\deploy-desktop.sh on that OS instead.
#
# The win package needs game\spritestudio\libs\windows\x86_64\ssruntime.dll.
# This repo ships only the macOS dylib, so fetch the Windows library first with
# scripts\download-sdk.ps1 (prebuilt) or scripts\build-runtime.ps1 (from source).
#
# Usage: scripts\deploy-desktop.ps1 [dest_dir]
#   dest_dir : output folder (default: dist)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RenpySdk = Join-Path $RootDir "renpy-sdk"
$Launcher = Join-Path $RenpySdk "launcher"
$Libs = Join-Path $RootDir "game/spritestudio/libs"

if ($Args.Count -ge 1 -and ($Args[0] -in @("-h", "--help", "help"))) {
    Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:', '^#   ' | ForEach-Object { $_.Line -replace '^# ?', '' }
    exit 0
}
$Dest = if ($Args.Count -ge 1) { $Args[0] } else { "dist" }
if (-not [System.IO.Path]::IsPathRooted($Dest)) { $Dest = Join-Path $RootDir $Dest }

# --- prerequisites --------------------------------------------------------
$Renpy = Join-Path $RenpySdk "renpy.exe"
if (-not (Test-Path $Renpy)) {
    Write-Host "deploy-desktop.ps1: renpy.exe not found in renpy-sdk\ — fetching the SDK first..."
    & (Join-Path $RootDir "scripts/fetch-renpy-sdk.ps1")
}
$Dll = Join-Path $Libs "windows/x86_64/ssruntime.dll"
if (-not (Test-Path $Dll)) {
    Write-Error @"
deploy-desktop.ps1: native library missing for the win package:
    game\spritestudio\libs\windows\x86_64\ssruntime.dll
  Without it the app builds but SSPlayer fails at load. Get it with
  scripts\download-sdk.ps1 (prebuilt) or scripts\build-runtime.ps1, then re-run.
"@
    exit 1
}

# --- build ----------------------------------------------------------------
Write-Host ">> building win desktop distribution -> $Dest"
& $Renpy $Launcher distribute $RootDir --package win --no-update --destination $Dest
if ($LASTEXITCODE -ne 0) { Write-Error "deploy-desktop.ps1: distribute failed ($LASTEXITCODE)"; exit 1 }

# --- unpack so the result is immediately runnable -------------------------
$Zip = Get-ChildItem -Path $Dest -Filter "*-win.zip" | Select-Object -First 1
if (-not $Zip) { Write-Error "deploy-desktop.ps1: expected *-win.zip in $Dest"; exit 1 }
Write-Host ">> unpacking $($Zip.Name)"
Expand-Archive -Path $Zip.FullName -DestinationPath $Dest -Force

$Exe = Get-ChildItem -Path $Dest -Recurse -Filter "*.exe" |
    Where-Object { $_.FullName -notmatch '\\lib\\' } | Select-Object -First 1
if ($Exe) {
    Write-Host "deploy-desktop.ps1: done -> $($Exe.FullName)"
    Write-Host "  Run it:  & `"$($Exe.FullName)`""
} else {
    $Dir = Get-ChildItem -Path $Dest -Directory -Filter "*-win" | Select-Object -First 1
    Write-Host "deploy-desktop.ps1: done -> $($Dir.FullName)"
}
