$ErrorActionPreference = "Stop"

$HelpApp = Split-Path -Leaf $PSCommandPath
function Show-Usage {
    Write-Host "Usage: ${HelpApp} [--help]"
    Write-Host "  Install the SpriteStudio-SDK release pinned by scripts/SDK_VERSION.txt into"
    Write-Host "  game/spritestudio/libs/. Skips the download when that version is already in place."
}

foreach ($arg in $args) {
    switch -Regex ($arg) {
        '^(-h|--help|help)$' { Show-Usage; exit 0 }
        default {
            [Console]::Error.WriteLine("${HelpApp}: unknown argument '$arg'")
            Show-Usage
            exit 2
        }
    }
}

$baseDirectory = Split-Path -Parent $PSCommandPath
$rootDirectory = Split-Path -Parent $baseDirectory
$targetDir = "$rootDirectory/game/spritestudio/libs"
$versionFile = "$baseDirectory/SDK_VERSION.txt"
$currentVersionFile = "$targetDir/VERSION"
# Downloaded zips are cached here (gitignored) so a re-run that needs the same
# version reuses them instead of re-downloading tens of MB.
$cacheDir = "$baseDirectory/.sdk-cache"

$targetVersion = (Get-Content $versionFile).Trim()

if (Test-Path $currentVersionFile) {
    $currentVersion = (Get-Content $currentVersionFile).Trim()
    if ($currentVersion -eq $targetVersion) {
        Write-Host "SDK $targetVersion is already up to date. Skipping download."
        exit 0
    }
}

$baseUrl = "https://github.com/cri-middleware/SpriteStudio-SDK/releases/download/$targetVersion"
# RenPy consumes two archives: the native dynamic libraries, and the combined
# web archive — from which only the SIMD runtime-web/ bundle (ssruntime.js +
# ssruntime_bg.wasm) is needed for the Web export target, the same files
# build-runtime.sh copies from pkg/runtime-web/.
$dynamicAsset = "spritestudio-sdk-dynamic-libs.zip"
$webAsset = "spritestudio-sdk-web-libs.zip"
$sumsFile = "$cacheDir/SHA256SUMS"

Write-Host "Target SDK Version: $targetVersion"
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

function Get-Sha256($file) { (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower() }

# Fetch the checksum manifest (small): it both verifies integrity and decides
# whether an already-cached zip can be reused without re-downloading.
$ProgressPreference = 'SilentlyContinue'
Write-Host "Downloading checksum manifest: $baseUrl/SHA256SUMS"
Invoke-WebRequest -Uri "$baseUrl/SHA256SUMS" -OutFile $sumsFile

# Get-CachedZip <asset-name>: leave a checksum-verified copy of the asset in
# $cacheDir (reusing it when already valid, else downloading) and return its path.
function Get-CachedZip($asset) {
    $file = "$cacheDir/$asset"
    $expected = $null
    foreach ($line in Get-Content $sumsFile) {
        $parts = $line -split '\s+', 2
        if ($parts.Count -eq 2 -and $parts[1].Trim() -eq $asset) { $expected = $parts[0].ToLower(); break }
    }
    if (-not $expected) {
        Write-Error "No checksum entry for $asset in SHA256SUMS"
        exit 1
    }
    if ((Test-Path $file) -and ((Get-Sha256 $file) -eq $expected)) {
        Write-Host "Reusing cached $asset"
    } else {
        Write-Host "Downloading $baseUrl/$asset"
        Invoke-WebRequest -Uri "$baseUrl/$asset" -OutFile $file
        if ((Get-Sha256 $file) -ne $expected) {
            Remove-Item -Force $file
            Write-Error "Checksum mismatch for $asset"
            exit 1
        }
    }
    return $file
}

$dynamicZip = Get-CachedZip $dynamicAsset
$webZip = Get-CachedZip $webAsset
$ProgressPreference = 'Continue'
Write-Host "Checksum OK"

Write-Host "Extracting SDK..."
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
try {
    $global:ProgressPreference = 'SilentlyContinue'

    # Native dynamic libraries: extract to a temp, then move libs/* + license
    # notices into game/spritestudio/libs/<platform>/ (include/ and bindings/ are
    # unused here).
    Expand-Archive -Path $dynamicZip -DestinationPath $tmpDir -Force
    if (Test-Path $targetDir) { Remove-Item -Recurse -Force $targetDir }
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    Move-Item -Path "$tmpDir/libs/*" -Destination $targetDir -Force
    Copy-Item -Path "$tmpDir/LICENSE.md" -Destination $targetDir -Force -ErrorAction SilentlyContinue
    Copy-Item -Path "$tmpDir/THIRD-PARTY-LICENSES.*.md" -Destination $targetDir -Force -ErrorAction SilentlyContinue

    # Web runtime: the combined web archive holds runtime-web/, runtime-web-nosimd/
    # and converter-web/ subdirs; RenPy needs only the SIMD runtime-web/ bundle.
    # Expand it and copy just that subdir's contents into game/spritestudio/libs/web/
    # (the same files build-runtime.sh copies from pkg/runtime-web/).
    $webExtract = Join-Path $tmpDir "webpkg"
    New-Item -ItemType Directory -Force -Path $webExtract | Out-Null
    Expand-Archive -Path $webZip -DestinationPath $webExtract -Force
    New-Item -ItemType Directory -Force -Path "$targetDir/web" | Out-Null
    Copy-Item -Path "$webExtract/runtime-web/*" -Destination "$targetDir/web" -Recurse -Force

    $global:ProgressPreference = 'Continue'
} finally {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}

Set-Content -Path $currentVersionFile -Value $targetVersion

Write-Host "Done."
