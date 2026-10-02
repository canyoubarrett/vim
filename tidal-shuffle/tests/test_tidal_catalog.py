from types import SimpleNamespace
from pathlib import Path

import pytest

from tidal_shuffle.models import Candidate, Seed
from tidal_shuffle.tidal.catalog import TidalCatalog, TidalLoginRequired, connect_session, to_track


def fake_track(id, title, artists, duration=200, isrc=None, available=True, version=None, popularity=50, album="Album"):
    arts = [SimpleNamespace(name=a) for a in artists]
    return SimpleNamespace(id=id, name=title, title=title, full_name=(f"{title} ({version})" if version else title),
                           version=version, artist=arts[0], artists=arts, album=SimpleNamespace(name=album),
                           duration=duration, isrc=isrc, explicit=False, available=available, popularity=popularity)


class FakeSession:
    def __init__(self, search_results=None, isrc_results=None, tracks=None):
        self.search_results = search_results or {}
        self.isrc_results = isrc_results or {}
        self.tracks = tracks or {}
        self.search_calls = []

    def search(self, query, models=None, limit=50, offset=0):
        self.search_calls.append(query)
        for key, hits in self.search_results.items():
            if key.lower() in query.lower():
                return {"tracks": hits}
        return {"tracks": []}

    def get_tracks_by_isrc(self, isrc):
        from tidalapi.exceptions import ObjectNotFound
        if isrc in self.isrc_results:
            return self.isrc_results[isrc]
        raise ObjectNotFound

    def track(self, track_id):
        from tidalapi.exceptions import ObjectNotFound
        if str(track_id) in self.tracks:
            return self.tracks[str(track_id)]
        raise ObjectNotFound


def test_to_track_handles_version_and_unavailable():
    t = to_track(fake_track(1, "Song", ["A", "B"], version="Live", popularity=-1, available=False))
    assert t.title == "Song (Live)" and t.artists == ["A", "B"] and t.artist == "A"
    assert t.popularity is None and t.available is False and t.id == "1"


def test_find_prefers_isrc_and_caches():
    s = FakeSession(isrc_results={"XX1": [fake_track(10, "Song", ["Artist"], isrc="XX1")]})
    cat = TidalCatalog(s)
    track, score = cat.find("Song", "Artist", isrc="XX1")
    assert track.id == "10" and score >= 0.9
    assert s.search_calls == []
    cat.find("Song", "Artist", isrc="XX1")
    assert s.search_calls == []


def test_find_by_search_scores_and_rejects_live_version():
    s = FakeSession(search_results={"midnight city": [
        fake_track(1, "Midnight City", ["M83"], duration=243, version="Live"),
        fake_track(2, "Midnight City", ["M83"], duration=244),
        fake_track(3, "Midnight City", ["Karaoke Universe"], duration=244),
    ]})
    cat = TidalCatalog(s)
    track, score = cat.find("Midnight City", "M83", duration=243)
    assert track.id == "2" and score > 0.9


def test_find_returns_none_below_threshold():
    s = FakeSession(search_results={"hello": [fake_track(1, "Goodbye", ["Someone Else"])]})
    cat = TidalCatalog(s)
    track, score = cat.find("Hello", "Adele")
    assert track is None and score < 0.72


def test_find_falls_back_to_full_query():
    s = FakeSession(search_results={"song (feat. x) artist": [fake_track(5, "Song", ["Artist"])]})
    cat = TidalCatalog(s)
    track, _ = cat.find("Song (feat. X)", "Artist")
    assert track.id == "5"
    assert len(s.search_calls) == 2


def test_match_and_resolve_seed_fill_ids():
    s = FakeSession(search_results={"song": [fake_track(7, "Song", ["Artist"], isrc="I7", duration=180)]}, tracks={"9": fake_track(9, "Other", ["O"])})
    cat = TidalCatalog(s)
    c = Candidate("Song", "Artist")
    t = cat.match(c)
    assert t.id == "7" and c.tidal_id == "7" and c.isrc == "I7" and c.duration == 180 and c.match_score > 0.9
    seed = cat.resolve_seed(Seed("Song", "Artist"))
    assert seed.tidal_id == "7" and seed.isrc == "I7"
    c2 = Candidate("Other", "O", tidal_id="9")
    assert cat.match(c2).id == "9"
    assert cat.get_track("404") is None


def test_rate_limit_retry(monkeypatch):
    from tidalapi.exceptions import TooManyRequests
    calls = {"n": 0}
    class S(FakeSession):
        def search(self, query, models=None, limit=50, offset=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TooManyRequests(retry_after=1)
            return {"tracks": [fake_track(1, "Song", ["Artist"])]}
    waits = []
    cat = TidalCatalog(S(), sleep=waits.append)
    track, _ = cat.find("Song", "Artist")
    assert track.id == "1" and waits == [1.0]


class FakeLoginSession:
    def __init__(self, logged_in=False, file_ok=True):
        self.logged_in = logged_in
        self.file_ok = file_ok
        self.saved = None
        self.loaded = None
    def load_session_from_file(self, path):
        self.loaded = path
        if self.file_ok:
            self.logged_in = True
    def check_login(self):
        return self.logged_in
    def login_oauth(self):
        link = SimpleNamespace(verification_uri_complete="link.tidal.com/ABC", expires_in=300)
        self.logged_in = True
        return link, SimpleNamespace(result=lambda: None)
    def save_session_to_file(self, path):
        self.saved = path
        Path(path).write_text('{"token": "%s"}' % getattr(self, "access_token", ""))


def test_connect_session_loads_existing(tmp_path):
    f = tmp_path / "sess.json"
    f.write_text("{}")
    sess = FakeLoginSession()
    out = connect_session(f, printer=lambda m: None, session_factory=lambda: sess)
    assert out is sess and sess.loaded == f and sess.saved is None


def test_connect_session_interactive_login_and_save(tmp_path):
    f = tmp_path / "sub" / "sess.json"
    sess = FakeLoginSession(file_ok=False)
    msgs = []
    connect_session(f, printer=msgs.append, session_factory=lambda: sess)
    assert sess.saved == f and any("link.tidal.com/ABC" in m for m in msgs)


def test_connect_session_non_interactive_raises(tmp_path):
    with pytest.raises(TidalLoginRequired):
        connect_session(tmp_path / "x.json", interactive=False, session_factory=lambda: FakeLoginSession(file_ok=False))


def test_track_radio_uses_shell_without_metadata_fetch():
    class RadioSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.fetched = []
        def track(self, track_id=None, with_album=False):
            if track_id is None:
                from types import SimpleNamespace
                shell = SimpleNamespace(id=None)
                shell.get_track_radio = lambda limit=100: [fake_track(5, "R", ["A"]), fake_track(6, "V", ["B"])][:limit]
                return shell
            return super().track(track_id)
        def artist(self, artist_id=None):
            from types import SimpleNamespace
            shell = SimpleNamespace(id=None)
            shell.get_radio = lambda limit=100: [fake_track(8, "AR", ["C"])]
            sim = SimpleNamespace(id="s1", get_top_tracks=lambda limit=5: [fake_track(9, "Top", ["D"])])
            shell.get_similar = lambda: [sim]
            return shell
    cat = TidalCatalog(RadioSession())
    assert [t.title for t in cat.track_radio("1", limit=1)] == ["R"]
    assert [t.title for t in cat.artist_radio("2")] == ["AR"]
    assert [t.title for t in cat.similar_artists_top_tracks("2")] == ["Top"]


def test_retry_on_server_error_and_not_on_client_error():
    import requests
    calls = {"n": 0}
    class S(FakeSession):
        def search(self, query, models=None, limit=50, offset=0):
            calls["n"] += 1
            resp = SimpleNamespace(status_code=503 if calls["n"] == 1 else 400)
            if calls["n"] <= 2:
                raise requests.HTTPError("boom", response=resp)
            return {"tracks": []}
    waits = []
    cat = TidalCatalog(S(), sleep=waits.append)
    with pytest.raises(requests.HTTPError):
        cat.search_tracks("x")
    assert calls["n"] == 2 and waits == [1.0]


def test_persist_session_only_when_token_changed(tmp_path):
    from tidal_shuffle.tidal.catalog import persist_session
    f = tmp_path / "sess.json"
    f.write_text("{}")
    sess = FakeLoginSession()
    sess.access_token = "old"
    connect_session(f, printer=lambda m: None, session_factory=lambda: sess)
    assert persist_session(sess) is False
    sess.access_token = "new"
    assert persist_session(sess) is True
    assert '"new"' in f.read_text() and not f.with_suffix(".tmp").exists()
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert persist_session(sess) is False


def test_transient_search_failure_is_not_cached_as_no_match():
    import requests
    n = {"c": 0}
    class Flaky(FakeSession):
        def search(self, query, models=None, limit=50, offset=0):
            n["c"] += 1
            if n["c"] <= 4:  # one search = first try + three retries
                raise requests.ConnectionError("reset")
            return {"tracks": [fake_track(1, "Song", ["Artist"])]}
    cat = TidalCatalog(Flaky(), sleep=lambda s: None)
    assert cat.find("Song", "Artist")[0] is None
    assert cat.find("Song", "Artist")[0].id == "1"


def test_rate_limited_track_lookup_is_not_cached_as_missing():
    from tidalapi.exceptions import TooManyRequests
    class Limited(FakeSession):
        limited = True
        def track(self, track_id):
            if self.limited:
                raise TooManyRequests(retry_after=120)
            return fake_track(int(track_id), "T", ["A"])
    s = Limited()
    cat = TidalCatalog(s, sleep=lambda x: None)
    assert cat.get_track("123") is None
    s.limited = False
    assert cat.get_track("123").id == "123"


def test_live_and_studio_versions_get_separate_cache_entries():
    s = FakeSession(search_results={"blue monday": [fake_track(1, "Blue Monday", ["New Order"], version="Live"),
                                                    fake_track(2, "Blue Monday", ["New Order"])]})
    cat = TidalCatalog(s)
    assert cat.find("Blue Monday (Live)", "New Order")[0].id == "1"
    assert cat.find("Blue Monday", "New Order")[0].id == "2"


def test_tidalapi_requests_get_a_default_timeout():
    import requests
    from tidal_shuffle.tidal.catalog import add_default_timeout
    sess = SimpleNamespace(request_session=requests.Session())
    add_default_timeout(sess, timeout=7.5)
    adapter = sess.request_session.get_adapter("https://api.tidal.com/v1/search")
    seen = {}
    def fake_send(self, request, **kwargs):
        seen.update(kwargs)
        raise requests.ConnectionError("stop")
    import types
    adapter.__class__.__bases__[0].send, original = fake_send, adapter.__class__.__bases__[0].send
    try:
        with pytest.raises(requests.ConnectionError):
            sess.request_session.get("https://api.tidal.com/v1/search")
    finally:
        adapter.__class__.__bases__[0].send = original
    assert seen["timeout"] == 7.5
