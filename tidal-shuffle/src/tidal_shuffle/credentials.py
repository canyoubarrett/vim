"""Spotify Web API credentials entered in the settings menu (Esc → Spotify API).

Kept in ~/.config/tidal-shuffle/spotify.json, readable only by you. They take
the place of ``spotify.client_id`` / ``client_secret`` in the config file
(the SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET environment variables still
win), and take effect at once: the running sources pick them up.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

FIELDS = ("client_id", "client_secret")


def path() -> Path:
    from . import paths

    return paths.CONFIG_DIR / "spotify.json"


def load(where: Optional[Path] = None) -> dict:
    try:
        data = json.loads((where or path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(data[k]).strip() for k in FIELDS if data.get(k)}


def save(values: dict, where: Optional[Path] = None) -> None:
    target = where or path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {k: values[k] for k in FIELDS if values.get(k)}
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(target)


def mask(value: Optional[str]) -> str:
    """How a stored value is shown: never the secret itself."""
    if not value:
        return "not set"
    return "set · ends in " + value[-4:] if len(value) > 8 else "set"


def apply_live(cfg, sources: list, log: Callable[[str], None] = lambda m: None) -> None:
    """Hand the config's credentials to the running sources (the Spotify Web API
    source, and the Spotify app source's way of finding songs on Spotify)."""
    from .sources.spotify_api import SpotifyApiSource
    from .sources.spotify_ids import SpotifyApiIds

    cid, secret = cfg.spotify.client_id, cfg.spotify.client_secret
    api = None
    for src in sources:
        if isinstance(src, SpotifyApiSource):
            api = src
    if api is None:
        api = SpotifyApiSource(cid, secret, market=cfg.spotify.market, vibe=cfg.spotify.vibe, log=log)
    api.client_id, api.client_secret = cid, secret
    api._token, api._token_expires, api._dead = None, 0.0, None
    for src in sources:
        lookups = getattr(src, "id_lookups", None)
        if lookups is not None and not any(isinstance(l, SpotifyApiIds) for l in lookups):
            lookups.insert(0, SpotifyApiIds(api))


def check(client_id: str, client_secret: str) -> tuple[bool, str]:
    """Ask Spotify whether the credentials work: a token, then one search."""
    from .sources.spotify_api import SpotifyApiSource, SpotifyAuthError

    if not client_id or not client_secret:
        return False, "enter both the client ID and the client secret"
    api = SpotifyApiSource(client_id, client_secret)
    try:
        api._get("/search", q="track:hello", type="track", limit=1)
    except SpotifyAuthError as e:
        return False, str(e)
    except Exception as e:  # network trouble, an unexpected answer
        return False, f"Spotify did not answer as expected: {e}"
    finally:
        try:
            api.close()
        except Exception:
            pass
    return True, "Spotify accepts these credentials"
