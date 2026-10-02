import httpx

from tidal_shuffle.models import Seed
from tidal_shuffle.sources.deezer import DeezerSource


def dz_track(i, artist="Artist", artist_id=1, title=None, dur=200):
    return {"id": i, "title": title or f"Song {i}", "duration": dur, "rank": 100 - i,
            "artist": {"id": artist_id, "name": artist}, "album": {"title": "Album"}}


class Server:
    def __init__(self, radio_ok=True):
        self.radio_ok = radio_ok
        self.paths = []

    def __call__(self, request):
        self.paths.append(request.url.path + ("?" + str(request.url.query, "utf-8") if request.url.query else ""))
        p = request.url.path
        if p == "/track/isrc:ISRC1":
            return httpx.Response(200, json={"id": 7, "title": "Seed Song", "isrc": "ISRC1", "artist": {"id": 42, "name": "Seed Artist"}})
        if p.startswith("/track/isrc:"):
            return httpx.Response(200, json={"error": {"type": "DataException", "message": "no data", "code": 800}})
        if p == "/search":
            return httpx.Response(200, json={"data": [dz_track(7, "Seed Artist", 42, "Seed Song"), dz_track(8, "Other", 9, "Seed Song (Live)")]})
        if p == "/artist/42/radio":
            if not self.radio_ok:
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": [dz_track(7, "Seed Artist", 42, "Seed Song")] + [dz_track(i, f"R{i}", 100 + i) for i in range(1, 5)]})
        if p == "/artist/42/related":
            return httpx.Response(200, json={"data": [{"id": 500, "name": "Rel"}]})
        if p == "/artist/500/top":
            return httpx.Response(200, json={"data": [dz_track(i, "Rel", 500) for i in range(20, 23)]})
        return httpx.Response(404, json={"error": "nope"})


def make(server):
    return DeezerSource(client=httpx.Client(transport=httpx.MockTransport(server)), sleep=lambda s: None)


def test_isrc_first_then_radio():
    srv = Server()
    src = make(srv)
    seed = Seed("Seed Song", "Seed Artist", isrc="ISRC1")
    cands = src.candidates([seed], 10)
    assert srv.paths[0] == "/track/isrc:ISRC1"
    assert [c.title for c in cands] == ["Song 1", "Song 2", "Song 3", "Song 4"]  # seed removed
    assert cands[0].source == "deezer" and cands[0].duration == 200.0 and cands[0].score > cands[-1].score


def test_search_fallback_scores_and_sets_isrc():
    srv = Server()
    src = make(srv)
    seed = Seed("Seed Song", "Seed Artist")
    cands = src.candidates([seed], 10)
    assert any(p.startswith("/search?") for p in srv.paths)
    assert len(cands) == 4


def test_related_artists_when_radio_is_empty():
    srv = Server(radio_ok=False)
    cands = make(srv).candidates([Seed("Seed Song", "Seed Artist", isrc="ISRC1")], 10)
    assert [c.artist for c in cands] == ["Rel", "Rel", "Rel"]


def test_unknown_seed_gives_nothing():
    srv = Server()
    class S(Server):
        def __call__(self, request):
            if request.url.path == "/search":
                return httpx.Response(200, json={"data": []})
            return super().__call__(request)
    assert make(S()).candidates([Seed("Nope", "Nobody")], 5) == []


def test_disabled():
    assert DeezerSource(enabled=False).available()[0] is False
