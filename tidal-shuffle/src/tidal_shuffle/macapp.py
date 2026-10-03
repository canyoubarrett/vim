"""Tidal Shuffle as a Mac app: ``Tidal Shuffle.app``, with the Alter Era mark
as its icon, that opens the full-screen view in a terminal window.

The view is drawn in a terminal, so the app is a small bundle that starts
``tidal-shuffle run`` in Terminal (or iTerm, Ghostty...). It is made on the
Mac by ``tidal-shuffle app`` (``install.sh`` does it too) and points at this
installed copy, so ``tidal-shuffle update`` keeps it current. It can sit in
the Dock and be opened from Spotlight and Launchpad like any app.
"""

from __future__ import annotations

import io
import math
import os
import plistlib
import shlex
import shutil
import struct
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "Tidal Shuffle"
BUNDLE_ID = "com.alterera.tidalshuffle"
ICON_BG = (34, 34, 31)            # anthracite, the manual's ink


def default_destination() -> Path:
    """/Applications when it can be written to, else ~/Applications."""
    system = Path("/Applications")
    if system.is_dir() and os.access(system, os.W_OK):
        return system
    return Path.home() / "Applications"


def command_path() -> str:
    """The ``tidal-shuffle`` command of this installed copy."""
    beside = Path(sys.executable).parent / "tidal-shuffle"
    if beside.exists():
        return str(beside)
    return shutil.which("tidal-shuffle") or str(beside)


# -- the icon ---------------------------------------------------------------------
def icon_png(size: int) -> bytes:
    """The Alter Era mark on a rounded square, in Apple's icon grid
    (the square is 824/1024 of the canvas, with a transparent margin)."""
    from PIL import Image, ImageDraw

    from .visualizer import ALTER_ERA_FLAT_REGIONS, LOGO_COLORS

    ss = 4                                   # draw large, then scale down: smooth edges
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = big * 100 / 1024
    side = big - 2 * pad
    draw.rounded_rectangle((pad, pad, pad + side, pad + side), radius=side * 0.225, fill=ICON_BG + (255,))
    # the logo's own bounds (SVG units), fitted into the square with a margin
    x0, y0, x1, y1 = 127.0, 69.0, 373.0, 431.0
    scale = side * 0.74 / max(x1 - x0, y1 - y0)
    ox = pad + (side - (x1 - x0) * scale) / 2 - x0 * scale
    oy = pad + (side - (y1 - y0) * scale) / 2 - y0 * scale
    for _, colour, geom in ALTER_ERA_FLAT_REGIONS:
        fill = LOGO_COLORS[colour] + (255,)
        if isinstance(geom, tuple) and geom[0] == "circle":
            _, cx, cy, r = geom
            pts = [(cx + r * math.cos(a / 90 * 2 * math.pi), cy + r * math.sin(a / 90 * 2 * math.pi)) for a in range(90)]
        else:
            pts = geom
        draw.polygon([(ox + x * scale, oy + y * scale) for x, y in pts], fill=fill)
    img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ICNS entries macOS reads as PNG: type -> pixel size
_ICNS_TYPES = (("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512),
               ("ic10", 1024), ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512))


def icns_bytes() -> bytes:
    """An .icns file (PNG entries; no Mac-only tools needed to make it)."""
    cache: dict = {}
    body = b""
    for kind, px in _ICNS_TYPES:
        png = cache.get(px) or cache.setdefault(px, icon_png(px))
        body += kind.encode("ascii") + struct.pack(">I", len(png) + 8) + png
    return b"icns" + struct.pack(">I", len(body) + 8) + body


# -- the bundle -------------------------------------------------------------------
def _launcher(terminal: str) -> str:
    """The app's executable: open the run script in the chosen terminal app."""
    return f"""#!/bin/bash
# Tidal Shuffle.app: start the full-screen view in {terminal}.
here="$(cd "$(dirname "$0")/../Resources" && pwd)"
exec /usr/bin/open -a {shlex.quote(terminal)} "$here/run.command"
"""


def _run_script(command: str, args: list[str]) -> str:
    cmd = " ".join(shlex.quote(a) for a in [command, "run", *args])
    return f"""#!/bin/bash
# Started by Tidal Shuffle.app. Close the window or press q to stop.
printf '\\033]0;{APP_NAME}\\007'
if [ ! -x {shlex.quote(command)} ]; then
    echo "Tidal Shuffle is not installed at {command} any more."
    echo "Install it again (./install.sh), then run: tidal-shuffle app"
    read -r -p "Press Return to close." _
    exit 1
fi
exec {cmd}
"""


def build_app(dest: Optional[Path] = None, terminal: str = "Terminal", args: Optional[list[str]] = None,
              command: Optional[str] = None, version: str = "") -> Path:
    """Make (or remake) ``Tidal Shuffle.app`` in ``dest``; returns its path."""
    dest = Path(dest) if dest else default_destination()
    dest.mkdir(parents=True, exist_ok=True)
    app = dest / f"{APP_NAME}.app"
    tmp = dest / f".{APP_NAME}.app.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    contents = tmp / "Contents"
    macos, resources = contents / "MacOS", contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir()
    if not version:
        from . import __version__ as version
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "launch",
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHumanReadableCopyright": "Alter Era",
        "NSHighResolutionCapable": True,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    (contents / "PkgInfo").write_text("APPL????")
    for path, text in ((macos / "launch", _launcher(terminal)),
                       (resources / "run.command", _run_script(command or command_path(), list(args or [])))):
        path.write_text(text)
        path.chmod(0o755)
    (resources / "AppIcon.icns").write_bytes(icns_bytes())
    if app.exists():
        shutil.rmtree(app)
    tmp.rename(app)
    os.utime(app)                    # Finder and the Dock pick up the new icon
    return app
