$ErrorActionPreference = "Stop"

$HelpApp = Split-Path -Leaf $PSCommandPath
# Returned rather than written, so the unknown-argument path can send it to
# stderr as the .sh twin does.
function Show-Usage {
    "Usage: ${HelpApp} [--help]"
    "  Install the SpriteStudio-SDK release pinned by scripts/SDK_VERSION.txt into"
    "  game/spritestudio/libs/. Skips the download when that version is already in place."
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

# Expand-Archive writes each symlink an archive stores as a small file holding
# the link's target. The dynamic-libs archive's macOS framework is versioned --
# Versions/Current and the bundle-root aliases are symlinks -- so that leaves a
# framework nothing can load, and one build-release refuses to package. This
# extracts the same way, then puts every link entry back as a link, as unzip
# does for the .sh twin. Returns how many links it could not create: Windows
# makes symlinks only in Developer Mode or from an elevated shell, and without
# either the placeholder files stay.
function Expand-ZipKeepingLinks([string] $Zip, [string] $Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Destination)
    $sep = [System.IO.Path]::DirectorySeparatorChar
    $root = [System.IO.Path]::GetFullPath($Destination).TrimEnd($sep) + $sep
    $links = @()
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        foreach ($entry in $archive.Entries) {
            # The upper 16 bits of the external attributes are the Unix mode, in
            # which S_IFLNK marks a symlink; the entry's data is the link target.
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -ne 0xA000) { continue }
            $reader = New-Object System.IO.StreamReader($entry.Open())
            try { $links += , @($entry.FullName, $reader.ReadToEnd()) } finally { $reader.Dispose() }
        }
    } finally { $archive.Dispose() }

    $failed = 0
    foreach ($link in $links) {
        $path = Join-Path $root $link[0]
        $target = $link[1]
        $resolved = [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $path) $target))
        # Relative, and inside the tree being extracted: anything else is not a
        # link this archive has any business making.
        if ([System.IO.Path]::IsPathRooted($target) -or -not $resolved.StartsWith($root)) {
            throw "$($link[0]) in $(Split-Path -Leaf $Zip) links outside the archive ($target)"
        }
        Remove-Item -Force $path
        try {
            New-Item -ItemType SymbolicLink -Path $path -Target $target | Out-Null
        } catch {
            [System.IO.File]::WriteAllText($path, $target)
            $failed++
        }
    }
    return $failed
}

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
# Inside the cache rather than the system temp directory: Move-Item renames only
# within one volume, and across two it copies, which follows the symlinks.
$tmpDir = Join-Path $cacheDir ("extract-" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
try {
    $global:ProgressPreference = 'SilentlyContinue'

    # Native dynamic libraries: extract to a temp, then move libs/* + license
    # notices into game/spritestudio/libs/<platform>/ (include/ and bindings/ are
    # unused here).
    $unlinked = Expand-ZipKeepingLinks $dynamicZip $tmpDir
    if ($unlinked -gt 0) {
        [Console]::Error.WriteLine("${HelpApp}: WARNING: $unlinked symlink(s) in the macOS libssruntime.framework could not be")
        [Console]::Error.WriteLine("${HelpApp}:   created (Windows allows them in Developer Mode, or from an elevated shell), so")
        [Console]::Error.WriteLine("${HelpApp}:   libs/macos/ holds plain files instead. Nothing on Windows loads that framework,")
        [Console]::Error.WriteLine("${HelpApp}:   but it is no longer a bundle, and build-release refuses to package it. To fix,")
        [Console]::Error.WriteLine("${HelpApp}:   allow symlinks, delete game/spritestudio/libs/VERSION and run this again.")
    }
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
    Expand-ZipKeepingLinks $webZip $webExtract | Out-Null
    New-Item -ItemType Directory -Force -Path "$targetDir/web" | Out-Null
    Copy-Item -Path "$webExtract/runtime-web/*" -Destination "$targetDir/web" -Recurse -Force

    $global:ProgressPreference = 'Continue'
} finally {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}

Set-Content -Path $currentVersionFile -Value $targetVersion

Write-Host "Done."
