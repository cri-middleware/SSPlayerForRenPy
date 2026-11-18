# Generate Python flatbuffers bindings from the SpriteStudio-SDK schemas.
# Output: game/spritestudio/python/ss/

$ErrorActionPreference = "Stop"
$HelpApp = Split-Path -Leaf $PSCommandPath
# Returned rather than written, so the unknown-argument path can send it to
# stderr as the .sh twin does.
function Show-Usage {
    "Usage: ${HelpApp} [--help]"
    "  flatc --python over the SDK's .fbs schemas, into game/spritestudio/python/ss/."
    "  Needs flatc. The old bindings are removed first."
}
# Plain stderr and the code, as the .sh twin answers.
function Fail([string] $Message, [int] $Code = 1) {
    [Console]::Error.WriteLine("${HelpApp}: $Message")
    exit $Code
}

foreach ($arg in $args) {
    switch -Regex -CaseSensitive ($arg) {
        '^(-h|--help|help)$' { Show-Usage; exit 0 }
        default {
            [Console]::Error.WriteLine("${HelpApp}: unknown argument '$arg'")
            Show-Usage | ForEach-Object { [Console]::Error.WriteLine($_) }
            exit 2
        }
    }
}

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$SdkDir = $env:SSSDK
if ([string]::IsNullOrEmpty($SdkDir)) {
    foreach ($cand in @((Join-Path $RootDir "SpriteStudio-SDK"), (Join-Path $RootDir "../SpriteStudio-SDK"))) {
        if (Test-Path (Join-Path $cand "Cargo.toml")) { $SdkDir = $cand; break }
    }
}
# A $env:SSSDK that is set is checked too, as the .sh twin does.
if ([string]::IsNullOrEmpty($SdkDir) -or -not (Test-Path (Join-Path $SdkDir "Cargo.toml"))) {
    Fail "SpriteStudio-SDK not found."
}

if (-not (Get-Command "flatc" -ErrorAction SilentlyContinue)) {
    Fail "flatc not on PATH"
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

if ($LASTEXITCODE -ne 0) { Fail "flatc failed ($LASTEXITCODE)" $LASTEXITCODE }

Write-Host "generate-fbs-code.ps1: done."
