#!/usr/bin/env bash
#
# Install the user systemd units on a host, rewriting the paths they were
# written against.
#
# The committed units in deploy/systemd/ hardcode /opt/TechTrend and one
# operator's pnpm. That is deliberate -- they are the units that actually run
# production, and a unit file full of placeholders cannot be diffed against
# what systemd loaded. So this script rewrites them on the way in rather than
# keeping a second, parameterized copy: a duplicate set is how the worker's
# --stage list went untracked in the first place (see systemd/README.md).
#
# Usage:
#   deploy/install.sh --dry-run            # print what would be written
#   deploy/install.sh                      # write units, print next steps
#   deploy/install.sh --enable             # write, daemon-reload, enable --now
#
# Override anything:
#   TT_ROOT=/srv/techtrend PNPM_BIN=/usr/bin/pnpm deploy/install.sh

set -euo pipefail

die() { printf 'install: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

# --- where things are -------------------------------------------------------

# This script lives at $REPO/backend/deploy/install.sh.
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
default_root=$(cd -- "$here/../.." && pwd)

TT_ROOT=${TT_ROOT:-$default_root}
UNIT_DIR=${UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}
PNPM_BIN=${PNPM_BIN:-$(command -v pnpm || true)}

# The literals in the committed units, as written.
OLD_ROOT=/opt/TechTrend
OLD_PNPM=/home/idavoll/.local/lib/node24/bin/pnpm

dry_run=0
do_enable=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --enable)  do_enable=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $arg" ;;
  esac
done

src=$TT_ROOT/backend/deploy/systemd
[[ -d $src ]] || die "no unit directory at $src -- is TT_ROOT=$TT_ROOT the repo root?"

# --- preflight --------------------------------------------------------------
#
# Checked before anything is written, because a unit that points at a missing
# binary fails at `systemctl start` with a message that says nothing useful.

problems=()
[[ -x $TT_ROOT/backend/.venv/bin/techtrend ]] \
  || problems+=("no backend/.venv/bin/techtrend -- run: make install-backend")
[[ -f $TT_ROOT/backend/.env ]] \
  || problems+=("no backend/.env -- copy backend/.env.prod.example and fill it in")
[[ -x $TT_ROOT/ops/backup-db.sh ]] \
  || problems+=("ops/backup-db.sh is not executable -- run: chmod +x ops/backup-db.sh")
if [[ -z $PNPM_BIN ]]; then
  problems+=("pnpm not on PATH -- set PNPM_BIN=/path/to/pnpm (techtrend-web needs it)")
elif [[ ! -x $PNPM_BIN ]]; then
  problems+=("PNPM_BIN=$PNPM_BIN is not executable")
fi
if [[ ! -d $TT_ROOT/clients/apps/web/.next ]]; then
  problems+=("clients/apps/web/.next is missing -- techtrend-web serves a BUILD: run make build-web")
fi
if [[ -f $TT_ROOT/backend/.env ]] && grep -qE '^TT_AI_FAKE=true' "$TT_ROOT/backend/.env"; then
  problems+=("backend/.env still has TT_AI_FAKE=true -- every model call returns a canned answer")
fi

if ((${#problems[@]})); then
  printf 'install: refusing to continue:\n' >&2
  for p in "${problems[@]}"; do printf '  - %s\n' "$p" >&2; done
  printf '\nFix these, or re-run with --dry-run to see the units anyway.\n' >&2
  ((dry_run)) || exit 1
fi

# --- rewrite ----------------------------------------------------------------

rewrite() {
  sed -e "s|$OLD_PNPM|$PNPM_BIN|g" -e "s|$OLD_ROOT|$TT_ROOT|g" -- "$1"
}

shopt -s nullglob
units=("$src"/*.service "$src"/*.timer)
((${#units[@]})) || die "no .service or .timer files in $src"

printf 'install: TT_ROOT=%s\n' "$TT_ROOT"
printf 'install: PNPM_BIN=%s\n' "${PNPM_BIN:-<unset>}"
printf 'install: UNIT_DIR=%s\n\n' "$UNIT_DIR"

((dry_run)) || mkdir -p -- "$UNIT_DIR"

names=()
for unit in "${units[@]}"; do
  name=$(basename -- "$unit")
  body=$(rewrite "$unit")

  # A unit that still carries one of the old absolute paths means this script
  # has drifted from the units -- a new one was added with a different prefix.
  # Fail rather than install something that silently points at /opt.
  if printf '%s' "$body" | grep -qE '/opt/TechTrend|/home/idavoll'; then
    die "$name still contains a hardcoded path after rewriting.
     Update OLD_ROOT/OLD_PNPM in this script to match it."
  fi

  if ((dry_run)); then
    printf '===== %s =====\n%s\n\n' "$name" "$body"
  else
    printf '%s\n' "$body" > "$UNIT_DIR/$name"
    note "wrote $UNIT_DIR/$name"
  fi
  names+=("${name%.service}")
done
shopt -u nullglob

((dry_run)) && exit 0

# --- enable -----------------------------------------------------------------

services=(techtrend-worker techtrend-api techtrend-web techtrend-slackbot)
timers=(techtrend-backup.timer)

if ((do_enable)); then
  echo
  systemctl --user daemon-reload
  systemctl --user enable --now "${services[@]}"
  systemctl --user enable --now "${timers[@]}"
  # A user timer does not fire with nobody logged in without this, and a
  # backup that silently never runs is worse than no backup.
  loginctl enable-linger "$USER"
  echo
  systemctl --user --no-pager --plain status "${services[@]}" || true
else
  cat <<NEXT

Units written. To start them:

    systemctl --user daemon-reload
    systemctl --user enable --now ${services[*]}
    systemctl --user enable --now ${timers[*]}
    loginctl enable-linger "\$USER"      # or the backup timer never fires

Or re-run this script with --enable.

Still installed by hand, and not in this directory: techtrend-report.timer.
NEXT
fi
