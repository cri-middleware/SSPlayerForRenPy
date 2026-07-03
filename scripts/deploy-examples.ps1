#!/usr/bin/env pwsh
#
# Convert the SpriteStudio test projects into playback data under game\sprites\
# (.ssab + referenced textures, via ssconverter-cli). Windows counterpart of
# scripts/deploy-examples.sh.
#
# Scope: ONLY the playback data. The native libssruntime binary is the job of
# scripts/build-runtime.ps1, not this script.
#   game\sprites\            <- deploy-examples.ps1 (this script)
#   game\spritestudio\libs\  <- build-runtime.ps1
#
# Usage: scripts\deploy-examples.ps1 [-Mode release|debug]   (ssconverter-cli build mode)
#
# SDK location: $env:SSSDK, else .\SpriteStudio-SDK (submodule), else ..\SpriteStudio-SDK.

param(
    [ValidateSet("release", "debug")] [string]$Mode = "release"
)

$ErrorActionPreference = "Stop"
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
$pythonCmd = "python"
if (-not (Get-Command $pythonCmd -ErrorAction SilentlyContinue)) {
    if (Get-Command "python3" -ErrorAction SilentlyContinue) {
        $pythonCmd = "python3"
    } else {
        Write-Error "python/python3 not on PATH"
    }
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
}

Convert-Project "tests/overall" "overall" (Join-Path $GameDir "ss_assets\overall")
Convert-Project "tests/Ringo" "Ringo"     (Join-Path $GameDir "ss_assets\Ringo")
Convert-Project "tests/ParticleEffect" "ParticleEffect" (Join-Path $GameDir "ss_assets\ParticleEffect")
Write-Host "deploy-examples.ps1: done -> game\ss_assets\{overall,Ringo,ParticleEffect}\"
