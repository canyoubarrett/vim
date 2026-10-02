import json
import urllib.error

from tidal_shuffle.tidal.luna import LunaApi


class FakeServer:
    def __init__(self, alive=True, state=None):
        self.alive = alive
        self.state = state or {"playing": True, "track": {"id": 42, "title": "T"}}
        self.posts = []

    def __call__(self, req, timeout):
        if not self.alive:
            raise urllib.error.URLError("refused")
        if req.get_method() == "GET":
            return json.dumps(self.state).encode()
        body = json.loads(req.data.decode()) if req.data else {}
        path = req.full_url.rsplit("/", 1)[-1]
        self.posts.append((path, body))
        if path == "playNext":
            self.state["track"] = {"id": int(body["itemId"])}
        return json.dumps({"type": "ok", "action": path}).encode()


def test_alive_state_and_current_track():
    srv = FakeServer()
    api = LunaApi(opener=srv)
    assert api.alive() and api.current_track_id() == "42"
    assert LunaApi(opener=FakeServer(alive=False)).alive() is False


def test_play_now_sequence_and_headers():
    srv = FakeServer()
    api = LunaApi(token="secret", opener=srv)
    assert api.play_now("7") is True
    assert [p for p, _ in srv.posts] == ["playNext", "next", "resume"]
    assert srv.posts[0][1] == {"itemId": "7"}
    assert api.current_track_id() == "7"


def test_error_responses_are_false():
    class Err(FakeServer):
        def __call__(self, req, timeout):
            if req.get_method() == "POST":
                return json.dumps({"type": "error", "error": "nope"}).encode()
            return super().__call__(req, timeout)
    api = LunaApi(opener=Err())
    assert api.play_next("1") is False
    assert LunaApi(opener=FakeServer(alive=False)).play_next("1") is False
