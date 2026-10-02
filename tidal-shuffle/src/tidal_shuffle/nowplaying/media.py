"""macOS MediaRemote backends: ``media-control`` (preferred) and ``nowplaying-cli``."""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import time
from typing import Callable, Optional

from .. import activity
from ..models import TIDAL_BUNDLE_ID, NowPlaying

Runner = Callable[..., subprocess.CompletedProcess]


def _to_float(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in ("null", "none", "(null)", "missing value"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_timestamp(value, now: Optional[float] = None) -> Optional[float]:
    """Accept epoch seconds/milliseconds, ISO 8601, or NSDate-style strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if v > 1e14:      # microseconds
            return v / 1e6
        if v > 1e11:      # milliseconds
            return v / 1e3
        return v
    s = str(value).strip()
    if not s or s.lower() in ("null", "none"):
        return None
    num = _to_float(s)
    if num is not None:
        return parse_timestamp(num)
    try:
        iso = s.replace("Z", "+00:00")
        if iso.endswith("+0000"):
            iso = iso[:-5] + "+00:00"
        return _dt.datetime.fromisoformat(iso).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            d = _dt.datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=_dt.timezone.utc)
            return d.timestamp()
        except ValueError:
            continue
    return None


def parse_media_control(payload: dict, now: Optional[float] = None) -> Optional[NowPlaying]:
    """Turn ``media-control get`` JSON into a :class:`NowPlaying`."""
    if not isinstance(payload, dict):
        return None
    if "payload" in payload and isinstance(payload["payload"], dict):  # stream line
        payload = payload["payload"]
    title = payload.get("title")
    bundle = payload.get("bundleIdentifier") or payload.get("parentApplicationBundleIdentifier")
    if not title and not bundle:
        return None
    playing = payload.get("playing")
    rate = _to_float(payload.get("playbackRate"))
    if playing is None and rate is not None:
        playing = rate > 0
    ts = parse_timestamp(payload.get("timestamp"))
    elapsed = _to_float(payload.get("elapsedTime"))
    if elapsed is not None and ts is None:
        ts = now if now is not None else time.time()
    return NowPlaying(
        title=str(title or ""),
        artist=str(payload.get("artist") or ""),
        album=payload.get("album") or None,
        duration=_to_float(payload.get("duration")),
        elapsed=elapsed,
        timestamp=ts,
        playing=bool(playing) if playing is not None else None,
        playback_rate=rate,
        bundle_id=bundle,
        source="media-control",
    )


class MediaControlBackend:
    """``brew install media-control`` — works on every macOS version."""

    name = "media-control"
    PROPS = None  # it always prints everything

    def __init__(self, binary: Optional[str] = None, run: Runner = subprocess.run, log: Optional[Callable[[str], None]] = None):
        self.binary = binary or shutil.which("media-control") or "/opt/homebrew/bin/media-control"
        self._run = run
        self.log = log or (lambda m: None)
        self._failures = 0

    def available(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None and not shutil.os.path.exists(self.binary):
            return False, "media-control not installed (brew install media-control)"
        return True, ""

    def read(self) -> Optional[NowPlaying]:
        try:
            r = self._run([self.binary, "get", "--no-artwork"], capture_output=True, text=True, timeout=6)
        except (OSError, subprocess.SubprocessError) as e:
            self._failures += 1
            if self._failures in (1, 20):
                self.log(f"media-control failed: {e}")
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        try:
            payload = json.loads(r.stdout)
        except ValueError:
            return None
        self._failures = 0
        return parse_media_control(payload)


NPCLI_PROPS = ["title", "artist", "album", "duration", "elapsedTime", "playbackRate", "timestamp"]


def parse_nowplaying_cli(output: str, now: Optional[float] = None, assume_tidal: bool = True) -> Optional[NowPlaying]:
    """Parse ``nowplaying-cli get title artist album duration elapsedTime playbackRate timestamp``.

    nowplaying-cli prints one value per line and cannot say which app is
    playing, so callers decide whether to trust it (``assume_tidal``).
    """
    lines = output.split("\n")
    lines += [""] * (len(NPCLI_PROPS) - len(lines))
    vals = dict(zip(NPCLI_PROPS, (l.strip() for l in lines)))
    title = vals["title"]
    if not title or title.lower() in ("null", "(null)"):
        return None
    rate = _to_float(vals["playbackRate"])
    ts = parse_timestamp(vals["timestamp"])
    elapsed = _to_float(vals["elapsedTime"])
    if elapsed is not None and ts is None:
        ts = now if now is not None else time.time()
    artist = vals["artist"] if vals["artist"].lower() not in ("null", "(null)") else ""
    album = vals["album"] if vals["album"].lower() not in ("null", "(null)", "") else None
    return NowPlaying(
        title=title, artist=artist, album=album, duration=_to_float(vals["duration"]), elapsed=elapsed,
        timestamp=ts, playing=(rate > 0) if rate is not None else None, playback_rate=rate,
        bundle_id=TIDAL_BUNDLE_ID if assume_tidal else None, source="nowplaying-cli",
    )


class NowPlayingCliBackend:
    """``brew install nowplaying-cli`` — fallback; cannot identify the app."""

    name = "nowplaying-cli"

    def __init__(self, binary: Optional[str] = None, run: Runner = subprocess.run, assume_tidal: bool = True,
                 log: Optional[Callable[[str], None]] = None):
        self.binary = binary or shutil.which("nowplaying-cli") or "/opt/homebrew/bin/nowplaying-cli"
        self._run = run
        self.assume_tidal = assume_tidal
        self.log = log or (lambda m: None)

    def available(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None and not shutil.os.path.exists(self.binary):
            return False, "nowplaying-cli not installed (brew install nowplaying-cli)"
        return True, ""

    def read(self) -> Optional[NowPlaying]:
        if activity.is_busy():
            return None  # another app (Spotify harvest) owns now-playing; we cannot tell them apart
        try:
            r = self._run([self.binary, "get", *NPCLI_PROPS], capture_output=True, text=True, timeout=6)
        except (OSError, subprocess.SubprocessError) as e:
            self.log(f"nowplaying-cli failed: {e}")
            return None
        if r.returncode != 0:
            return None
        return parse_nowplaying_cli(r.stdout, assume_tidal=self.assume_tidal)


def detect_backend(preference: str = "auto", log: Optional[Callable[[str], None]] = None):
    """Pick the MediaRemote backend according to config and what is installed."""
    candidates = {
        "media-control": MediaControlBackend(log=log),
        "nowplaying-cli": NowPlayingCliBackend(log=log),
    }
    if preference in candidates:
        return candidates[preference]
    for name in ("media-control", "nowplaying-cli"):
        if candidates[name].available()[0]:
            return candidates[name]
    return None
