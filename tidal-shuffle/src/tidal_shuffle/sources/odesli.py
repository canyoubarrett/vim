"""Odesli (song.link): map a TIDAL track to its Spotify id.

The keyless public API was retired on 2026-07-31 (requests now get HTTP 401
``PUBLIC_API_ACCESS_DEPRECATED``), so this is only used when an API key is
configured. Any 401/403/410 disables it for the rest of the session.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from ..http import HttpError, get_json, make_client
from ..lru import BoundedDict

API_URL = "https://api.song.link/v1-alpha.1/links"


class OdesliMapper:
    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.Client] = None, country: str = "US",
                 min_interval: Optional[float] = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, log: Optional[Callable[[str], None]] = None):
        self.api_key = (api_key or "").strip() or None
        self._client = client or make_client(timeout=15.0)
        self.country = country
        # 10 requests/minute without a key, 60 with one.
        self.min_interval = min_interval if min_interval is not None else (1.0 if self.api_key else 6.5)
        self._sleep = sleep
        self._clock = clock
        self._last_call = -1e9
        self._cache = BoundedDict(500)
        self._dead: Optional[str] = None
        self.log = log or (lambda m: None)

    def available(self) -> tuple[bool, str]:
        if self._dead:
            return False, self._dead
        if not self.api_key:
            return False, "Odesli's keyless API was retired on 2026-07-31; set spotify.app.odesli_api_key to use it"
        return True, ""

    def _throttle(self) -> None:
        wait = self.min_interval - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def lookup(self, url: str) -> Optional[dict]:
        if url in self._cache:
            return self._cache[url]
        if self._dead:
            return None
        self._throttle()
        params = {"url": url, "userCountry": self.country, "songIfSingle": "true"}
        if self.api_key:
            params["key"] = self.api_key
        try:
            data = get_json(self._client, API_URL, params=params, sleep=self._sleep, retries=1)
        except HttpError as e:
            if e.status in (401, 403, 410):
                self._dead = f"Odesli refused the request ({e.status}); disabled for this session"
                self.log(self._dead)
            else:
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
