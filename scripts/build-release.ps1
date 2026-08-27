# Build the release: the drop-in `spritestudio/` folder a creator pastes into
# their Ren'Py project, the playable Web demo, and the checksums over both.
#
#   .\scripts\build-release.ps1                  # both assets
#   .\scripts\build-release.ps1 demo=skip        # the plugin zip only, much faster
#   .\scripts\build-release.ps1 sdk=build        # compile the libs from the submodule
#   .\scripts\build-release.ps1 out=C:\tmp\rel   # somewhere else
#
# release.yml's release job runs the .sh twin for the assets it uploads, so CI
# and a local run cannot drift. The workflow keeps only what is GitHub's -- the
# checkout, the artifact upload and the Release itself.
#
# Both assets ship, so both are built here. The Web demo is not a side product:
# pages.yml publishes it as the playable demo by downloading it off the Release,
# so a release without it leaves the site pointing at the previous one. It is
# also the expensive half -- it fetches the Ren'Py SDK and runs a full Web
# export -- which is what demo=skip is for while iterating on the plugin zip.
#
# This is the phase AFTER it has been decided what is being released: the tag
# comes from the checkout, not from an option. What this does NOT do is bump
# __version__ or tag anything.
#
# The two checks are the ones that have actually bitten:
#
#   The tag must match __version__. A Release called v1.2.3 carrying
#   SSPlayerForRenPy-1.2.4.zip is worse than no release, and nothing downstream
#   would notice.
#
#   The macOS framework must still be a bundle. libs/macos/libssruntime.framework
#   is versioned -- Versions/Current and the bundle-root aliases are symlinks --
#   and zip FOLLOWS symlinks unless told not to, flattening it into plain copies.
#   That invalidates its code signature, so a game bundling the extracted
#   framework can no longer be signed or notarised. Consumers get that framework
#   only through this zip, and the working tree here always has the real
#   symlinks, so a flattened bundle would ship unnoticed.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = "Stop"

$app = Split-Path -Leaf $PSCommandPath
$rootDirectory = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$packageDirectory = "$rootDirectory/game/spritestudio"

# --- options ---------------------------------------------------------------

$out = "release-dist"
$sdk = "download"
$demo = "build"
$verify = "yes"
$clean = "yes"

function Show-Usage {
    Write-Host "Usage: $app [options]"
    Write-Host "$app options:"
    Write-Host "  out=<dir>               Where the zips and SHA256SUMS land (default:"
    Write-Host "                          release-dist). Relative paths resolve against the"
    Write-Host "                          current directory."
    Write-Host "  sdk=<download|build|skip>"
    Write-Host "                          Where the SpriteStudio SDK libs come from (default:"
    Write-Host "                          download). download = download-sdk.ps1, the version"
    Write-Host "                          pinned by scripts/SDK_VERSION.txt (what CI uses)."
    Write-Host "                          build = build-runtime.ps1, from the submodule sources"
    Write-Host "                          -- this host's platform only, so never a release."
    Write-Host "                          skip = use game/spritestudio/libs/ as it stands."
    Write-Host "  demo=<build|skip>       Whether to build the Web demo (default: build)."
    Write-Host "                          build fetches the Ren'Py SDK and runs the Web export,"
    Write-Host "                          which is most of the wall clock here. skip leaves the"
    Write-Host "                          demo out -- fine while iterating on the plugin zip,"
    Write-Host "                          never for a release: pages.yml publishes the demo by"
    Write-Host "                          downloading it off the Release."
    Write-Host "  verify=<yes|no>         Re-open the finished zips and check them (default: yes)."
    Write-Host "  clean=<yes|no>          Delete <out> before building (default: yes)."
    Write-Host "  -h | --help             Show this help"
    Write-Host ""
    Write-Host "Output: <out>/ holds SSPlayerForRenPy-<version>.zip, the Web demo zip, the"
    Write-Host "version-less alias of each (the stable releases/latest/download/ names the"
    Write-Host "README, the docs and pages.yml use), and SHA256SUMS over all four."
    Write-Host ""
    Write-Host "There is no option for which release this is: the tag comes from the checkout"
    Write-Host "this runs in, and it must match __version__."
}

foreach ($argument in $Arguments) {
    switch -Regex ($argument) {
        '^(-h|--help|help)$' { Show-Usage; exit 0 }
        # Lower-cased where the option is a keyword; out= is a path.
        '^out='    { $out = $argument.Substring(4) }
        '^sdk='    { $sdk = $argument.Substring(4).ToLower() }
        '^demo='   { $demo = $argument.Substring(5).ToLower() }
        '^verify=' { $verify = $argument.Substring(7).ToLower() }
        '^clean='  { $clean = $argument.Substring(6).ToLower() }
        default {
            Write-Error "${app}: unknown argument '$argument' (options are key=value; see $app --help)"
        }
    }
}

if ($sdk    -notin @("download", "build", "skip")) { Write-Error "${app}: sdk must be download, build or skip (got '$sdk')" }
if ($demo   -notin @("build", "skip"))             { Write-Error "${app}: demo must be build or skip (got '$demo')" }
if ($verify -notin @("yes", "no"))                 { Write-Error "${app}: verify must be yes or no (got '$verify')" }
if ($clean  -notin @("yes", "no"))                 { Write-Error "${app}: clean must be yes or no (got '$clean')" }

# GetFullPath(path, basePath) rather than Join-Path: Join-Path concatenates
# unconditionally, so an out= that is already absolute would be appended to the
# current directory instead of used as given.
$out = [System.IO.Path]::GetFullPath($out, (Get-Location).Path)

$rootFull = [System.IO.Path]::GetFullPath($rootDirectory)
$packageFull = [System.IO.Path]::GetFullPath($packageDirectory)
if (($out -eq $rootFull) -or ($out -eq $packageFull) -or ($out -eq [System.IO.Path]::GetPathRoot($out))) {
    Write-Error "${app}: refusing to use '$out' as out= (it is deleted when clean=yes)"
}

Set-Location $rootDirectory

# --- what this release is called -------------------------------------------
$version = (& "$rootDirectory/scripts/release-version.ps1").Trim()
$manifestTag = "v$version"

if (($env:GITHUB_REF_TYPE -eq "tag") -and $env:GITHUB_REF_NAME) {
    $tag = $env:GITHUB_REF_NAME
    $tagSource = "GITHUB_REF_NAME -- the ref this release was dispatched from"
} else {
    $described = & git -C $rootDirectory describe --exact-match --match 'v[0-9]*' --tags HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $described) {
        $tag = $described.Trim()
        $tagSource = "the release tag HEAD is checked out at"
    } else {
        $tag = ""
        $tagSource = "HEAD is not on a release tag, so this is a build, not a release"
    }
}

$artifact = "SSPlayerForRenPy-$version.zip"
$demoZip = "SSPlayerForRenPy-web-demo-$version.zip"
# Version-less aliases: the README, the docs and pages.yml all fetch through
# releases/latest/download/<name>, a URL that must not change when the version
# does. Byte-identical copies under a stable name.
$alias = "SSPlayerForRenPy.zip"
$demoAlias = "SSPlayerForRenPy-web-demo.zip"

Write-Host "options"
Write-Host "  out      => $out"
Write-Host "  sdk      => $sdk"
Write-Host "  demo     => $demo"
Write-Host "  verify   => $verify"
Write-Host "  clean    => $clean"
Write-Host "  version  => $version"
if ($tag) { Write-Host "  tag      => $tag" } else { Write-Host "  tag      => (none)" }
Write-Host "              ($tagSource)"

# A tag that disagrees with the shipped __version__ is not a warning: the
# Release would be called one thing and carry a zip called another, and the
# version inside the drop-in folder a creator ends up with is the zip's.
if ($tag -and ($tag -ne $manifestTag)) {
    Write-Host ""
    Write-Error "${app}: tag $tag does not match __version__ ($manifestTag). Bump ss_renpy.__version__, or retag -- the assets would be named $artifact."
}

# --- preflight -------------------------------------------------------------

if (-not (Test-Path -PathType Container $packageDirectory)) {
    Write-Error "${app}: game/spritestudio not found -- is this the SSPlayerForRenPy repo?"
}

# `zip` rather than Compress-Archive: -y stores symlinks rather than following
# them, which Compress-Archive cannot do at all, and the macOS framework depends
# on it. Same tool as the .sh twin, so the two archives match.
if (-not (Get-Command zip -ErrorAction SilentlyContinue)) {
    Write-Error "${app}: zip not found -- it is what packages the archives, and Compress-Archive cannot store the symlinks the macOS framework needs. Install it, or run scripts/build-release.sh."
}

# Get-FileHash returns an upper-case hash; sha256sum writes lower-case. Emit the
# lower-case form so SHA256SUMS is byte-identical to the one the shell twin (and
# CI) writes, and so `sha256sum -c` accepts it.
function Get-Sha256($file) { (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower() }

function Write-Step($message) {
    Write-Host ""
    Write-Host ">> $message"
}

$failed = New-Object System.Collections.Generic.List[string]

if (($clean -eq "yes") -and (Test-Path $out)) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path $out | Out-Null

# --- the native libraries --------------------------------------------------
if ($sdk -eq "download") {
    Write-Step "installing the pinned SDK native libraries"
    & "$rootDirectory/scripts/download-sdk.ps1"
} elseif ($sdk -eq "build") {
    Write-Step "building the SDK native libraries from source (THIS HOST ONLY)"
    Write-Host "   Other platforms are left as they were, so what lands in the zip is"
    Write-Host "   whatever is in game/spritestudio/libs. Never a release."
    & "$rootDirectory/scripts/build-runtime.ps1"
} else {
    Write-Step "sdk=skip -- keeping game/spritestudio/libs as it stands"
}

if (-not (Test-Path "$packageDirectory/libs/VERSION")) {
    Write-Error "${app}: game/spritestudio/libs/VERSION is missing -- the SDK libs are not installed. Run scripts/download-sdk.ps1, or pass sdk=download"
}
Write-Host "   libs/VERSION => $((Get-Content "$packageDirectory/libs/VERSION").Trim())"

# --- the plugin zip --------------------------------------------------------
Write-Step "packaging game/spritestudio -> $artifact"

# The licence documents ride inside the drop-in folder so they travel with every
# copy: the vendored FlatBuffers runtime is Apache-2.0, which requires the
# licence text to accompany redistribution. They are copies of the repo-root
# originals, so they are removed again afterwards however this exits -- leaving
# them behind would put two untracked files in game/spritestudio that only a
# release run ever creates.
try {
    Copy-Item -Force "$rootDirectory/LICENSE.md" "$packageDirectory/"
    Copy-Item -Force "$rootDirectory/LICENSE.ja.md" "$packageDirectory/"
    Copy-Item -Force "$rootDirectory/THIRD_PARTY_NOTICES.md" "$packageDirectory/"

    # `spritestudio` at the archive root, so a creator drops it straight into
    # their project's game/ directory. -X drops the extra file attributes,
    # keeping the archive reproducible.
    Push-Location "$rootDirectory/game"
    try {
        & zip -qr -X -y "$out/$artifact" spritestudio -x '*.rpyc' '*/__pycache__/*' '*/.DS_Store'
    } finally { Pop-Location }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue "$packageDirectory/LICENSE.md", "$packageDirectory/LICENSE.ja.md", "$packageDirectory/THIRD_PARTY_NOTICES.md"
}

Copy-Item -Force "$out/$artifact" "$out/$alias"
Write-Host "   $artifact"
Write-Host "   $alias  (stable releases/latest/download/ name)"

# --- the Web demo ----------------------------------------------------------
if ($demo -eq "build") {
    Write-Step "building the Web demo -> $demoZip"
    # The Ren'Py SDK plus its Web support, then the animation data the demo
    # plays, then the export itself. deploy-examples must run before deploy-web:
    # the exporter packs game/ as it stands.
    & "$rootDirectory/scripts/fetch-renpy-sdk.ps1"
    & "$rootDirectory/scripts/fetch-renpy-web.ps1"
    & "$rootDirectory/scripts/deploy-examples.ps1"
    & "$rootDirectory/scripts/deploy-web.ps1" web_out
    Push-Location "$rootDirectory/web_out"
    try { & zip -qr -X "$out/$demoZip" . -x '*/.DS_Store' } finally { Pop-Location }
    Copy-Item -Force "$out/$demoZip" "$out/$demoAlias"
    Write-Host "   $demoZip"
    Write-Host "   $demoAlias  (stable name pages.yml downloads)"
} else {
    Write-Step "demo=skip -- no Web demo in this build"
    Write-Host "   pages.yml publishes the demo by downloading it off the Release, so a"
    Write-Host "   release built this way would leave the site on the previous one."
}

# --- checksums -------------------------------------------------------------
# Covers the aliases too: they are byte-identical copies, but they download
# separately, so a consumer verifying one needs its line.
Write-Step "writing SHA256SUMS"
$archives = Get-ChildItem -Path $out -Filter *.zip -File | Sort-Object Name
$sumLines = foreach ($file in $archives) { "$(Get-Sha256 $file.FullName)  $($file.Name)" }
[System.IO.File]::WriteAllText("$out/SHA256SUMS", ($sumLines -join "`n") + "`n", (New-Object System.Text.UTF8Encoding $false))
Write-Host "   $($archives.Count) archives"

# --- verify ----------------------------------------------------------------
if ($verify -eq "yes") {
    Write-Step "verifying $out"

    # The macOS framework is still a bundle. This is the regression guard for the
    # -y above, and the only place it can be checked: the repo's own working tree
    # always has the real symlinks, so nothing before the zip can tell.
    #
    # unzip, not Expand-Archive: Expand-Archive would materialise the symlink
    # entries as something else, which is exactly what is being tested.
    $check = "$rootDirectory/build/release-zipcheck"
    if (Test-Path $check) { Remove-Item -Recurse -Force $check }
    New-Item -ItemType Directory -Force -Path $check | Out-Null
    & unzip -qq "$out/$artifact" -d $check

    $framework = "$check/spritestudio/libs/macos/libssruntime.framework"
    if (-not (Test-Path -PathType Container $framework)) {
        $failed.Add("$artifact has no libs/macos/libssruntime.framework")
    } else {
        foreach ($link in @("$framework/Versions/Current", "$framework/libssruntime")) {
            $item = Get-Item -Force -ErrorAction SilentlyContinue $link
            if ((-not $item) -or ($item.LinkType -ne "SymbolicLink")) {
                $failed.Add("$($link.Substring($check.Length + 1)) is not a symlink -- the macOS framework was flattened (zip needs -y)")
            }
        }
        if ($failed.Count -eq 0) { Write-Host "   macOS framework: version symlinks intact" }
    }

    # The drop-in folder has to work with no scripts/, no SDK and no build, so
    # the things a creator's project reaches for have to be inside it.
    foreach ($f in @("spritestudio/LICENSE.md", "spritestudio/LICENSE.ja.md", "spritestudio/THIRD_PARTY_NOTICES.md",
                     "spritestudio/libs/VERSION", "spritestudio/python/ss_renpy/__init__.py")) {
        if (-not (Test-Path "$check/$f")) { $failed.Add("$artifact is missing $f") }
    }

    # The version inside the folder is the one the archive is named after. This
    # is the tag check from the other end: it catches a zip built from a tree
    # whose __init__.py was edited after the name was computed.
    $packed = ""
    $packedInit = "$check/spritestudio/python/ss_renpy/__init__.py"
    if (Test-Path $packedInit) {
        foreach ($line in Get-Content $packedInit) {
            if ($line -match '^__version__\s*=\s*"([^"]*)"') { $packed = $Matches[1]; break }
        }
    }
    if ($packed -ne $version) {
        $failed.Add("$artifact contains __version__ $packed, expected $version")
    }

    # Compiled bytecode and caches are excluded on purpose: .rpyc files built
    # against this Ren'Py would be stale in a creator's project.
    $entries = & unzip -Z1 "$out/$artifact"
    if ($entries | Where-Object { $_ -match '\.rpyc$|/__pycache__/' }) {
        $failed.Add("$artifact contains .rpyc or __pycache__ (the -x patterns did not hold)")
    }

    Remove-Item -Recurse -Force $check

    if ($demo -eq "build") {
        $demoEntries = & unzip -Z1 "$out/$demoZip"
        foreach ($f in @("index.html", "game.zip")) {
            if ($demoEntries -notcontains $f) { $failed.Add("$demoZip has no $f") }
        }
        # The two post-export steps deploy-web exists to apply: the runtime has
        # to sit outside game.zip as a real file, because a browser's ES-module
        # import cannot read into the archive.
        if (-not ($demoEntries | Where-Object { $_ -match 'spritestudio/libs/web/ssruntime_bg\.wasm$' })) {
            $failed.Add("$demoZip has no HTTP-reachable ssruntime_bg.wasm (deploy-web step 4)")
        }
        if ($failed.Count -eq 0) { Write-Host "   Web demo: index.html, game.zip and the unpacked runtime" }
    }

    # Each alias is the same bytes as the zip it stands in for.
    if ((Get-Sha256 "$out/$artifact") -ne (Get-Sha256 "$out/$alias")) {
        $failed.Add("$alias is not identical to $artifact")
    }
    if ($demo -eq "build") {
        if ((Get-Sha256 "$out/$demoZip") -ne (Get-Sha256 "$out/$demoAlias")) {
            $failed.Add("$demoAlias is not identical to $demoZip")
        }
    }

    foreach ($line in Get-Content "$out/SHA256SUMS") {
        $parts = $line -split '\s+', 2
        if ($parts.Count -ne 2) { continue }
        if ((Get-Sha256 (Join-Path $out $parts[1].Trim())) -ne $parts[0].ToLower()) {
            $failed.Add("SHA256SUMS does not verify for $($parts[1].Trim())")
        }
    }

    if ($failed.Count -gt 0) {
        Write-Host ""
        Write-Error "${app}: the release in $out is not shippable:`n  $($failed -join "`n  ")"
    }
    Write-Host "   aliases identical, SHA256SUMS verified"
    Write-Host "   all checks passed"
} else {
    Write-Step "verify=no -- the archives are not checked"
}

# --- done ------------------------------------------------------------------
Write-Host ""
if ($tag) {
    Write-Host "${app}: done -> $out  ($tag)"
} else {
    Write-Host "${app}: done -> $out  ($manifestTag)"
}
Write-Host ""
Get-ChildItem -Path $out | ForEach-Object { Write-Host ("  {0,12}  {1}" -f $_.Length, $_.Name) }
Write-Host ""
Write-Host "${app}: this is what release.yml attaches to the draft Release."
Write-Host "${app}: try the plugin before shipping it -- unzip into a Ren'Py project's game/:"
Write-Host "  unzip -o $out/$artifact -d <your-renpy-project>/game/"
