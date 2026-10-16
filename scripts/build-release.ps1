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

# Plain stderr and the code, matching the .sh twin (2 = bad usage, 1 = the
# release cannot be built). Write-Error throws under $ErrorActionPreference =
# "Stop", so an `exit 2` after one never runs and the shell always sees 1.
function Fail([string] $Message, [int] $Code = 1) {
    [Console]::Error.WriteLine("${app}: $Message")
    exit $Code
}

# $ErrorActionPreference does not cover native commands, nor a child script
# that ends with `exit <n>`: both only set $LASTEXITCODE. Every one is checked,
# as `set -e` does in the .sh twin.
function Assert-Exit([string] $What) {
    if ($LASTEXITCODE -ne 0) { Fail "$What failed ($LASTEXITCODE)" }
}
function Invoke-Script([string] $Name, [string[]] $ScriptArgs = @()) {
    $global:LASTEXITCODE = 0
    & "$rootDirectory/scripts/$Name" @ScriptArgs
    Assert-Exit $Name
}

# --- options ---------------------------------------------------------------

$out = "release-dist"
$sdk = "download"
$demo = "build"
$verify = "yes"
$clean = "yes"

function Show-Usage {
    Write-Host "Usage: $app [options]"
    Write-Host "$app options:"
    Write-Host "  out=<dir>               Where the zips and SHA256SUMS land (default: $out)."
    Write-Host "                          Relative paths resolve against the current directory."
    Write-Host "  sdk=<download|build|skip>"
    Write-Host "                          Where the SpriteStudio SDK libs come from (default:"
    Write-Host "                          $sdk). download = download-sdk.ps1, the release"
    Write-Host "                          pinned by scripts/SDK_VERSION.txt (release.yml's"
    Write-Host "                          choice). build = build-runtime.ps1, from the submodule"
    Write-Host "                          sources -- this host's platform only, so never a"
    Write-Host "                          release. skip = use game/spritestudio/libs/ as it"
    Write-Host "                          stands."
    Write-Host "  demo=<build|skip>       Whether to build the Web demo (default: $demo)."
    Write-Host "                          build fetches the Ren'Py SDK and runs the Web export,"
    Write-Host "                          which is most of the wall clock here. skip leaves the"
    Write-Host "                          demo out -- fine while iterating on the plugin zip,"
    Write-Host "                          never for a release: pages.yml publishes the demo by"
    Write-Host "                          downloading it off the Release."
    Write-Host "  verify=<yes|no>         Re-open the finished zips and check them (default:"
    Write-Host "                          $verify)."
    Write-Host "  clean=<yes|no>          Delete <out> before building (default: $clean)."
    Write-Host "  in= skip=               Accepted and ignored here. The family's build-release"
    Write-Host "                          scripts share out= clean= verify= in= sdk= skip=,"
    Write-Host "                          so one command line drives all of them."
    Write-Host "  -h | --help             Show this help"
    Write-Host ""
    Write-Host "Output: <out>/ holds SSPlayerForRenPy-<version>.zip, the Web demo zip, the"
    Write-Host "version-less alias of each (the stable releases/latest/download/ names the"
    Write-Host "README, the docs and pages.yml use), and SHA256SUMS over all four."
    Write-Host ""
    Write-Host "There is no option for which release this is: the tag comes from the checkout"
    Write-Host "this runs in (the ref the workflow was dispatched from, or 'git checkout <tag>'"
    Write-Host "locally), and it must match __version__."
}

# Case-sensitive, and `continue` after a match (switch -Regex runs every case
# that matches), so an argument means here what it means to the .sh twin.
foreach ($argument in $Arguments) {
    switch -Regex -CaseSensitive ($argument) {
        '^(-h|--help|help)$' { Show-Usage; exit 0 }
        # Lower-cased where the option is a keyword; out= is a path.
        '^out='    { $out = $argument.Substring(4); continue }
        '^sdk='    { $sdk = $argument.Substring(4).ToLower(); continue }
        '^demo='   { $demo = $argument.Substring(5).ToLower(); continue }
        '^verify=' { $verify = $argument.Substring(7).ToLower(); continue }
        '^clean='  { $clean = $argument.Substring(6).ToLower(); continue }
        # Accepted so one command line drives build-release in every repository
        # of the family; this one has no use for them.
        '^(in|skip)=' {
            [Console]::Error.WriteLine("${app}: " + ($argument -replace '=.*$', '') + "= does not apply here; ignored")
            continue
        }
        '=' { Fail "unknown option '$($argument -replace '=.*$', '')' (see $app --help)" 2 }
        default { Fail "unknown argument '$argument' (options are key=value; see $app --help)" 2 }
    }
}

if ($sdk    -notin @("download", "build", "skip")) { Fail "sdk must be download, build or skip (got '$sdk')" 2 }
if ($demo   -notin @("build", "skip"))             { Fail "demo must be build or skip (got '$demo')" 2 }
if ($verify -notin @("yes", "no"))                 { Fail "verify must be yes or no (got '$verify')" 2 }
if ($clean  -notin @("yes", "no"))                 { Fail "clean must be yes or no (got '$clean')" 2 }

# GetFullPath(path, basePath) rather than Join-Path: Join-Path concatenates
# unconditionally, so an out= that is already absolute would be appended to the
# current directory instead of used as given.
$out = [System.IO.Path]::GetFullPath($out, (Get-Location).Path)

$rootFull = [System.IO.Path]::GetFullPath($rootDirectory)
$packageFull = [System.IO.Path]::GetFullPath($packageDirectory)
if (($out -eq $rootFull) -or ($out -eq $packageFull) -or ($out -eq [System.IO.Path]::GetPathRoot($out))) {
    Fail "refusing to use '$out' as out= (it is deleted when clean=yes)" 2
}

Set-Location $rootDirectory

# --- what this release is called -------------------------------------------
$global:LASTEXITCODE = 0
$version = "$(& "$rootDirectory/scripts/release-version.ps1")".Trim()
Assert-Exit "release-version.ps1"
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
    [Console]::Error.WriteLine("")
    [Console]::Error.WriteLine("${app}: tag $tag does not match __version__ ($manifestTag).")
    Fail "bump ss_renpy.__version__, or retag -- the assets would be named $artifact."
}

# --- preflight -------------------------------------------------------------

if (-not (Test-Path -PathType Container $packageDirectory)) {
    Fail "game/spritestudio not found -- is this the SSPlayerForRenPy repo?"
}

# `zip` rather than Compress-Archive: -y stores symlinks rather than following
# them, which Compress-Archive cannot do at all, and the macOS framework depends
# on it. `unzip` for the verify step, for the same reason. The same tools as the
# .sh twin, so the two archives match.
foreach ($tool in @("zip", "unzip")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Fail "$tool not found -- it is what packages the archives, and Compress-Archive / Expand-Archive cannot handle the symlinks the macOS framework needs. Install it, or run scripts/build-release.sh."
    }
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
# sdk=download ships the release scripts/SDK_VERSION.txt names, while CI tests
# the submodule and the demo's packs are converted with it: the two have to be
# the same commit, or what ships is not what was tested.
if ($sdk -eq "download") {
    $sdkPin = (Get-Content (Join-Path $rootDirectory "scripts/SDK_VERSION.txt") -Raw).Trim()
    $sdkUrl = "$(& git -C $rootDirectory config -f .gitmodules submodule.SpriteStudio-SDK.url)".Trim()
    $sdkHave = "$(& git -C $rootDirectory rev-parse HEAD:SpriteStudio-SDK)".Trim()
    $sdkWant = ""
    $sdkRefs = @(& git ls-remote $sdkUrl "refs/tags/$sdkPin" "refs/tags/$sdkPin^{}")
    if ($LASTEXITCODE -ne 0) { Fail "could not list the tags of $sdkUrl" }
    foreach ($line in $sdkRefs) {
        $sha, $ref = $line -split "`t"
        if ($ref -eq "refs/tags/$sdkPin^{}") { $sdkWant = $sha; break }
        if ($ref -eq "refs/tags/$sdkPin") { $sdkWant = $sha }
    }
    if ($sdkHave -ne $sdkWant) {
        $wantText = if ($sdkWant) { $sdkWant } else { "no such tag" }
        [Console]::Error.WriteLine("${APP}: the SpriteStudio-SDK submodule is at $sdkHave, not at $sdkPin ($wantText), which scripts/SDK_VERSION.txt names")
        Fail "CI tests the submodule and sdk=download ships $sdkPin -- point the submodule at that release, or pass sdk=build"
    }
    Write-Host "   SpriteStudio-SDK submodule => $sdkPin"
}
if ($sdk -eq "download") {
    Write-Step "installing the pinned SDK native libraries"
    Invoke-Script "download-sdk.ps1"
} elseif ($sdk -eq "build") {
    Write-Step "building the SDK native libraries from source (THIS HOST ONLY)"
    Write-Host "   Other platforms are left as they were, so what lands in the zip is"
    Write-Host "   whatever is in game/spritestudio/libs. Never a release."
    Invoke-Script "build-runtime.ps1"
} else {
    Write-Step "sdk=skip -- keeping game/spritestudio/libs as it stands"
}

if (-not (Test-Path "$packageDirectory/libs/VERSION")) {
    [Console]::Error.WriteLine("${app}: game/spritestudio/libs/VERSION is missing -- the SDK libs are not installed")
    Fail "run scripts/download-sdk.ps1, or pass sdk=download"
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

    # The documentation rides along the same way, so what a creator's tooling
    # reads next to the library is the documentation of that library -- not the
    # site's, which is built from the latest release and can be ahead. README.md
    # is the folder's front door; docs/ is docs/en/ but its index.md (the site's
    # home page), as Markdown with the layout kept so the links between pages
    # resolve. The screenshots and videos stay online, which README.md says.
    # spritestudio.rpy leaves both out of a game's build.
    Copy-Item -Force "$rootDirectory/scripts/release-docs/zip-README.md" "$packageDirectory/README.md"
    if (Test-Path "$packageDirectory/docs") { Remove-Item -Recurse -Force "$packageDirectory/docs" }
    $docsSource = (Resolve-Path "$rootDirectory/docs/en").Path
    foreach ($page in Get-ChildItem -Path $docsSource -Recurse -File -Filter *.md) {
        $rel = $page.FullName.Substring($docsSource.Length + 1)
        if ($rel -eq "index.md") { continue }
        $to = Join-Path "$packageDirectory/docs" $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $to) | Out-Null
        Copy-Item -Force $page.FullName $to
    }

    # `spritestudio` at the archive root, so a creator drops it straight into
    # their project's game/ directory. -X drops the extra file attributes;
    # each entry's modification time stays.
    Push-Location "$rootDirectory/game"
    try {
        & zip -qr -X -y "$out/$artifact" spritestudio -x '*.rpyc' '*/__pycache__/*' '*/.DS_Store'
        Assert-Exit "zip ($artifact)"
    } finally { Pop-Location }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue "$packageDirectory/LICENSE.md", "$packageDirectory/LICENSE.ja.md", "$packageDirectory/THIRD_PARTY_NOTICES.md", "$packageDirectory/README.md"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$packageDirectory/docs"
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
    Invoke-Script "fetch-renpy-sdk.ps1"
    Invoke-Script "fetch-renpy-web.ps1"
    Invoke-Script "deploy-examples.ps1"
    Invoke-Script "deploy-web.ps1" @("web_out")
    Push-Location "$rootDirectory/web_out"
    try {
        & zip -qr -X "$out/$demoZip" . -x '*/.DS_Store'
        Assert-Exit "zip ($demoZip)"
    } finally { Pop-Location }
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
    Assert-Exit "unzip ($artifact)"

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
                     "spritestudio/libs/VERSION", "spritestudio/python/ss_renpy/__init__.py", "spritestudio/README.md")) {
        if (-not (Test-Path "$check/$f")) { $failed.Add("$artifact is missing $f") }
    }

    # README.md is the front door to docs/. Every page it links to is looked up
    # in the unpacked archive, so renaming or dropping a page fails the release
    # instead of shipping a link that goes nowhere.
    if (Test-Path "$check/spritestudio/README.md") {
        $links = @([regex]::Matches((Get-Content -Raw "$check/spritestudio/README.md"), '\]\((docs/[^):#]+)') | ForEach-Object { $_.Groups[1].Value })
        if ($links.Count -eq 0) { $failed.Add("no docs/ links parsed out of README.md -- the check proved nothing") }
        foreach ($link in $links) {
            if (-not (Test-Path "$check/spritestudio/$link")) { $failed.Add("README.md links to $link, which is not in $artifact") }
        }
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
    Assert-Exit "unzip -Z1 ($artifact)"
    if ($entries | Where-Object { $_ -match '\.rpyc$|/__pycache__/' }) {
        $failed.Add("$artifact contains .rpyc or __pycache__ (the -x patterns did not hold)")
    }

    Remove-Item -Recurse -Force $check

    if ($demo -eq "build") {
        $demoEntries = & unzip -Z1 "$out/$demoZip"
        Assert-Exit "unzip -Z1 ($demoZip)"
        foreach ($f in @("index.html", "game.zip")) {
            if ($demoEntries -notcontains $f) { $failed.Add("$demoZip has no $f") }
        }
        # The Brain is read out of game.zip at startup (ssruntime_web.load_library),
        # so the export plays only if both runtime files were packed into it.
        $demoCheck = "$rootDirectory/build/release-democheck"
        if (Test-Path $demoCheck) { Remove-Item -Recurse -Force $demoCheck }
        & unzip -q "$out/$demoZip" game.zip -d $demoCheck
        if ($LASTEXITCODE -eq 0) {
            $gameEntries = & unzip -Z1 "$demoCheck/game.zip"
            Assert-Exit "unzip -Z1 (game.zip)"
            foreach ($f in @("ssruntime.js", "ssruntime_bg.wasm")) {
                if ($gameEntries -notcontains "game/spritestudio/libs/web/$f") {
                    $failed.Add("${demoZip}: game.zip has no spritestudio/libs/web/$f")
                }
            }
            # The documentation is the creator's, not the player's: spritestudio.rpy
            # classifies it out of every build, and this export is one.
            if ($gameEntries | Where-Object { $_ -match '^game/spritestudio/(README\.md$|docs/)' }) {
                $failed.Add("${demoZip}: game.zip carries spritestudio/README.md or docs/ (the build.classify in spritestudio.rpy did not hold)")
            }
        }
        if (Test-Path $demoCheck) { Remove-Item -Recurse -Force $demoCheck }
        if ($failed.Count -eq 0) { Write-Host "   Web demo: index.html, and game.zip with the runtime" }
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
        [Console]::Error.WriteLine("")
        Fail "the release in $out is not shippable:`n  $($failed -join "`n  ")"
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
