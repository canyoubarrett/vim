"""A tiny JSON-file cache with a time-to-live, shared by the API clients.

Last.fm's API terms ask clients to cache similarity data for at least a week,
and every cached answer is one request less against rate-limited services.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional


class DiskCache:
    def __init__(self, path: Optional[Path], ttl: float, max_entries: int = 5000,
                 clock: Callable[[], float] = time.time):
        self.path = Path(path) if path else None
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._data: dict[str, list] = {}
        self._lock = threading.Lock()
        self._dirty = 0
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        now = self._clock()
        if isinstance(raw, dict):
            self._data = {k: v for k, v in raw.items()
                          if isinstance(v, list) and len(v) == 2 and now - float(v[0]) < self.ttl}

    def get(self, key: str) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            if self._clock() - float(hit[0]) >= self.ttl:
                self._data.pop(key, None)
                return None
            return hit[1]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = [self._clock(), value]
            if len(self._data) > self.max_entries:
                for k, _ in sorted(self._data.items(), key=lambda kv: kv[1][0])[: len(self._data) - self.max_entries]:
                    self._data.pop(k, None)
            self._dirty += 1
        if self._dirty >= 10:
            self.flush()

    def flush(self) -> None:
        if self.path is None:
            return
        with self._lock:
            if not self._dirty:
                return
            payload = json.dumps(self._data)
            self._dirty = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".cache-", suffix=".json")
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            os.replace(tmp, self.path)
        except OSError:
            pass
