#!/usr/bin/env bash
#
# Check that every scripts/*.sh and its .ps1 twin answer the same way. Each is
# run with --help and with an argument no script takes, and the twins have to
# agree on both exit statuses and on the help they print:
#
#   --help             exits 0 -- or 2, from a script that takes nothing at all
#   --no-such-option   exits 2, before the script has done anything
#
# A script without a twin is held to the same two answers on its own. The help
# is compared once what is meant to differ is taken out: each twin's own name
# (.sh / .ps1), the path separator, $env:NAME for $NAME, the launcher's name
# (renpy.exe / renpy.sh) and the line wrapping. Anything else a pair says
# differently on purpose is listed in expected_difference below.
#
# It needs bash and PowerShell 7 both, which is why it has no .ps1 twin of its
# own; ci.yml runs it on every pull request.
#
# Usage: scripts/check-twins.sh [--help]
#   PWSH : the PowerShell to run the .ps1 twins with (default: pwsh)
set -euo pipefail

APP="$(basename "$0")"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

usage() { sed -n '3,/^[^#]/p' "$0" | sed '/^[^#]/d; s/^# \{0,1\}//'; }
for a in "$@"; do
  case "$a" in
    -h|--help|help) usage; exit 0 ;;
    *) echo "$APP: unknown argument '$a' (see $APP --help)" >&2; exit 2 ;;
  esac
done

PWSH="${PWSH:-pwsh}"
command -v "$PWSH" > /dev/null 2>&1 || {
  echo "$APP: $PWSH not found -- PowerShell 7 is what runs the .ps1 twins (set PWSH to point at one)" >&2
  exit 1
}
BOGUS="--no-such-option"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A script that starts real work instead of answering would otherwise hold the
# job until it timed out. timeout is coreutils, so where it is missing (a stock
# macOS) the runs go unguarded.
GUARD=()
command -v timeout > /dev/null 2>&1 && GUARD=(timeout 120)

# run <stdout-file> <command...>: prints the exit status. stdin is closed so a
# prompt cannot wait for input.
run () {
  local out="$1" code=0
  shift
  ( cd "$ROOT_DIR" && ${GUARD[@]+"${GUARD[@]}"} "$@" ) < /dev/null > "$out" 2> "$out.err" || code=$?
  echo "$code"
}

# The help with what is meant to differ between twins taken out, one word per
# line so a difference reads as a diff.
normalise () {
  tr -d '\r' \
    | sed -e 's|\\|/|g' -e 's/\.ps1/.sh/g' -e 's/\$env:/$/g' -e 's/renpy\.exe/renpy.sh/g' \
    | tr -s ' \t\n' '\n\n\n' | sed '/^$/d'
}

# What a pair says differently on purpose, as a sed script over the .ps1's help.
expected_difference () {
  case "$1" in
    # The .ps1 defaults to py, the launcher a python.org install puts on PATH.
    prepare-docs) echo 's/(default: py)/(default: python3)/' ;;
    *) echo '' ;;
  esac
}

FAILED=0
fail () {
  echo "FAIL $*"
  FAILED=$((FAILED + 1))
}

cd "$ROOT_DIR"
for ps1 in scripts/*.ps1; do
  [ -f "${ps1%.ps1}.sh" ] || fail "$ps1 has no .sh twin"
done

pairs=0
singles=0
for sh in scripts/*.sh; do
  name="$(basename "$sh" .sh)"
  [ "$name.sh" = "$APP" ] && continue
  ps1="scripts/$name.ps1"

  sh_help="$(run "$TMP/$name.sh.help" bash "$sh" --help)"
  sh_bogus="$(run "$TMP/$name.sh.bogus" bash "$sh" "$BOGUS")"
  case "$sh_help" in
    0) [ -s "$TMP/$name.sh.help" ] || fail "$sh --help exits 0 but prints nothing" ;;
    2) ;;
    *) fail "$sh --help exits $sh_help (expected 0, or 2 from a script that takes nothing)" ;;
  esac
  [ "$sh_bogus" = 2 ] || fail "$sh $BOGUS exits $sh_bogus (expected 2)"

  if [ ! -f "$ps1" ]; then
    singles=$((singles + 1))
    echo "ok   $sh (no twin): --help $sh_help, $BOGUS $sh_bogus"
    continue
  fi
  pairs=$((pairs + 1))

  ps_help="$(run "$TMP/$name.ps1.help" "$PWSH" -NoLogo -NoProfile -NonInteractive -File "$ps1" --help)"
  ps_bogus="$(run "$TMP/$name.ps1.bogus" "$PWSH" -NoLogo -NoProfile -NonInteractive -File "$ps1" "$BOGUS")"
  [ "$ps_help" = "$sh_help" ] || fail "$name: --help exits $sh_help from the .sh but $ps_help from the .ps1"
  [ "$ps_bogus" = "$sh_bogus" ] || fail "$name: $BOGUS exits $sh_bogus from the .sh but $ps_bogus from the .ps1"

  normalise < "$TMP/$name.sh.help" > "$TMP/$name.sh.words"
  sed -e "$(expected_difference "$name")" "$TMP/$name.ps1.help" | normalise > "$TMP/$name.ps1.words"
  if cmp -s "$TMP/$name.sh.words" "$TMP/$name.ps1.words"; then
    echo "ok   $name.{sh,ps1}: --help $sh_help, $BOGUS $sh_bogus, same help"
  else
    fail "$name: the twins print different help (normalised, a word per line; - .sh, + .ps1)"
    diff -u "$TMP/$name.sh.words" "$TMP/$name.ps1.words" | sed '1,2d' || true
  fi
done

echo ""
if [ "$FAILED" -gt 0 ]; then
  echo "$APP: $FAILED problem(s) across $pairs pairs and $singles scripts without a twin" >&2
  exit 1
fi
echo "$APP: $pairs pairs agree, and $singles scripts without a twin answer as they should"
