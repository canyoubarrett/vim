"""A stand-in for ``tidalapi.Session`` backed by the end-to-end test catalog."""

from __future__ import annotations

import re
import unicodedata
from types import SimpleNamespace


def _norm(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


class FakeTrack:
    def __init__(self, session, data):
        self._session = session
        self.id = int(data["id"])
        self.name = self.title = data["title"]
        self.version = None
        self.full_name = data["title"]
        self.artist = SimpleNamespace(name=data["artist"], id=int(data["artist_id"]))
        self.artists = [self.artist]
        self.album = SimpleNamespace(name=data.get("album", ""), id=int(data.get("album_id", 1)))
        self.duration = int(data["duration"])
        self.isrc = data.get("isrc")
        self.explicit = False
        self.available = True
        self.popularity = data.get("popularity", 50)
        self._lyrics = data.get("lyrics")

    def lyrics(self):
        if not self._lyrics:
            raise LookupError("MetadataNotAvailable: no lyrics for this track")
        return SimpleNamespace(subtitles=self._lyrics, text="")

    def get_track_radio(self, limit=100):
        return self._session._radio(str(self.id), limit)


class Shell:
    def __init__(self, session, kind):
        self._session, self._kind, self.id = session, kind, None

    def get_track_radio(self, limit=100):
        return self._session._radio(str(self.id), limit)

    def get_radio(self, limit=100):
        return []

    def get_similar(self):
        return []


class FakeSession:
    def __init__(self, catalog: dict):
        self.catalog = catalog
        self.by_id = {t["id"]: t for t in catalog["tracks"]}
        self.user = SimpleNamespace(id=1)
        self.access_token = "fake"
        self.searches = []

    def check_login(self):
        return True

    def save_session_to_file(self, path):
        pass

    def search(self, query, models=None, limit=50, offset=0):
        self.searches.append(query)
        q = set(_norm(query))
        scored = []
        for t in self.catalog["tracks"]:
            words = set(_norm(t["title"] + " " + t["artist"]))
            overlap = len(q & words)
            if overlap:
                scored.append((-overlap, t["id"]))
        scored.sort()
        return {"tracks": [FakeTrack(self, self.by_id[i]) for _, i in scored[:limit]], "top_hit": None}

    def track(self, track_id=None, with_album=False):
        if track_id is None:
            return Shell(self, "track")
        from tidalapi.exceptions import ObjectNotFound

        data = self.by_id.get(str(track_id))
        if data is None:
            raise ObjectNotFound("Track not found")
        return FakeTrack(self, data)

    def artist(self, artist_id=None):
        return Shell(self, "artist")

    def get_tracks_by_isrc(self, isrc):
        from tidalapi.exceptions import ObjectNotFound

        hits = [FakeTrack(self, t) for t in self.catalog["tracks"] if t.get("isrc") == isrc]
        if not hits:
            raise ObjectNotFound
        return hits

    def _radio(self, tid, limit):
        ids = self.catalog.get("tidal_radio", {}).get(tid, [])
        return [FakeTrack(self, self.by_id[i]) for i in ids[:limit]]
