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
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { Write-Error "cargo (Rust) not on PATH" }
$CargoFlags = if ($Mode -eq "debug") { @() } else { @("--release") }

# --- convert test projects -> game\sprites\<project> ----------------------
function Convert-Project([string]$Sspj, [string]$Dest) {
    Write-Host ">> converting $Sspj -> $Dest"
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Push-Location $SdkDir
    try { cargo run $CargoFlags -q -p ssconverter-cli -- $Sspj -o $Dest } finally { Pop-Location }
}
Convert-Project "tests/overall/overall.sspj" (Join-Path $GameDir "sprites\overall")
Convert-Project "tests/Ringo/Ringo.sspj"     (Join-Path $GameDir "sprites\Ringo")
Write-Host "deploy-examples.ps1: done -> game\sprites\{overall,Ringo}\"
