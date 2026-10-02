import json

import httpx
import pytest

from tidal_shuffle.models import Seed
from tidal_shuffle.sources.lastfm import LastfmError, LastfmSource


def make_source(handler, key="k"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LastfmSource(key, client=client, sleep=lambda s: None)


def similar_payload(n=5):
    return {"similartracks": {"track": [
        {"name": f"Sim {i}", "artist": {"name": f"Art {i}"}, "match": 1 - i * 0.1, "duration": 200 + i, "mbid": "", "url": "u"}
        for i in range(n)]}}


def test_unavailable_without_key():
    src = LastfmSource(None)
    assert src.available()[0] is False
    assert LastfmSource("your_lastfm_api_key").available()[0] is False
    assert LastfmSource("abc").available() == (True, "")


def test_similar_tracks_parse_and_rank():
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=similar_payload())
    src = make_source(handler)
    cands = src.candidates([Seed("Song", "Artist")], 10)
    assert calls[0]["method"] == "track.getSimilar"
    assert calls[0]["track"] == "Song" and calls[0]["artist"] == "Artist" and calls[0]["autocorrect"] == "1"
    assert [c.title for c in cands] == [f"Sim {i}" for i in range(5)]
    assert cands[0].score == pytest.approx(1.0) and cands[0].rank == 0 and cands[0].source == "lastfm"
    assert cands[1].duration == 201.0
    # cached: a second call does not hit the network again
    src.candidates([Seed("Song", "Artist")], 10)
    assert len(calls) == 1


def test_expands_to_similar_artists_when_sparse():
    def handler(request):
        m = request.url.params["method"]
        if m == "track.getSimilar":
            return httpx.Response(200, json={"similartracks": {"track": []}})
        if m == "artist.getSimilar":
            return httpx.Response(200, json={"similarartists": {"artist": [{"name": "Other", "match": "0.9"}, {"name": "Third", "match": "0.5"}]}})
        if m == "artist.getTopTracks":
            a = request.url.params["artist"]
            return httpx.Response(200, json={"toptracks": {"track": [{"name": f"{a} hit {i}", "artist": {"name": a}, "listeners": "10"} for i in range(3)]}})
        raise AssertionError(m)
    src = make_source(handler)
    cands = src.candidates([Seed("Obscure", "Nobody")], 12)
    assert cands and all(c.artist in ("Other", "Third", "Nobody") for c in cands)
    assert cands[0].artist == "Other"  # higher artist match ranks first


def test_single_item_responses_are_lists():
    def handler(request):
        return httpx.Response(200, json={"similartracks": {"track": {"name": "Only", "artist": {"name": "One"}, "match": 0.7}}})
    src = make_source(handler)
    cands = src.similar_tracks("S", "A", 5)
    assert [c.title for c in cands] == ["Only"]


def test_not_found_error_code_is_empty_not_fatal():
    def handler(request):
        if request.url.params["method"] == "track.getSimilar":
            return httpx.Response(200, json={"error": 6, "message": "Track not found"})
        return httpx.Response(200, json={})
    src = make_source(handler)
    assert src.candidates([Seed("S", "A")], 5) == []


def test_other_api_errors_raise():
    def handler(request):
        return httpx.Response(200, json={"error": 10, "message": "Invalid API key"})
    src = make_source(handler)
    with pytest.raises(LastfmError, match="Invalid API key"):
        src.similar_tracks("S", "A", 5)


def test_rate_limit_retries_then_succeeds():
    n = {"calls": 0}
    def handler(request):
        n["calls"] += 1
        if n["calls"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=similar_payload(2))
    src = make_source(handler)
    assert len(src.similar_tracks("S", "A", 5)) == 2
    assert n["calls"] == 2


def test_duration_units():
    assert LastfmSource._duration({"duration": "245"}) == 245.0
    assert LastfmSource._duration({"duration": "245000"}) == 245.0
    assert LastfmSource._duration({"duration": "0"}) is None
    assert LastfmSource._duration({}) is None
