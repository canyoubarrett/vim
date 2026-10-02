"""macOS MediaRemote backends: ``media-control`` (preferred) and ``nowplaying-cli``.

Both tools only ever report the single application macOS "elected" as the
now-playing app. ``media-control`` tells us which app that is; ``nowplaying-cli``
v2 does too (``clientBundleIdentifier``) but older builds cannot.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
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
    """Accept epoch seconds/milliseconds/microseconds, ISO 8601, or NSDate-style strings."""
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


def _micros(payload: dict, key: str) -> Optional[float]:
    v = _to_float(payload.get(key + "Micros"))
    return v / 1e6 if v is not None else None


def parse_media_control(payload, now: Optional[float] = None) -> Optional[NowPlaying]:
    """Turn ``media-control get [--micros]`` JSON (or a ``stream`` line) into a :class:`NowPlaying`.

    ``media-control get`` prints the literal ``null`` when nothing is playing.
    """
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
    duration = _micros(payload, "duration")
    if duration is None:
        duration = _to_float(payload.get("duration"))
    elapsed = _micros(payload, "elapsedTime")
    if elapsed is None:
        elapsed = _to_float(payload.get("elapsedTime"))
    ts = _to_float(payload.get("timestampEpochMicros"))
    ts = ts / 1e6 if ts is not None else parse_timestamp(payload.get("timestamp"))
    if elapsed is not None and ts is None:
        ts = now if now is not None else time.time()
    if playing is False:
        rate = 0.0  # playbackRate can stay at a stale 1 while paused
    return NowPlaying(
        title=str(title or ""),
        artist=str(payload.get("artist") or ""),
        album=payload.get("album") or None,
        duration=duration,
        elapsed=elapsed,
        timestamp=ts,
        playing=bool(playing) if playing is not None else None,
        playback_rate=rate,
        bundle_id=bundle,
        source="media-control",
    )


def _binary_ok(path: str) -> bool:
    return bool(path) and (shutil.which(path) is not None or os.path.exists(path))


class MediaControlBackend:
    """``brew install media-control`` — works on every macOS version."""

    name = "media-control"

    def __init__(self, binary: Optional[str] = None, run: Runner = subprocess.run, log: Optional[Callable[[str], None]] = None):
        self.binary = binary or shutil.which("media-control") or "/opt/homebrew/bin/media-control"
        self._run = run
        self.log = log or (lambda m: None)
        self._failures = 0

    def available(self) -> tuple[bool, str]:
        if not _binary_ok(self.binary):
            return False, "media-control not installed (brew install media-control)"
        return True, ""

    def read(self) -> Optional[NowPlaying]:
        try:
            r = self._run([self.binary, "get", "--micros", "--no-artwork"], capture_output=True, text=True, timeout=8)
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


NPCLI_PROPS = ["title", "artist", "album", "duration", "elapsedTime", "playbackRate", "timestamp", "clientBundleIdentifier"]


def _npcli_value(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in ("null", "(null)", "") else s


def parse_nowplaying_cli(output: str, now: Optional[float] = None, assume_tidal: bool = True) -> Optional[NowPlaying]:
    """Parse ``nowplaying-cli get [--json] <props>``.

    v2 prints a JSON object keyed by property name (with ``clientBundleIdentifier``
    on recent macOS); v1 prints one value per line and never says which app is
    playing, in which case ``assume_tidal`` decides.
    """
    text = output.strip()
    vals: dict = {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            vals = {k: data.get(k) for k in NPCLI_PROPS}
    if not vals:
        lines = text.split("\n")
        lines += [""] * (len(NPCLI_PROPS) - len(lines))
        vals = dict(zip(NPCLI_PROPS, lines))
    title = _npcli_value(vals.get("title"))
    if not title:
        return None
    rate = _to_float(vals.get("playbackRate"))
    ts = parse_timestamp(vals.get("timestamp"))
    elapsed = _to_float(vals.get("elapsedTime"))
    if elapsed is not None and ts is None:
        ts = now if now is not None else time.time()
    bundle = _npcli_value(vals.get("clientBundleIdentifier"))
    if bundle is None and assume_tidal:
        bundle = TIDAL_BUNDLE_ID
    return NowPlaying(
        title=title, artist=_npcli_value(vals.get("artist")) or "", album=_npcli_value(vals.get("album")),
        duration=_to_float(vals.get("duration")), elapsed=elapsed, timestamp=ts,
        playing=(rate > 0) if rate is not None else None, playback_rate=rate,
        bundle_id=bundle, source="nowplaying-cli",
    )


class NowPlayingCliBackend:
    """``brew install nowplaying-cli`` — fallback; older builds cannot identify the app."""

    name = "nowplaying-cli"

    def __init__(self, binary: Optional[str] = None, run: Runner = subprocess.run, assume_tidal: bool = True,
                 log: Optional[Callable[[str], None]] = None):
        self.binary = binary or shutil.which("nowplaying-cli") or "/opt/homebrew/bin/nowplaying-cli"
        self._run = run
        self.assume_tidal = assume_tidal
        self.log = log or (lambda m: None)
        self._json_supported: Optional[bool] = None

    def available(self) -> tuple[bool, str]:
        if not _binary_ok(self.binary):
            return False, "nowplaying-cli not installed (brew install nowplaying-cli)"
        return True, ""

    def _get(self, use_json: bool) -> Optional[str]:
        args = [self.binary, "get"] + (["--json"] if use_json else []) + NPCLI_PROPS
        try:
            r = self._run(args, capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.SubprocessError) as e:
            self.log(f"nowplaying-cli failed: {e}")
            return None
        return r.stdout if r.returncode == 0 else None

    def read(self) -> Optional[NowPlaying]:
        if activity.is_busy():
            return None  # another app (Spotify harvest) owns now-playing; older builds cannot tell them apart
        if self._json_supported is not False:
            out = self._get(use_json=True)
            if out is not None and out.strip().startswith("{"):
                self._json_supported = True
                return parse_nowplaying_cli(out, assume_tidal=self.assume_tidal)
            self._json_supported = False  # v1: prints help text for unknown flags
        out = self._get(use_json=False)
        if out is None:
            return None
        return parse_nowplaying_cli(out, assume_tidal=self.assume_tidal)


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
