"""Spotify Web API as a recommendation source (client-credentials flow).

What a Spotify app can still reach depends on when it was created:

* apps with extended quota from before 2024-11-27 keep ``/recommendations``
  and ``/related-artists``;
* since 2026 every development-mode app needs its owner to have Premium (all
  calls answer 403 otherwise), search returns at most 10 items, and artist
  top tracks are gone.

This source probes what works, remembers what does not, and degrades:
recommendations → related artists' top tracks → same-genre search. Its most
useful job for most people is finding the current song's Spotify id for the
``spotify-app`` source.
"""

from __future__ import annotations

import base64
import time
from typing import Callable, Optional, Sequence

import httpx

from ..http import HttpError, get_json, make_client
from ..matching import core_title, primary_artist, score_match
from ..models import Candidate, Seed, VibeParams
from .base import dedupe, tag

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SEARCH_LIMIT = 10  # the 2026 maximum for development-mode apps


class SpotifyAuthError(RuntimeError):
    pass


def _track_to_candidate(t: dict, score: float) -> Optional[Candidate]:
    if not t or t.get("type") not in (None, "track") or not t.get("name"):
        return None
    artists = [a.get("name") for a in (t.get("artists") or []) if a.get("name")]
    if not artists:
        return None
    dur = t.get("duration_ms")
    return Candidate(
        title=t["name"], artist=artists[0], album=(t.get("album") or {}).get("name"),
        duration=(dur / 1000.0) if isinstance(dur, (int, float)) else None,
        isrc=(t.get("external_ids") or {}).get("isrc"), popularity=t.get("popularity"),
        spotify_id=t.get("id"), score=score,
        extra={"artists": artists, "artist_ids": [a.get("id") for a in (t.get("artists") or [])]},
    )


class SpotifyApiSource:
    name = "spotify-api"

    def __init__(self, client_id: Optional[str], client_secret: Optional[str], market: str = "US",
                 vibe: Optional[VibeParams] = None, client: Optional[httpx.Client] = None,
                 sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time,
                 log: Optional[Callable[[str], None]] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.market = market or "US"
        self.vibe = vibe or VibeParams()
        self._client = client or make_client()
        self._sleep = sleep
        self._now = now
        self.log = log or (lambda m: None)
        self._token: Optional[str] = None
        self._token_expires = 0.0
        self._dead: Optional[str] = None
        self._paused_until = 0.0
        self.recommendations_available: Optional[bool] = None
        self.related_available: Optional[bool] = None
        self.top_tracks_available: Optional[bool] = None
        self._cache: dict[tuple, object] = {}

    # -- auth ---------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not self.client_id or not self.client_secret or "your_" in (self.client_id + self.client_secret):
            return False, "no Spotify client_id/client_secret configured"
        if self._dead:
            return False, self._dead
        if self._now() < self._paused_until:
            return False, f"rate limited for another {self._paused_until - self._now():.0f}s"
        return True, ""

    def _ensure_token(self) -> str:
        if self._token and self._now() < self._token_expires - 30:
            return self._token
        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        try:
            resp = self._client.post(TOKEN_URL, headers={"Authorization": f"Basic {creds}"},
                                     data={"grant_type": "client_credentials"})
        except httpx.HTTPError as e:
            raise SpotifyAuthError(f"could not reach Spotify auth: {e}") from None
        if resp.status_code != 200:
            detail = resp.text[:200]
            msg = f"Spotify auth failed (HTTP {resp.status_code}): {detail}"
            if resp.status_code in (400, 401, 403):
                self._dead = msg
            raise SpotifyAuthError(msg)
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = self._now() + float(data.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, **params) -> dict:
        key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
        if key in self._cache:
            return self._cache[key]  # type: ignore[return-value]
        token = self._ensure_token()
        try:
            data = get_json(self._client, f"{API}{path}", params=params or None,
                            headers={"Authorization": f"Bearer {token}"}, sleep=self._sleep)
        except HttpError as e:
            if e.status == 401:
                self._token = None
                token = self._ensure_token()
                data = get_json(self._client, f"{API}{path}", params=params or None,
                                headers={"Authorization": f"Bearer {token}"}, sleep=self._sleep)
            elif e.status == 403 and "premium" in str(e).lower():
                self._dead = ("Spotify answers 403: the owner of this Spotify developer app needs Premium "
                              "(required for development-mode apps since 2026)")
                self.log(self._dead)
                raise SpotifyAuthError(self._dead) from None
            elif e.status == 429:
                wait = e.retry_after if e.retry_after else 60.0
                self._paused_until = self._now() + wait
                self.log(f"Spotify rate-limited this app; pausing the Web API for {wait:.0f}s")
                raise SpotifyAuthError("Spotify rate limit") from None
            else:
                raise
        self._cache[key] = data
        return data

    # -- lookups ------------------------------------------------------------
    def find_track(self, seed: Seed) -> Optional[dict]:
        if seed.spotify_id:
            try:
                return self._get(f"/tracks/{seed.spotify_id}", market=self.market)
            except HttpError:
                pass
        if seed.isrc:
            try:
                items = self._get("/search", q=f"isrc:{seed.isrc}", type="track", limit=5, market=self.market)["tracks"]["items"]
                items = [t for t in items if t]
                if items:
                    return items[0]
            except (HttpError, KeyError):
                pass
        queries = [f"track:{core_title(seed.title)} artist:{primary_artist(seed.artist)}", f"{core_title(seed.title)} {primary_artist(seed.artist)}"]
        best, best_score = None, 0.0
        for q in queries:
            try:
                items = self._get("/search", q=q, type="track", limit=SEARCH_LIMIT, market=self.market)["tracks"]["items"]
            except (HttpError, KeyError):
                continue
            for t in items:
                if not t:
                    continue
                names = [a.get("name", "") for a in t.get("artists") or []]
                s = score_match(seed.title, seed.artist, t.get("name", ""), names, seed.duration,
                                (t.get("duration_ms") or 0) / 1000.0 or None)
                if s > best_score:
                    best, best_score = t, s
            if best_score >= 0.9:
                break
        return best if best_score >= 0.7 else None

    def recommendations(self, seed_ids: list[str], limit: int) -> list[Candidate]:
        if self.recommendations_available is False or not seed_ids:
            return []
        params: dict = {"seed_tracks": ",".join(seed_ids[:5]), "limit": min(limit, 100), "market": self.market}
        params.update(self.vibe.to_api_params())
        if self.vibe.genres:
            remaining = max(0, 5 - len(seed_ids[:5]))
            if remaining:
                params["seed_genres"] = ",".join(self.vibe.genres[:remaining])
        try:
            data = self._get("/recommendations", **params)
        except HttpError as e:
            if e.status in (403, 404):
                self.recommendations_available = False
                self.log("Spotify recommendations endpoint not available for this app; using fallbacks")
                return []
            raise
        self.recommendations_available = True
        tracks = data.get("tracks") or []
        n = max(1, len(tracks))
        out = [_track_to_candidate(t, 1.0 - 0.5 * (i / n)) for i, t in enumerate(tracks)]
        return [c for c in out if c]

    def artist_top_tracks(self, artist_id: str, score: float) -> list[Candidate]:
        if self.top_tracks_available is False:
            return []
        try:
            tracks = self._get(f"/artists/{artist_id}/top-tracks", market=self.market).get("tracks") or []
            self.top_tracks_available = True
        except HttpError as e:
            if e.status in (403, 404):
                self.top_tracks_available = False
            return []
        n = max(1, len(tracks))
        out = [_track_to_candidate(t, score * (1.0 - 0.4 * (i / n))) for i, t in enumerate(tracks)]
        return [c for c in out if c]

    def related_artist_tracks(self, artist_id: str, limit: int) -> list[Candidate]:
        out: list[Candidate] = []
        related: list[dict] = []
        if self.related_available is not False:
            try:
                related = self._get(f"/artists/{artist_id}/related-artists").get("artists") or []
                self.related_available = True
            except HttpError as e:
                if e.status in (403, 404):
                    self.related_available = False
                    self.log("Spotify related-artists endpoint not available for this app")
                else:
                    raise
        related = [a for a in related[:8] if a.get("id")]
        per_artist = max(3, limit // max(1, len(related))) if related else 0
        for i, a in enumerate(related):
            out.extend(self.artist_top_tracks(a["id"], 0.8 - 0.05 * i)[:per_artist])
            if len(out) >= limit:
                break
        if not out:
            # Same-genre tracks: works for every app.
            try:
                genres = self._get(f"/artists/{artist_id}").get("genres") or []
            except HttpError:
                genres = []
            for g in genres[:2]:
                for offset in range(0, max(SEARCH_LIMIT, min(limit, 30)), SEARCH_LIMIT):
                    try:
                        items = self._get("/search", q=f'genre:"{g}"', type="track", limit=SEARCH_LIMIT,
                                          offset=offset, market=self.market)["tracks"]["items"]
                    except (HttpError, KeyError):
                        break
                    for i, t in enumerate(items):
                        c = _track_to_candidate(t, 0.55 - 0.3 * ((offset + i) / 30.0))
                        if c:
                            out.append(c)
                    if len(items) < SEARCH_LIMIT:
                        break
        return out

    # -- Source protocol ----------------------------------------------------
    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        try:
            return self._candidates(seeds, limit)
        except SpotifyAuthError as e:
            self.log(str(e))
            return []

    def _candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        try:
            resolved = []
            for s in seeds[:5]:
                t = self.find_track(s)
                if t:
                    resolved.append(t)
                    if s.spotify_id is None:
                        s.spotify_id = t.get("id")
                    if s.isrc is None:
                        s.isrc = (t.get("external_ids") or {}).get("isrc")
        except SpotifyAuthError as e:
            self.log(str(e))
            return []
        if not resolved:
            return []
        primary = resolved[0]
        cands = self.recommendations([t["id"] for t in resolved], limit)
        if len(cands) < 3:
            artist_id = ((primary.get("artists") or [{}])[0]).get("id")
            if artist_id:
                cands += self.related_artist_tracks(artist_id, limit)
                if len(cands) < 3:
                    cands += self.artist_top_tracks(artist_id, 0.45)
        cands = [c for c in dedupe(cands) if c.spotify_id != primary.get("id")]
        cands.sort(key=lambda c: -c.score)
        return tag(cands[:limit], self.name)

    def close(self) -> None:
        self._client.close()
