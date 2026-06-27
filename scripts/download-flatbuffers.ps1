# Download the pure-Python flatbuffers runtime from GitHub and vendor it.
# Output: game/spritestudio/python/flatbuffers/

$ErrorActionPreference = "Stop"
$FbVersion = "v25.12.19"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OutDir = "$RootDir\game\spritestudio\python\flatbuffers"

Write-Host "Downloading FlatBuffers $FbVersion python runtime..."

$TmpZip = "$env:TEMP\flatbuffers-$FbVersion.zip"
$TmpExtract = "$env:TEMP\flatbuffers-extract"

Invoke-WebRequest -Uri "https://github.com/google/flatbuffers/archive/refs/tags/$FbVersion.zip" -OutFile $TmpZip

if (Test-Path $TmpExtract) { Remove-Item -Recurse -Force $TmpExtract }
Expand-Archive -Path $TmpZip -DestinationPath $TmpExtract

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
$ExtractedFbVer = $FbVersion.TrimStart('v')
Copy-Item -Recurse "$TmpExtract\flatbuffers-$ExtractedFbVer\python\flatbuffers" "$OutDir"

Remove-Item -Force $TmpZip
Remove-Item -Recurse -Force $TmpExtract

Write-Host "download-flatbuffers.ps1: done. Vendored to $OutDir."
