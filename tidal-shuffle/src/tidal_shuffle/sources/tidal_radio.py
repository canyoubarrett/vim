"""TIDAL's own track radio as a source (no extra accounts needed)."""

from __future__ import annotations

from typing import Optional, Sequence

from ..models import Candidate, Seed, TidalTrack
from ..tidal.catalog import TidalCatalog
from .base import tag


class TidalRadioSource:
    name = "tidal-radio"

    def __init__(self, catalog: Optional[TidalCatalog], limit: int = 50):
        self.catalog = catalog
        self.limit = limit

    def available(self) -> tuple[bool, str]:
        if self.catalog is None:
            return False, "not logged in to TIDAL"
        return True, ""

    def _fallbacks(self, seed: Seed, limit: int) -> list[TidalTrack]:
        """Artist radio, then similar artists' top tracks, when track radio is empty."""
        assert self.catalog is not None
        track = self.catalog.get_track(seed.tidal_id) if seed.tidal_id else None
        if track is None or not track.artist_id:
            return []
        tracks = self.catalog.artist_radio(track.artist_id, limit=limit)
        if not tracks:
            tracks = self.catalog.similar_artists_top_tracks(track.artist_id)
        return tracks

    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        assert self.catalog is not None
        seed = seeds[0]
        if not seed.tidal_id:
            seed = self.catalog.resolve_seed(seed)
        if not seed.tidal_id:
            return []
        want = max(limit, self.limit)
        tracks = self.catalog.track_radio(seed.tidal_id, limit=want)
        if not tracks:
            tracks = self._fallbacks(seed, want)
        out: list[Candidate] = []
        n = max(1, len(tracks))
        for i, tt in enumerate(tracks):
            if not tt.available or tt.id == str(seed.tidal_id):
                continue
            out.append(Candidate(
                title=tt.title, artist=tt.artist, album=tt.album, duration=tt.duration, isrc=tt.isrc,
                popularity=tt.popularity, tidal_id=tt.id, score=1.0 - 0.6 * (i / n),
            ))
        return tag(out[:limit], self.name)
