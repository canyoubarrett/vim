"""Persistent play history used to avoid repeats and artist pile-ups."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .matching import normalize
from .paths import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / "history.json"


@dataclass
class HistoryEntry:
    title: str
    artist: str
    tidal_id: Optional[str] = None
    source: Optional[str] = None
    ts: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (normalize(self.title), normalize(self.artist))


class HistoryStore:
    """Ordered, bounded, JSON-backed list of what the shuffler played."""

    def __init__(self, path: Optional[Path] = None, max_entries: int = 2000):
        self.path = Path(path) if path else HISTORY_FILE
        self.max_entries = max_entries
        self._entries: list[HistoryEntry] = []
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if entries is None and isinstance(data, dict) and "played" in data:
            # v1 format: a bare list of tidal ids.
            entries = [{"title": "", "artist": "", "tidal_id": str(t), "ts": 0.0} for t in data.get("played", [])]
        for e in entries or []:
            try:
                self._entries.append(HistoryEntry(
                    title=str(e.get("title", "")),
                    artist=str(e.get("artist", "")),
                    tidal_id=(str(e["tidal_id"]) if e.get("tidal_id") is not None else None),
                    source=e.get("source"),
                    ts=float(e.get("ts", 0.0) or 0.0),
                ))
            except (AttributeError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 2, "entries": [asdict(e) for e in self._entries]}
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".history-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- queries -----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> list[HistoryEntry]:
        return list(self._entries)

    def recent(self, n: int) -> list[HistoryEntry]:
        return self._entries[-n:] if n > 0 else []

    def recent_keys(self, within_count: int = 200, within_days: Optional[float] = None, now: Optional[float] = None) -> set:
        return {e.key for e in self._window(within_count, within_days, now) if e.title}

    def recent_tidal_ids(self, within_count: int = 200, within_days: Optional[float] = None, now: Optional[float] = None) -> set:
        return {e.tidal_id for e in self._window(within_count, within_days, now) if e.tidal_id}

    def recent_artists(self, n: int) -> list[str]:
        return [e.artist for e in self.recent(n) if e.artist]

    def _window(self, within_count: int, within_days: Optional[float], now: Optional[float]) -> list[HistoryEntry]:
        entries = self.recent(within_count) if within_count else list(self._entries)
        if within_days:
            cutoff = (now if now is not None else time.time()) - within_days * 86400
            entries = [e for e in entries if e.ts >= cutoff]
        return entries

    def has_played(self, title: str = "", artist: str = "", tidal_id: Optional[str] = None,
                   within_count: int = 0, within_days: Optional[float] = None) -> bool:
        if tidal_id and tidal_id in self.recent_tidal_ids(within_count, within_days):
            return True
        if title and (normalize(title), normalize(artist)) in self.recent_keys(within_count, within_days):
            return True
        return False

    # -- mutation ----------------------------------------------------------
    def add(self, title: str, artist: str, tidal_id: Optional[str] = None,
            source: Optional[str] = None, ts: Optional[float] = None) -> HistoryEntry:
        entry = HistoryEntry(title=title, artist=artist, tidal_id=tidal_id, source=source,
                             ts=ts if ts is not None else time.time())
        self._entries.append(entry)
        self._save()
        return entry

    def clear(self) -> None:
        self._entries.clear()
        self._save()
