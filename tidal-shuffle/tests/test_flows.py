"""Shuffle flows: audio features, scoring, picking, and switching while running."""

import random

import httpx

from tidal_shuffle.config import load_config
from tidal_shuffle.engine import Engine
from tidal_shuffle.features import Features, ReccoBeats
from tidal_shuffle.flows import FLOWS, UNKNOWN_FIT, score
from tidal_shuffle.history import HistoryStore
from tidal_shuffle.models import Candidate, Seed
from tidal_shuffle.picker import PickContext, order_candidates
from tidal_shuffle.sources.base import StaticSource
from tests.test_engine import FakeCatalog

SID = "0VjIjW4GlUZAMYd2vXMi3b"
SID2 = "1VjIjW4GlUZAMYd2vXMi3c"


def test_reccobeats_parses_maps_and_caches(tmp_path):
    calls = []
    def handler(req):
        calls.append(req.url.params["ids"])
        return httpx.Response(200, json={"content": [
            {"id": "uuid-1", "href": f"https://open.spotify.com/track/{SID}", "energy": 0.81, "valence": 0.4,
             "danceability": 0.6, "acousticness": 0.02, "instrumentalness": 0.1, "tempo": 128.0}]})
    rb = ReccoBeats(httpx.Client(transport=httpx.MockTransport(handler)), cache_path=tmp_path / "f.json")
    got = rb.features([SID, SID2])
    assert set(got) == {SID} and got[SID].energy == 0.81 and got[SID].tempo == 128.0
    assert calls == [f"{SID},{SID2}"]
    again = ReccoBeats(httpx.Client(transport=httpx.MockTransport(handler)), cache_path=tmp_path / "f.json")
    assert again.features([SID, SID2])[SID].energy == 0.81 and len(calls) == 1   # both from the cache ("unknown" too)


def test_reccobeats_down_is_quiet_and_retried_later(tmp_path):
    t = {"now": 0.0}
    def boom(req):
        raise httpx.ConnectError("refused")
    logs = []
    rb = ReccoBeats(httpx.Client(transport=httpx.MockTransport(boom)), log=logs.append, clock=lambda: t["now"])
    assert rb.features([SID]) == {} and any("unavailable" in m for m in logs)
    rb.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{"energy": 0.5}])))
    assert rb.features([SID]) == {}            # still cooling down
    t["now"] = 700.0
    assert rb.features([SID])[SID].energy == 0.5   # positional match when the answer has no ids


def f(energy, **kw):
    return Features(energy=energy, **kw)


def test_rising_falling_steady_targets():
    cands = {"a": f(0.3), "b": f(0.56), "c": f(0.9), "d": None}
    r = score("rising", cands, f(0.5), None)
    assert abs(r.target - 0.56) < 1e-9 and max(r.fits, key=r.fits.get) == "b" and r.fits["d"] == UNKNOWN_FIT
    r = score("falling", cands, f(0.36), None)
    assert abs(r.target - 0.30) < 1e-9 and max(r.fits, key=r.fits.get) == "a"
    r = score("steady", cands, f(0.3), f(0.9))           # the first song set the level
    assert r.target == 0.9 and max(r.fits, key=r.fits.get) == "c"
    r = score("steady", cands, f(0.3), f(0.9), level=0.55)   # unless a level is given
    assert max(r.fits, key=r.fits.get) == "b"
    assert score("rising", cands, f(0.95), None).target == 0.96 and score("falling", cands, f(0.05), None).target == 0.08


def test_soundscape_and_vibe_compare_the_sound():
    acoustic = f(0.3, acousticness=0.9, instrumentalness=0.6, valence=0.3, tempo=90)
    electronic = f(0.3, acousticness=0.05, instrumentalness=0.6, valence=0.3, tempo=90)
    cands = {"acoustic": f(0.35, acousticness=0.85, instrumentalness=0.5, valence=0.35, tempo=95), "electronic": electronic}
    r = score("soundscape", cands, None, acoustic)
    assert r.fits["acoustic"] > r.fits["electronic"] * 2     # same energy, different texture
    r = score("vibe", {"sad": f(0.3, valence=0.1), "happy": f(0.3, valence=0.9)}, f(0.32, valence=0.15), None)
    assert r.fits["sad"] > r.fits["happy"]


def test_no_features_steps_aside():
    r = score("rising", {"a": None, "b": None}, None, None)
    assert r.fits == {} and "following the song radio" in r.note
    assert score("radio", {"a": f(0.5)}, f(0.5), None).fits == {}


def test_picker_prefers_the_fit_over_the_radio_order():
    cands = [Candidate(f"S{i}", f"A{i}", score=1 - i / 20, rank=i, duration=200) for i in range(10)]
    fit = {c.key: (1.0 if c.title == "S7" else 0.05) for c in cands}
    for strategy in ("top", "weighted", "random", "discovery"):
        firsts = [order_candidates(cands, PickContext(fit=fit), strategy, random.Random(s))[0][0].title for s in range(40)]
        assert firsts.count("S7") >= 30, (strategy, firsts.count("S7"))
    ordered, _ = order_candidates(cands, PickContext(), "top")
    assert ordered[0].title == "S0"                       # no flow: radio order as before


class FakeFeatures:
    def __init__(self, table):
        self.table = table
    def features(self, ids):
        return {i: self.table[i] for i in ids if i in self.table}


def test_engine_rising_flow_picks_the_next_step_up(tmp_path):
    cands = [Candidate(f"Song {i}", f"Band {i}", score=1 - i / 20, duration=200, spotify_id=f"sp{i}") for i in range(8)]
    energies = {f"sp{i}": f(0.1 + i * 0.1) for i in range(8)}
    energies["seed"] = f(0.45)
    cfg = load_config(overrides={"shuffle": {"flow": "rising", "strategy": "top", "lookahead": 1}}, env={})
    eng = Engine(cfg, [StaticSource(cands, name="spotify-app")], FakeCatalog(), HistoryStore(tmp_path / "h.json"),
                 rng=random.Random(0), log=lambda m: None, features=FakeFeatures(energies))
    seed = Seed("Seed", "Seed Artist")
    seed.spotify_id = "seed"
    plan = eng.plan(seed, anchor=seed)
    assert plan.primary.track.title == "Song 4"          # 0.5: the step above 0.45
    assert abs(plan.flow_target - 0.51) < 1e-9 and any("rising" in n for n in plan.notes)
    assert plan.primary.candidate.extra["energy"] == 0.5


def test_engine_without_features_service_is_plain_radio(tmp_path):
    cands = [Candidate(f"Song {i}", f"Band {i}", score=1 - i / 20, duration=200, spotify_id=f"sp{i}") for i in range(4)]
    cfg = load_config(overrides={"shuffle": {"flow": "rising", "strategy": "top", "lookahead": 1}}, env={})
    eng = Engine(cfg, [StaticSource(cands, name="spotify-app")], FakeCatalog(), HistoryStore(tmp_path / "h.json"),
                 rng=random.Random(0), log=lambda m: None)
    assert eng.plan(Seed("Seed", "X")).primary.track.title == "Song 0"


def test_presets_and_flag():
    assert load_config(preset="warm-up", env={}).shuffle.flow == "rising"
    assert load_config(preset="wind-down", env={}).shuffle.flow == "falling"
    assert load_config(preset="soundscape", env={}).shuffle.flow == "soundscape"
    chill = load_config(preset="chill", env={}).shuffle
    assert chill.flow == "steady" and chill.energy == 0.3
    assert set(FLOWS) == {"radio", "rising", "falling", "steady", "soundscape", "vibe"}


def test_flow_key_cycles_and_replans(tmp_path):
    from tests.test_loop import build, cands as loop_cands
    loop, world, clock, logs, history = build(tmp_path, loop_cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(12):
        loop.step(); clock.sleep(1)
    assert loop.state.plan is not None
    loop.post("flow")
    loop.handle_commands()
    assert loop.config.shuffle.flow == "rising" and any(m.startswith("flow: rising") for m in logs)
    assert loop.state.plan is not None and loop.state.plan.flow == "rising"   # planned again, the new way
    for _ in range(5):
        loop.post("flow")
    loop.handle_commands()
    assert loop.config.shuffle.flow == "radio"            # wrapped around
