# Generate Python flatbuffers bindings from the SpriteStudio-SDK schemas.
# Output: game/spritestudio/python/ss/

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$SdkDir = $env:SSSDK
if ([string]::IsNullOrEmpty($SdkDir)) {
    if (Test-Path "$RootDir\SpriteStudio-SDK\Cargo.toml") {
        $SdkDir = "$RootDir\SpriteStudio-SDK"
    } elseif (Test-Path "$RootDir\..\SpriteStudio-SDK\Cargo.toml") {
        $SdkDir = "$RootDir\..\SpriteStudio-SDK"
    } else {
        Write-Error "SpriteStudio-SDK not found."
        exit 1
    }
}

if (-not (Get-Command "flatc" -ErrorAction SilentlyContinue)) {
    Write-Error "flatc not found on PATH."
    exit 1
}

$OutDir = "$RootDir\game\spritestudio\python"
Write-Host "Generating Python bindings to $OutDir\ss ..."

if (Test-Path "$OutDir\ss") {
    Remove-Item -Recurse -Force "$OutDir\ss"
}

& flatc --python -o "$OutDir" `
    "$SdkDir\libs\ssab\fbs\ssab.fbs" `
    "$SdkDir\libs\ssab\fbs\ssqb.fbs" `
    "$SdkDir\libs\ssruntime\fbs\effect_draw_plan.fbs" `
    "$SdkDir\libs\ssruntime\fbs\framedata.fbs"

if ($LASTEXITCODE -ne 0) {
    Write-Error "flatc failed."
    exit $LASTEXITCODE
}

Write-Host "generate-fbs-code.ps1: done."
