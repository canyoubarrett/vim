"""Make a folder (and zip) to give Tidal Shuffle to a friend.

    python3 tools/make_share.py            # → dist/Tidal Shuffle/ and dist/Tidal-Shuffle-<version>.zip

The folder holds one thing to double-click, "Install Tidal Shuffle.command",
a short read-me, the two manuals, and the program. The installer copies the
program to ~/.tidal-shuffle (so the folder can be deleted afterwards), installs
what it needs (Homebrew, Python, media-control), signs in to TIDAL, and makes
Tidal Shuffle.app. Nothing personal goes in: no settings, history, Spotify
credentials or pictures.
"""

from __future__ import annotations

import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
NAME = "Tidal Shuffle"
PROGRAM = [("src", "src"), ("pyproject.toml", "pyproject.toml"), ("install.sh", "install.sh"),
           ("README.md", "README.md"), ("config.example.yaml", "config.example.yaml")]
SKIP = re.compile(r"(__pycache__|\.pyc$|\.egg-info|\.DS_Store)")

INSTALLER = r"""#!/bin/bash
# Double-click to install Tidal Shuffle. Safe to run again (it updates).
cd "$(dirname "$0")" || exit 1
here="$(pwd)"
home="$HOME/.tidal-shuffle"
bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() {
    printf '\n\033[31m%s\033[0m\n' "$*"
    read -r -p "Press Return to close this window." _
    exit 1
}
clear
printf '\033[1mTidal Shuffle %(version)s\033[0m: installer\n'
echo "This takes a few minutes. Keep this window open; it will say when it is done."

[ "$(uname)" = "Darwin" ] || fail "Tidal Shuffle runs on a Mac only."
[ -d /Applications/TIDAL.app ] || echo "Note: the TIDAL app is not in /Applications. Install it from tidal.com/download."
[ -d /Applications/Spotify.app ] || echo "Note: the Spotify app is not in /Applications. It gives the best suggestions (spotify.com/download)."

# 1. Homebrew (it brings Apple's command line tools; your Mac password is asked)
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
if ! command -v brew >/dev/null 2>&1; then
    bold "1/4  Homebrew is needed (a standard installer for Mac tools)."
    echo "It asks for your Mac password (nothing shows while you type) and may take 5-10 minutes."
    read -r -p "Press Return to install it, or close this window to stop. " _
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || fail "Homebrew did not install. Try again, or install it from https://brew.sh first."
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
    command -v brew >/dev/null 2>&1 || fail "Homebrew was installed but cannot be found. Open a new Terminal window and run this again."
else
    bold "1/4  Homebrew: already installed."
fi

# 2. The program, copied to ~/.tidal-shuffle (this folder can be deleted afterwards)
bold "2/4  Installing Tidal Shuffle in $home"
mkdir -p "$home/source" || fail "Could not create $home"
rsync -a --delete --exclude ".venv" "$here/Tidal Shuffle program/" "$home/source/" || fail "Could not copy the program."
xattr -dr com.apple.quarantine "$home/source" 2>/dev/null
chmod +x "$home/source/install.sh"
"$home/source/install.sh" || fail "The installation stopped (see above)."
ts="$home/source/.venv/bin/tidal-shuffle"

# 3. TIDAL sign-in (once)
if [ ! -f "$HOME/.config/tidal-shuffle/tidal_session.json" ]; then
    bold "3/4  Sign in to TIDAL: open the link below, approve it, then come back here."
    "$ts" login || fail "TIDAL sign-in did not finish. Run this installer again to retry."
else
    bold "3/4  TIDAL: already signed in."
fi

# 4. Check everything, then open the app
bold "4/4  Checking everything"
"$ts" doctor || true
app="/Applications/Tidal Shuffle.app"
[ -d "$app" ] || app="$HOME/Applications/Tidal Shuffle.app"
bold "Done. Tidal Shuffle is installed: $app"
echo "Open it from Launchpad or Spotlight (or drag it to the Dock). Play a song in TIDAL first."
echo "macOS will ask to let Terminal control Spotify and see the media keys: allow both."
read -r -p "Press Return to open Tidal Shuffle now. " _
open "$app"
"""

README = """TIDAL SHUFFLE {version}
A smarter shuffle for the TIDAL app on the Mac, by Alter Era.

It follows the song TIDAL is playing, picks a related one (from Spotify's song
radio and other sources) and plays it in TIDAL when the song ends.

YOU NEED
  - a Mac with the TIDAL app (and a TIDAL subscription)
  - the Spotify app (free is fine), signed in: it gives the best suggestions
  - an internet connection; your Mac password (to install Homebrew, once)

INSTALL
  1. Copy this folder anywhere (the Desktop is fine).
  2. Double-click "Install Tidal Shuffle.command".
     If macOS says it cannot be opened ("Apple could not verify..."):
       open System Settings > Privacy & Security, scroll down, click
       "Open Anyway" next to the installer's name, then double-click it again.
     (Or, in Terminal: xattr -dr com.apple.quarantine ~/Desktop/"Tidal Shuffle")
  3. Follow the window: it installs what is needed, asks you to approve the
     TIDAL sign-in in your browser, checks everything and opens the app.
  4. Afterwards this folder can be deleted. The app is in Applications.

USE
  Play any song in TIDAL, then open Tidal Shuffle (Launchpad or Spotlight).
  Keys: space play/pause, n next, esc settings, q quit. Allow Terminal to
  control Spotify and to see the media keys when macOS asks.
  More in the operation card and the manual (the two PDFs).

UPDATE
  Get a newer copy of this folder and double-click the installer again.
  Your settings are kept.

REMOVE
  Delete "Tidal Shuffle" from Applications, and the hidden folders
  ~/.tidal-shuffle and ~/.config/tidal-shuffle.
"""


def version() -> str:
    text = (ROOT / "src" / "tidal_shuffle" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def build() -> Path:
    v = version()
    out = DIST / NAME
    if out.exists():
        shutil.rmtree(out)
    prog = out / f"{NAME} program"
    prog.mkdir(parents=True)
    for src, dst in PROGRAM:
        s, d = ROOT / src, prog / dst
        if s.is_dir():
            shutil.copytree(s, d, ignore=lambda dirpath, names: [n for n in names if SKIP.search(n)])
        else:
            shutil.copy2(s, d)
    inst = out / f"Install {NAME}.command"
    inst.write_text(INSTALLER.replace("%(version)s", v))
    (out / "Read me.txt").write_text(README.format(version=v))
    for pdf, title in (("tidal-shuffle-operation-card.pdf", "operation card"), ("tidal-shuffle-manual.pdf", "manual")):
        src = ROOT / "docs" / "manual" / pdf
        if src.exists():
            shutil.copy2(src, out / f"{NAME} - {title}.pdf")
    for path in (inst, prog / "install.sh"):
        path.chmod(0o755)
    return out


def zip_folder(folder: Path) -> Path:
    """A zip that keeps the executable bits (Archive Utility honours them)."""
    target = DIST / f"Tidal-Shuffle-{version()}.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.rglob("*")):
            arc = str(Path(NAME) / path.relative_to(folder))
            if path.is_dir():
                info = zipfile.ZipInfo(arc + "/")
                info.external_attr = (0o40755 << 16) | 0x10
                z.writestr(info, "")
                continue
            info = zipfile.ZipInfo.from_file(path, arc)
            mode = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    return target


if __name__ == "__main__":
    folder = build()
    print(folder)
    if "--no-zip" not in sys.argv:
        print(zip_folder(folder))
