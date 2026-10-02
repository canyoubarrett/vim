import json
import subprocess

import httpx

from tidal_shuffle import activity
from tidal_shuffle.models import TIDAL_BUNDLE_ID
from tidal_shuffle.nowplaying.media import (MediaControlBackend, NowPlayingCliBackend, detect_backend,
                                            parse_media_control, parse_nowplaying_cli, parse_timestamp)
from tidal_shuffle.sources.odesli import OdesliMapper


# ---- odesli ---------------------------------------------------------------
def odesli_payload():
    return {
        "entityUniqueId": "TIDAL_SONG::123",
        "linksByPlatform": {
            "spotify": {"url": "https://open.spotify.com/track/abc123", "entityUniqueId": "SPOTIFY_SONG::abc123"},
            "tidal": {"url": "https://listen.tidal.com/track/123", "entityUniqueId": "TIDAL_SONG::123"},
        },
        "entitiesByUniqueId": {
            "SPOTIFY_SONG::abc123": {"id": "abc123", "title": "T", "artistName": "A", "platforms": ["spotify"]},
            "TIDAL_SONG::123": {"id": "123", "title": "T", "artistName": "A", "platforms": ["tidal"]},
        },
    }


def test_odesli_maps_both_ways_and_throttles():
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=odesli_payload())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    waits = []
    t = {"now": 0.0}
    m = OdesliMapper(client=client, sleep=waits.append, clock=lambda: t["now"], min_interval=5)
    assert m.spotify_id_for_tidal("123") == "abc123"
    assert calls[0]["url"] == "https://tidal.com/browse/track/123" and calls[0]["userCountry"] == "US"
    assert m.tidal_id_for_spotify("abc123") == "123"
    assert waits and waits[0] == 5  # second call throttled
    m.spotify_id_for_tidal("123")  # cached
    assert len(calls) == 2


def test_odesli_falls_back_to_url_parsing_and_handles_errors():
    payload = {"linksByPlatform": {"spotify": {"url": "https://open.spotify.com/track/zzz?si=1"}}, "entitiesByUniqueId": {}}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    m = OdesliMapper(client=client, sleep=lambda s: None, clock=lambda: 0.0)
    assert m.spotify_id_for_tidal("1") == "zzz"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404, text="no")))
    m = OdesliMapper(client=client, sleep=lambda s: None, clock=lambda: 0.0)
    assert m.spotify_id_for_tidal("2") is None


# ---- timestamp parsing ----------------------------------------------------
def test_parse_timestamp_variants():
    assert parse_timestamp(1700000000) == 1700000000.0
    assert parse_timestamp(1700000000123) == 1700000000.123
    assert parse_timestamp("1700000000.5") == 1700000000.5
    assert abs(parse_timestamp("2023-11-14T22:13:20Z") - 1700000000.0) < 1
    assert abs(parse_timestamp("2023-11-14 22:13:20 +0000") - 1700000000.0) < 1
    assert parse_timestamp("null") is None and parse_timestamp(None) is None
    assert parse_timestamp("garbage") is None


# ---- media-control ----------------------------------------------------------
def test_parse_media_control_payload():
    payload = {"bundleIdentifier": TIDAL_BUNDLE_ID, "playing": True, "title": "Song", "artist": "Artist", "album": "Al",
               "duration": 243.2, "elapsedTime": 12.5, "timestamp": "2023-11-14T22:13:20Z", "playbackRate": 1}
    np = parse_media_control(payload)
    assert np.is_tidal and np.title == "Song" and np.duration == 243.2 and np.elapsed == 12.5 and np.playing is True
    assert abs(np.timestamp - 1700000000.0) < 1 and np.source == "media-control"
    assert abs(np.position_at(1700000010.0) - 22.5) < 0.01


def test_parse_media_control_micros_and_null():
    payload = {"bundleIdentifier": TIDAL_BUNDLE_ID, "playing": False, "title": "Song", "artist": "A",
               "durationMicros": 243200000, "elapsedTimeMicros": 12500000, "timestampEpochMicros": 1700000000250000, "playbackRate": 1}
    np = parse_media_control(payload)
    assert np.duration == 243.2 and np.elapsed == 12.5 and abs(np.timestamp - 1700000000.25) < 1e-6
    assert np.playing is False and np.playback_rate == 0.0 and np.position_at(1700000100.0) == 12.5
    assert parse_media_control(None) is None  # `media-control get` prints the literal null


def test_parse_media_control_stream_line_and_missing_fields():
    line = {"type": "data", "diff": False, "payload": {"bundleIdentifier": "com.spotify.client", "playing": False, "title": "Ad"}}
    np = parse_media_control(line)
    assert np.bundle_id == "com.spotify.client" and np.playing is False and not np.is_tidal
    assert parse_media_control({}) is None
    np2 = parse_media_control({"title": "X", "bundleIdentifier": TIDAL_BUNDLE_ID, "elapsedTime": 3, "playbackRate": 0}, now=100.0)
    assert np2.timestamp == 100.0 and np2.playing is False


def test_media_control_backend_runs_binary(tmp_path):
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"bundleIdentifier": TIDAL_BUNDLE_ID, "playing": True, "title": "S", "artist": "A"}), stderr="")
    b = MediaControlBackend(binary="/fake/media-control", run=run)
    assert b.read().title == "S" and calls[0][1:] == ["get", "--micros", "--no-artwork"]
    assert b.available()[0] is False  # fake binary does not exist
    def bad(cmd, **kw):
        raise OSError("boom")
    assert MediaControlBackend(binary="/fake", run=bad).read() is None


# ---- nowplaying-cli ----------------------------------------------------------
def test_parse_nowplaying_cli_lines():
    out = "Song\nArtist\nnull\n243.2\n12.5\n1\n2023-11-14 22:13:20 +0000\nnull\n"
    np = parse_nowplaying_cli(out)
    assert np.title == "Song" and np.artist == "Artist" and np.album is None and np.duration == 243.2
    assert np.playing is True and np.is_tidal and np.source == "nowplaying-cli"
    assert parse_nowplaying_cli("null\nnull\n") is None
    assert parse_nowplaying_cli("Song\nArtist\n", assume_tidal=False).bundle_id is None


def test_parse_nowplaying_cli_json_with_bundle_id():
    out = json.dumps({"title": "Ad", "artist": "", "album": None, "duration": 30, "elapsedTime": 0, "playbackRate": 1,
                      "timestamp": None, "clientBundleIdentifier": "com.spotify.client"}, indent=2)
    np = parse_nowplaying_cli(out)
    assert np.bundle_id == "com.spotify.client" and not np.is_tidal and np.timestamp is not None
    out2 = json.dumps({"title": "S", "artist": "A", "clientBundleIdentifier": None})
    assert parse_nowplaying_cli(out2).is_tidal


def test_nowplaying_cli_backend_falls_back_to_line_format():
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        if "--json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="Usage: nowplaying-cli ...", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="S\nA\n\n200\n1\n1\n\n\n", stderr="")
    b = NowPlayingCliBackend(binary="/fake/nowplaying-cli", run=run)
    activity._busy_until.clear()
    assert b.read().title == "S" and b._json_supported is False
    b.read()
    assert not any("--json" in c for c in calls[2:])


def test_nowplaying_cli_backend_respects_busy_flag(monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr(activity, "_clock", lambda: t["now"])
    activity._busy_until.clear()
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="S\nA\n\n200\n1\n1\n\n", stderr="")
    b = NowPlayingCliBackend(binary="/fake/nowplaying-cli", run=run)
    assert b.read().title == "S"
    with activity.busy("spotify-harvest", seconds=30, linger=3):
        assert b.read() is None
    assert b.read() is None          # lingers 3 s
    t["now"] = 10.0
    assert b.read().title == "S"
    activity._busy_until.clear()


def test_detect_backend_prefers_media_control_or_none(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert detect_backend("auto") is None
    assert detect_backend("nowplaying-cli").name == "nowplaying-cli"
