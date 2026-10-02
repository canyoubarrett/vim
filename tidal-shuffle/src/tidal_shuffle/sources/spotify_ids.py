"""Ways to find the Spotify track id of the song TIDAL is playing.

The Spotify desktop harvest needs a ``spotify:track:`` URI to start the song's
radio, and AppleScript cannot search. Each lookup below is tried in the
configured order until one answers:

* ``spotify-api``  – Spotify Web API search (needs credentials and, since
  2026, a Premium account on the app owner)
* ``listenbrainz`` – ListenBrainz's keyless ``spotify-id-from-metadata`` index
* ``odesli``       – song.link, only with an API key
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Protocol

import httpx

from ..http import HttpError, make_client, post_json
from ..matching import core_title, primary_artist
from ..models import Seed


class SpotifyIdLookup(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def lookup(self, seed: Seed) -> Optional[str]: ...


class ListenBrainzSpotifyIds:
    """``labs.api.listenbrainz.org/spotify-id-from-metadata`` (no key, ~1 request/s)."""

    name = "listenbrainz"
    URL = "https://labs.api.listenbrainz.org/spotify-id-from-metadata/json"

    def __init__(self, client: Optional[httpx.Client] = None, min_interval: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 log: Optional[Callable[[str], None]] = None):
        self._client = client or make_client(timeout=15.0)
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last = -1e9
        self._dead: Optional[str] = None
        self._cache: dict[tuple, Optional[str]] = {}
        self.log = log or (lambda m: None)

    def available(self) -> tuple[bool, str]:
        return (False, self._dead) if self._dead else (True, "")

    def _query(self, artist: str, album: str, title: str) -> Optional[str]:
        wait = self.min_interval - (self._clock() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()
        body = [{"artist_name": artist, "release_name": album, "track_name": title}]
        try:
            rows = post_json(self._client, type(self).URL, body, sleep=self._sleep, retries=1)
        except HttpError as e:
            if e.status in (401, 403, 404, 410):
                self._dead = f"ListenBrainz lookup unavailable (HTTP {e.status})"
                self.log(self._dead)
            else:
                self.log(f"ListenBrainz lookup failed: {e}")
            return None
        if not isinstance(rows, list):
            return None
        for row in rows:
            ids = (row or {}).get("spotify_track_ids") or []
            if ids:
                return str(ids[0])
        return None

    def lookup(self, seed: Seed) -> Optional[str]:
        key = (seed.title.lower(), seed.artist.lower(), (seed.album or "").lower())
        if key in self._cache:
            return self._cache[key]
        attempts = [(seed.artist, seed.album or "", seed.title)]
        simple = (primary_artist(seed.artist), "", core_title(seed.title))
        if simple != attempts[0]:
            attempts.append(simple)
        found = None
        for artist, album, title in attempts:
            if self._dead:
                break
            found = self._query(artist, album, title)
            if found:
                break
        self._cache[key] = found
        return found


class OdesliSpotifyIds:
    """song.link by TIDAL id (needs ``spotify.app.odesli_api_key``)."""

    name = "odesli"

    def __init__(self, mapper, catalog=None, log: Optional[Callable[[str], None]] = None):
        self.mapper = mapper
        self.catalog = catalog
        self.log = log or (lambda m: None)

    def available(self) -> tuple[bool, str]:
        return self.mapper.available()

    def lookup(self, seed: Seed) -> Optional[str]:
        if not seed.tidal_id and self.catalog is not None:
            try:
                self.catalog.resolve_seed(seed)
            except Exception as e:
                self.log(f"could not resolve seed on TIDAL: {e}")
        if not seed.tidal_id:
            return None
        return self.mapper.spotify_id_for_tidal(seed.tidal_id)


class SpotifyApiIds:
    """Spotify Web API search, sharing the configured ``spotify-api`` client."""

    name = "spotify-api"

    def __init__(self, api):
        self.api = api

    def available(self) -> tuple[bool, str]:
        return self.api.available()

    def lookup(self, seed: Seed) -> Optional[str]:
        try:
            track = self.api.find_track(seed)
        except Exception:  # auth / Premium problems disable the API client itself
            return None
        return track.get("id") if track else None
