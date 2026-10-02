from tidal_shuffle.models import Seed
from tidal_shuffle.sources.tidal_radio import TidalRadioSource
from tidal_shuffle.tidal.catalog import to_track
from tests.test_tidal_catalog import fake_track


class FakeCatalog:
    def __init__(self, radio, artist_radio=None, similar=None):
        self.radio, self._artist_radio, self.similar = radio, artist_radio or [], similar or []
        self.calls = []
    def resolve_seed(self, seed):
        seed.tidal_id = "1"
        return seed
    def get_track(self, tid):
        t = to_track(fake_track(int(tid), "Seed", ["S"]))
        t.artist_id = "77"
        return t
    def track_radio(self, tid, limit=50):
        self.calls.append(("track_radio", tid, limit))
        return [to_track(t) for t in self.radio[:limit]]
    def artist_radio(self, aid, limit=50):
        self.calls.append(("artist_radio", aid, limit))
        return [to_track(t) for t in self._artist_radio[:limit]]
    def similar_artists_top_tracks(self, aid, artists=5, per_artist=5):
        self.calls.append(("similar", aid))
        return [to_track(t) for t in self.similar]


def test_unavailable_without_catalog():
    assert TidalRadioSource(None).available()[0] is False


def test_radio_candidates_are_tagged_with_tidal_ids():
    radio = [fake_track(1, "Seed", ["S"]), fake_track(2, "R1", ["A"], isrc="X"), fake_track(3, "R2", ["B"], available=False), fake_track(4, "R3", ["C"])]
    cat = FakeCatalog(radio)
    src = TidalRadioSource(cat, limit=50)
    cands = src.candidates([Seed("Seed", "S")], 10)
    assert [c.title for c in cands] == ["R1", "R3"]
    assert cands[0].tidal_id == "2" and cands[0].isrc == "X" and cands[0].source == "tidal-radio" and cands[0].rank == 0
    assert cands[0].score > cands[1].score
    assert cat.calls == [("track_radio", "1", 50)]


def test_falls_back_to_artist_radio_then_similar():
    cat = FakeCatalog([], artist_radio=[fake_track(9, "AR", ["Z"])])
    cands = TidalRadioSource(cat).candidates([Seed("Seed", "S")], 10)
    assert [c.title for c in cands] == ["AR"]
    assert [c[0] for c in cat.calls] == ["track_radio", "artist_radio"]
    cat2 = FakeCatalog([], similar=[fake_track(11, "Sim", ["Q"])])
    cands2 = TidalRadioSource(cat2).candidates([Seed("Seed", "S")], 10)
    assert [c.title for c in cands2] == ["Sim"]


def test_unresolvable_seed_returns_empty():
    class Cat(FakeCatalog):
        def resolve_seed(self, seed):
            return seed
    assert TidalRadioSource(Cat([])).candidates([Seed("Seed", "S")], 5) == []
