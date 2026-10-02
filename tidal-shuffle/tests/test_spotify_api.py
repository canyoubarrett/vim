import json

import httpx
import pytest

from tidal_shuffle.models import Seed, VibeParams
from tidal_shuffle.sources.spotify_api import SpotifyApiSource, SpotifyAuthError


def sp_track(id, name, artist, artist_id="ar1", pop=50, isrc=None, dur=200000):
    return {"id": id, "type": "track", "name": name, "artists": [{"id": artist_id, "name": artist}],
            "album": {"name": "Al"}, "duration_ms": dur, "popularity": pop, "external_ids": ({"isrc": isrc} if isrc else {})}


class Server:
    """A tiny fake Spotify: configure which endpoints work."""

    def __init__(self, recs=True, related=True, radio=True, token_ok=True):
        self.recs, self.related, self.radio, self.token_ok = recs, related, radio, token_ok
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url, p = str(request.url), dict(request.url.params)
        if url.startswith("https://accounts.spotify.com/api/token"):
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}) if self.token_ok \
                else httpx.Response(400, json={"error": "invalid_client"})
        assert request.headers["Authorization"] == "Bearer tok"
        path = request.url.path
        if path == "/v1/search":
            q, typ = p["q"], p["type"]
            if typ == "track" and q.startswith("isrc:"):
                return httpx.Response(200, json={"tracks": {"items": [sp_track("seed", "Seed Song", "Seed Artist", isrc=q[5:])]}})
            if typ == "track" and "Seed Song" in q:
                return httpx.Response(200, json={"tracks": {"items": [sp_track("live", "Seed Song (Live)", "Seed Artist"), sp_track("seed", "Seed Song", "Seed Artist", isrc="ISRC1")]}})
            if typ == "track" and q.startswith("genre:"):
                return httpx.Response(200, json={"tracks": {"items": [sp_track(f"g{i}", f"Genre {i}", f"GA{i}") for i in range(4)]}})
            if typ == "playlist":
                if not self.radio:
                    return httpx.Response(200, json={"playlists": {"items": [None, {"id": "x", "name": "Seed Song Radio", "owner": {"id": "someone"}}]}})
                return httpx.Response(200, json={"playlists": {"items": [{"id": "pl1", "name": "Seed Song Radio", "owner": {"id": "spotify"}}]}})
            return httpx.Response(200, json={"tracks": {"items": []}})
        if path == "/v1/recommendations":
            if not self.recs:
                return httpx.Response(403, json={"error": {"status": 403}})
            return httpx.Response(200, json={"tracks": [sp_track(f"r{i}", f"Rec {i}", f"RA{i}", pop=90 - i) for i in range(5)]})
        if path == "/v1/playlists/pl1/tracks":
            return httpx.Response(200, json={"items": [{"track": sp_track("seed", "Seed Song", "Seed Artist")}] + [{"track": sp_track(f"p{i}", f"Radio {i}", f"PA{i}")} for i in range(4)]})
        if path == "/v1/artists/ar1/related-artists":
            if not self.related:
                return httpx.Response(404, json={"error": {"status": 404}})
            return httpx.Response(200, json={"artists": [{"id": "rel1", "name": "Rel One"}]})
        if path == "/v1/artists/rel1/top-tracks":
            return httpx.Response(200, json={"tracks": [sp_track(f"t{i}", f"Top {i}", "Rel One", "rel1") for i in range(3)]})
        if path == "/v1/artists/ar1/top-tracks":
            return httpx.Response(200, json={"tracks": [sp_track(f"own{i}", f"Own {i}", "Seed Artist") for i in range(3)]})
        if path == "/v1/artists/ar1":
            return httpx.Response(200, json={"id": "ar1", "genres": ["dream pop"]})
        return httpx.Response(404, json={"error": "nope"})


def make(server, **kw):
    client = httpx.Client(transport=httpx.MockTransport(server))
    return SpotifyApiSource("id", "secret", client=client, sleep=lambda s: None, now=lambda: 1000.0, **kw)


def test_availability():
    assert SpotifyApiSource(None, None).available()[0] is False
    assert SpotifyApiSource("your_spotify_client_id", "x").available()[0] is False
    assert make(Server()).available() == (True, "")


def test_recommendations_path_with_vibe():
    server = Server()
    src = make(server, vibe=VibeParams(energy=0.8, genres=["pop"]))
    seed = Seed("Seed Song", "Seed Artist")
    cands = src.candidates([seed], 10)
    assert [c.title for c in cands] == [f"Rec {i}" for i in range(5)]
    assert cands[0].spotify_id == "r0" and cands[0].source == "spotify-api" and cands[0].popularity == 90
    assert seed.spotify_id == "seed" and seed.isrc == "ISRC1"
    rec = [r for r in server.requests if r.url.path == "/v1/recommendations"][0]
    assert rec.url.params["seed_tracks"] == "seed" and rec.url.params["target_energy"] == "0.8" and rec.url.params["seed_genres"] == "pop"
    assert src.recommendations_available is True


def test_isrc_seed_lookup_is_used_first():
    server = Server()
    src = make(server)
    src.candidates([Seed("Seed Song", "Seed Artist", isrc="QQ1")], 5)
    search = [r for r in server.requests if r.url.path == "/v1/search"][0]
    assert search.url.params["q"] == "isrc:QQ1"


def test_falls_back_to_related_artists_when_recs_forbidden():
    src = make(Server(recs=False))
    cands = src.candidates([Seed("Seed Song", "Seed Artist")], 10)
    assert src.recommendations_available is False
    assert [c.title for c in cands][:3] == ["Top 0", "Top 1", "Top 2"]


def test_premium_required_disables_the_source():
    class Premium(Server):
        def __call__(self, request):
            if "api/token" in str(request.url):
                return super().__call__(request)
            return httpx.Response(403, json={"error": {"status": 403, "message": "Active premium subscription required for the owner of the app."}})
    src = make(Premium())
    assert src.candidates([Seed("Seed Song", "Seed Artist")], 5) == []
    ok, reason = src.available()
    assert not ok and "Premium" in reason


def test_genre_search_respects_the_ten_item_limit():
    server = Server(recs=False, related=False)
    src = make(server)
    src.candidates([Seed("Seed Song", "Seed Artist")], 30)
    limits = [int(r.url.params["limit"]) for r in server.requests if r.url.path == "/v1/search"]
    assert limits and max(limits) <= 10


def test_falls_back_to_related_artists_then_genre():
    src = make(Server(recs=False, radio=False))
    cands = src.candidates([Seed("Seed Song", "Seed Artist")], 10)
    assert [c.title for c in cands][:3] == ["Top 0", "Top 1", "Top 2"]
    src2 = make(Server(recs=False, radio=False, related=False))
    cands2 = src2.candidates([Seed("Seed Song", "Seed Artist")], 10)
    assert src2.related_available is False
    assert any(c.title.startswith("Genre") for c in cands2)


def test_auth_failure_marks_source_dead():
    src = make(Server(token_ok=False))
    assert src.candidates([Seed("Seed Song", "Seed Artist")], 5) == []
    ok, reason = src.available()
    assert ok is False and "auth failed" in reason


def test_token_is_cached_and_refreshed_on_401():
    server = Server()
    src = make(server)
    src.candidates([Seed("Seed Song", "Seed Artist")], 5)
    token_calls = [r for r in server.requests if "api/token" in str(r.url)]
    assert len(token_calls) == 1
    src.candidates([Seed("Seed Song", "Seed Artist")], 5)  # cached results, no new token
    assert len([r for r in server.requests if "api/token" in str(r.url)]) == 1


def test_short_rate_limit_pauses_the_api_temporarily():
    t = {"now": 1000.0}
    class Limited(Server):
        limited = True
        def __call__(self, request):
            if "api/token" not in str(request.url) and self.limited:
                return httpx.Response(429, headers={"Retry-After": "60"})
            return super().__call__(request)
    server = Limited()
    src = SpotifyApiSource("id", "secret", client=httpx.Client(transport=httpx.MockTransport(server)),
                           sleep=lambda s: None, now=lambda: t["now"])
    assert src.candidates([Seed("Seed Song", "Seed Artist")], 5) == []
    assert src.available()[0] is False
    t["now"] += 61
    server.limited = False
    assert src.available() == (True, "")
