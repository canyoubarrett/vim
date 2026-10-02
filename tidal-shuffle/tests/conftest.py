import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Keep every test away from the real ~/.config/tidal-shuffle.
_HOME = Path(os.environ.get("PYTEST_TIDAL_HOME", "")) if os.environ.get("PYTEST_TIDAL_HOME") else None


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "tidal-shuffle-home"
    home.mkdir()
    monkeypatch.setenv("TIDAL_SHUFFLE_HOME", str(home))
    monkeypatch.delenv("TIDAL_SHUFFLE_CONFIG", raising=False)
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    # paths.py computes CONFIG_DIR at import; point module constants at tmp too.
    from tidal_shuffle import paths, config, history
    monkeypatch.setattr(paths, "CONFIG_DIR", home)
    monkeypatch.setattr(paths, "CONFIG_FILE", home / "config.yaml")
    monkeypatch.setattr(paths, "TIDAL_SESSION_FILE", home / "tidal_session.json")
    monkeypatch.setattr(config, "CONFIG_DIR", home)
    monkeypatch.setattr(config, "CONFIG_FILE", home / "config.yaml")
    monkeypatch.setattr(config, "TIDAL_SESSION_FILE", home / "tidal_session.json")
    monkeypatch.setattr(history, "HISTORY_FILE", home / "history.json")
    return home
