#!/usr/bin/env pwsh
#
# Run the headless test suite (tools\verify_*.py + tools\m0_smoke.py) — the
# whole engine-independent layer, in plain CPython, with no Ren'Py and no GUI.
# Windows counterpart of scripts/run-tests.sh (same key=value interface). The
# work is tools\run_tests.py; this picks the interpreter and forwards the
# arguments, the way deploy-examples.ps1 delegates to tools\cli_convert.py.
#
# Two prerequisites, both gitignored and so both missing from a fresh clone.
# The runner checks them before it starts anything and names the script that
# produces each, rather than letting the suite report green on a tree where
# nothing loaded:
#   game\spritestudio\libs\   <- build-runtime.ps1
#   game\ss_assets\           <- deploy-examples.ps1
#
# GL2 rendering is not covered here and cannot be: PMA, mesh, blend, mask and
# the ss-* GLSL need a GUI run — sign off via Shift+B or scripts\run-demo.ps1.
#
# Usage: scripts\run-tests.ps1 [only=<names>] [skip=<names>] [list=yes] [verbose=yes]
#   only    : comma-separated substrings; run only the tools that match
#   skip    : comma-separated substrings; skip the tools that match
#   list    : yes to list the discovered tools and exit
#   verbose : yes to stream every tool's output, not just the failing ones
#
# Exit status: 0 all passed, 1 something failed or was skipped, 2 preflight failed.

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

foreach ($item in $Args) {
    if ($item -match "^-?-?help$" -or $item -eq "-h") {
        # The contiguous block from "# Usage:" to "# Exit status", which is what
        # the .sh twin prints with sed -n '/^# Usage:/,/^# Exit status/p'.
        $emit = $false
        foreach ($line in (Get-Content $PSCommandPath)) {
            if ($line -match '^# Usage:') { $emit = $true }
            if ($emit) { $line -replace '^# ?', '' }
            if ($emit -and $line -match '^# Exit status') { break }
        }
        exit 0
    }
}

# Same interpreter resolution as deploy-examples.ps1: prefer the python Ren'Py
# ships for THIS host when the SDK is present, so a machine with only the
# Ren'Py SDK can still run the suite.
$pythonCmd = ""
$RenpyLibDir = Join-Path $RootDir "renpy-sdk\lib"
if (Test-Path $RenpyLibDir) {
    $plat = if ($IsMacOS) { "py3-mac-*" } elseif ($IsLinux) { "py3-linux-*" } else { "py3-windows-*" }
    $RenpyPythonDirs = Get-ChildItem -Path $RenpyLibDir -Directory -Filter $plat
    if ($RenpyPythonDirs.Count -gt 0) {
        $bundledPython = Join-Path $RenpyPythonDirs[0].FullName "python.exe"
        if (-not (Test-Path $bundledPython)) {
            $bundledPython = Join-Path $RenpyPythonDirs[0].FullName "python"
        }
        if (Test-Path $bundledPython) {
            $pythonCmd = $bundledPython
        }
    }
}

if (-not $pythonCmd) {
    if (Get-Command "python" -ErrorAction SilentlyContinue) {
        $pythonCmd = "python"
    } elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
        $pythonCmd = "python3"
    } else {
        Write-Error "python/python3 not found in renpy-sdk or PATH"
    }
}

& $pythonCmd (Join-Path $RootDir "tools\run_tests.py") @Args
exit $LASTEXITCODE
