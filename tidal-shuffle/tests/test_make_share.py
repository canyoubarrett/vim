"""The folder (and zip) for giving Tidal Shuffle to a friend."""

import importlib.util
import stat
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("make_share", ROOT / "tools" / "make_share.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DIST", tmp_path / "dist")
    return mod


def test_the_share_folder_has_one_thing_to_double_click(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    folder = mod.build()
    names = sorted(p.name for p in folder.iterdir())
    assert "Install Tidal Shuffle.command" in names and "Read me.txt" in names and "Tidal Shuffle program" in names
    inst = folder / "Install Tidal Shuffle.command"
    assert inst.stat().st_mode & stat.S_IXUSR
    assert subprocess.run(["bash", "-n", str(inst)]).returncode == 0           # it parses
    assert mod.version() in inst.read_text() and "%(" not in inst.read_text()
    prog = folder / "Tidal Shuffle program"
    assert (prog / "install.sh").stat().st_mode & stat.S_IXUSR
    assert (prog / "src" / "tidal_shuffle" / "assets" / "alter-era-flat.svg").exists()
    every = [p.name for p in folder.rglob("*")]
    for personal in ("ui.json", "spotify.json", "history.json", "tidal_session.json", "config.yaml", "backdrops"):
        assert personal not in every
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in every)
    assert not (prog / "tests").exists()


def test_the_zip_keeps_the_installer_executable(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    target = mod.zip_folder(mod.build())
    with zipfile.ZipFile(target) as z:
        info = z.getinfo("Tidal Shuffle/Install Tidal Shuffle.command")
        assert (info.external_attr >> 16) & 0o111
        assert not (z.getinfo("Tidal Shuffle/Read me.txt").external_attr >> 16) & 0o111
        assert all(n.startswith("Tidal Shuffle/") for n in z.namelist())
