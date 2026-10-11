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

if ($args.Count -gt 0) {
    [Console]::Error.WriteLine("$(Split-Path -Leaf $PSCommandPath): takes no arguments - what it does is in its header comment")
    exit 2
}
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Launcher = Join-Path $RootDir "renpy-sdk\renpy.exe"

if (-not (Test-Path $Launcher)) {
    Write-Host "run-demo.ps1: Ren'Py SDK not found at renpy-sdk\ - fetching it first..."
    & (Join-Path $RootDir "scripts\fetch-renpy-sdk.ps1")
}
$PythonExe = Join-Path $RootDir "renpy-sdk\lib\py3-windows-x86_64\python.exe"
$RenpyPy = Join-Path $RootDir "renpy-sdk\renpy.py"

if (Test-Path $PythonExe) {
    Write-Host "Launching the SSPlayer demo (console mode): $PythonExe $RenpyPy $RootDir"
    # Using python.exe (a console app) ensures standard output is piped to the shell.
    # The & operator natively waits for console apps to finish.
    & $PythonExe $RenpyPy $RootDir
} else {
    Write-Host "Launching the SSPlayer demo: $Launcher $RootDir"
    # Fallback to the GUI launcher.
    Start-Process -FilePath $Launcher -ArgumentList $RootDir -Wait -NoNewWindow
}
