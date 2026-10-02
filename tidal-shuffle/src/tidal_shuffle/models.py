"""Data models shared across Tidal Shuffle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

TIDAL_BUNDLE_ID = "com.tidal.desktop"
SPOTIFY_BUNDLE_ID = "com.spotify.client"


def _norm_key(s: Optional[str]) -> str:
    # Local import to avoid a circular import at module load time.
    from .matching import normalize

    return normalize(s or "")


@dataclass
class NowPlaying:
    """A snapshot of what macOS reports as "now playing".

    ``elapsed`` is the playback position *at* ``timestamp`` (unix seconds). The
    MediaRemote framework hands out a position snapshot plus the time it was
    taken, so callers must extrapolate with :meth:`position_at` instead of
    trusting ``elapsed`` directly.
    """

    title: str
    artist: str
    album: Optional[str] = None
    duration: Optional[float] = None
    elapsed: Optional[float] = None
    timestamp: Optional[float] = None
    playing: Optional[bool] = None
    playback_rate: Optional[float] = None
    bundle_id: Optional[str] = None
    tidal_id: Optional[str] = None   # known only when read through the TIDAL app itself
    source: str = ""                 # which backend produced this snapshot

    @property
    def is_tidal(self) -> bool:
        return self.bundle_id == TIDAL_BUNDLE_ID or bool(self.tidal_id)

    @property
    def key(self) -> tuple[str, str]:
        return (_norm_key(self.title), _norm_key(self.artist))

    def same_track(self, other: Optional["NowPlaying"]) -> bool:
        return other is not None and self.key == other.key

    def position_at(self, now: float) -> Optional[float]:
        """Best estimate of the playback position (seconds) at wall time ``now``."""
        if self.elapsed is None:
            return None
        if self.playing is False:
            return self.elapsed
        if self.timestamp is None:
            return self.elapsed
        rate = self.playback_rate if self.playback_rate is not None else 1.0
        if self.playing is None and rate == 0:
            return self.elapsed
        pos = self.elapsed + max(0.0, now - self.timestamp) * rate
        if self.duration is not None:
            pos = min(pos, self.duration)
        return pos

    def remaining_at(self, now: float) -> Optional[float]:
        pos = self.position_at(now)
        if pos is None or self.duration is None:
            return None
        return max(0.0, self.duration - pos)

    def label(self) -> str:
        return f"{self.title} — {self.artist}"


@dataclass
class Seed:
    """The song recommendations are generated *from*."""

    title: str
    artist: str
    album: Optional[str] = None
    duration: Optional[float] = None
    isrc: Optional[str] = None
    tidal_id: Optional[str] = None
    spotify_id: Optional[str] = None

    @classmethod
    def from_now_playing(cls, np: NowPlaying) -> "Seed":
        return cls(title=np.title, artist=np.artist, album=np.album, duration=np.duration, tidal_id=np.tidal_id)

    @property
    def key(self) -> tuple[str, str]:
        return (_norm_key(self.title), _norm_key(self.artist))

    def label(self) -> str:
        return f"{self.title} — {self.artist}"


@dataclass
class Candidate:
    """A recommended song as returned by a source, before/after Tidal matching."""

    title: str
    artist: str
    album: Optional[str] = None
    duration: Optional[float] = None
    isrc: Optional[str] = None
    source: str = ""
    score: float = 0.5
    rank: int = 0
    popularity: Optional[int] = None
    spotify_id: Optional[str] = None
    tidal_id: Optional[str] = None
    match_score: Optional[float] = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (_norm_key(self.title), _norm_key(self.artist))

    def label(self) -> str:
        return f"{self.title} — {self.artist}"


@dataclass
class TidalTrack:
    """A track in the TIDAL catalog."""

    id: str
    title: str
    artist: str
    artists: list[str] = field(default_factory=list)
    album: Optional[str] = None
    duration: Optional[float] = None
    isrc: Optional[str] = None
    explicit: bool = False
    available: bool = True
    popularity: Optional[int] = None

    @property
    def key(self) -> tuple[str, str]:
        return (_norm_key(self.title), _norm_key(self.artist))

    @property
    def url(self) -> str:
        return f"https://tidal.com/browse/track/{self.id}"

    @property
    def deep_link(self) -> str:
        return f"tidal://track/{self.id}"

    def label(self) -> str:
        return f"{self.title} — {self.artist}"


@dataclass
class Pick:
    """A fully resolved "play this next" decision."""

    candidate: Candidate
    track: TidalTrack
    reason: str = ""

    @property
    def source(self) -> str:
        return self.candidate.source

    def label(self) -> str:
        return self.track.label()


@dataclass
class VibeParams:
    """Tunable attributes for the Spotify recommendations endpoint.

    These only have an effect on Spotify apps that still have access to
    ``GET /v1/recommendations`` (apps created before 2024-11-27 with extended
    quota). They are ignored by every other source.
    """

    energy: Optional[float] = None
    valence: Optional[float] = None
    tempo: Optional[float] = None
    acousticness: Optional[float] = None
    danceability: Optional[float] = None
    instrumentalness: Optional[float] = None
    genres: list[str] = field(default_factory=list)
    min_popularity: Optional[int] = None
    max_popularity: Optional[int] = None

    def to_api_params(self) -> dict:
        params: dict = {}
        for name in ("energy", "valence", "tempo", "acousticness", "danceability", "instrumentalness"):
            value = getattr(self, name)
            if value is not None:
                params[f"target_{name}"] = value
        if self.min_popularity is not None:
            params["min_popularity"] = self.min_popularity
        if self.max_popularity is not None:
            params["max_popularity"] = self.max_popularity
        return params

    def is_empty(self) -> bool:
        return not self.to_api_params() and not self.genres
