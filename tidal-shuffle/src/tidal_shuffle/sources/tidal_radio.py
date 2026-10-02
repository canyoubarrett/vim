"""TIDAL's own track radio as a source (no extra accounts needed)."""

from __future__ import annotations

from typing import Optional, Sequence

from ..models import Candidate, Seed
from ..tidal.catalog import TidalCatalog, to_track
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

    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        from tidalapi.exceptions import TidalAPIError

        assert self.catalog is not None
        seed = seeds[0]
        if not seed.tidal_id:
            seed = self.catalog.resolve_seed(seed)
        if not seed.tidal_id:
            return []
        raw = self.catalog.raw_track(seed.tidal_id)
        tracks = []
        try:
            tracks = raw.get_track_radio(limit=max(limit, self.limit))
        except TidalAPIError:
            tracks = []
        if not tracks:
            try:
                artist = getattr(raw, "artist", None)
                if artist is not None and hasattr(artist, "get_radio"):
                    tracks = artist.get_radio(limit=max(limit, self.limit))
            except TidalAPIError:
                tracks = []
        out: list[Candidate] = []
        n = max(1, len(tracks))
        for i, t in enumerate(tracks):
            tt = to_track(t)
            if not tt.available or tt.id == str(seed.tidal_id):
                continue
            out.append(Candidate(
                title=tt.title, artist=tt.artist, album=tt.album, duration=tt.duration, isrc=tt.isrc,
                popularity=tt.popularity, tidal_id=tt.id, score=1.0 - 0.6 * (i / n),
            ))
        return tag(out[:limit], self.name)
