#!/usr/bin/env pwsh
#
# Build the Ren'Py Web export of this project, with the stock exporter and
# nothing applied afterwards: the Brain's wasm module ships inside game.zip and
# SSPlayer loads it from there at startup, so the export plays as it comes out.
#
# Prereqs: Ren'Py SDK in renpy-sdk\ (fetch-renpy-sdk.ps1) with Web support
# (fetch-renpy-web.ps1), and the web runtime under game\spritestudio\libs\web\
# (download-sdk.ps1 / build-runtime.ps1).
#
# Usage: scripts\deploy-web.ps1 [dest_dir]
#   dest_dir : output folder (default: web_out)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RenpySdk = Join-Path $RootDir "renpy-sdk"
$Launcher = Join-Path $RenpySdk "launcher"
$WebAssets = Join-Path $RootDir "game/spritestudio/libs/web"

if ($Args.Count -ge 1 -and ($Args[0] -in @("-h", "--help", "help"))) {
    Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:', '^#   ' | ForEach-Object { $_.Line -replace '^# ?', '' }
    exit 0
}
$Dest = if ($Args.Count -ge 1) { $Args[0] } else { "web_out" }
if (-not [System.IO.Path]::IsPathRooted($Dest)) { $Dest = Join-Path $RootDir $Dest }

# --- prerequisites --------------------------------------------------------
$Renpy = Join-Path $RenpySdk "renpy.exe"
if (-not (Test-Path $Renpy)) { Write-Error "deploy-web.ps1: renpy.exe not found in renpy-sdk\ — run scripts\fetch-renpy-sdk.ps1 first."; exit 1 }
if (-not (Test-Path (Join-Path $RenpySdk "web"))) { Write-Error "deploy-web.ps1: Ren'Py Web support not found — run scripts\fetch-renpy-web.ps1 first."; exit 1 }
if (-not (Test-Path (Join-Path $WebAssets "ssruntime.js")) -or -not (Test-Path (Join-Path $WebAssets "ssruntime_bg.wasm"))) {
    Write-Error "deploy-web.ps1: web runtime missing under game\spritestudio\libs\web\ — run scripts\download-sdk.ps1 first."; exit 1
}

# The top-level renpy.exe is a GUI-subsystem binary: launched from a console it
# prints nothing, doesn't block, and returns exit 0 immediately — so web_build
# would silently do nothing. Drive Ren'Py through the console python instead
# (same trick as run-demo.ps1) so we get output, blocking, and a real exit code.
$PythonExe = Join-Path $RenpySdk "lib/py3-windows-x86_64/python.exe"
$RenpyPy   = Join-Path $RenpySdk "renpy.py"
if (Test-Path $PythonExe) {
    $RenpyExe = $PythonExe; $RenpyPre = @($RenpyPy)
} else {
    $RenpyExe = $Renpy;     $RenpyPre = @()
}

# --- run the Web export ----------------------------------------------------
Write-Host ">> building Web export -> $Dest"
& $RenpyExe @RenpyPre $Launcher web_build $RootDir --dest $Dest
if ($LASTEXITCODE -ne 0) { Write-Error "deploy-web.ps1: web_build failed ($LASTEXITCODE)"; exit 1 }

if (-not (Test-Path (Join-Path $Dest "index.html"))) { Write-Error "deploy-web.ps1: export did not produce $Dest\index.html"; exit 1 }

Write-Host "deploy-web.ps1: done -> $Dest"
Write-Host "  Serve it over HTTP (not file://), as any Ren'Py Web export."
