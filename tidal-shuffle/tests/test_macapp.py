"""Tidal Shuffle.app: the bundle, its launcher and its icon."""

import io
import os
import plistlib
import stat
import struct

from click.testing import CliRunner
from PIL import Image

from tidal_shuffle.macapp import build_app, icns_bytes, icon_png


def test_the_app_bundle_opens_the_view_in_the_chosen_terminal(tmp_path):
    app = build_app(tmp_path, terminal="iTerm", args=["--preset", "chill"], command="/opt/ts/bin/tidal-shuffle",
                    version="9.9.9")
    assert app.name == "Tidal Shuffle.app"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "launch" and info["CFBundleIdentifier"] == "com.alterera.tidalshuffle"
    assert info["CFBundleShortVersionString"] == "9.9.9" and info["CFBundlePackageType"] == "APPL"
    launch = app / "Contents" / "MacOS" / "launch"
    run = app / "Contents" / "Resources" / "run.command"
    for f in (launch, run):
        assert os.stat(f).st_mode & stat.S_IXUSR
    assert "open -a iTerm" in launch.read_text()
    assert "exec /opt/ts/bin/tidal-shuffle run --preset chill" in run.read_text()
    assert (app / "Contents" / "Resources" / "AppIcon.icns").read_bytes()[:4] == b"icns"
    # made again: replaced in place, nothing left over
    build_app(tmp_path, command="/opt/ts/bin/tidal-shuffle")
    assert [p.name for p in tmp_path.iterdir() if "Tidal Shuffle" in p.name] == ["Tidal Shuffle.app"]
    assert "open -a Terminal" in launch.read_text()


def test_the_icon_is_the_logo_on_a_rounded_square():
    img = Image.open(io.BytesIO(icon_png(256))).convert("RGBA")
    assert img.size == (256, 256)
    assert img.getpixel((2, 2))[3] == 0                         # the margin is transparent
    assert img.getpixel((40, 128))[:3] == (34, 34, 31)          # the square
    colours = {img.getpixel((x, y))[:3] for x in range(64, 192, 4) for y in range(40, 220, 4)}
    assert (255, 194, 0) in colours or any(abs(c[0] - 253) < 6 and abs(c[1] - 192) < 6 and c[2] < 10 for c in colours)
    data = icns_bytes()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    kinds, i = [], 8
    while i < len(data):
        kind, n = data[i:i + 4].decode(), struct.unpack(">I", data[i + 4:i + 8])[0]
        assert data[i + 8:i + 16] == b"\x89PNG\r\n\x1a\n"
        kinds.append(kind)
        i += n
    assert "ic10" in kinds and "ic07" in kinds and i == len(data)


def test_the_app_command(tmp_path):
    from tidal_shuffle.cli import cli

    res = CliRunner().invoke(cli, ["app", "--dest", str(tmp_path), "--terminal", "Ghostty"])
    assert res.exit_code == 0, res.output
    assert "made" in res.output
    assert "open -a Ghostty" in (tmp_path / "Tidal Shuffle.app" / "Contents" / "MacOS" / "launch").read_text()
