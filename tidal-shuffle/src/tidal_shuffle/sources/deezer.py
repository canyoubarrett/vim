"""Deezer's public API as a keyless recommendation source.

Deezer exposes catalog search, ISRC lookup, related artists and an
"artist radio" (a mix of tracks around an artist) without any API key, which
makes it a good zero-setup complement to Last.fm.
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Sequence

import httpx

from ..http import HttpError, get_json, make_client
from ..matching import core_title, primary_artist, score_match
from ..models import Candidate, Seed
from .base import dedupe, tag

API = "https://api.deezer.com"


def _track_candidate(t: dict, score: float) -> Optional[Candidate]:
    if not isinstance(t, dict) or not t.get("title") or not (t.get("artist") or {}).get("name"):
        return None
    dur = t.get("duration")
    return Candidate(
        title=t["title"], artist=t["artist"]["name"], album=(t.get("album") or {}).get("title"),
        duration=float(dur) if isinstance(dur, (int, float)) and dur > 0 else None,
        isrc=t.get("isrc"), popularity=None, score=score,
        extra={"deezer_id": t.get("id"), "rank": t.get("rank"), "artist_id": t["artist"].get("id")},
    )


class DeezerSource:
    name = "deezer"

    def __init__(self, enabled: bool = True, client: Optional[httpx.Client] = None,
                 sleep: Callable[[float], None] = time.sleep, log: Optional[Callable[[str], None]] = None):
        self.enabled = enabled
        self._client = client or make_client()
        self._sleep = sleep
        self.log = log or (lambda m: None)
        self._cache: dict[tuple, object] = {}

    def available(self) -> tuple[bool, str]:
        return (True, "") if self.enabled else (False, "disabled in config (deezer.enabled)")

    def _get(self, path: str, **params) -> dict:
        key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
        if key in self._cache:
            return self._cache[key]  # type: ignore[return-value]
        for attempt in range(2):
            data = get_json(self._client, f"{API}{path}", params=params or None, sleep=self._sleep)
            err = data.get("error") if isinstance(data, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            if err and code in (4, 700) and attempt == 0:  # quota / busy: Deezer asks clients to wait
                self._sleep(5.0)
                continue
            break
        if err:
            if code == 800:  # "no data"
                data = {"data": []}
            else:
                raise HttpError(f"deezer {path}: {err}")
        self._cache[key] = data
        return data

    # -- lookups ---------------------------------------------------------------
    def find_track(self, seed: Seed) -> Optional[dict]:
        if seed.isrc:
            try:
                t = self._get(f"/track/isrc:{seed.isrc}")
                if t.get("id"):
                    return t
            except HttpError:
                pass
        q = f'artist:"{primary_artist(seed.artist)}" track:"{core_title(seed.title)}"'
        best, best_score = None, 0.0
        for query in (q, f"{core_title(seed.title)} {primary_artist(seed.artist)}"):
            try:
                items = self._get("/search", q=query, limit=10).get("data") or []
            except HttpError:
                continue
            for t in items:
                name = (t.get("artist") or {}).get("name", "")
                s = score_match(seed.title, seed.artist, t.get("title", ""), [name], seed.duration, t.get("duration"))
                if s > best_score:
                    best, best_score = t, s
            if best_score >= 0.9:
                break
        return best if best_score >= 0.7 else None

    def artist_radio(self, artist_id, limit: int) -> list[Candidate]:
        try:
            items = self._get(f"/artist/{artist_id}/radio", limit=min(limit, 100)).get("data") or []
        except HttpError as e:
            self.log(f"deezer artist radio failed: {e}")
            return []
        n = max(1, len(items))
        return [c for c in (_track_candidate(t, 0.95 - 0.5 * (i / n)) for i, t in enumerate(items)) if c]

    def related_top_tracks(self, artist_id, limit: int) -> list[Candidate]:
        out: list[Candidate] = []
        try:
            related = self._get(f"/artist/{artist_id}/related", limit=8).get("data") or []
        except HttpError:
            related = []
        per = max(3, limit // max(1, len(related))) if related else 0
        for i, a in enumerate(related):
            if not a.get("id"):
                continue
            try:
                top = self._get(f"/artist/{a['id']}/top", limit=per).get("data") or []
            except HttpError:
                continue
            for j, t in enumerate(top):
                c = _track_candidate(t, (0.8 - 0.05 * i) * (1 - 0.3 * (j / max(1, len(top)))))
                if c:
                    out.append(c)
            if len(out) >= limit:
                break
        return out

    # -- Source protocol ------------------------------------------------------
    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        seed = seeds[0]
        track = self.find_track(seed)
        if not track:
            return []
        if seed.isrc is None and track.get("isrc"):
            seed.isrc = track["isrc"]
        artist_id = (track.get("artist") or {}).get("id")
        if not artist_id:
            return []
        cands = self.artist_radio(artist_id, limit)
        if len(cands) < 3:
            cands += self.related_top_tracks(artist_id, limit)
        cands = [c for c in dedupe(cands) if c.extra.get("deezer_id") != track.get("id")]
        cands.sort(key=lambda c: -c.score)
        return tag(cands[:limit], self.name)

    def close(self) -> None:
        self._client.close()
