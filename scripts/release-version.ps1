# Print the package version -- what a release of this plugin should be tagged as.
#
#   .\scripts\release-version.ps1            # 7.0.0b1
#   "v$(.\scripts\release-version.ps1)"      # v7.0.0b1  -- the git tag
#
# It is `__version__` in game/spritestudio/python/ss_renpy/__init__.py, and
# nothing else. That file ships inside the drop-in folder, so it is the version
# a creator actually has in their project -- which is why it, and not
# scripts/SDK_VERSION.txt or scripts/RENPY_VERSION.txt, is what a release is
# named after. Those two pin dependencies and move on their own schedule.
#
# The tag is what names a release. This is what the tag *must* be: build-release
# refuses a tag that disagrees, because a Release called v1.2.3 carrying
# SSPlayerForRenPy-1.2.4.zip is worse than no release at all.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = "Stop"

$app = Split-Path -Leaf $PSCommandPath
foreach ($argument in $Arguments) {
    switch -Regex ($argument) {
        '^(-h|--help|help)$' {
            Write-Host "Usage: $app"
            Write-Host "Prints __version__ from game/spritestudio/python/ss_renpy/__init__.py"
            Write-Host "(no leading 'v')."
            exit 0
        }
        default { Write-Error "${app}: unexpected argument '$argument' (see $app --help)" }
    }
}

$rootDirectory = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$init = "$rootDirectory/game/spritestudio/python/ss_renpy/__init__.py"

if (-not (Test-Path $init)) {
    Write-Error "${app}: $init not found -- is this the SSPlayerForRenPy repo?"
}

$version = ""
foreach ($line in Get-Content $init) {
    if ($line -match '^__version__\s*=\s*"([^"]*)"') { $version = $Matches[1]; break }
}

if (-not $version) {
    Write-Error "${app}: no __version__ in game/spritestudio/python/ss_renpy/__init__.py"
}

Write-Output $version
