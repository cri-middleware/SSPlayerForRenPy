$ErrorActionPreference = "Stop"

$baseDirectory = Split-Path -Parent $PSCommandPath
$rootDirectory = Split-Path -Parent $baseDirectory
$targetDir = "$rootDirectory/game/spritestudio/libs"
$versionFile = "$rootDirectory/SDK_VERSION.txt"
$currentVersionFile = "$targetDir/VERSION"

$targetVersion = (Get-Content $versionFile).Trim()

if (Test-Path $currentVersionFile) {
    $currentVersion = (Get-Content $currentVersionFile).Trim()
    if ($currentVersion -eq $targetVersion) {
        Write-Host "SDK $targetVersion is already up to date. Skipping download."
        exit 0
    }
}

# Note: The zip file name should match what is actually published on the SpriteStudio-SDK releases.
$url = "https://github.com/cri-middleware/SpriteStudio-SDK/releases/download/$targetVersion/spritestudio-sdk-dynamic-libs.zip"
$zipFile = "$targetDir/sdk.zip"

Write-Host "Target SDK Version: $targetVersion"
Write-Host "Download URL: $url"
Write-Host "Downloading SDK..."
if (-Not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
}
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri $url -OutFile $zipFile
$ProgressPreference = 'Continue'

Write-Host "Extracting SDK..."
$global:ProgressPreference = 'SilentlyContinue'
Expand-Archive -Path $zipFile -DestinationPath $targetDir -Force
$global:ProgressPreference = 'Continue'
Remove-Item $zipFile

Set-Content -Path $currentVersionFile -Value $targetVersion

Write-Host "Done."
