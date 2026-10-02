"""Filesystem locations. Overridable with ``TIDAL_SHUFFLE_HOME`` for tests."""

from __future__ import annotations

import os
from pathlib import Path


def _home() -> Path:
    override = os.environ.get("TIDAL_SHUFFLE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "tidal-shuffle"


CONFIG_DIR = _home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
TIDAL_SESSION_FILE = CONFIG_DIR / "tidal_session.json"
SPOTIFY_TOKEN_FILE = CONFIG_DIR / "spotify_token.json"
LOG_FILE = CONFIG_DIR / "tidal-shuffle.log"
TIMING_FILE = CONFIG_DIR / "timing.json"
