"""Loop tests with a fake clock, scripted now-playing and a fake player."""

import random

from tidal_shuffle.config import load_config
from tidal_shuffle.engine import Engine
from tidal_shuffle.history import HistoryStore
from tidal_shuffle.loop import ShuffleLoop
from tidal_shuffle.models import Candidate, NowPlaying, TidalTrack, TIDAL_BUNDLE_ID
from tidal_shuffle.sources.base import StaticSource
from tidal_shuffle.tidal.cdp import PlayOutcome
from tests.test_engine import FakeCatalog


class Clock:
    def __init__(self):
        self.mono = 1000.0
        self.wall = 50000.0
    def sleep(self, s):
        self.mono += s
        self.wall += s


class World:
    """Fake TIDAL: what macOS reports depends on wall time and what was played."""

    def __init__(self, clock, verify=True):
        self.clock = clock
        self.track = None          # (title, artist, duration, tidal_id)
        self.start_wall = None
        self.verify = verify
        self.played = []
        self.prepared = []
        self.stolen_until = None   # wall time until which another app owns now-playing
        self.playing = True

    def start(self, title, artist, duration, tidal_id=None):
        self.track = (title, artist, duration, tidal_id)
        self.start_wall = self.clock.wall

    # NowPlayingBackend
    name = "world"
    def available(self):
        return True, ""
    def read(self):
        if self.track is None:
            return None
        if self.stolen_until is not None and self.clock.wall < self.stolen_until:
            return NowPlaying("Ad", "Spotify", bundle_id="com.spotify.client")
        title, artist, duration, tid = self.track
        elapsed = self.clock.wall - self.start_wall
        if elapsed >= duration:
            # TIDAL auto-advances to an album track we did not choose
            self.start("Album Filler", "Someone", 200, "filler")
            return self.read()
        return NowPlaying(title, artist, duration=duration, elapsed=elapsed, timestamp=self.clock.wall,
                          playing=self.playing, bundle_id=TIDAL_BUNDLE_ID, tidal_id=tid)

    # TidalPlayer
    queue_supported = False
    queued = None
    def supports_queue(self):
        return self.queue_supported
    def queue_next(self, track):
        self.queued = track
        return True
    def prepare(self, track):
        self.prepared.append(track.id)
        return True
    def play(self, track):
        self.played.append(track.id)
        if self.verify:
            self.start(track.title, track.artist, track.duration or 180, track.id)
            return PlayOutcome(True, "cdp/row", track.id)
        return PlayOutcome(False, "open-url", None, "opened")
    def press(self, control):
        return True


def build(tmp_path, cands, overrides=None, verify=True):
    cfg = load_config(overrides=overrides, env={})
    clock = Clock()
    world = World(clock, verify=verify)
    history = HistoryStore(tmp_path / "h.json")
    src = StaticSource(cands, name="lastfm")
    engine = Engine(cfg, [src], FakeCatalog(), history, rng=random.Random(0), log=lambda m: None)
    logs = []
    loop = ShuffleLoop(cfg, engine, world, world, history, log=logs.append,
                       clock=lambda: clock.mono, wall=lambda: clock.wall, sleep=clock.sleep)
    return loop, world, clock, logs, history


def cands():
    return [Candidate("Next One", "Band A", score=0.9, duration=180),
            Candidate("Second", "Band B", score=0.8, duration=200),
            Candidate("Third", "Band C", score=0.7, duration=210)]


def test_full_cycle_plans_prepares_and_hands_off(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=60, tidal_id="seed")
    loop.run(max_iterations=200)
    assert world.played[:1] == ["t-Next One"]
    assert world.prepared[:1] == ["t-Next One"]
    assert history.has_played(tidal_id="t-Next One")
    assert any("now playing our pick" in m for m in logs)
    # hand-off happened near the end of the seed song, not at its start
    first_play_log = next(i for i, m in enumerate(logs) if m.startswith("▶ playing"))
    assert any("prepared" in m for m in logs[:first_play_log])


def test_handoff_timing_is_before_end(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}, "player": {"handoff_seconds": 3}})
    world.start("Seed Song", "Seed Artist", duration=90, tidal_id="seed")
    while not world.played:
        loop.step()
        clock.sleep(0.5)
    elapsed_at_handoff = clock.wall - 50000.0
    assert 85 <= elapsed_at_handoff <= 90.5


def test_user_skip_resets_plan_and_reseeds(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(10):
        loop.step(); clock.sleep(1)
    assert loop.state.plan is not None
    world.start("User Choice", "Someone Else", duration=300, tidal_id="user")
    loop.step()
    assert loop.state.plan is None
    assert loop.state.current.title == "User Choice"
    assert any("track changed" in m for m in logs)
    assert loop.state.anchor.title == "Seed Song"  # anchor stays with the session start


def test_now_playing_stolen_by_other_app_keeps_going(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=40, tidal_id="seed")
    loop.step(); clock.sleep(5); loop.step()
    assert loop.state.plan is not None
    world.stolen_until = clock.wall + 60  # Spotify owns now-playing through the end of the song
    for _ in range(100):
        loop.step(); clock.sleep(0.5)
        if world.played:
            break
    assert world.played == ["t-Next One"]  # handed off on the estimated remaining time


def test_backup_used_when_primary_fails(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    real_play = world.play
    def flaky(track):
        if track.id == "t-Next One":
            world.played.append(track.id)
            return PlayOutcome(False, "cdp", None, "no play button")
        return real_play(track)
    world.play = flaky
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="seed")
    for _ in range(200):
        loop.step(); clock.sleep(0.5)
        if len(world.played) >= 2:
            break
    loop.step()
    assert world.played[:2] == ["t-Next One", "t-Second"]
    assert loop.state.current.title == "Second"


def test_dry_run_plans_but_never_plays(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="seed")
    loop.run(dry_run=True, once=True, max_iterations=50)
    assert loop.state.plan is not None and world.played == []


def test_idle_then_play(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    delay = loop.step()
    assert delay == loop.config.player.idle_poll_interval
    assert any("waiting for TIDAL" in m for m in logs)
    world.start("Seed Song", "Seed Artist", duration=100, tidal_id="seed")
    loop.step()
    assert loop.state.current.title == "Seed Song"


def test_deep_link_fallback_is_verified_by_now_playing(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}}, verify=False)
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="seed")
    for _ in range(80):
        loop.step(); clock.sleep(0.5)
        if world.played:
            break
    assert world.played == ["t-Next One"]
    assert not history.has_played(tidal_id="t-Next One")  # not verified -> not recorded
    # the user presses play on the opened track
    world.start("Next One", "Band A", 180, "t-Next One")
    loop.step()
    assert any("now playing our pick" in m for m in logs)


def test_skip_now_plays_immediately(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    assert loop.skip_now() is True
    assert world.played == ["t-Next One"]


def test_paused_track_does_not_hand_off(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="seed")
    world.playing = False
    for _ in range(40):
        loop.step(); clock.sleep(1)
    assert world.played == []


def test_queue_mode_hands_pick_to_tidal_and_records_when_it_plays(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    world.start("Seed Song", "Seed Artist", duration=60, tidal_id="seed")
    for _ in range(12):
        loop.step(); clock.sleep(1)
    assert world.queued.id == "t-Next One"
    assert loop.state.expected.track.id == "t-Next One" and loop.state.queued is not None
    assert not history.has_played(tidal_id="t-Next One")
    # run to the end of the seed song: no hard hand-off happens in queue mode
    for _ in range(120):
        loop.step(); clock.sleep(0.5)
        if world.played:
            break
    assert world.played == []
    # TIDAL plays the queued track by itself
    world.start("Next One", "Band A", 180, "t-Next One")
    loop.step()
    assert history.has_played(tidal_id="t-Next One")
    assert any("now playing our pick" in m for m in logs)


def test_mixed_metadata_snapshot_is_debounced(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id=None)
    loop.step()
    assert loop.state.current.title == "Seed Song"
    # one bogus snapshot: new title, old artist (what TIDAL emits mid-transition)
    class Flicker:
        name = "flicker"
        def __init__(self, inner): self.inner, self.n = inner, 0
        def available(self): return True, ""
        def read(self):
            self.n += 1
            if self.n == 1:
                return NowPlaying("Other Song", "Seed Artist", duration=300, elapsed=1.0, timestamp=clock.wall, playing=True, bundle_id=TIDAL_BUNDLE_ID)
            return self.inner.read()
    loop.nowplaying = Flicker(world)
    loop.step(); clock.sleep(1); loop.step()
    assert loop.state.current.title == "Seed Song"
    assert loop.state.tracks_seen == 1


class SlowSource:
    """A source that blocks until the test releases it (like a long Spotify harvest)."""

    name = "slow"

    def __init__(self, cands):
        import threading
        self.cands = cands
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = 0

    def available(self):
        return True, ""

    def candidates(self, seeds, limit):
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        return [Candidate(**c.__dict__) for c in self.cands]


def build_bg(tmp_path, source):
    cfg = load_config(overrides={"shuffle": {"strategy": "top"}}, env={})
    clock = Clock()
    world = World(clock)
    history = HistoryStore(tmp_path / "h.json")
    engine = Engine(cfg, [source], FakeCatalog(), history, rng=random.Random(0), log=lambda m: None)
    logs = []
    loop = ShuffleLoop(cfg, engine, world, world, history, log=logs.append,
                       clock=lambda: clock.mono, wall=lambda: clock.wall, sleep=clock.sleep, background=True)
    return loop, world, clock, logs


def wait_for(cond, timeout=5.0):
    import time as _t
    end = _t.monotonic() + timeout
    while _t.monotonic() < end:
        if cond():
            return True
        _t.sleep(0.01)
    return False


def test_background_planning_keeps_loop_responsive(tmp_path):
    src = SlowSource(cands())
    loop, world, clock, logs = build_bg(tmp_path, src)
    world.start("Seed Song", "Seed Artist", duration=40, tidal_id="seed")
    for _ in range(12):
        loop.step(); clock.sleep(1)
    assert src.started.wait(2)
    assert loop.state.planning is not None and loop.state.plan is None
    # the loop keeps polling while the source is busy
    before = loop.state.tracks_seen
    for _ in range(5):
        loop.step(); clock.sleep(1)
    assert loop.state.tracks_seen == before
    src.release.set()
    assert wait_for(lambda: loop.state.planning.done())
    loop.step()
    assert loop.state.plan is not None and loop.state.plan.primary.track.title == "Next One"
    for _ in range(60):
        loop.step(); clock.sleep(0.5)
        if world.played:
            break
    assert world.played == ["t-Next One"]
    loop.close()


def test_stale_background_plan_is_discarded_after_track_change(tmp_path):
    src = SlowSource(cands())
    loop, world, clock, logs = build_bg(tmp_path, src)
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(6):
        loop.step(); clock.sleep(1)
    assert src.started.wait(2)
    stale = loop.state.planning
    world.start("User Choice", "Someone", duration=300, tidal_id="user")
    loop.step()
    assert loop.state.planning is None and loop.state.current.title == "User Choice"
    src.release.set()
    assert wait_for(lambda: stale.done())
    loop.step()
    assert loop.state.plan is None or loop.state.plan.seed.title == "User Choice"
    loop.close()


def test_planner_exception_becomes_a_note(tmp_path):
    class Boom:
        name = "boom"
        def available(self): return True, ""
        def candidates(self, seeds, limit): raise RuntimeError("kaboom")
    loop, world, clock, logs = build_bg(tmp_path, Boom())
    loop.engine.plan = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine exploded"))
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(8):
        loop.step(); clock.sleep(1)
    assert wait_for(lambda: loop.state.planning is None or loop.state.planning.done())
    loop.step()
    assert loop.state.plan is not None and any("engine exploded" in n for n in loop.state.plan.notes)
    loop.close()
