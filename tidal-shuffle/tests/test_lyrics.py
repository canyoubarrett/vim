"""Lyrics: LRC parsing, sources and the background service."""

import json
import time

import httpx

from tidal_shuffle.lyrics import Lyrics, LyricsService, LrclibLyrics, TidalLyrics, parse_lrc

LRC = """[ar:M83]
[ti:Midnight City]
[offset:+500]
[00:12.50]Waiting in a car
[00:15.0][01:15.000]Waiting for a ride in the dark
[00:20.12]<00:20.12>The <00:20.50>night <00:21.00>city
[00:25.00]
"""


def test_parse_lrc():
    lines = parse_lrc(LRC)
    assert [(round(l.time, 2), l.text) for l in lines] == [
        (12.0, "Waiting in a car"), (14.5, "Waiting for a ride in the dark"), (19.62, "The night city"),
        (24.5, ""), (74.5, "Waiting for a ride in the dark")]


def test_index_at():
    lyr = Lyrics(lines=parse_lrc("[00:10.00]a\n[00:20.00]b\n[00:30.00]c"), synced=True)
    assert lyr.index_at(5) == -1
    assert lyr.index_at(9.8) == 0          # shown a hair early
    assert lyr.index_at(25) == 1
    assert lyr.index_at(300) == 2
    assert Lyrics(lines=lyr.lines, synced=False).index_at(25) == -1


def lrclib(handler):
    return LrclibLyrics(httpx.Client(transport=httpx.MockTransport(handler)))


def test_lrclib_exact_get():
    def handler(req):
        assert req.url.path == "/api/get"
        assert req.url.params["duration"] == "244"
        return httpx.Response(200, json={"trackName": "Midnight City", "artistName": "M83", "duration": 244,
                                         "instrumental": False, "syncedLyrics": "[00:01.00]hi", "plainLyrics": "hi"})
    lyr = lrclib(handler).fetch("Midnight City", "M83", "Hurry Up", 243.6, None)
    assert lyr.synced and lyr.lines[0].text == "hi" and lyr.source == "LRCLIB"


def test_lrclib_search_picks_the_right_recording():
    def handler(req):
        if req.url.path == "/api/get":
            return httpx.Response(404, json={"code": 404, "name": "TrackNotFound"})
        return httpx.Response(200, json=[
            {"trackName": "Them Changes (Live)", "artistName": "Buddy Miles", "duration": 400, "syncedLyrics": "[00:01.00]live"},
            {"trackName": "Them Changes", "artistName": "Thundercat", "duration": 188, "syncedLyrics": "[00:01.00]other"},
            {"trackName": "Them Changes", "artistName": "Buddy Miles", "duration": 196, "plainLyrics": "plain only"},
            {"trackName": "Them Changes", "artistName": "Buddy Miles", "duration": 197, "syncedLyrics": "[00:01.00]right"},
        ])
    lyr = lrclib(handler).fetch("Them Changes", "Buddy Miles", "Them Changes", 196.0, None)
    assert lyr.synced and lyr.lines[0].text == "right"


def test_lrclib_instrumental_and_nothing():
    lyr = lrclib(lambda r: httpx.Response(200, json=[{"trackName": "Intro", "artistName": "X", "duration": 60,
                                                         "instrumental": True}])).fetch("Intro", "X", None, 60, None)
    assert lyr.instrumental and not lyr.lines
    assert lrclib(lambda r: httpx.Response(200, json=[])).fetch("Nope", "Nobody", None, None, None) is None


class Raw:
    def __init__(self, subtitles, text):
        self.subtitles, self.text = subtitles, text
    def lyrics(self):
        if self.subtitles is None:
            raise RuntimeError("MetadataNotAvailable")
        return self


class Cat:
    def __init__(self, raw):
        self.raw = raw
    def raw_track(self, tid):
        return self.raw
    def find(self, title, artist, duration=None):
        class T: id = "77"
        return T(), 0.9


def test_tidal_lyrics_synced_plain_and_missing():
    assert TidalLyrics(Cat(Raw("[00:02.00]tidal", "tidal"))).fetch("a", "b", None, None, "5").synced
    plain = TidalLyrics(Cat(Raw("", "line one\nline two\n"))).fetch("a", "b", None, None, None)
    assert not plain.synced and [l.text for l in plain.lines] == ["line one", "line two"]
    assert TidalLyrics(Cat(Raw(None, None))).fetch("a", "b", None, None, "5") is None


class Src:
    def __init__(self, name, result, boom=False):
        self.name, self.result, self.boom, self.calls = name, result, boom, 0
    def fetch(self, *a):
        self.calls += 1
        if self.boom:
            raise RuntimeError("down")
        return self.result


def wait(svc, *args):
    for _ in range(100):
        r = svc.get(*args)
        if r != "pending":
            return r
        time.sleep(0.02)
    raise AssertionError("still pending")


def test_service_prefers_synced_and_caches(tmp_path):
    plain = Lyrics(lines=parse_lrc("") or [], synced=False, source="TIDAL")
    plain.lines = [type(parse_lrc("[00:01.00]x")[0])(None, "plain")]
    synced = Lyrics(lines=parse_lrc("[00:01.00]synced"), synced=True, source="LRCLIB")
    a, b = Src("tidal", plain), Src("lrclib", synced)
    svc = LyricsService([a, b], cache_path=tmp_path / "lyrics.json")
    assert svc.get("Song", "Artist") == "pending"
    got = wait(svc, "Song", "Artist")
    assert got.synced and got.lines[0].text == "synced"
    # from disk in a new service, no source asked
    c = Src("tidal", None)
    again = LyricsService([c], cache_path=tmp_path / "lyrics.json").get("Song", "Artist")
    assert again.synced and c.calls == 0


def test_service_none_found_is_remembered_but_failures_are_not(tmp_path):
    svc = LyricsService([Src("tidal", None)], cache_path=tmp_path / "l.json")
    assert wait(svc, "A", "B") is None
    assert json.loads((tmp_path / "l.json").read_text())
    svc2 = LyricsService([Src("lrclib", None, boom=True)], cache_path=tmp_path / "l2.json")
    assert wait(svc2, "C", "D") is None
    assert not (tmp_path / "l2.json").exists()


def test_lrclib_retries_with_a_plainer_title_for_synced_lyrics():
    asked = []
    def handler(req):
        if req.url.path == "/api/get":
            return httpx.Response(200, json={"trackName": "Song (2019 Remaster)", "artistName": "Band feat. Guest",
                                             "duration": 200, "plainLyrics": "only plain"})
        asked.append((req.url.params["track_name"], req.url.params["artist_name"]))
        if req.url.params["track_name"] == "Song":
            return httpx.Response(200, json=[{"trackName": "Song", "artistName": "Band", "duration": 201,
                                              "syncedLyrics": "[00:01.00]synced at last"}])
        return httpx.Response(200, json=[])
    lyr = lrclib(handler).fetch("Song (2019 Remaster)", "Band feat. Guest", "Album", 200.0, None)
    assert lyr.synced and lyr.lines[0].text == "synced at last"
    assert asked[-1] == ("Song", "Band")


def test_timings_from_two_sources_are_combined_when_they_agree():
    from tidal_shuffle.lyrics import Lyrics, merge_lyrics, parse_lrc

    a = Lyrics(lines=parse_lrc("[00:10.00]one two\n[00:20.00]three four\n[00:30.00]five six\n[00:40.00]seven"),
               synced=True, source="TIDAL")
    b = Lyrics(lines=parse_lrc("[00:10.40]One two\n[00:20.60]three four\n[00:30.20]five six\n[00:41.00]seven"),
               synced=True, source="LRCLIB")
    m = merge_lyrics([a, b])
    assert m.source == "TIDAL + LRCLIB" and [l.time for l in m.lines] == [10.2, 20.3, 30.1, 40.5]
    # another recording (a steady offset): one timing is kept, not averaged
    c = Lyrics(lines=parse_lrc("[00:15.00]one two\n[00:25.00]three four\n[00:35.00]five six\n[00:45.00]seven"),
               synced=True, source="LRCLIB")
    assert merge_lyrics([a, c]) is a
    # synced beats plain, whichever came first; plain only when nothing is synced
    plain = Lyrics(lines=[], synced=False, source="TIDAL")
    plain.lines = parse_lrc("[00:01.00]x")
    plain.synced = False
    assert merge_lyrics([plain, b]) is b
    assert merge_lyrics([plain]) is plain
    inst = Lyrics(lines=[], instrumental=True, source="LRCLIB")
    assert merge_lyrics([inst]) is inst and merge_lyrics([]) is None


def test_word_timing_is_taken_from_the_source_that_has_it():
    from tidal_shuffle.lyrics import Lyrics, merge_lyrics, parse_lrc

    a = Lyrics(lines=parse_lrc("[00:10.00]one two\n[00:20.00]three four\n[00:30.00]five six"), synced=True, source="TIDAL")
    b = Lyrics(lines=parse_lrc("[00:10.20]<00:10.20>one <00:10.90>two\n[00:20.20]three four\n[00:30.20]five six"),
               synced=True, source="LRCLIB")
    m = merge_lyrics([a, b])
    assert m.lines[0].words and m.lines[0].words[0] == (10.1, 0)
