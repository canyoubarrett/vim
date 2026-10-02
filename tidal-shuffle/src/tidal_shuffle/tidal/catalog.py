"""TIDAL catalog access on top of the unofficial ``tidalapi`` library.

Responsibilities: log in (device-link OAuth, persisted to disk), search,
ISRC lookup, and fuzzy matching of a (title, artist) pair to a TIDAL track.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..matching import DEFAULT_ACCEPT_THRESHOLD, core_title, normalize, primary_artist, score_match, strip_featuring
from ..models import Candidate, Seed, TidalTrack

log = logging.getLogger(__name__)
Printer = Callable[[str], None]


class TidalLoginRequired(RuntimeError):
    pass


def _artist_names(t: Any) -> list[str]:
    names: list[str] = []
    for a in (getattr(t, "artists", None) or []):
        n = getattr(a, "name", None)
        if n and n not in names:
            names.append(n)
    primary = getattr(getattr(t, "artist", None), "name", None)
    if primary and primary not in names:
        names.insert(0, primary)
    return names


def to_track(t: Any) -> TidalTrack:
    """Convert a ``tidalapi.Track`` (or anything duck-typed like it)."""
    names = _artist_names(t)
    title = getattr(t, "full_name", None) or getattr(t, "name", None) or getattr(t, "title", "") or ""
    version = getattr(t, "version", None)
    if version and f"({version})" not in title:
        title = f"{title} ({version})"
    album = getattr(getattr(t, "album", None), "name", None)
    duration = getattr(t, "duration", None)
    popularity = getattr(t, "popularity", None)
    available = getattr(t, "available", None)
    if available is None:
        available = getattr(t, "allow_streaming", True)
    artist_id = getattr(getattr(t, "artist", None), "id", None)
    return TidalTrack(
        id=str(getattr(t, "id")),
        title=title,
        artist=names[0] if names else "Unknown",
        artists=names,
        album=album,
        duration=float(duration) if duration is not None else None,
        isrc=getattr(t, "isrc", None) or None,
        explicit=bool(getattr(t, "explicit", False)),
        available=bool(available),
        popularity=(int(popularity) if isinstance(popularity, (int, float)) and popularity >= 0 else None),
        artist_id=str(artist_id) if artist_id is not None else None,
    )


def connect_session(session_file: Path, printer: Printer = print, interactive: bool = True,
                    session_factory: Optional[Callable[[], Any]] = None) -> Any:
    """Return a logged-in ``tidalapi.Session``.

    Loads the persisted session if possible; otherwise (when ``interactive``)
    runs TIDAL's device-link login and saves the result.
    """
    if session_factory is None:
        import tidalapi  # imported lazily so tests never need the network

        # item_limit is appended as `limit` to every request (including the
        # openapi v2 ISRC lookup), so keep it modest.
        session_factory = lambda: tidalapi.Session(tidalapi.Config(item_limit=100))  # noqa: E731
    session = session_factory()
    session_file = Path(session_file).expanduser()
    if session_file.exists():
        try:
            session.load_session_from_file(session_file)
        except Exception as e:  # corrupt/expired file, dead refresh token...; fall through to login
            log.info("could not load TIDAL session: %s", e)
    try:
        if session.check_login():
            session._tidal_shuffle_loaded_token = getattr(session, "access_token", None)
            session._tidal_shuffle_session_file = session_file
            return session
    except Exception as e:
        log.info("TIDAL session check failed: %s", e)
    if not interactive:
        raise TidalLoginRequired("TIDAL login required; run `tidal-shuffle login`")
    try:
        login, future = session.login_oauth()
    except Exception as e:
        raise TidalLoginRequired(f"could not reach TIDAL to start the login: {e}") from None
    printer(f"Open this link to log in to TIDAL (expires in {int(login.expires_in)}s):")
    printer(f"  https://{login.verification_uri_complete}")
    try:
        future.result()
    except Exception as e:
        raise TidalLoginRequired(f"TIDAL login failed: {e}") from None
    if not session.check_login():
        raise TidalLoginRequired("TIDAL login did not complete")
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session.save_session_to_file(session_file)
    session._tidal_shuffle_loaded_token = getattr(session, "access_token", None)
    session._tidal_shuffle_session_file = session_file
    return session


def persist_session(session: Any) -> bool:
    """Write the session file again if tidalapi refreshed the access token in memory."""
    path = getattr(session, "_tidal_shuffle_session_file", None)
    if path is None:
        return False
    if getattr(session, "access_token", None) == getattr(session, "_tidal_shuffle_loaded_token", None):
        return False
    try:
        session.save_session_to_file(Path(path))
        session._tidal_shuffle_loaded_token = session.access_token
        return True
    except Exception as e:
        log.info("could not persist TIDAL session: %s", e)
        return False


class TidalCatalog:
    """Search/lookup against TIDAL with caching and fuzzy matching."""

    def __init__(self, session: Any, search_limit: int = 10, threshold: float = DEFAULT_ACCEPT_THRESHOLD,
                 log_fn: Optional[Callable[[str], None]] = None, sleep: Callable[[float], None] = time.sleep):
        self.session = session
        self.search_limit = search_limit
        self.threshold = threshold
        self.log = log_fn or (lambda m: None)
        self._sleep = sleep
        self._find_cache: dict[tuple, tuple[Optional[TidalTrack], float]] = {}
        self._track_cache: dict[str, Optional[TidalTrack]] = {}

    # -- raw access ---------------------------------------------------------
    def _retry(self, fn: Callable[[], Any], what: str) -> Any:
        """tidalapi has no retry of its own: back off on 429, 5xx and connection errors."""
        import requests
        from tidalapi.exceptions import TooManyRequests

        for attempt in range(3):
            try:
                return fn()
            except TooManyRequests as e:
                wait = e.retry_after if getattr(e, "retry_after", -1) and e.retry_after > 0 else 2 ** attempt
                if wait > 30:
                    raise  # retrying early would only earn another 429
                self.log(f"TIDAL rate limited during {what}; waiting {wait}s")
                self._sleep(float(wait))
            except requests.HTTPError as e:
                status = getattr(getattr(e, "response", None), "status_code", 0) or 0
                if status < 500:
                    raise
                self.log(f"TIDAL server error {status} during {what}; retrying")
                self._sleep(min(2.0 ** attempt, 8.0))
            except (requests.ConnectionError, requests.Timeout, ValueError) as e:
                # ValueError covers tidalapi choking on a non-JSON error body.
                self.log(f"TIDAL request failed during {what}: {e}; retrying")
                self._sleep(min(2.0 ** attempt, 8.0))
        return fn()

    def search_tracks(self, query: str, limit: Optional[int] = None) -> list[TidalTrack]:
        import tidalapi

        limit = limit or self.search_limit
        res = self._retry(lambda: self.session.search(query, models=[tidalapi.Track], limit=limit), f"search {query!r}")
        items = res.get("tracks", []) if isinstance(res, dict) else getattr(res, "tracks", []) or []
        return [to_track(t) for t in items]

    def tracks_by_isrc(self, isrc: str) -> list[TidalTrack]:
        from tidalapi.exceptions import TidalAPIError

        try:
            items = self._retry(lambda: self.session.get_tracks_by_isrc(isrc), f"isrc {isrc}")
        except TidalAPIError:
            return []
        except Exception as e:  # tidalapi raises bare HTTP errors for odd ISRCs
            self.log(f"ISRC lookup failed for {isrc}: {e}")
            return []
        return [to_track(t) for t in items or []]

    def get_track(self, tidal_id: str) -> Optional[TidalTrack]:
        from tidalapi.exceptions import ObjectNotFound, TidalAPIError

        tidal_id = str(tidal_id)
        if tidal_id in self._track_cache:
            return self._track_cache[tidal_id]
        try:
            track = to_track(self._retry(lambda: self.session.track(tidal_id), f"track {tidal_id}"))
        except ObjectNotFound:
            track = None  # genuinely gone: remember that
        except Exception as e:  # rate limit, auth refresh, network: try again next time
            self.log(f"TIDAL track {tidal_id} lookup failed: {e}")
            return None
        self._track_cache[tidal_id] = track
        return track

    def raw_track(self, tidal_id: str) -> Any:
        """The underlying ``tidalapi.Track`` with full metadata."""
        return self._retry(lambda: self.session.track(str(tidal_id)), f"track {tidal_id}")

    # -- radio ----------------------------------------------------------------
    def _radio_tracks(self, fn: Callable[[], Any], what: str) -> list[TidalTrack]:
        from tidalapi.exceptions import TidalAPIError

        try:
            items = self._retry(fn, what) or []
        except TidalAPIError as e:
            self.log(f"{what}: {e}")
            return []
        out = []
        for t in items:
            if getattr(t, "duration", None) is None and not hasattr(t, "name"):
                continue  # videos and other non-track items
            out.append(to_track(t))
        return out

    def track_radio(self, tidal_id: str, limit: int = 50) -> list[TidalTrack]:
        """TIDAL's track radio. Builds the Track shell without a metadata request."""
        def fetch():
            shell = self.session.track()
            shell.id = str(tidal_id)
            return shell.get_track_radio(limit=limit)
        return self._radio_tracks(fetch, f"track radio {tidal_id}")

    def artist_radio(self, artist_id: str, limit: int = 50) -> list[TidalTrack]:
        def fetch():
            shell = self.session.artist()
            shell.id = str(artist_id)
            return shell.get_radio(limit=limit)
        return self._radio_tracks(fetch, f"artist radio {artist_id}")

    def similar_artists_top_tracks(self, artist_id: str, artists: int = 5, per_artist: int = 5) -> list[TidalTrack]:
        from tidalapi.exceptions import TidalAPIError

        def fetch_similar():
            shell = self.session.artist()
            shell.id = str(artist_id)
            return shell.get_similar()
        try:
            similar = self._retry(fetch_similar, f"similar artists {artist_id}") or []
        except TidalAPIError:
            return []
        out: list[TidalTrack] = []
        for a in similar[:artists]:
            try:
                top = self._retry(lambda a=a: a.get_top_tracks(limit=per_artist), f"top tracks {getattr(a, 'id', '?')}") or []
            except TidalAPIError:
                continue
            out.extend(to_track(t) for t in top)
        return out

    # -- matching -----------------------------------------------------------
    def _score(self, title: str, artist: str, duration: Optional[float], t: TidalTrack) -> float:
        s = score_match(title, artist, t.title, t.artists or [t.artist], duration, t.duration)
        if not t.available:
            s *= 0.1
        return s

    def find(self, title: str, artist: str, duration: Optional[float] = None,
             isrc: Optional[str] = None) -> tuple[Optional[TidalTrack], float]:
        """Best TIDAL track for a song, with the match score (0 if none)."""
        key = (normalize(strip_featuring(title)), normalize(primary_artist(artist)), isrc or "")
        if key in self._find_cache:
            return self._find_cache[key]

        best: Optional[TidalTrack] = None
        best_score = 0.0
        failed = False
        if isrc:
            for t in self.tracks_by_isrc(isrc):
                if not t.available:
                    continue
                s = max(0.9, self._score(title, artist, duration, t))  # same recording by definition
                if s > best_score:
                    best, best_score = t, s
        if best is None:
            queries = [f"{core_title(title)} {primary_artist(artist)}"]
            if queries[0].lower() != f"{title} {artist}".lower():
                queries.append(f"{title} {artist}")
            seen: set[str] = set()
            for q in queries:
                try:
                    hits = self.search_tracks(q)
                except Exception as e:
                    self.log(f"TIDAL search failed for {q!r}: {e}")
                    failed = True
                    continue
                for t in hits:
                    if t.id in seen:
                        continue
                    seen.add(t.id)
                    s = self._score(title, artist, duration, t)
                    if s > best_score:
                        best, best_score = t, s
                if best_score >= 0.9:
                    break
        if best is None or best_score < self.threshold:
            result: tuple[Optional[TidalTrack], float] = (None, best_score)
        else:
            result = (best, best_score)
        if not (failed and result[0] is None):  # a network hiccup is not a "no match"
            self._find_cache[key] = result
        return result

    # -- Catalog protocol ---------------------------------------------------
    def resolve_seed(self, seed: Seed) -> Seed:
        if seed.tidal_id:
            track = self.get_track(seed.tidal_id)
        else:
            track, _ = self.find(seed.title, seed.artist, seed.duration, seed.isrc)
        if track is not None:
            seed.tidal_id = track.id
            seed.isrc = seed.isrc or track.isrc
            seed.duration = seed.duration or track.duration
            seed.album = seed.album or track.album
        return seed

    def match(self, cand: Candidate) -> Optional[TidalTrack]:
        if cand.tidal_id:
            track = self.get_track(cand.tidal_id)
            if track is not None and track.available:
                cand.match_score = 1.0
                return track
        track, score = self.find(cand.title, cand.artist, cand.duration, cand.isrc)
        cand.match_score = score
        if track is not None:
            cand.tidal_id = track.id
            cand.isrc = cand.isrc or track.isrc
            cand.duration = cand.duration or track.duration
        return track
