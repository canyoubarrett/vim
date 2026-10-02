"""A tiny process-wide "something noisy is happening" flag.

While the Spotify harvest runs, macOS's now-playing slot belongs to Spotify.
Backends that cannot tell apps apart (nowplaying-cli) consult this flag and
report nothing instead of mistaking Spotify's track for TIDAL's.
"""

from __future__ import annotations

import contextlib
import time
from typing import Callable, Iterator

_busy_until: dict[str, float] = {}
_clock: Callable[[], float] = time.monotonic


def mark_busy(name: str, seconds: float) -> None:
    _busy_until[name] = _clock() + seconds


def clear(name: str, linger: float = 3.0) -> None:
    _busy_until[name] = _clock() + linger


def is_busy() -> bool:
    now = _clock()
    return any(until > now for until in _busy_until.values())


@contextlib.contextmanager
def busy(name: str, seconds: float, linger: float = 3.0) -> Iterator[None]:
    mark_busy(name, seconds)
    try:
        yield
    finally:
        clear(name, linger)
