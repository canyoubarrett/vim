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
    def play_track(self, tid, verify_timeout=8.0):
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


def test_cdp_failure_falls_through_to_deep_link_with_play_param():
    cfg = load_config(overrides={"player": {"play_strategy": "auto"}}, env={}).player
    calls = []
    p = TidalPlayer(cfg, FakeCdp(outcome=PlayOutcome(False, "row", "9", "wrong track")), run=runner(calls))
    out = p.play(TidalTrack(id="3", title="T", artist="A"))
    assert not out.ok and calls[-1][-1] == "tidal://track/3"
    cfg2 = load_config(overrides={"player": {"play_strategy": "open-url-play"}}, env={}).player
    p2 = TidalPlayer(cfg2, FakeCdp(), run=runner(calls))
    p2.play(TidalTrack(id="4", title="T", artist="A"))
    assert calls[-1][-1] == "tidal://track/4?play=true"


def test_cdp_exception_is_contained():
    cfg = load_config(env={}).player
    calls = []
    p = TidalPlayer(cfg, FakeCdp(outcome=CdpError("socket")), run=runner(calls))
    out = p.play(TidalTrack(id="5", title="T", artist="A"))
    assert not out.ok and calls
