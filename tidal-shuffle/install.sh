#!/bin/bash
# Install Tidal Shuffle on a Mac: ./install.sh
#
# Makes a private Python environment in .venv (no system pip needed),
# installs media-control, and puts the `tidal-shuffle` command on your PATH.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || die "this installer is for macOS"

# Homebrew: needed for a recent Python and for media-control.
if ! command -v brew >/dev/null 2>&1; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$b" ] && eval "$("$b" shellenv)" && break
    done
fi
command -v brew >/dev/null 2>&1 || die "Homebrew is not installed. Install it from https://brew.sh, then run ./install.sh again."

# Python 3.10 or newer. The python3 that ships with macOS is 3.9, which is too old.
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }
python=""
for p in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$p" >/dev/null 2>&1 && py_ok "$(command -v "$p")"; then
        python="$(command -v "$p")"
        break
    fi
done
if [ -z "$python" ]; then
    say "Installing Python 3.12 with Homebrew"
    brew install python@3.12
    python="$(brew --prefix python@3.12)/bin/python3.12"
fi
say "Using $("$python" --version) at $python"

say "Creating the Python environment in .venv"
"$python" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

if ! command -v media-control >/dev/null 2>&1; then
    say "Installing media-control"
    brew install media-control 2>/dev/null || brew install ungive/media-control/media-control
fi

# Put the command on PATH via Homebrew's bin directory (already on PATH).
bindir="$(brew --prefix)/bin"
ln -sf "$here/.venv/bin/tidal-shuffle" "$bindir/tidal-shuffle"
say "Linked $bindir/tidal-shuffle"

say "Installed: $("$here/.venv/bin/tidal-shuffle" --version)"
# Tidal Shuffle.app, for the Dock and Spotlight (opens the view in Terminal)
"$here/.venv/bin/tidal-shuffle" app || say "Could not make Tidal Shuffle.app (run \`tidal-shuffle app\` later)"
# Is the `tidal-shuffle` your shell finds this one? (An older copy elsewhere on
# PATH, e.g. from pipx or another folder, would keep running the old code.)
found="$(command -v tidal-shuffle || true)"
real() { "$python" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
if [ -n "$found" ] && [ "$(real "$found")" != "$(real "$here/.venv/bin/tidal-shuffle")" ]; then
    printf '\033[33mWarning:\033[0m %s comes first on your PATH and is a different copy.\n' "$found"
    printf '  Remove it (rm %s) or put %s first, then open a new terminal window.\n' "$found" "$bindir"
fi

cat <<'EOF'

Done. Check with `tidal-shuffle --version` (in an already open window, run
`hash -r` first if it still shows an older version). Next:

  tidal-shuffle login     # sign in to TIDAL (approve the link it prints)
  tidal-shuffle doctor    # checks everything and says how to fix it
  tidal-shuffle run       # start shuffling: play any song in TIDAL

EOF
