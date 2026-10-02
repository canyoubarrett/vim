"""Odesli (song.link): map a TIDAL track to its Spotify id without any API key.

Unauthenticated use is rate limited (about 10 requests per minute), which is
plenty for one lookup per song. Results are cached for the process lifetime.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from ..http import HttpError, get_json, make_client

API_URL = "https://api.song.link/v1-alpha.1/links"


class OdesliMapper:
    def __init__(self, client: Optional[httpx.Client] = None, country: str = "US",
                 min_interval: float = 6.5, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, log: Optional[Callable[[str], None]] = None):
        self._client = client or make_client(timeout=15.0)
        self.country = country
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_call = -1e9
        self._cache: dict[str, Optional[dict]] = {}
        self.log = log or (lambda m: None)

    def _throttle(self) -> None:
        wait = self.min_interval - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def lookup(self, url: str) -> Optional[dict]:
        if url in self._cache:
            return self._cache[url]
        self._throttle()
        try:
            data = get_json(self._client, API_URL, params={"url": url, "userCountry": self.country, "songIfSingle": "true"},
                            sleep=self._sleep, retries=1)
        except HttpError as e:
            self.log(f"odesli lookup failed for {url}: {e}")
            data = None
        self._cache[url] = data
        return data

    @staticmethod
    def _platform_id(data: Optional[dict], platform: str, kind: str) -> Optional[str]:
        if not data:
            return None
        link = (data.get("linksByPlatform") or {}).get(platform) or {}
        uid = link.get("entityUniqueId")
        entity = (data.get("entitiesByUniqueId") or {}).get(uid) if uid else None
        if entity and entity.get("id"):
            return str(entity["id"])
        url = link.get("url") or ""
        marker = f"/{kind}/"
        if marker in url:
            return url.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0] or None
        return None

    def spotify_id_for_tidal(self, tidal_id: str) -> Optional[str]:
        data = self.lookup(f"https://tidal.com/browse/track/{tidal_id}")
        return self._platform_id(data, "spotify", "track")

    def tidal_id_for_spotify(self, spotify_id: str) -> Optional[str]:
        data = self.lookup(f"https://open.spotify.com/track/{spotify_id}")
        return self._platform_id(data, "tidal", "track")
