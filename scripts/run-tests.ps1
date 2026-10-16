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
    if ($item -cmatch '^(-h|--help|help)$') {
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

# Same interpreter resolution as run-tests.sh and deploy-examples.*: prefer the
# python Ren'Py ships for THIS host and arch when the SDK is present (a bare
# py3-* glob grabs py3-linux first, and on Linux the first arch), so a machine
# with only the Ren'Py SDK can still run the suite. Not found is a preflight
# failure, exit status 2, as documented above.
$pythonCmd = ""
$RenpyLibDir = Join-Path $RootDir "renpy-sdk/lib"
if (Test-Path $RenpyLibDir) {
    $plat = if ($IsMacOS) { "py3-mac-*" } elseif ($IsLinux) { "py3-linux-$("$(& uname -m)".Trim())*" } else { "py3-windows-*" }
    $RenpyPythonDir = Get-ChildItem -Path $RenpyLibDir -Directory -Filter $plat | Sort-Object Name | Select-Object -First 1
    if ($RenpyPythonDir) {
        foreach ($name in "python", "python.exe") {
            $candidate = Join-Path $RenpyPythonDir.FullName $name
            if (Test-Path -PathType Leaf $candidate) { $pythonCmd = $candidate; break }
        }
    }
}
if (-not $pythonCmd) {
    # python3 first, as in the .sh twin -- except on Windows, where python3 is
    # often only the Microsoft Store's stand-in and python the real interpreter.
    $order = if ($IsMacOS -or $IsLinux) { @("python3", "python") } else { @("python", "python3") }
    foreach ($name in $order) {
        if (Get-Command $name -ErrorAction SilentlyContinue) { $pythonCmd = $name; break }
    }
}
if (-not $pythonCmd) {
    [Console]::Error.WriteLine("run-tests.ps1: python/python3 not found in renpy-sdk or PATH")
    exit 2
}

& $pythonCmd (Join-Path $RootDir "tools\run_tests.py") @Args
exit $LASTEXITCODE
