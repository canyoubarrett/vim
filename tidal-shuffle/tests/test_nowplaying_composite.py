from tidal_shuffle.models import NowPlaying, TIDAL_BUNDLE_ID
from tidal_shuffle.nowplaying.base import CompositeBackend, StaticBackend
from tidal_shuffle.tidal.cdp import CdpNowPlaying


class FakeCdp:
    def __init__(self, np=None, fail=False):
        self.np, self.fail = np, fail
    def alive(self):
        return True
    def now_playing(self):
        if self.fail:
            raise RuntimeError("boom")
        return self.np


def test_media_only_when_no_cdp():
    media = StaticBackend([NowPlaying("T", "A", bundle_id=TIDAL_BUNDLE_ID, elapsed=1.0, timestamp=5.0)])
    comp = CompositeBackend(media, None)
    np = comp.read()
    assert np.title == "T" and np.elapsed == 1.0


def test_cdp_identity_with_media_timing_when_same_track():
    media = StaticBackend([NowPlaying("Song", "Artist", album="Al", duration=200.0, elapsed=10.0, timestamp=5.0, playing=True, bundle_id=TIDAL_BUNDLE_ID, source="media-control")])
    cdp = FakeCdp(CdpNowPlaying(title="Song", artist="Artist", artists=["Artist"], track_id="42", playing=True, position=12.0, duration=201.0))
    np = CompositeBackend(media, cdp, wall=lambda: 100.0).read()
    assert np.tidal_id == "42" and np.is_tidal and np.elapsed == 10.0 and np.timestamp == 5.0 and np.duration == 200.0
    assert np.album == "Al" and np.source == "cdp+media-control"


def test_cdp_wins_when_media_shows_another_app():
    media = StaticBackend([NowPlaying("Ad", "Spotify", bundle_id="com.spotify.client", elapsed=3.0, timestamp=1.0)])
    cdp = FakeCdp(CdpNowPlaying(title="Song", artist="Artist", artists=["Artist"], track_id="42", playing=True, position=30.0, duration=200.0))
    np = CompositeBackend(media, cdp, wall=lambda: 100.0).read()
    assert np.title == "Song" and np.tidal_id == "42" and np.elapsed == 30.0 and np.timestamp == 100.0 and np.duration == 200.0


def test_cdp_failure_falls_back_to_media():
    media = StaticBackend([NowPlaying("T", "A", bundle_id=TIDAL_BUNDLE_ID)])
    np = CompositeBackend(media, FakeCdp(fail=True)).read()
    assert np.title == "T"
    assert CompositeBackend(None, FakeCdp(None)).read() is None


def test_availability_reasons():
    class Dead:
        name = "dead"
        def available(self): return False, "missing"
        def read(self): return None
    class DeadCdp(FakeCdp):
        def alive(self): return False
    ok, reason = CompositeBackend(Dead(), DeadCdp()).available()
    assert not ok and "media-control" in reason
    assert CompositeBackend(Dead(), FakeCdp()).available()[0]
