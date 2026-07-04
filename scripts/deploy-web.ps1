#!/usr/bin/env pwsh
#
# Build the Ren'Py Web export AND apply the two SSPlayer post-export steps the
# Web target needs (docs\export.md §3, §4) but that the Ren'Py exporter cannot
# do on its own:
#   3. inject the ssruntime.js / .wasm module <script> into index.html, and
#   4. copy game\spritestudio\libs\web\{ssruntime.js,ssruntime_bg.wasm} out of
#      game.zip into <dest>\game\spritestudio\libs\web\ as real, HTTP-reachable
#      files (a browser's ES-module import cannot read files inside game.zip).
#
# The exporter regenerates index.html and repacks game.zip on every run, so
# these steps must be re-applied after each export — that is what this script
# automates. Both steps are idempotent, so re-running is safe.
#
# Prereqs: Ren'Py SDK in renpy-sdk\ (fetch-renpy-sdk.ps1) with Web support
# (fetch-renpy-web.ps1), and the web runtime under game\spritestudio\libs\web\
# (download-sdk.ps1 / build-runtime.ps1).
#
# Usage: scripts\deploy-web.ps1 [dest_dir]
#   dest_dir : output folder (default: web_out)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RenpySdk = Join-Path $RootDir "renpy-sdk"
$Launcher = Join-Path $RenpySdk "launcher"
$WebAssets = Join-Path $RootDir "game/spritestudio/libs/web"

if ($Args.Count -ge 1 -and ($Args[0] -in @("-h", "--help", "help"))) {
    Get-Content $PSCommandPath | Select-String -Pattern '^# Usage:', '^#   ' | ForEach-Object { $_.Line -replace '^# ?', '' }
    exit 0
}
$Dest = if ($Args.Count -ge 1) { $Args[0] } else { "web_out" }
if (-not [System.IO.Path]::IsPathRooted($Dest)) { $Dest = Join-Path $RootDir $Dest }

# --- prerequisites --------------------------------------------------------
$Renpy = Join-Path $RenpySdk "renpy.exe"
if (-not (Test-Path $Renpy)) { Write-Error "deploy-web.ps1: renpy.exe not found in renpy-sdk\ — run scripts\fetch-renpy-sdk.ps1 first."; exit 1 }
if (-not (Test-Path (Join-Path $RenpySdk "web"))) { Write-Error "deploy-web.ps1: Ren'Py Web support not found — run scripts\fetch-renpy-web.ps1 first."; exit 1 }
if (-not (Test-Path (Join-Path $WebAssets "ssruntime.js")) -or -not (Test-Path (Join-Path $WebAssets "ssruntime_bg.wasm"))) {
    Write-Error "deploy-web.ps1: web runtime missing under game\spritestudio\libs\web\ — run scripts\download-sdk.ps1 first."; exit 1
}

# --- 2. run the Web export ------------------------------------------------
Write-Host ">> building Web export -> $Dest"
& $Renpy $Launcher web_build $RootDir --dest $Dest
if ($LASTEXITCODE -ne 0) { Write-Error "deploy-web.ps1: web_build failed ($LASTEXITCODE)"; exit 1 }

$Index = Join-Path $Dest "index.html"
if (-not (Test-Path $Index)) { Write-Error "deploy-web.ps1: export did not produce $Index"; exit 1 }

# --- 3. inject the module <script> before renpy-pre.js (idempotent) -------
$content = Get-Content -Raw $Index
if ($content.Contains("spritestudio/libs/web/ssruntime.js")) {
    Write-Host ">> index.html: module script already present"
} else {
    Write-Host ">> index.html: injecting ssruntime module script"
    $anchor = '  <script src="renpy-pre.js"></script>'
    if (-not $content.Contains($anchor)) { Write-Error "deploy-web.ps1: renpy-pre.js anchor not found in index.html"; exit 1 }
    $inject = @"
  <script type="module">
    import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
    window.ssruntime = ss;
    window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
  </script>
"@
    $content = $content.Replace($anchor, $inject + "`n" + $anchor)
    Set-Content -NoNewline -Path $Index -Value $content
}

# --- 4. copy the web runtime out of game.zip as real files ----------------
Write-Host ">> placing web runtime under $Dest\game\spritestudio\libs\web\"
$OutWeb = Join-Path $Dest "game/spritestudio/libs/web"
New-Item -ItemType Directory -Force -Path $OutWeb | Out-Null
Copy-Item (Join-Path $WebAssets "ssruntime.js") $OutWeb -Force
Copy-Item (Join-Path $WebAssets "ssruntime_bg.wasm") $OutWeb -Force

Write-Host "deploy-web.ps1: done -> $Dest"
Write-Host "  Serve it over HTTP (not file://). Any static server works; the assets"
Write-Host "  need .js=application/javascript and .wasm=application/wasm MIME types."
