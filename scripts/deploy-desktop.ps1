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
# Native libraries are not committed to this repo, so fetch them first with
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
# The top-level renpy.exe is a GUI-subsystem binary: launched from a console it
# prints nothing, doesn't block, and returns exit 0 immediately — so `distribute`
# would silently build nothing. Drive Ren'Py through the console python instead
# (same trick as run-demo.ps1) so we get output, blocking, and a real exit code.
$PythonExe = Join-Path $RenpySdk "lib/py3-windows-x86_64/python.exe"
$RenpyPy   = Join-Path $RenpySdk "renpy.py"
if (Test-Path $PythonExe) {
    $RenpyExe = $PythonExe; $RenpyPre = @($RenpyPy)
} else {
    $RenpyExe = $Renpy;     $RenpyPre = @()
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
& $RenpyExe @RenpyPre $Launcher distribute $RootDir --package win --no-update --destination $Dest
if ($LASTEXITCODE -ne 0) { Write-Error "deploy-desktop.ps1: distribute failed ($LASTEXITCODE)"; exit 1 }

# --- unpack so the result is immediately runnable -------------------------
# Ren'Py's `distribute` returns exit code 0 even when it builds nothing (e.g.
# the project fails to compile/dump, or on Windows renpy.exe doesn't propagate
# the child exit code), so $LASTEXITCODE above can't be trusted. If the build
# produced no output, $Dest may not even exist — guard with Test-Path so this
# reports the real cause instead of crashing Get-ChildItem with ItemNotFound.
$Zip = if (Test-Path $Dest) { Get-ChildItem -Path $Dest -Filter "*-win.zip" | Select-Object -First 1 }
if (-not $Zip) {
    Write-Error @"
deploy-desktop.ps1: distribute produced no *-win.zip in $Dest.
  distribute exits 0 even when it builds nothing, so this usually means the
  build was aborted. Re-run and read the 'distribute' output above, or launch
  the project once to confirm it compiles:
    renpy-sdk\renpy.exe "$RootDir"
"@
    exit 1
}
Write-Host ">> unpacking $($Zip.Name)"
$global:ProgressPreference = 'SilentlyContinue'
Expand-Archive -Path $Zip.FullName -DestinationPath $Dest -Force
$global:ProgressPreference = 'Continue'

$Exe = Get-ChildItem -Path $Dest -Recurse -Filter "*.exe" |
    Where-Object { $_.FullName -notmatch '\\lib\\' } | Select-Object -First 1
if ($Exe) {
    Write-Host "deploy-desktop.ps1: done -> $($Exe.FullName)"
    Write-Host "  Run it:  & `"$($Exe.FullName)`""
} else {
    $Dir = Get-ChildItem -Path $Dest -Directory -Filter "*-win" | Select-Object -First 1
    Write-Host "deploy-desktop.ps1: done -> $($Dir.FullName)"
}
