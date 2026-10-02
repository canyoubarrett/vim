from types import SimpleNamespace

from tidal_shuffle.models import Seed
from tidal_shuffle.sources.tidal_radio import TidalRadioSource
from tests.test_tidal_catalog import fake_track


class FakeCatalog:
    def __init__(self, radio, artist_radio=None, fail_radio=False):
        self.radio, self.artist_radio, self.fail_radio = radio, artist_radio or [], fail_radio
    def resolve_seed(self, seed):
        seed.tidal_id = "1"
        return seed
    def raw_track(self, tid):
        from tidalapi.exceptions import MetadataNotAvailable
        def get_track_radio(limit=100):
            if self.fail_radio:
                raise MetadataNotAvailable("no radio")
            return self.radio[:limit]
        artist = SimpleNamespace(get_radio=lambda limit=100: self.artist_radio[:limit])
        return SimpleNamespace(id=tid, get_track_radio=get_track_radio, artist=artist)


def test_unavailable_without_catalog():
    assert TidalRadioSource(None).available()[0] is False


def test_radio_candidates_are_tagged_with_tidal_ids():
    radio = [fake_track(1, "Seed", ["S"]), fake_track(2, "R1", ["A"], isrc="X"), fake_track(3, "R2", ["B"], available=False), fake_track(4, "R3", ["C"])]
    src = TidalRadioSource(FakeCatalog(radio))
    cands = src.candidates([Seed("Seed", "S")], 10)
    assert [c.title for c in cands] == ["R1", "R3"]
    assert cands[0].tidal_id == "2" and cands[0].isrc == "X" and cands[0].source == "tidal-radio" and cands[0].rank == 0
    assert cands[0].score > cands[1].score


def test_falls_back_to_artist_radio():
    src = TidalRadioSource(FakeCatalog([], artist_radio=[fake_track(9, "AR", ["Z"])], fail_radio=True))
    cands = src.candidates([Seed("Seed", "S")], 10)
    assert [c.title for c in cands] == ["AR"]


def test_unresolvable_seed_returns_empty():
    class Cat(FakeCatalog):
        def resolve_seed(self, seed):
            return seed
    assert TidalRadioSource(Cat([])).candidates([Seed("Seed", "S")], 5) == []
