# Download the pure-Python flatbuffers runtime from GitHub and vendor it.
# Output: game/spritestudio/python/flatbuffers/

$ErrorActionPreference = "Stop"

if ($args.Count -gt 0) {
    [Console]::Error.WriteLine("$(Split-Path -Leaf $PSCommandPath): takes no arguments - what it does is in its header comment")
    exit 2
}
$FbVersion = "v25.12.19"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OutDir = "$RootDir\game\spritestudio\python\flatbuffers"

Write-Host "Downloading FlatBuffers $FbVersion python runtime..."

$TmpZip = "$env:TEMP\flatbuffers-$FbVersion.zip"
$TmpExtract = "$env:TEMP\flatbuffers-extract"

$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri "https://github.com/google/flatbuffers/archive/refs/tags/$FbVersion.zip" -OutFile $TmpZip
$ProgressPreference = 'Continue'

if (Test-Path $TmpExtract) { Remove-Item -Recurse -Force $TmpExtract }
$global:ProgressPreference = 'SilentlyContinue'
Expand-Archive -Path $TmpZip -DestinationPath $TmpExtract
$global:ProgressPreference = 'Continue'

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
$ExtractedFbVer = $FbVersion.TrimStart('v')
Copy-Item -Recurse "$TmpExtract\flatbuffers-$ExtractedFbVer\python\flatbuffers" "$OutDir"

Remove-Item -Force $TmpZip
Remove-Item -Recurse -Force $TmpExtract

Write-Host "download-flatbuffers.ps1: done. Vendored to $OutDir."
