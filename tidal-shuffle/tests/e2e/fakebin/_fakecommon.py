"""Shared helpers for the fake macOS binaries used by the end-to-end test."""

import json
import os
import time
import urllib.request

FAKE_DIR = os.environ["FAKE_DIR"]
PORT = os.environ["FAKE_TIDAL_PORT"]
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(tool, msg):
    with open(os.path.join(FAKE_DIR, "calls.log"), "a") as f:
        f.write(f"{time.time():.3f} {tool} {msg}\n")


def tidal(path, timeout=3.0):
    """GET a test endpoint on the fake TIDAL app; None if it is not running."""
    try:
        with _OPENER.open(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except OSError:
        return None


def catalog():
    with open(os.path.join(FAKE_DIR, "catalog.json")) as f:
        return json.load(f)


SPOTIFY_STATE = os.path.join(FAKE_DIR, "spotify_state.json")


def spotify_state():
    try:
        with open(SPOTIFY_STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"running": False, "playing": False, "volume": 64, "elected": False}


def save_spotify_state(st):
    tmp = SPOTIFY_STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, SPOTIFY_STATE)
