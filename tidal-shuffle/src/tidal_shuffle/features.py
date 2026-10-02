"""How a song sounds, in numbers: energy, mood (valence), danceability,
acousticness, instrumentalness and tempo. They drive the shuffle flows
(rising / falling / steady energy, same soundscape, similar vibe).

Spotify no longer gives these to new apps, so they come from ReccoBeats
(https://reccobeats.com), a free, keyless service that takes Spotify track
ids, which the Spotify radio harvest already provides. Answers are cached for
half a year; if the service is unreachable the flows quietly fall back to the
plain song radio.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .cache import DiskCache

_SPOTIFY_ID = re.compile(r"(?:track[/:])?([0-9A-Za-z]{22})")


@dataclass
class Features:
    energy: float
    valence: float = 0.5
    danceability: float = 0.5
    acousticness: float = 0.5
    instrumentalness: float = 0.0
    tempo: float = 120.0

    # how much each dimension counts when comparing two songs' sound
    WEIGHTS = {"energy": 1.4, "valence": 1.0, "danceability": 0.8, "acousticness": 1.2,
               "instrumentalness": 0.9, "tempo": 0.6}

    def vector(self) -> dict:
        return {"energy": self.energy, "valence": self.valence, "danceability": self.danceability,
                "acousticness": self.acousticness, "instrumentalness": self.instrumentalness,
                "tempo": min(1.0, max(0.0, (self.tempo - 50.0) / 150.0))}

    def distance(self, other: "Features", only: Optional[Iterable[str]] = None) -> float:
        """Weighted distance in 0..~1 (0 = sounds the same)."""
        a, b = self.vector(), other.vector()
        keys = list(only) if only else list(a)
        num = sum(self.WEIGHTS[k] * (a[k] - b[k]) ** 2 for k in keys)
        den = sum(self.WEIGHTS[k] for k in keys)
        return math.sqrt(num / den) if den else 0.0


def _num(d: dict, key: str, default: Optional[float] = None) -> Optional[float]:
    v = d.get(key)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


class ReccoBeats:
    """Audio features for Spotify track ids from ReccoBeats."""

    name = "reccobeats"
    URL = "https://api.reccobeats.com/v1/audio-features"
    BATCH = 40

    def __init__(self, client=None, cache_path: Optional[Path] = None, log: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.monotonic):
        if client is None:
            from .http import make_client

            client = make_client(timeout=10.0)
        self.client = client
        self.cache = DiskCache(cache_path, ttl=180 * 86400, max_entries=20000)
        self.log = log or (lambda m: None)
        self._clock = clock
        self._down_until = 0.0

    def features(self, spotify_ids: Iterable[str]) -> dict[str, Features]:
        """Features for the ids it knows; never raises."""
        ids = [i for i in dict.fromkeys(spotify_ids) if i]
        out: dict[str, Features] = {}
        missing = []
        for sid in ids:
            hit = self.cache.get(sid)
            if hit is None:
                missing.append(sid)
            elif hit:
                out[sid] = Features(**hit)
        if missing and self._clock() >= self._down_until:
            for start in range(0, len(missing), self.BATCH):
                chunk = missing[start:start + self.BATCH]
                try:
                    got = self._fetch(chunk)
                except Exception as e:
                    self.log(f"song energy data unavailable ({e}); trying again in 10 minutes")
                    self._down_until = self._clock() + 600
                    break
                for sid in chunk:
                    f = got.get(sid)
                    self.cache.set(sid, asdict(f) if f else {})   # remember "unknown" too
                    if f:
                        out[sid] = f
            self.cache.flush()
        return out

    def _fetch(self, ids: list[str]) -> dict[str, Features]:
        resp = self.client.get(self.URL, params={"ids": ",".join(ids)})
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        items = data.get("content", data.get("audio_features", [])) if isinstance(data, dict) else data
        out: dict[str, Features] = {}
        for pos, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            sid = None
            for key in ("href", "spotifyId", "spotify_id", "uri", "id"):
                m = _SPOTIFY_ID.search(str(item.get(key) or ""))
                if m and m.group(1) in ids:
                    sid = m.group(1)
                    break
            if sid is None and len(items) == len(ids):
                sid = ids[pos]        # same order as asked
            energy = _num(item, "energy")
            if sid is None or energy is None:
                continue
            out[sid] = Features(energy=energy, valence=_num(item, "valence", 0.5),
                                danceability=_num(item, "danceability", 0.5),
                                acousticness=_num(item, "acousticness", 0.5),
                                instrumentalness=_num(item, "instrumentalness", 0.0),
                                tempo=_num(item, "tempo", 120.0))
        return out
