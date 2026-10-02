"""Now-playing backends: where we learn what TIDAL is playing right now."""

from __future__ import annotations

import time
from typing import Callable, Optional, Protocol

from ..models import TIDAL_BUNDLE_ID, NowPlaying


class NowPlayingBackend(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def read(self) -> Optional[NowPlaying]: ...


class StaticBackend:
    """Replays a scripted sequence of snapshots (tests, dry runs)."""

    name = "static"

    def __init__(self, snapshots: Optional[list] = None):
        self.snapshots = list(snapshots or [])
        self.index = 0

    def available(self) -> tuple[bool, str]:
        return True, ""

    def read(self) -> Optional[NowPlaying]:
        if not self.snapshots:
            return None
        snap = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        self.index += 1
        return snap


class CompositeBackend:
    """Merge the TIDAL app's own footer (via CDP) with macOS MediaRemote timing.

    * identity (title / artist / numeric track id) comes from TIDAL itself when
      CDP is available, so a muted Spotify harvest that briefly steals macOS's
      "now playing" slot cannot confuse us;
    * elapsed time comes from MediaRemote when it is reporting the same TIDAL
      track, otherwise from the footer clock.
    """

    name = "composite"

    def __init__(self, media: Optional[NowPlayingBackend], cdp=None, wall: Callable[[], float] = time.time,
                 log: Optional[Callable[[str], None]] = None):
        self.media = media
        self.cdp = cdp
        self._wall = wall
        self.log = log or (lambda m: None)
        self._cdp_failures = 0
        self._clock_anchor: Optional[tuple] = None  # (song, shown second, when it ticked over)

    def available(self) -> tuple[bool, str]:
        if self.media is not None:
            ok, reason = self.media.available()
            if ok:
                return True, ""
        if self.cdp is not None and self.cdp.alive():
            return True, ""
        return False, "no now-playing backend (install media-control or launch TIDAL with the debug port)"

    def _read_media(self) -> Optional[NowPlaying]:
        if self.media is None:
            return None
        try:
            return self.media.read()
        except Exception as e:
            self.log(f"now-playing backend {self.media.name} failed: {e}")
            return None

    def _read_cdp(self):
        if self.cdp is None:
            return None
        try:
            np = self.cdp.now_playing()
            self._cdp_failures = 0
            return np
        except Exception as e:
            self._cdp_failures += 1
            if self._cdp_failures in (1, 10, 100):
                self.log(f"TIDAL footer read failed: {e}")
            return None

    def read(self) -> Optional[NowPlaying]:
        media = self._read_media()
        footer = self._read_cdp()
        if footer is None:
            return media
        now = self._wall()
        np = NowPlaying(
            title=footer.title or (media.title if media and media.is_tidal else "") or "",
            artist=footer.artist or (media.artist if media and media.is_tidal else "") or "",
            bundle_id=TIDAL_BUNDLE_ID,
            tidal_id=footer.track_id,
            playing=footer.playing,
            source="cdp",
        )
        if not np.title:
            return media
        same = media is not None and media.is_tidal and media.same_track(np)
        if same:
            np.album = media.album
            np.duration = media.duration
            np.elapsed = media.elapsed
            np.timestamp = media.timestamp
            np.playback_rate = media.playback_rate
            if media.playing is not None:
                np.playing = media.playing if footer.playing is None else footer.playing
            np.source = "cdp+" + (media.source or "media")
        else:
            np.duration = footer.duration
            np.elapsed, np.timestamp = self._smooth_clock(np, footer.position, now)
        return np

    def _smooth_clock(self, np: NowPlaying, shown: Optional[float], now: float):
        """The footer clock shows whole seconds. Anchor to the moment the shown
        second last changed, so the position is known to within one poll rather
        than up to a second behind (which made hand-offs near the end miss)."""
        if shown is None:
            self._clock_anchor = None
            return None, None
        key = np.tidal_id or np.key
        anchor = getattr(self, "_clock_anchor", None)
        if anchor is None or anchor[0] != key or anchor[1] != shown:
            # a new second ticked over (or a new song): it started about now
            self._clock_anchor = (key, shown, now)
            return shown, now
        _, _, since = anchor
        if np.playing is False or now - since > 1.5:
            return shown, now  # paused or the clock is not moving: no extrapolation
        return shown, since
