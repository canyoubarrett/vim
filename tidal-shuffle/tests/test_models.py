from tidal_shuffle.models import Candidate, NowPlaying, Seed, TidalTrack, VibeParams, TIDAL_BUNDLE_ID


def test_position_extrapolates_from_timestamp_when_playing():
    np = NowPlaying("T", "A", duration=200.0, elapsed=10.0, timestamp=1000.0, playing=True, playback_rate=1.0)
    assert np.position_at(1005.0) == 15.0
    assert np.remaining_at(1005.0) == 185.0


def test_position_frozen_when_paused():
    np = NowPlaying("T", "A", duration=200.0, elapsed=10.0, timestamp=1000.0, playing=False)
    assert np.position_at(1050.0) == 10.0


def test_position_clamped_to_duration():
    np = NowPlaying("T", "A", duration=20.0, elapsed=10.0, timestamp=1000.0, playing=True)
    assert np.position_at(2000.0) == 20.0
    assert np.remaining_at(2000.0) == 0.0


def test_position_without_timestamp_or_elapsed():
    assert NowPlaying("T", "A", elapsed=5.0).position_at(99.0) == 5.0
    assert NowPlaying("T", "A").position_at(99.0) is None
    assert NowPlaying("T", "A", elapsed=5.0).remaining_at(99.0) is None


def test_same_track_uses_normalised_keys():
    a = NowPlaying("Déjà Vu", "Beyoncé", bundle_id=TIDAL_BUNDLE_ID)
    b = NowPlaying("deja vu", "beyonce")
    assert a.same_track(b)
    assert a.is_tidal and not b.is_tidal
    assert not a.same_track(None)


def test_seed_from_now_playing_and_track_urls():
    seed = Seed.from_now_playing(NowPlaying("T", "A", album="Al", duration=1.0))
    assert (seed.title, seed.artist, seed.album, seed.duration) == ("T", "A", "Al", 1.0)
    t = TidalTrack(id="123", title="T", artist="A")
    assert t.deep_link == "tidal://track/123"
    assert t.url.endswith("/track/123")
    assert Candidate("T", "A").key == t.key


def test_vibe_params_to_api():
    v = VibeParams(energy=0.5, min_popularity=10, genres=["rock"])
    assert v.to_api_params() == {"target_energy": 0.5, "min_popularity": 10}
    assert not v.is_empty()
    assert VibeParams().is_empty()
