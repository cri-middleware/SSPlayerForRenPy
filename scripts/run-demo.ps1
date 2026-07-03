#!/usr/bin/env pwsh
#
# Launch the SSPlayer demo in the downloaded Ren'Py SDK. Windows counterpart of
# scripts/run-demo.sh; fetches the SDK first if it is not present yet.
#
# Usage: scripts\run-demo.ps1
#
# Equivalent manual command (from the project root):
#   renpy-sdk\renpy.exe .

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Launcher = Join-Path $RootDir "renpy-sdk\renpy.exe"

if (-not (Test-Path $Launcher)) {
    Write-Host "run-demo.ps1: Ren'Py SDK not found at renpy-sdk\ - fetching it first..."
    & (Join-Path $RootDir "scripts\fetch-renpy-sdk.ps1")
}

Write-Host "Launching the SSPlayer demo: $Launcher $RootDir"
Start-Process -FilePath $Launcher -ArgumentList $RootDir -Wait -NoNewWindow
