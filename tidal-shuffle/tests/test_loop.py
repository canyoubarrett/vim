"""Loop tests with a fake clock, scripted now-playing and a fake player."""
import time

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
        self.start_delay = 0.0     # seconds between "play" and the song actually sounding
        self.pending = None        # (wall time it starts, track)
        self.fillers = 0           # how often TIDAL auto-advanced to a song we did not pick
        self.paused_at = None      # elapsed seconds when paused (the song is frozen there)
        self.presses = []
        self.still_next = True

    def start(self, title, artist, duration, tidal_id=None):
        self.track = (title, artist, duration, tidal_id)
        self.start_wall = self.clock.wall
        self.playing = True
        self.paused_at = None

    # NowPlayingBackend
    name = "world"
    def available(self):
        return True, ""
    def read(self):
        if self.pending is not None and self.clock.wall >= self.pending[0]:
            at, t = self.pending
            self.pending = None
            self.start(t.title, t.artist, t.duration or 180, t.id)
            self.start_wall = at
        if self.track is None:
            return None
        if self.stolen_until is not None and self.clock.wall < self.stolen_until:
            return NowPlaying("Ad", "Spotify", bundle_id="com.spotify.client")
        title, artist, duration, tid = self.track
        elapsed = self.clock.wall - self.start_wall
        if not self.playing and self.paused_at is not None:
            elapsed = self.paused_at   # paused: frozen, and TIDAL does not move on
        if elapsed >= duration and self.playing:
            # TIDAL auto-advances to an album track we did not choose
            self.fillers += 1
            self.start("Album Filler", "Someone", 200, "filler")
            self.start_wall = self.start_wall - (elapsed - duration)
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
    def queue_still_next(self, track):
        return self.still_next
    def prepare(self, track):
        self.prepared.append(track.id)
        return True
    def play(self, track):
        self.played.append(track.id)
        if self.verify:
            if self.start_delay:
                self.pending = (self.clock.wall + self.start_delay, track)
            else:
                self.start(track.title, track.artist, track.duration or 180, track.id)
            return PlayOutcome(True, "cdp/row", track.id)
        return PlayOutcome(False, "open-url", None, "opened")
    def press(self, control):
        self.presses.append(control)
        if control == "pause" and self.playing and self.track:
            self.paused_at = self.clock.wall - self.start_wall
            self.playing = False
        elif control == "play" and not self.playing and self.paused_at is not None:
            self.start_wall = self.clock.wall - self.paused_at
            self.playing, self.paused_at = True, None
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


def test_songs_you_started_are_not_picked_again(tmp_path):
    # The radio for the first pick contains the song you started with.
    class Radio:
        name = "lastfm"
        def available(self): return True, ""
        def candidates(self, seeds, limit):
            if seeds[0].title == "Seed Song":
                return [Candidate("Next One", "Band A", score=0.9, duration=30, source="lastfm")]
            return [Candidate("Seed Song", "Seed Artist", score=0.95, duration=30, source="lastfm"),
                    Candidate("Third", "Band C", score=0.5, duration=30, source="lastfm")]
    cfg = load_config(overrides={"shuffle": {"strategy": "top", "lookahead": 1, "artist_cooldown": 0, "min_duration": 1}}, env={})
    clock = Clock()
    world = World(clock)
    history = HistoryStore(tmp_path / "h.json")
    engine = Engine(cfg, [Radio()], FakeCatalog(), history, rng=random.Random(0), log=lambda m: None)
    loop = ShuffleLoop(cfg, engine, world, world, history, log=lambda m: None,
                       clock=lambda: clock.mono, wall=lambda: clock.wall, sleep=clock.sleep)
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="t-Seed Song")
    for _ in range(200):
        loop.step(); clock.sleep(0.5)
        if len(world.played) >= 2:
            break
    assert world.played == ["t-Next One", "t-Third"]
    assert [e.source for e in history.entries()][:2] == ["tidal", "lastfm"]


def test_deep_link_pick_is_recorded_once_it_plays(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}}, verify=False)
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="seed")
    for _ in range(80):
        loop.step(); clock.sleep(0.5)
        if world.played:
            break
    assert not history.has_played(tidal_id="t-Next One")
    world.start("Next One", "Band A", 180, "t-Next One")  # you press play on the opened song
    loop.step()
    assert history.has_played(tidal_id="t-Next One") and loop.state.picks_played == 1


def test_orphaned_queue_pick_is_recognised_later(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(8):
        loop.step(); clock.sleep(1)
    assert loop.state.queued is not None
    world.start("User Choice", "Someone", duration=300, tidal_id="user")  # you skip away
    loop.step()
    assert "t-Next One" in loop.state.orphaned
    world.start("Next One", "Band A", 180, "t-Next One")  # TIDAL plays the old queued pick later
    loop.step()
    assert history.has_played(tidal_id="t-Next One")
    assert any("earlier pick" in m for m in logs)


def test_skip_now_with_a_queued_pick_just_moves_on(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    presses = []
    world.press = lambda control: presses.append(control) or True
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(8):
        loop.step(); clock.sleep(1)
    assert loop.skip_now() is True
    assert presses == ["next"] and world.played == []


def test_skip_now_without_queue_does_not_queue_and_play_twice(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    assert loop.skip_now() is True
    assert world.queued is None and world.played == ["t-Next One"]


def test_slow_prepare_still_hands_off(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    real_prepare = world.prepare
    def slow_prepare(track):
        clock.sleep(9.0)  # the track page took ages to render
        return real_prepare(track)
    world.prepare = slow_prepare
    world.start("Seed Song", "Seed Artist", duration=40, tidal_id="seed")
    for _ in range(120):
        loop.step(); clock.sleep(0.4)
        if world.played:
            break
    assert world.played == ["t-Next One"]


def test_failed_pick_is_never_retried_even_with_a_thin_pool(tmp_path):
    src = StaticSource([Candidate("Broken", "B1", score=0.9, duration=200)], name="lastfm")
    cfg = load_config(overrides={"shuffle": {"strategy": "top"}}, env={})
    engine = Engine(cfg, [src], FakeCatalog(), HistoryStore(tmp_path / "h.json"), rng=random.Random(0))
    from tidal_shuffle.models import Seed
    plan = engine.plan(Seed("Seed", "S"), exclude_keys={("broken", "b1")})
    assert plan.picks == []


def test_current_song_is_never_offered_in_anchor_mode(tmp_path):
    src = StaticSource([Candidate("User Choice", "Someone", score=0.99, duration=200),
                        Candidate("Other", "O", score=0.5, duration=200)], name="lastfm")
    cfg = load_config(overrides={"shuffle": {"strategy": "top", "seed": "anchor", "allow_seed_artist": True}}, env={})
    engine = Engine(cfg, [src], FakeCatalog(), HistoryStore(tmp_path / "h.json"), rng=random.Random(0))
    from tidal_shuffle.models import Seed
    plan = engine.plan(Seed("User Choice", "Someone"), anchor=Seed("Start", "X"))
    assert [p.track.title for p in plan.picks] == ["Other"]


def test_planner_thread_is_a_daemon(tmp_path):
    src = SlowSource(cands())
    loop, world, clock, logs = build_bg(tmp_path, src)
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(6):
        loop.step(); clock.sleep(1)
    assert src.started.wait(2)
    import threading
    planners = [t for t in threading.enumerate() if t.name == "tidal-shuffle-planner"]
    assert planners and all(t.daemon for t in planners)
    src.release.set()
    loop.close()


def test_a_skip_during_planning_cancels_the_stale_work(tmp_path):
    src = SlowSource(cands())
    cancelled = []
    src.cancel = lambda: (cancelled.append(1), src.release.set())
    loop, world, clock, logs = build_bg(tmp_path, src)
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(6):
        loop.step(); clock.sleep(1)
    assert src.started.wait(2)
    world.start("User Choice", "Someone", duration=300, tidal_id="user")
    loop.step()
    assert cancelled == [1]
    loop.close()


def test_history_write_failure_does_not_stop_the_loop(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    def broken(*a, **k):
        raise OSError(28, "No space left on device")
    history.add = broken
    world.start("Seed Song", "Seed Artist", duration=30, tidal_id="seed")
    for _ in range(80):
        loop.step(); clock.sleep(0.5)
        if world.played:
            break
    assert world.played == ["t-Next One"]
    assert sum("could not save the play history" in m for m in logs) == 1


def test_same_track_by_id_even_if_artist_credit_differs(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Collab", "A", duration=300, tidal_id="c1")
    loop.step()
    seen = loop.state.tracks_seen
    # a reader that credits "A, B" and has no id: still the same song
    loop._observe(NowPlaying("Collab", "A, B", duration=300, elapsed=5, timestamp=clock.wall, playing=True,
                             bundle_id=TIDAL_BUNDLE_ID), clock.mono)
    loop._observe(NowPlaying("Collab", "A, B", duration=300, elapsed=6, timestamp=clock.wall, playing=True,
                             bundle_id=TIDAL_BUNDLE_ID), clock.mono)
    assert loop.state.tracks_seen == seen


def _run_songs(loop, world, clock, n):
    """Step until n picks were played (or a safety limit)."""
    for _ in range(20000):
        loop.step()
        clock.sleep(0.4)
        if len(world.played) >= n and world.pending is None:
            return
    raise AssertionError("did not finish")


def test_slow_tidal_start_is_learned_and_the_handoff_moves_earlier(tmp_path):
    many = [Candidate(f"Song {i}", f"Band {i}", score=1 - i / 100, duration=70) for i in range(12)]
    loop, world, clock, logs, _ = build(tmp_path, many, {"shuffle": {"strategy": "top", "artist_cooldown": 0},
                                                       "player": {"plan_after_seconds": 1, "handoff_mode": "timed"}})
    loop.timing_path = tmp_path / "timing.json"
    world.start_delay = 4.0  # TIDAL takes 4 s to start a song; the 3 s default is too late
    world.start("Seed Song", "Seed Artist", duration=70, tidal_id="seed")
    _run_songs(loop, world, clock, 1)
    assert world.fillers == 1                       # the first hand-off was late
    _run_songs(loop, world, clock, 2)               # by the time the pick shows up, the delay is learned
    assert 3.5 <= loop.start_delay <= 4.5
    assert loop.handoff_lead() >= loop.start_delay + 0.9
    _run_songs(loop, world, clock, 5)
    assert world.fillers == 1                       # never late again
    assert any("TIDAL took" in m for m in logs)
    # remembered for the next run
    import json
    assert 3.5 <= json.loads((tmp_path / "timing.json").read_text())["start_delay"] <= 4.5
    loop2, *_ = build(tmp_path, many, {"player": {"handoff_mode": "timed"}})
    loop2.timing_path = tmp_path / "timing.json"
    loop2.start_delay = loop2._load_start_delay()
    assert abs(loop2.handoff_lead() - loop.handoff_lead()) < 0.01


def test_fast_tidal_keeps_the_configured_lead(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}, "player": {"handoff_mode": "timed"}})
    world.start_delay = 0.5
    world.start("Seed Song", "Seed Artist", duration=70, tidal_id="seed")
    _run_songs(loop, world, clock, 1)
    loop.step(); clock.sleep(0.4); loop.step()
    assert world.fillers == 0
    assert loop.start_delay is not None and loop.start_delay < 1.5
    assert loop.handoff_lead() == 3.0


def test_adaptive_handoff_can_be_turned_off(tmp_path):
    loop, *_ = build(tmp_path, cands(), {"player": {"adaptive_handoff": False, "handoff_mode": "timed"}})
    loop.start_delay = 6.0
    assert loop.handoff_lead() == 3.0


def test_queued_pick_that_is_no_longer_next_is_started_at_the_end(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    world.still_next = False   # e.g. you added songs to TIDAL's queue yourself
    world.start("Seed Song", "Seed Artist", duration=60, tidal_id="seed")
    for _ in range(200):
        loop.step(); clock.sleep(0.4)
        if world.played:
            break
    assert world.queued.id == "t-Next One"
    assert world.played == ["t-Next One"]
    assert any("no longer next" in m for m in logs)
    assert world.fillers == 0


def test_queued_pick_that_tidal_never_plays_is_started_directly(tmp_path):
    """TIDAL accepted the queue entry but paused at the end of the song instead."""
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    world.start("Seed Song", "Seed Artist", duration=60, tidal_id="seed")
    def read_paused_at_end(orig=world.read):
        if world.track and world.track[3] == "seed" and clock.wall - world.start_wall >= 60:
            return NowPlaying("Seed Song", "Seed Artist", duration=60, elapsed=60, timestamp=clock.wall,
                              playing=False, bundle_id=TIDAL_BUNDLE_ID, tidal_id="seed")
        return orig()
    world.read = read_paused_at_end
    for _ in range(200):
        loop.step(); clock.sleep(0.4)
        if world.played:
            break
    assert world.queued.id == "t-Next One"
    assert world.played == ["t-Next One"]
    assert clock.wall - 50000.0 < 60 + 5   # within a few seconds of the end
    assert any("did not move on" in m for m in logs)


def test_queued_pick_on_a_blank_entry_is_started_directly(tmp_path):
    """TIDAL moved to a blank queue entry: no title, so nothing TIDAL-like is reported."""
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.queue_supported = True
    world.start("Seed Song", "Seed Artist", duration=60, tidal_id="seed")
    def read_blank_after_end(orig=world.read):
        if world.track and world.track[3] == "seed" and clock.wall - world.start_wall >= 60:
            return None
        return orig()
    world.read = read_blank_after_end
    for _ in range(200):
        loop.step(); clock.sleep(0.4)
        if world.played:
            break
    assert world.played == ["t-Next One"]
    assert clock.wall - 50000.0 < 60 + 5


def test_keyboard_commands(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    pressed = []
    world.press = lambda c: pressed.append(c) or True
    world.start("Seed Song", "Seed Artist", duration=200, tidal_id="seed")
    for _ in range(12):
        loop.step(); clock.sleep(1)
    loop.post("playpause")
    loop.handle_commands()
    assert pressed == ["pause"] and loop.state.current.playing is False
    world.playing = False
    loop.post("playpause")
    loop.handle_commands()
    assert pressed[-1] == "play"
    loop.post("next")
    loop.handle_commands()
    assert world.played == ["t-Next One"]
    loop.post("previous")
    loop.post("help")
    loop.handle_commands()
    assert pressed[-1] == "previous" and any(m.startswith("keys:") for m in logs)


def test_quit_key_stops_the_run(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands())
    world.start("Seed Song", "Seed Artist", duration=200, tidal_id="seed")
    loop.post("quit")
    loop.run(max_iterations=50)
    assert clock.mono == 1000.0  # stopped before doing anything


def test_pause_mode_holds_tidal_at_the_end_so_nothing_is_cut_or_skipped(tmp_path):
    many = [Candidate(f"Song {i}", f"Band {i}", score=1 - i / 100, duration=70) for i in range(12)]
    loop, world, clock, logs, _ = build(tmp_path, many, {"shuffle": {"strategy": "top", "artist_cooldown": 0},
                                                       "player": {"plan_after_seconds": 1}})
    assert loop.config.player.handoff_mode == "pause"
    world.start_delay = 4.0          # slow TIDAL: the old timing let TIDAL's own song in
    world.start("Seed Song", "Seed Artist", duration=70, tidal_id="seed")
    played_until = []
    orig_press = world.press
    def press(control):
        if control == "pause":
            played_until.append(clock.wall - world.start_wall)
        return orig_press(control)
    world.press = press
    _run_songs(loop, world, clock, 4)
    assert world.fillers == 0                                  # TIDAL never got to its own next song
    assert all(69.0 <= t <= 70.0 for t in played_until), played_until   # each song played to its last half second
    assert len(played_until) == 4


def test_pause_mode_resumes_tidal_when_no_pick_can_be_started(tmp_path):
    loop, world, clock, logs, _ = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.play = lambda track: (world.played.append(track.id), PlayOutcome(False, "cdp/row", None, "no button"))[1]
    world.start("Seed Song", "Seed Artist", duration=60, tidal_id="seed")
    for _ in range(200):
        loop.step(); clock.sleep(0.4)
        if world.played:
            break
    loop.step()
    assert world.presses[:2] == ["pause", "play"]
    assert world.playing


def test_one_slow_start_does_not_make_every_handoff_early(tmp_path):
    loop, *_ = build(tmp_path, cands(), {"player": {"handoff_mode": "timed"}})
    loop._delay_samples = [2.0, 2.1, 1.9, 2.0]
    loop.start_delay = 2.0
    from tidal_shuffle.models import Pick
    pick = Pick(candidate=cands()[0], track=TidalTrack(id="p", title="Next One", artist="Band A"))
    loop.state.last_handoff = (100.0, pick)
    np = NowPlaying("Next One", "Band A", duration=180, elapsed=0.0, timestamp=50000.0 + 9.0,
                    bundle_id=TIDAL_BUNDLE_ID, tidal_id="p")
    loop._wall = lambda: 50000.0 + 9.0
    loop._learn_start_delay(np, 109.0)   # one 9 s outlier
    assert loop.start_delay == 2.0
    assert loop.handoff_lead() == 3.0


def test_next_key_never_blocks_the_other_keys_while_a_pick_is_chosen(tmp_path):
    """A slow plan (a Spotify harvest) runs in the background; play/pause still works meanwhile."""
    import threading
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    loop.background = True
    release = threading.Event()
    real_plan = loop.engine.plan
    def slow_plan(*a, **k):
        release.wait(5)
        return real_plan(*a, **k)
    loop.engine.plan = slow_plan
    pressed = []
    orig_press = world.press
    world.press = lambda c: pressed.append(c) or orig_press(c)
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    loop.step()                      # sees the song; plans only after plan_after_seconds
    loop.post("next")
    loop.post("playpause")
    t0 = time.monotonic()
    loop.handle_commands()
    assert time.monotonic() - t0 < 1.0          # did not wait for the plan
    assert pressed == ["pause"]                  # play/pause went through at once
    assert loop.state.skip_requested and any("choosing a song" in m for m in logs)
    loop.post("next")
    loop.handle_commands()
    assert any("still choosing" in m for m in logs)   # no second plan
    release.set()
    for _ in range(100):
        loop.step()
        if world.played:
            break
        time.sleep(0.02)
    assert world.played == ["t-Next One"]       # switched once the pick was ready (even while paused)
    assert not loop.state.skip_requested


def test_next_key_plays_a_ready_pick_at_once(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    for _ in range(12):
        loop.step(); clock.sleep(1)
    assert loop.state.plan is not None
    loop.post("next")
    loop.handle_commands()
    assert world.played == ["t-Next One"]


def test_preset_command_applies_it_and_chooses_the_next_song_again(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    loop.step()
    gen = loop.state.generation
    loop.post("preset:vibe")
    loop.handle_commands()
    assert any("presets can only be switched" in m for m in logs)
    applied = []

    def apply(name):
        applied.append(name)
        loop.config.shuffle.flow = "vibe"
        return f"preset: {name}"
    loop.apply_preset = apply
    loop.post("preset:vibe")
    loop.handle_commands()
    assert applied == ["vibe"] and "preset: vibe" in logs
    assert loop.state.generation == gen + 1          # anything planned the old way is dropped

    def broken(name):
        raise ValueError("nope")
    loop.apply_preset = broken
    loop.post("preset:x")
    loop.handle_commands()
    assert any(m.startswith("⚠ preset x: nope") for m in logs)



def test_max_poll_checks_now_playing_often_while_the_screen_is_up(tmp_path):
    loop, world, clock, logs, history = build(tmp_path, cands(), {"shuffle": {"strategy": "top"}})
    world.start("Seed Song", "Seed Artist", duration=300, tidal_id="seed")
    waits = []
    loop._sleep = lambda d: (waits.append(d), clock.sleep(d))
    loop.run(max_iterations=3)
    assert max(waits) > 1.0
    waits.clear()
    loop._closed = False
    loop.max_poll = 0.5
    loop.run(max_iterations=3)
    assert waits and max(waits) <= 0.5
