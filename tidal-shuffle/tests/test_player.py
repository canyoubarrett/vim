from tidal_shuffle.config import load_config
from tidal_shuffle.models import TidalTrack
from tidal_shuffle.tidal.cdp import CdpError, PlayOutcome
from tidal_shuffle.tidal.player import TidalPlayer


class FakeCdp:
    def __init__(self, alive=True, outcome=None, launch_ok=True):
        self._alive, self.outcome, self.launch_ok = alive, outcome or PlayOutcome(True, "row", "1"), launch_ok
        self.launched = 0
    def alive(self): return self._alive
    def launch(self, relaunch_if_running=True):
        self.launched += 1
        self._alive = self.launch_ok
        return self.launch_ok
    def prepare(self, tid, timeout=15.0): return True
    def has_luna(self): return False
    def play_track(self, tid, verify_timeout=8.0, title=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome
    def press(self, c): return True


def runner(calls):
    def run(cmd, **kw):
        calls.append(cmd)
        class R: returncode = 0
        return R()
    return run


def test_cdp_path():
    cfg = load_config(env={}).player
    cdp = FakeCdp()
    p = TidalPlayer(cfg, cdp)
    assert p.ensure_ready() == "cdp"
    out = p.play(TidalTrack(id="1", title="T", artist="A"))
    assert out.ok and out.method == "cdp/row"


def test_relaunch_when_not_alive_then_fallback_to_url():
    cfg = load_config(env={}).player
    cdp = FakeCdp(alive=False, launch_ok=False)
    calls = []
    p = TidalPlayer(cfg, cdp, run=runner(calls))
    assert p.ensure_ready() == "open-url" and cdp.launched == 1
    out = p.play(TidalTrack(id="7", title="T", artist="A"))
    assert not out.ok and out.method == "open-url" and calls[-1] == ["open", "-g", "tidal://track/7"]


def test_relaunch_succeeds():
    cfg = load_config(env={}).player
    cdp = FakeCdp(alive=False, launch_ok=True)
    assert TidalPlayer(cfg, cdp).ensure_ready() == "cdp"


def test_cdp_strategy_raises_when_unreachable():
    cfg = load_config(overrides={"player": {"play_strategy": "cdp", "auto_relaunch": False}}, env={}).player
    import pytest
    with pytest.raises(RuntimeError, match="remote-debugging-port"):
        TidalPlayer(cfg, FakeCdp(alive=False)).ensure_ready()


def test_cdp_failure_reports_without_opening_deep_links():
    cfg = load_config(overrides={"player": {"play_strategy": "auto"}}, env={}).player
    calls = []
    p = TidalPlayer(cfg, FakeCdp(outcome=PlayOutcome(False, "row", "9", "wrong track")), run=runner(calls))
    out = p.play(TidalTrack(id="3", title="T", artist="A"))
    assert not out.ok and out.method == "cdp/row" and calls == []
    cfg2 = load_config(overrides={"player": {"play_strategy": "open-url-play"}}, env={}).player
    p2 = TidalPlayer(cfg2, FakeCdp(), run=runner(calls))
    p2.play(TidalTrack(id="4", title="T", artist="A"))
    assert calls[-1][-1] == "tidal://track/4?play=true"


def test_cdp_exception_is_contained():
    cfg = load_config(env={}).player
    calls = []
    p = TidalPlayer(cfg, FakeCdp(outcome=CdpError("socket")), run=runner(calls))
    out = p.play(TidalTrack(id="5", title="T", artist="A"))
    assert not out.ok and out.method == "cdp" and "socket" in out.detail


class FakeLuna:
    def __init__(self, alive=True, current="9"):
        self._alive, self.current, self.calls = alive, current, []
    def alive(self): return self._alive
    def play_next(self, tid): self.calls.append(("play_next", tid)); self.current = tid; return True
    def play_now(self, tid): self.calls.append(("play_now", tid)); self.current = tid; return True
    def current_track_id(self): return self.current


def test_luna_api_is_preferred_and_never_relaunches_tidal():
    cfg = load_config(env={}).player
    cdp = FakeCdp(alive=False, launch_ok=True)
    luna = FakeLuna()
    p = TidalPlayer(cfg, cdp, luna=luna, sleep=lambda s: None, clock=lambda: 0.0)
    assert p.ensure_ready() == "luna-api" and cdp.launched == 0
    assert p.supports_queue() and p.queue_next(TidalTrack(id="4", title="T", artist="A"))
    out = p.play(TidalTrack(id="5", title="T", artist="A"))
    assert out.ok and out.method == "luna-api" and luna.calls[-1] == ("play_now", "5")


def test_luna_verify_times_out_with_fake_clock():
    cfg = load_config(overrides={"player": {"verify_seconds": 2}}, env={}).player
    t = {"now": 0.0}
    def sleep(s): t["now"] += s
    luna = FakeLuna(current="other")
    luna.play_now = lambda tid: True
    p = TidalPlayer(cfg, FakeCdp(alive=False), luna=luna, sleep=sleep, clock=lambda: t["now"])
    out = p.play(TidalTrack(id="5", title="T", artist="A"))
    assert not out.ok and t["now"] >= 2


class QueueCdp(FakeCdp):
    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)
        self.asked = []
        self.next_id = None
    def store_queue_next(self, tid):
        self.asked.append(tid)
        res = self.answers.pop(0)
        if res == "ok":
            self.next_id = tid
        return res
    def store_next_id(self):
        return self.next_id


def test_stock_tidal_queue_is_used_and_checked():
    cfg = load_config(overrides={"player": {"tidal_queue": True}}, env={}).player
    cdp = QueueCdp(["ok"])
    p = TidalPlayer(cfg, cdp)
    p.ensure_ready()
    t = TidalTrack(id="4", title="T", artist="A")
    assert p.supports_queue() and p.queue_next(t)
    assert p.queue_still_next(t)
    cdp.next_id = "99"  # something else got in front of it
    assert not p.queue_still_next(t)


def test_unreadable_queue_is_given_up_at_once():
    cfg = load_config(overrides={"player": {"tidal_queue": True}}, env={}).player
    logs = []
    cdp = QueueCdp(["unreadable"])
    p = TidalPlayer(cfg, cdp, log=logs.append)
    p.ensure_ready()
    assert not p.queue_next(TidalTrack(id="4", title="T", artist="A"))
    assert not p.supports_queue() and cdp.asked == ["4"]
    assert any("not usable" in m for m in logs)


def test_queue_that_does_not_take_twice_is_given_up():
    cfg = load_config(overrides={"player": {"tidal_queue": True}}, env={}).player
    cdp = QueueCdp(["not-next", "not-next"])
    p = TidalPlayer(cfg, cdp, log=lambda m: None)
    p.ensure_ready()
    t = TidalTrack(id="4", title="T", artist="A")
    assert not p.queue_next(t) and p.supports_queue()
    assert not p.queue_next(t) and not p.supports_queue()


def test_stock_tidal_queue_is_off_by_default():
    cfg = load_config(env={}).player
    cdp = QueueCdp(["ok"])
    p = TidalPlayer(cfg, cdp)
    p.ensure_ready()
    assert not p.supports_queue()
    assert not p.queue_next(TidalTrack(id="4", title="T", artist="A")) and cdp.asked == []
