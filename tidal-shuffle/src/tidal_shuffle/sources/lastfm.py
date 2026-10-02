"""Last.fm similarity as a recommendation source.

Uses ``track.getSimilar`` first; if that comes back empty (common for obscure
songs) it widens to similar artists' top tracks and finally the seed artist's
own top tracks.
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Sequence

import httpx

from ..http import HttpError, get_json, make_client
from ..models import Candidate, Seed
from .base import tag

API_URL = "https://ws.audioscrobbler.com/2.0/"


class LastfmError(RuntimeError):
    pass


class LastfmSource:
    name = "lastfm"

    def __init__(self, api_key: Optional[str], expand_similar_artists: bool = True,
                 client: Optional[httpx.Client] = None, sleep: Callable[[float], None] = time.sleep):
        self.api_key = api_key
        self.expand_similar_artists = expand_similar_artists
        self._client = client or make_client()
        self._sleep = sleep
        self._cache: dict[tuple, object] = {}

    # ------------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not self.api_key or "your_" in self.api_key:
            return False, "no Last.fm API key (lastfm.api_key or LASTFM_API_KEY)"
        return True, ""

    def _call(self, method: str, **params) -> dict:
        key = (method, tuple(sorted(params.items())))
        if key in self._cache:
            return self._cache[key]  # type: ignore[return-value]
        query = {"method": method, "api_key": self.api_key, "format": "json", "autocorrect": 1}
        query.update({k: v for k, v in params.items() if v is not None})
        try:
            data = get_json(self._client, API_URL, params=query, sleep=self._sleep)
        except HttpError as e:
            # Last.fm returns errors as JSON with a 400 status; surface the message.
            raise LastfmError(str(e)) from None
        if isinstance(data, dict) and "error" in data:
            code = data.get("error")
            msg = data.get("message", "unknown error")
            if code == 6:  # "track not found" and friends
                data = {}
            else:
                raise LastfmError(f"Last.fm error {code}: {msg}")
        self._cache[key] = data
        return data

    # ------------------------------------------------------------------
    @staticmethod
    def _as_list(value) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _artist_name(obj) -> str:
        if isinstance(obj, dict):
            return str(obj.get("name") or obj.get("#text") or "")
        return str(obj or "")

    @staticmethod
    def _duration(obj) -> Optional[float]:
        raw = obj.get("duration")
        try:
            d = float(raw)
        except (TypeError, ValueError):
            return None
        if d <= 0:
            return None
        # track.getSimilar reports seconds; track.getInfo reports milliseconds.
        return d / 1000.0 if d > 3000 else d

    def similar_tracks(self, title: str, artist: str, limit: int) -> list[Candidate]:
        data = self._call("track.getSimilar", track=title, artist=artist, limit=limit)
        items = self._as_list((data.get("similartracks") or {}).get("track"))
        out: list[Candidate] = []
        for t in items:
            name = t.get("name")
            a = self._artist_name(t.get("artist"))
            if not name or not a:
                continue
            try:
                match = float(t.get("match", 0.5))
            except (TypeError, ValueError):
                match = 0.5
            out.append(Candidate(title=name, artist=a, duration=self._duration(t),
                                 score=max(0.05, min(1.0, match)),
                                 extra={"mbid": t.get("mbid"), "url": t.get("url")}))
        return out

    def similar_artists(self, artist: str, limit: int = 8) -> list[tuple[str, float]]:
        data = self._call("artist.getSimilar", artist=artist, limit=limit)
        items = self._as_list((data.get("similarartists") or {}).get("artist"))
        out = []
        for a in items:
            name = a.get("name")
            if not name:
                continue
            try:
                match = float(a.get("match", 0.5))
            except (TypeError, ValueError):
                match = 0.5
            out.append((name, match))
        return out

    def artist_top_tracks(self, artist: str, limit: int = 10) -> list[Candidate]:
        data = self._call("artist.getTopTracks", artist=artist, limit=limit)
        items = self._as_list((data.get("toptracks") or {}).get("track"))
        out: list[Candidate] = []
        n = max(1, len(items))
        for i, t in enumerate(items):
            name = t.get("name")
            a = self._artist_name(t.get("artist")) or artist
            if not name:
                continue
            out.append(Candidate(title=name, artist=a, duration=self._duration(t),
                                 score=0.6 * (1 - i / n) + 0.2,
                                 extra={"mbid": t.get("mbid"), "listeners": t.get("listeners")}))
        return out

    # ------------------------------------------------------------------
    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        seed = seeds[0]
        cands = self.similar_tracks(seed.title, seed.artist, limit)
        if len(cands) < max(3, limit // 4) and self.expand_similar_artists:
            per_artist = max(2, limit // 6)
            for name, match in self.similar_artists(seed.artist, limit=8):
                for c in self.artist_top_tracks(name, limit=per_artist):
                    c.score = max(0.05, min(1.0, 0.5 * match + 0.3 * c.score))
                    cands.append(c)
                if len(cands) >= limit:
                    break
        if len(cands) < 3:
            for c in self.artist_top_tracks(seed.artist, limit=max(5, limit // 3)):
                c.score *= 0.6
                cands.append(c)
        cands.sort(key=lambda c: -c.score)
        return tag(cands[:limit], self.name)

    def close(self) -> None:
        self._client.close()
