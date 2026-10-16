#!/usr/bin/env pwsh
#
# Convert the SpriteStudio test projects into playback data under
# game\ss_assets\ (.ssab + referenced textures, via
# tools\cli_convert.py).
#
# Scope: ONLY the playback data. The native libssruntime binary is the job of
# scripts\build-runtime.{sh,ps1}, not this script.
#   game\ss_assets\           <- deploy-examples.{sh,ps1}   (this script)
#   game\spritestudio\libs\   <- build-runtime.{sh,ps1}
# Both are gitignored.
#
# Usage: scripts\deploy-examples.ps1   (no options)
#
# SDK location: $env:SSSDK, else .\SpriteStudio-SDK (submodule), else ..\SpriteStudio-SDK.

$ErrorActionPreference = "Stop"

foreach ($arg in $args) {
    switch -Regex -CaseSensitive ($arg) {
        '^(-h|--help)$' {
            # The header comment, all of it, as the .sh twin prints it.
            foreach ($line in (Get-Content $PSCommandPath | Select-Object -Skip 1)) {
                if ($line -notmatch '^#') { break }
                $line -replace '^# ?', ''
            }
            exit 0
        }
        default {
            [Console]::Error.WriteLine("deploy-examples.ps1: unknown arg '$arg'")
            exit 2
        }
    }
}

$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$GameDir = Join-Path $RootDir "game"

# --- locate the SDK -------------------------------------------------------
$SdkDir = $env:SSSDK
if (-not $SdkDir) {
    foreach ($cand in @((Join-Path $RootDir "SpriteStudio-SDK"), (Join-Path $RootDir "..\SpriteStudio-SDK"))) {
        if (Test-Path (Join-Path $cand "Cargo.toml")) { $SdkDir = (Resolve-Path $cand).Path; break }
    }
}
if (-not $SdkDir -or -not (Test-Path (Join-Path $SdkDir "Cargo.toml"))) {
    Write-Error "SpriteStudio-SDK not found (init the submodule or set `$env:SSSDK)"
}
# Ren'Py ships a python per platform (py3-mac-universal / py3-linux-<arch> /
# py3-windows-x86_64). Pick the one matching THIS host and arch -- a bare py3-*
# grabs py3-linux first, and on Linux the first arch -- as the .sh twin does.
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
    [Console]::Error.WriteLine("deploy-examples.ps1: python/python3 not found in renpy-sdk or PATH")
    exit 1
}

# --- convert test projects -> SpriteStudio_Source/ -> game\ss_assets\<project> ---
$SourceDir = Join-Path $RootDir "SpriteStudio_Source"
New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null

function Convert-Project([string]$TestFolder, [string]$ProjectName, [string]$Dest) {
    Write-Host ">> copying $TestFolder to SpriteStudio_Source\$ProjectName and converting..."
    
    $srcDir = Join-Path $SdkDir $TestFolder
    $workDir = Join-Path $SourceDir $ProjectName
    
    if (Test-Path $workDir) { Remove-Item -Recurse -Force $workDir }
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null
    Copy-Item -Recurse -Force "$srcDir\*" "$workDir\"
    
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    
    $sspjPath = Join-Path $workDir "$ProjectName.sspj"
    & $pythonCmd (Join-Path $RootDir "tools\cli_convert.py") $sspjPath $Dest
    # cli_convert.py exits 1 on conversion failure; $ErrorActionPreference does
    # not cover native commands, so propagate explicitly (the .sh uses set -e).
    if ($LASTEXITCODE -ne 0) {
        Write-Error "deploy-examples.ps1: conversion failed for $ProjectName ($LASTEXITCODE)"
    }
    # Stamp the auto-importer freshness marker so a dev-mode launch does not
    # reconvert this pack (cli_convert.py itself writes no marker). Non-fatal.
    & $pythonCmd (Join-Path $RootDir "tools\ss_stamp_import.py") $sspjPath $Dest
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "deploy-examples.ps1: could not stamp import marker for $ProjectName (will reconvert on next dev launch)"
    }
}

Convert-Project "tests/overall" "overall" (Join-Path $GameDir "ss_assets\overall")
Convert-Project "tests/Ringo" "Ringo"     (Join-Path $GameDir "ss_assets\Ringo")
Convert-Project "tests/ParticleEffect" "ParticleEffect" (Join-Path $GameDir "ss_assets\ParticleEffect")
Convert-Project "tests/Doll" "Doll" (Join-Path $GameDir "ss_assets\Doll")
Write-Host "deploy-examples.ps1: done -> game\ss_assets\{overall,Ringo,ParticleEffect,Doll}\"
