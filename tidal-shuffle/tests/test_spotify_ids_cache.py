import json

import httpx

from tidal_shuffle.cache import DiskCache
from tidal_shuffle.models import Seed
from tidal_shuffle.sources.odesli import OdesliMapper
from tidal_shuffle.sources.spotify_ids import ListenBrainzSpotifyIds, OdesliSpotifyIds, SpotifyApiIds


def lb(handler):
    return ListenBrainzSpotifyIds(client=httpx.Client(transport=httpx.MockTransport(handler)),
                                  sleep=lambda s: None, clock=lambda: 0.0)


def test_listenbrainz_posts_metadata_and_reads_first_id():
    bodies = []
    def handler(request):
        assert request.method == "POST" and request.url.path == "/spotify-id-from-metadata/json"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=[{"artist_name": "M83", "release_name": "Hurry Up", "track_name": "Midnight City",
                                          "spotify_track_ids": ["1eyzqe2QqGZUmfcPZtrIyt", "other"]}])
    look = lb(handler)
    assert look.lookup(Seed("Midnight City", "M83", album="Hurry Up, We're Dreaming")) == "1eyzqe2QqGZUmfcPZtrIyt"
    assert bodies[0] == [{"artist_name": "M83", "release_name": "Hurry Up, We're Dreaming", "track_name": "Midnight City"}]
    look.lookup(Seed("Midnight City", "M83", album="Hurry Up, We're Dreaming"))
    assert len(bodies) == 1  # cached


def test_listenbrainz_retries_with_simplified_names_then_gives_up():
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content)[0])
        return httpx.Response(200, json=[{"spotify_track_ids": []}])
    assert lb(handler).lookup(Seed("Song (feat. X) - Remastered", "A, B", album="Al")) is None
    assert bodies[1] == {"artist_name": "A", "release_name": "", "track_name": "Song"}


def test_listenbrainz_disables_itself_when_refused():
    look = lb(lambda r: httpx.Response(401, json={"code": 401, "error": "token required"}))
    assert look.lookup(Seed("S", "A")) is None
    ok, reason = look.available()
    assert not ok and "401" in reason


def test_odesli_needs_a_key_and_dies_on_deprecation():
    assert OdesliMapper().available()[0] is False
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(401, json={"statusCode": 401, "code": "PUBLIC_API_ACCESS_DEPRECATED"})
    m = OdesliMapper(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                     sleep=lambda s: None, clock=lambda: 0.0)
    assert m.available()[0]
    assert OdesliSpotifyIds(m).lookup(Seed("S", "A", tidal_id="5")) is None
    assert calls[0]["key"] == "k" and not m.available()[0]


def test_spotify_api_adapter():
    class Api:
        def available(self): return True, ""
        def find_track(self, seed): return {"id": "abc"}
    assert SpotifyApiIds(Api()).lookup(Seed("S", "A")) == "abc"


def test_disk_cache_ttl_and_persistence(tmp_path):
    t = {"now": 1000.0}
    c = DiskCache(tmp_path / "c.json", ttl=100, clock=lambda: t["now"])
    c.set("a", {"x": 1})
    c.flush()
    assert DiskCache(tmp_path / "c.json", ttl=100, clock=lambda: t["now"]).get("a") == {"x": 1}
    t["now"] = 1200.0
    assert c.get("a") is None
    assert DiskCache(tmp_path / "c.json", ttl=100, clock=lambda: t["now"]).get("a") is None


def test_disk_cache_caps_entries(tmp_path):
    t = {"now": 0.0}
    c = DiskCache(tmp_path / "c.json", ttl=1e9, max_entries=3, clock=lambda: t["now"])
    for i in range(5):
        t["now"] += 1
        c.set(str(i), i)
    assert [c.get(str(i)) for i in range(5)] == [None, None, 2, 3, 4]
