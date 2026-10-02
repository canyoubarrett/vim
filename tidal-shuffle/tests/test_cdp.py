"""Tests for the CDP driver using a scripted fake TIDAL page."""

import json
import re

import pytest

from tidal_shuffle.tidal.cdp import CdpError, CdpNowPlaying, TidalCdp, _parse_clock


class FakePage:
    """Simulates the parts of the TIDAL web player our JS touches."""

    def __init__(self):
        self.path = "/home"
        self.rows = {}            # path -> list of track ids rendered
        self.playing_id = None
        self.playing = False
        self.title = None
        self.artists = []
        self.times = []
        self.fail_click = False
        self.evals = []

    def evaluate(self, js, timeout=10.0):
        self.evals.append(js)
        if js.strip() == "location.pathname":
            return self.path
        if "history.pushState" in js:
            m = re.search(r"const target = '(/track/\d+)'", js)
            target = m.group(1)
            if self.path == target:
                return "already"
            self.path = target
            return "pushed"
        if "rows.some(r => r.querySelector(S.row_play))" in js:
            rows = self.rows.get(self.path, [])
            if not rows:
                return False
            m = re.search(r'const want = "(/track/\d+)"', js)
            if m and not any(f"/track/{r}" == m.group(1) for r in rows):
                return "other"
            return True
        if "rows.find(r => r.innerHTML.includes(want" in js:
            if self.fail_click:
                return ""
            m = re.search(r"const want = '/track/(\d+)'", js)
            tid = m.group(1)
            rows = self.rows.get(self.path, [])
            if tid in rows:
                self.playing_id, self.playing = tid, True
                return "row"
            if rows and self.path == f"/track/{tid}":
                self.playing_id, self.playing = rows[0], True
                return "first-row"
            return ""
        if "return {title, artists, id, playing, paused, times" in js:
            return {"title": self.title, "artists": self.artists, "id": self.playing_id,
                    "playing": self.playing, "paused": (self.playing_id is not None and not self.playing),
                    "times": self.times, "path": self.path, "hasFooter": True}
        if "const label =" in js:
            return True
        if "buttonLabels" in js:
            return {"path": self.path, "counts": {"row": len(self.rows.get(self.path, []))}}
        raise AssertionError("unexpected js: " + js[:80])

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t
    def sleep(self, s):
        self.t += s


def make(page=None, alive=True, targets=None, clock=None):
    page = page or FakePage()
    clock = clock or Clock()
    def http_get(url, timeout):
        if not alive:
            raise OSError("refused")
        if url.endswith("/json/version"):
            return json.dumps({"Browser": "Chrome/120", "Protocol-Version": "1.3"})
        if url.endswith("/json"):
            return json.dumps(targets if targets is not None else [
                {"type": "background_page", "url": "chrome-extension://x", "webSocketDebuggerUrl": "ws://bg"},
                {"type": "page", "url": "https://desktop.tidal.com/home", "webSocketDebuggerUrl": "ws://page"},
            ])
        raise AssertionError(url)
    cdp = TidalCdp(http_get=http_get, connect=lambda ws: page, sleep=clock.sleep, clock=clock, log=lambda m: None)
    return cdp, page, clock


def test_parse_clock():
    assert _parse_clock("3:05") == 185.0
    assert _parse_clock("1:02:03") == 3723.0
    assert _parse_clock("abc") is None


def test_alive_and_target_selection():
    cdp, page, _ = make()
    assert cdp.alive() is True
    assert cdp.page_ws_url() == "ws://page"
    dead, _, _ = make(alive=False)
    assert dead.alive() is False
    with pytest.raises(CdpError):
        dead.targets()


def test_now_playing_parses_footer():
    cdp, page, _ = make()
    page.title, page.artists, page.playing_id, page.playing, page.times = "Song", ["A", "B"], "123", True, ["1:10", "3:40"]
    np = cdp.now_playing()
    assert isinstance(np, CdpNowPlaying)
    assert (np.title, np.artist, np.artists, np.track_id, np.playing) == ("Song", "A", ["A", "B"], "123", True)
    assert (np.position, np.duration) == (70.0, 220.0)
    page.title, page.playing_id = None, None
    assert cdp.now_playing() is None


def test_play_track_happy_path():
    cdp, page, clock = make()
    page.rows["/track/555"] = ["555", "556"]
    out = cdp.play_track("555", verify_timeout=5)
    assert out.ok and out.method == "row" and out.observed_id == "555"
    assert page.path == "/track/555"


def test_play_track_when_rows_never_load():
    cdp, page, clock = make()
    out = cdp.play_track("777", verify_timeout=2, prepare_timeout=3)
    assert not out.ok and "did not load" in out.detail
    assert clock.t >= 3


def test_play_track_wrong_track_reported():
    cdp, page, clock = make()
    page.rows["/track/1"] = ["2"]  # page renders but not our row; first-row fallback plays 2
    out = cdp.play_track("1", verify_timeout=2, prepare_timeout=3)
    assert not out.ok and out.observed_id == "2" and out.method == "first-row"


def test_play_track_no_button():
    cdp, page, clock = make()
    page.rows["/track/9"] = ["9"]
    page.fail_click = True
    out = cdp.play_track("9", verify_timeout=1)
    assert not out.ok and "no play button" in out.detail


def test_evaluate_reconnects_once():
    class Flaky:
        def __init__(self):
            self.n = 0
        def evaluate(self, js, timeout=10.0):
            self.n += 1
            if self.n == 1:
                raise OSError("socket closed")
            return "/home"
        def close(self):
            pass
    flaky = Flaky()
    clock = Clock()
    cdp = TidalCdp(http_get=lambda u, t: json.dumps([{"type": "page", "url": "https://desktop.tidal.com/", "webSocketDebuggerUrl": "ws://p"}]),
                   connect=lambda ws: flaky, sleep=clock.sleep, clock=clock)
    assert cdp.current_path() == "/home"
    assert flaky.n == 2


def test_launch_waits_for_endpoint():
    state = {"alive": False, "running": True, "popen": [], "runs": []}
    def http_get(url, timeout):
        if state["alive"]:
            return json.dumps({"Browser": "x"})
        raise OSError
    def run(cmd, **kw):
        state["runs"].append(cmd)
        if cmd[0] == "pgrep":
            class R: returncode = 0 if state["running"] else 1
            return R()
        if cmd[0] == "osascript":
            state["running"] = False
            class R: returncode = 0
            return R()
        raise AssertionError(cmd)
    def popen(cmd, **kw):
        state["popen"].append(cmd)
        state["alive"] = True
    clock = Clock()
    cdp = TidalCdp(http_get=http_get, run=run, popen=popen, sleep=clock.sleep, clock=clock, port=9333)
    import shutil
    if shutil.which("pgrep") is None:
        pytest.skip("pgrep not available")
    assert cdp.launch() is True
    assert any("--remote-debugging-port=9333" in c for c in state["popen"][0])
    assert any(c[0] == "osascript" for c in state["runs"])


def test_prepared_page_is_not_waited_for_again():
    cdp, page, clock = make()
    page.rows["/track/1"] = ["2"]  # the row has no self-link: "other"
    assert cdp.prepare("1", timeout=6) is True
    before = clock.t
    out = cdp.play_track("1", verify_timeout=2)
    assert clock.t - before <= 2.0 + 0.5  # only the 2 s verification, no 3 s grace wait first
    assert out.method == "first-row"


def test_missing_reply_is_not_resent():
    class NoReply:
        def __init__(self): self.sent = 0
        def evaluate(self, js, timeout=10.0):
            self.sent += 1
            raise CdpError("Runtime.evaluate: no reply (timed out)")
        def close(self): pass
    conn = NoReply()
    clock = Clock()
    cdp = TidalCdp(http_get=lambda u, t: json.dumps([{"type": "page", "url": "https://desktop.tidal.com/", "webSocketDebuggerUrl": "ws://p"}]),
                   connect=lambda ws: conn, sleep=clock.sleep, clock=clock)
    with pytest.raises(CdpError):
        cdp.click_play_for_track("5")
    assert conn.sent == 1
