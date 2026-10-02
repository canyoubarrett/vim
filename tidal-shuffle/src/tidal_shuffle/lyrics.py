"""Lyrics for the song playing, synced to the playback position when possible.

Sources, in order:

* TIDAL's own lyrics (``tracks/<id>/lyrics`` through the logged-in session),
  which carry LRC timestamps ("subtitles") for most catalog songs;
* LRCLIB (https://lrclib.net), a free, keyless database of synced lyrics.

Synced lyrics are LRC: ``[mm:ss.xx] line``. Unsynced (plain) lyrics are shown
scrolled in step with the song's progress instead.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .cache import DiskCache
from .matching import artist_similarity, title_similarity

_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_OFFSET_RE = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.I)
_META_RE = re.compile(r"^\[[a-z]{1,8}:.*\]\s*$", re.I)


@dataclass
class LyricLine:
    time: Optional[float]   # seconds; None for unsynced lyrics
    text: str


@dataclass
class Lyrics:
    lines: list[LyricLine] = field(default_factory=list)
    synced: bool = False
    source: str = ""
    instrumental: bool = False

    def index_at(self, position: float, lead: float = 0.25) -> int:
        """Index of the line being sung at ``position`` (-1 before the first line)."""
        if not self.synced:
            return -1
        pos = position + lead  # show a line a hair early; reading lags hearing
        idx = -1
        for i, line in enumerate(self.lines):
            if line.time is not None and line.time <= pos:
                idx = i
            else:
                break
        return idx

    def to_json(self) -> dict:
        return {"lines": [[l.time, l.text] for l in self.lines], "synced": self.synced,
                "source": self.source, "instrumental": self.instrumental}

    @classmethod
    def from_json(cls, data: dict) -> "Lyrics":
        return cls(lines=[LyricLine(t, s) for t, s in data.get("lines", [])], synced=bool(data.get("synced")),
                   source=str(data.get("source", "")), instrumental=bool(data.get("instrumental")))


def parse_lrc(text: str) -> list[LyricLine]:
    """Parse LRC text into time-ordered lines. Handles several time tags on one
    line, centiseconds or milliseconds, metadata tags and ``[offset:±ms]``."""
    offset = 0.0
    out: list[LyricLine] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _OFFSET_RE.match(line)
        if m:
            offset = int(m.group(1)) / 1000.0  # positive offset: lyrics come earlier
            continue
        tags = []
        pos = 0
        while True:
            m = _TAG_RE.match(line, pos)
            if not m:
                break
            mins, secs, frac = m.group(1), m.group(2), m.group(3) or "0"
            t = int(mins) * 60 + int(secs) + int(frac) / (10 ** len(frac))
            tags.append(t)
            pos = m.end()
        if not tags:
            continue  # metadata such as [ar:...] or untimed text
        words = line[pos:].strip()
        words = re.sub(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>", "", words).strip()  # enhanced LRC word stamps
        for t in tags:
            out.append(LyricLine(max(0.0, t - offset), words))
    out.sort(key=lambda l: l.time or 0.0)
    return out


def plain_lines(text: str) -> list[LyricLine]:
    return [LyricLine(None, l.rstrip()) for l in (text or "").splitlines() if not _META_RE.match(l.strip())]


def _from_texts(synced: Optional[str], plain: Optional[str], source: str) -> Optional[Lyrics]:
    lines = parse_lrc(synced) if synced else []
    if lines:
        return Lyrics(lines=lines, synced=True, source=source)
    lines = plain_lines(plain) if plain else []
    # trim leading/trailing blank lines
    while lines and not lines[0].text.strip():
        lines.pop(0)
    while lines and not lines[-1].text.strip():
        lines.pop()
    if lines:
        return Lyrics(lines=lines, synced=False, source=source)
    return None


class TidalLyrics:
    name = "tidal"

    def __init__(self, catalog):
        self.catalog = catalog

    def fetch(self, title: str, artist: str, album: Optional[str], duration: Optional[float],
              tidal_id: Optional[str]) -> Optional[Lyrics]:
        if self.catalog is None:
            return None
        if not tidal_id:
            track, _ = self.catalog.find(title, artist, duration)
            tidal_id = track.id if track else None
        if not tidal_id:
            return None
        try:
            raw = self.catalog.raw_track(tidal_id).lyrics()
        except Exception:
            return None  # MetadataNotAvailable: TIDAL has no lyrics for it
        return _from_texts(getattr(raw, "subtitles", ""), getattr(raw, "text", ""), "TIDAL")


class LrclibLyrics:
    name = "lrclib"
    BASE = "https://lrclib.net/api"

    def __init__(self, client=None):
        if client is None:
            from .http import make_client

            client = make_client(timeout=10.0)
        self.client = client

    def _get(self, path: str, params: dict):
        resp = self.client.get(f"{self.BASE}/{path}", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def fetch(self, title: str, artist: str, album: Optional[str], duration: Optional[float],
              tidal_id: Optional[str]) -> Optional[Lyrics]:
        params = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(round(duration))
        hit = self._get("get", params) if album and duration else None
        if not hit:
            results = self._get("search", {"track_name": title, "artist_name": artist}) or []
            hit = self._best(results, title, artist, duration)
        if not hit:
            return None
        if hit.get("instrumental"):
            return Lyrics(lines=[], synced=False, source="LRCLIB", instrumental=True)
        return _from_texts(hit.get("syncedLyrics"), hit.get("plainLyrics"), "LRCLIB")

    @staticmethod
    def _best(results: list, title: str, artist: str, duration: Optional[float]) -> Optional[dict]:
        best, best_score = None, 0.0
        for r in results if isinstance(results, list) else []:
            ts = title_similarity(title, r.get("trackName") or "")
            ar = artist_similarity(artist, [r.get("artistName") or ""])
            if ts < 0.8 or ar < 0.7:
                continue
            score = ts + ar
            d = r.get("duration")
            if duration and d:
                diff = abs(float(d) - duration)
                if diff > 8:
                    continue  # another recording (live, extended...)
                score -= diff / 10.0
            if r.get("syncedLyrics"):
                score += 0.5
            if score > best_score:
                best, best_score = r, score
        return best


class LyricsService:
    """Fetch lyrics in the background and cache them on disk."""

    def __init__(self, sources: list, cache_path: Optional[Path] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.sources = sources
        self.cache = DiskCache(cache_path, ttl=30 * 86400, max_entries=3000)
        self.log = log or (lambda m: None)
        self._lock = threading.Lock()
        self._results: dict[str, Any] = {}     # key -> Lyrics | None (none found) | "pending"

    @staticmethod
    def key(title: str, artist: str) -> str:
        from .matching import normalize

        return f"{normalize(artist)}|{normalize(title)}"

    def get(self, title: str, artist: str, album: Optional[str] = None, duration: Optional[float] = None,
            tidal_id: Optional[str] = None):
        """``Lyrics``, ``None`` (none exist) or ``"pending"`` (still looking)."""
        key = self.key(title, artist)
        with self._lock:
            if key in self._results:
                return self._results[key]
            cached = self.cache.get(key)
            if cached is not None:
                result = Lyrics.from_json(cached) if cached else None
                self._results[key] = result
                return result
            self._results[key] = "pending"
        threading.Thread(target=self._fetch, args=(key, title, artist, album, duration, tidal_id),
                         name="tidal-shuffle-lyrics", daemon=True).start()
        return "pending"

    def _fetch(self, key, title, artist, album, duration, tidal_id) -> None:
        found: Optional[Lyrics] = None
        failed = False
        for src in self.sources:
            try:
                lyr = src.fetch(title, artist, album, duration, tidal_id)
            except Exception as e:
                self.log(f"lyrics from {src.name} failed: {e}")
                failed = True
                continue
            if lyr is None:
                continue
            if lyr.instrumental:
                found = found or lyr
                continue
            if lyr.synced:
                found = lyr
                break
            found = found if (found is not None and not found.instrumental) else lyr  # keep looking for synced
        if found is not None or not failed:   # a failed lookup is retried next time
            self.cache.set(key, found.to_json() if found is not None else {})
            self.cache.flush()
        with self._lock:
            self._results[key] = found
