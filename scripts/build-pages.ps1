#!/usr/bin/env pwsh
#
# Build the GitHub Pages site locally -- everything .github/workflows/pages.yml
# publishes, in the same order: the documentation in both locales into site\,
# then the playable Ren'Py Web demo into site\demo\. PowerShell twin of
# build-pages.sh.
#
#   scripts\build-pages.ps1                       # docs + demo from the latest release
#   scripts\build-pages.ps1 serve=yes             # ... and serve site\ on :8000
#   scripts\build-pages.ps1 demo=build            # build the demo here instead
#   scripts\build-pages.ps1 demo=build sdk=build  # ... from a locally built SDK too
#   scripts\build-pages.ps1 demo=skip             # documentation only
#
# The demo is a release ASSET, not something pages.yml builds: release.yml
# exports it (fetch-renpy-web + deploy-examples + deploy-web) and attaches
# SSPlayerForRenPy-web-demo.zip to the release; pages.yml only downloads it.
# demo=download is that path and the default -- it is what a Pages deploy will
# actually publish. demo=build runs those release.yml steps here instead, which
# is the only way to see a demo that is not in a release yet (and the only way
# at all before the first release carrying the asset is published).
#
# Ordering: the English documentation build clears site\, and both the Japanese
# site (site\ja) and the demo (site\demo) live inside it -- so the demo goes in
# last, exactly as in pages.yml. Rerunning is safe; nothing here is incremental.
#
# What this does NOT reproduce is the deploy job (actions/deploy-pages) -- there
# is no local equivalent of publishing. Serving site\ over HTTP is as close as a
# local run gets, and it is enough to check every link, both locales and the
# demo actually running in a browser.
$ErrorActionPreference = "Stop"

$APP = Split-Path -Leaf $PSCommandPath
$ROOT_DIR = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

# The version-less alias release.yml uploads next to the pinned zip; pages.yml
# downloads this same name.
$DEMO_ASSET = "SSPlayerForRenPy-web-demo.zip"
# Where deploy-web.ps1 writes the export before it is copied into site\demo --
# the same directory name release.yml uses, and already gitignored.
$WORK_DIR = "web_out"

function Fail {
    param([string] $Message, [int] $Code = 1)
    [Console]::Error.WriteLine("${APP}: $Message")
    exit $Code
}

# --- options --------------------------------------------------------------
$opts = [ordered]@{
    demo    = "download"
    sdk     = "download"
    tag     = ""
    zip     = ""
    docs    = "yes"
    prepare = "auto"
    venv    = ".venv"
    serve   = "no"
    port    = "8000"
}

function Show-Usage {
    Write-Host "Usage: $APP [options]"
    Write-Host "$APP options:"
    Write-Host "  demo=<download|build|skip>"
    Write-Host "                          Where site\demo comes from (default: download)"
    Write-Host "                          download = the release asset pages.yml publishes"
    Write-Host "                          build    = run the release.yml Web export here"
    Write-Host "                          skip     = documentation only"
    Write-Host "  sdk=<download|build|skip>"
    Write-Host "                          Where the SpriteStudio SDK libs come from (default: download)"
    Write-Host "                          download = download-sdk.ps1, the version pinned by"
    Write-Host "                                     scripts\SDK_VERSION.txt (what CI uses)"
    Write-Host "                          build    = build-runtime.ps1, from the submodule sources"
    Write-Host "                          skip     = use game\spritestudio\libs\ as it stands"
    Write-Host "                          Only consulted for demo=build -- a downloaded demo"
    Write-Host "                          carries its own runtime."
    Write-Host "  tag=<vX.Y.Z>            Release to take the demo from (default: latest)."
    Write-Host "                          demo=download only."
    Write-Host "  zip=<path>              Use this already-downloaded $DEMO_ASSET"
    Write-Host "                          instead of asking gh for one. demo=download only."
    Write-Host "  docs=<yes|no>           Build the documentation (default: yes). no keeps"
    Write-Host "                          whatever site\ already holds -- handy when only the"
    Write-Host "                          demo is being re-checked."
    Write-Host "  prepare=<auto|yes|no>   Run prepare-docs.ps1 first (default: auto)."
    Write-Host "                          auto = only when no zensical is found."
    Write-Host "  venv=<dir>              Virtualenv for the docs toolchain, relative to the"
    Write-Host "                          repo root (default: .venv). Passed to prepare-docs.ps1"
    Write-Host "                          and build-docs.ps1."
    Write-Host "  serve=<yes|no>          Serve site\ over HTTP when the build is done"
    Write-Host "                          (default: no). Foreground; Ctrl-C to stop."
    Write-Host "  port=<n>                Port for serve=yes (default: 8000)"
    Write-Host "  -h | --help             Show this help"
    Write-Host ""
    Write-Host "Output: site\ (en) + site\ja\ (ja) + site\demo\ -- the exact tree pages.yml"
    Write-Host "uploads. The documentation builds are --strict, so a broken internal link or a"
    Write-Host "nav entry pointing at a missing page fails the build here rather than on a"
    Write-Host "release publish."
    Write-Host ""
    Write-Host "The demo needs a real HTTP server (a browser cannot ES-module import from"
    Write-Host "file://), so open it through serve=yes, not by double-clicking the file."
}

foreach ($item in $args) {
    if ($item -in "-h", "--help", "help") {
        Show-Usage
        exit 0
    } elseif ($item -match "=") {
        $key, $value = $item -split "=", 2
        if (-not $opts.Contains($key)) {
            Fail "unknown option '$key' (see $APP --help)" 2
        }
        # Lower-cased where the option is an enum; tag=/zip=/venv=/port= are not.
        $opts[$key] = if ($key -in "demo", "sdk", "docs", "prepare", "serve") { $value.ToLower() } else { $value }
    } else {
        Fail "unknown argument '$item' (options are key=value; see $APP --help)" 2
    }
}

if ($opts.demo -notin "download", "build", "skip") { Fail "demo must be download, build or skip (got '$($opts.demo)')" 2 }
if ($opts.sdk -notin "download", "build", "skip")  { Fail "sdk must be download, build or skip (got '$($opts.sdk)')" 2 }
if ($opts.docs -notin "yes", "no")                 { Fail "docs must be yes or no (got '$($opts.docs)')" 2 }
if ($opts.prepare -notin "auto", "yes", "no")      { Fail "prepare must be auto, yes or no (got '$($opts.prepare)')" 2 }
if ($opts.serve -notin "yes", "no")                { Fail "serve must be yes or no (got '$($opts.serve)')" 2 }
if ($opts.port -notmatch '^\d+$')                  { Fail "port must be a number (got '$($opts.port)')" 2 }

# tag=/zip= describe where a downloaded demo comes from, so they are meaningless
# -- and, silently ignored, misleading -- anywhere else.
if ($opts.demo -ne "download") {
    if ($opts.tag) { Fail "tag= applies to demo=download (got demo=$($opts.demo))" 2 }
    if ($opts.zip) { Fail "zip= applies to demo=download (got demo=$($opts.demo))" 2 }
}
if ($opts.tag -and $opts.zip) {
    Fail "tag= and zip= are alternatives -- zip= is already a specific build" 2
}

$demoNote = ""
if ($opts.tag) { $demoNote = " (tag $($opts.tag))" } elseif ($opts.zip) { $demoNote = " (zip $($opts.zip))" }
$sdkNote = if ($opts.demo -eq "build") { "" } else { " (unused: demo=$($opts.demo))" }
$serveNote = if ($opts.serve -eq "yes") { " (port $($opts.port))" } else { "" }

Write-Host "options"
Write-Host "  demo    => $($opts.demo)$demoNote"
Write-Host "  sdk     => $($opts.sdk)$sdkNote"
Write-Host "  docs    => $($opts.docs)"
Write-Host "  prepare => $($opts.prepare)"
Write-Host "  venv    => $($opts.venv)"
Write-Host "  serve   => $($opts.serve)$serveNote"
Write-Host ""

$SITE_DIR = Join-Path $ROOT_DIR "site"
$DEMO_DIR = Join-Path $SITE_DIR "demo"

# Every script here resolves its own paths from the repo root, and site\ is
# written relative to it, so run from there however this was invoked. Every exit
# below happens inside the try, so the finally is what restores the location --
# popping it a second time on the way out would be an error of its own.
Push-Location $ROOT_DIR

function Invoke-Step {
    param([string] $Script, [string[]] $ScriptArgs = @())
    Write-Host ""
    Write-Host ">> scripts/$Script $($ScriptArgs -join ' ')"
    $global:LASTEXITCODE = 0
    & (Join-Path $ROOT_DIR "scripts/$Script") @ScriptArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "scripts/$Script failed ($LASTEXITCODE)" $LASTEXITCODE
    }
}

try {
    # --- documentation toolchain ------------------------------------------
    # Same probe as build-docs.ps1: a venv laid out either way, else PATH
    # (which is how a run with no venv at all still works).
    function Test-Zensical {
        $venvDir = Join-Path $ROOT_DIR $opts.venv
        $venvBin = if (Test-Path (Join-Path $venvDir "Scripts")) {
            Join-Path $venvDir "Scripts"
        } else {
            Join-Path $venvDir "bin"
        }
        foreach ($candidate in @((Join-Path $venvBin "zensical.exe"), (Join-Path $venvBin "zensical"))) {
            if (Test-Path $candidate) { return $true }
        }
        return [bool] (Get-Command zensical -ErrorAction SilentlyContinue)
    }

    if ($opts.docs -eq "yes") {
        switch ($opts.prepare) {
            "yes" { Invoke-Step "prepare-docs.ps1" @("venv=$($opts.venv)") }
            "auto" {
                if (Test-Zensical) {
                    Write-Host "${APP}: zensical already available; skipping prepare-docs.ps1 (prepare=yes forces it)"
                } else {
                    Invoke-Step "prepare-docs.ps1" @("venv=$($opts.venv)")
                }
            }
            "no" { }
        }

        # Both locales, English first -- build-docs.ps1 owns that order.
        Invoke-Step "build-docs.ps1" @("venv=$($opts.venv)")
    } else {
        Write-Host "${APP}: docs=no -- site\ keeps whatever the last build left there"
    }

    # --- demo: download the release asset (what pages.yml does) -----------
    function Get-Demo {
        $src = $opts.zip
        $tmp = $null

        if ($src) {
            if (-not (Test-Path $src)) { Fail "no such file: $src" }
            Write-Host ""
            Write-Host ">> using $src"
        } else {
            if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
                [Console]::Error.WriteLine("${APP}: gh (GitHub CLI) not on PATH -- install it, pass zip=<path> to a")
                Fail "downloaded $DEMO_ASSET, or build the demo with demo=build"
            }
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
            New-Item -ItemType Directory -Force -Path $tmp | Out-Null
            Write-Host ""
            $global:LASTEXITCODE = 0
            if ($opts.tag) {
                Write-Host ">> gh release download $($opts.tag) --pattern $DEMO_ASSET"
                & gh release download $opts.tag --pattern $DEMO_ASSET --dir $tmp
            } else {
                Write-Host ">> gh release download (latest) --pattern $DEMO_ASSET"
                & gh release download --pattern $DEMO_ASSET --dir $tmp
            }
            if ($LASTEXITCODE -ne 0) {
                # Says what is wrong rather than assuming the reader can just build the
                # demo instead: the sh twin runs on the Pages runner, where they cannot.
                $from = if ($opts.tag) { $opts.tag } else { "the latest release" }
                [Console]::Error.WriteLine("")
                [Console]::Error.WriteLine("${APP}: could not download $DEMO_ASSET from $from.")
                [Console]::Error.WriteLine("${APP}: release.yml attaches that asset, so it exists only on releases that")
                [Console]::Error.WriteLine("${APP}: workflow produced -- check the release actually carries it.")
                Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
                Fail "In a working tree, '$APP demo=build' runs the same export steps instead."
            }
            $src = Join-Path $tmp $DEMO_ASSET
        }

        Write-Host ">> unpacking into site\demo\"
        if (Test-Path $DEMO_DIR) { Remove-Item -Recurse -Force $DEMO_DIR }
        New-Item -ItemType Directory -Force -Path $DEMO_DIR | Out-Null
        Expand-Archive -Path $src -DestinationPath $DEMO_DIR -Force
        if ($tmp) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
    }

    # --- demo: build it here (what release.yml does) ----------------------
    function Build-Demo {
        switch ($opts.sdk) {
            "download" {
                $global:LASTEXITCODE = 0
                Write-Host ""
                Write-Host ">> scripts/download-sdk.ps1"
                & (Join-Path $ROOT_DIR "scripts/download-sdk.ps1")
                if ($LASTEXITCODE -ne 0) {
                    [Console]::Error.WriteLine("")
                    [Console]::Error.WriteLine("${APP}: download-sdk.ps1 failed -- the libs it fetches come from the")
                    [Console]::Error.WriteLine("${APP}: SpriteStudio-SDK release pinned by scripts\SDK_VERSION.txt.")
                    Fail "To build them from the submodule instead: $APP demo=build sdk=build"
                }
            }
            "build" {
                # Two builds, because the export needs two different things: the
                # wasm runtime the demo loads in the browser, and a host
                # ssconverter for deploy-examples.ps1 below. build=release for
                # both, to match the libs download-sdk.ps1 would have fetched.
                Invoke-Step "build-runtime.ps1" @("platform=web", "build=release")
                Invoke-Step "build-runtime.ps1" @("build=release")
            }
            "skip" { }
        }

        if (-not (Test-Path (Join-Path $ROOT_DIR "game/spritestudio/libs/web/ssruntime.js"))) {
            [Console]::Error.WriteLine("${APP}: no web runtime under game\spritestudio\libs\web\ -- rerun with")
            Fail "sdk=download (or sdk=build) rather than sdk=$($opts.sdk)"
        }

        # Fetch the Ren'Py SDK only when it is missing: fetch-renpy-sdk.ps1
        # replaces renpy-sdk\ wholesale, taking the Web support with it, which
        # would then have to be re-fetched too. CI starts from an empty runner
        # and so always fetches; a working tree usually has both already.
        if (-not (Test-Path (Join-Path $ROOT_DIR "renpy-sdk/renpy.exe"))) {
            Invoke-Step "fetch-renpy-sdk.ps1"
        } else {
            Write-Host "${APP}: renpy-sdk\ present; not re-fetching (it would be replaced and redownloaded)"
        }
        if (-not (Test-Path (Join-Path $ROOT_DIR "renpy-sdk/web"))) {
            Invoke-Step "fetch-renpy-web.ps1"
        } else {
            Write-Host "${APP}: renpy-sdk\web present; not re-fetching"
        }

        # The exporter packs game\ as it stands, so the playback data has to
        # exist before the export runs -- same order as release.yml. web_out\ is
        # emptied first: the exporter overwrites what it produces but removes
        # nothing, so a file an earlier export swept in would otherwise ride
        # along into site\demo forever. CI gets that for free from a fresh runner.
        Invoke-Step "deploy-examples.ps1"
        $workPath = Join-Path $ROOT_DIR $WORK_DIR
        if (Test-Path $workPath) { Remove-Item -Recurse -Force $workPath }
        Invoke-Step "deploy-web.ps1" @($WORK_DIR)

        Write-Host ""
        Write-Host ">> copying $WORK_DIR\ into site\demo\"
        if (Test-Path $DEMO_DIR) { Remove-Item -Recurse -Force $DEMO_DIR }
        New-Item -ItemType Directory -Force -Path $DEMO_DIR | Out-Null
        Copy-Item -Path (Join-Path (Join-Path $ROOT_DIR $WORK_DIR) "*") -Destination $DEMO_DIR -Recurse -Force
    }

    switch ($opts.demo) {
        "download" { Get-Demo }
        "build"    { Build-Demo }
        "skip" {
            Write-Host ""
            Write-Host "${APP}: demo=skip -- site\demo is not part of this build"
        }
    }
} finally {
    Pop-Location
}

# --- what landed ----------------------------------------------------------
Write-Host ""
Write-Host "${APP}: done -> site\"
function Write-Report {
    param([string] $RelPath, [string] $Label)
    if (Test-Path (Join-Path $ROOT_DIR $RelPath)) {
        Write-Host "  ${Label}: $RelPath"
    } else {
        Write-Host "  ${Label}: MISSING ($RelPath)"
    }
}
Write-Report "site/index.html" "en  "
Write-Report "site/ja/index.html" "ja  "
if ($opts.demo -ne "skip") {
    Write-Report "site/demo/index.html" "demo"
}

# --- serve ----------------------------------------------------------------
$PYTHON_CMD = $null
foreach ($candidate in "py", "python", "python3") {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $PYTHON_CMD = $candidate; break }
}

Write-Host ""
if ($opts.serve -eq "yes") {
    if (-not $PYTHON_CMD) { Fail "no python on PATH to serve with -- use any static server on site\" }
    Write-Host "${APP}: http://localhost:$($opts.port)/  (docs)"
    Write-Host "${APP}: http://localhost:$($opts.port)/ja/  (Japanese)"
    Write-Host "${APP}: http://localhost:$($opts.port)/demo/  (Web demo)"
    Write-Host "${APP}: Ctrl-C to stop"
    Write-Host ""
    # Python's http.server already serves .js as text/javascript and .wasm as
    # application/wasm, which is all the demo needs; any static server will do.
    & $PYTHON_CMD -m http.server $opts.port -d $SITE_DIR
} else {
    $hint = if ($PYTHON_CMD) { $PYTHON_CMD } else { "py" }
    Write-Host "${APP}: serve it (the demo needs HTTP, not file://):"
    Write-Host "${APP}:   $APP serve=yes"
    Write-Host "${APP}:   $hint -m http.server $($opts.port) -d site"
}
