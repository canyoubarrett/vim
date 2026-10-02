"""The runtime loop: watch TIDAL, plan the next song, hand it off at the right time."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable, Optional

from .config import AppConfig
from .engine import Engine, Plan
from .history import HistoryStore
from .matching import same_song
from .models import NowPlaying, Pick, Seed
from .nowplaying.base import NowPlayingBackend
from .tidal.player import TidalPlayer

Logger = Callable[[str], None]


@dataclass
class LoopState:
    current: Optional[NowPlaying] = None
    started_at: float = 0.0          # monotonic time the current track (probably) started
    last_seen: float = 0.0           # monotonic time we last saw TIDAL playing
    plan: Optional[Plan] = None
    prepared_id: Optional[str] = None
    queued: Optional[Pick] = None    # pick handed to TIDAL's own queue (Luna only)
    handed_off: bool = False
    expected: Optional[Pick] = None
    handoff_at: float = 0.0
    anchor: Optional[Seed] = None
    recent_seeds: list[Seed] = field(default_factory=list)
    failed_keys: set = field(default_factory=set)
    pending: Optional[NowPlaying] = None   # candidate new track awaiting confirmation
    recorded: bool = False                 # was `expected` already written to history?
    orphaned: dict = field(default_factory=dict)  # tidal id -> pick still sitting in TIDAL's queue
    planning: Optional[Future] = None      # background plan in flight
    generation: int = 0                    # bumps on every track change; stale plans are dropped
    picks_played: int = 0
    tracks_seen: int = 0


class ShuffleLoop:
    def __init__(
        self,
        config: AppConfig,
        engine: Engine,
        player: TidalPlayer,
        nowplaying: NowPlayingBackend,
        history: HistoryStore,
        log: Optional[Logger] = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        background: bool = False,
    ):
        """``background=True`` plans on a worker thread so a slow source (the
        Spotify app harvest can take 30 s or more) never delays a hand-off."""
        self.config = config
        self.engine = engine
        self.player = player
        self.nowplaying = nowplaying
        self.history = history
        self.log = log or (lambda m: None)
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self.state = LoopState()
        self._announced_idle = False
        self.background = background
        self._closed = False

    # -- helpers --------------------------------------------------------------
    def remaining(self, np: Optional[NowPlaying], now: float) -> Optional[float]:
        """Seconds left in the current track, from the best information we have."""
        st = self.state
        if np is not None and np.is_tidal:
            rem = np.remaining_at(self._wall())
            if rem is not None:
                return rem
        if st.current is None:
            return None
        duration = st.current.duration
        if duration is None and st.plan is not None:
            duration = st.plan.seed.duration
        if duration is None:
            return None
        if st.current.playing is False:
            return None
        return max(0.0, duration - (now - st.started_at))

    def _matches_expected(self, np: NowPlaying) -> bool:
        exp = self.state.expected
        if exp is None:
            return False
        if np.tidal_id and exp.track.id:
            return np.tidal_id == exp.track.id
        return same_song(np.title, np.artist, exp.track.title, exp.track.artist) or \
            same_song(np.title, np.artist, exp.candidate.title, exp.candidate.artist)

    def _history_add(self, title: str, artist: str, tidal_id: Optional[str], source: str) -> None:
        try:
            self.history.add(title, artist, tidal_id=tidal_id, source=source)
        except OSError as e:  # disk full, read-only config dir...: keep shuffling
            if not getattr(self, "_history_warned", False):
                self.log(f"⚠ could not save the play history: {e}")
                self._history_warned = True

    def _record(self, pick: Pick) -> None:
        self._history_add(pick.track.title, pick.track.artist, pick.track.id, pick.source)
        self.state.picks_played += 1
        self.state.recorded = True

    # -- state transitions ----------------------------------------------------
    def on_new_track(self, np: NowPlaying, now: float) -> None:
        st = self.state
        pos = np.position_at(self._wall()) or 0.0
        was_ours = st.expected is not None and self._matches_expected(np)
        orphan = st.orphaned.pop(np.tidal_id, None) if (np.tidal_id and not was_ours) else None
        if st.current is not None:
            st.recent_seeds.append(Seed.from_now_playing(st.current))
            st.recent_seeds = st.recent_seeds[-10:]
        if st.queued is not None and not was_ours and st.queued.track.id:
            # You skipped elsewhere; our pick may still be waiting in TIDAL's queue.
            st.orphaned[st.queued.track.id] = st.queued
        if was_ours:
            self.log(f"✓ now playing our pick: {np.label()}  [{st.expected.source}]")
            if not st.recorded:
                self._record(st.expected)  # queued and opened-by-link picks count once they play
        elif orphan is not None:
            self.log(f"✓ now playing an earlier pick from TIDAL's queue: {np.label()}  [{orphan.source}]")
            self._record(orphan)
        else:
            if st.expected is not None and (st.handed_off or st.queued is not None):
                self.log(f"hand-off missed; TIDAL moved on to {np.label()} instead of {st.expected.label()}")
            elif st.current is not None:
                self.log(f"♫ track changed: {np.label()}")
            else:
                self.log(f"♫ now playing: {np.label()}")
            if st.anchor is None or st.current is None:
                st.anchor = Seed.from_now_playing(np)
            # Songs you (or TIDAL) chose count as heard, so they are not picked again soon.
            last = self.history.recent(1)
            if not last or last[0].key != np.key:
                self._history_add(np.title, np.artist, np.tidal_id, "tidal")
        st.tracks_seen += 1
        st.generation += 1
        if st.planning is not None and not st.planning.done():
            self.engine.cancel()  # e.g. stop a Spotify harvest for the song you skipped
        st.planning = None  # a plan still running for the previous song is ignored when it lands
        st.current = np
        st.started_at = now - pos
        st.last_seen = now
        st.plan = None
        st.prepared_id = None
        st.queued = None
        st.handed_off = False
        st.expected = None
        st.recorded = False
        st.failed_keys = set()
        st.pending = None

    def _compute_plan(self, seed: Seed, anchor: Optional[Seed], recent: list, exclude: Optional[set]) -> Plan:
        try:
            return self.engine.plan(seed, anchor=anchor, recent=recent, exclude_keys=exclude)
        except Exception as e:  # never let planning take the loop down
            plan = Plan(seed=seed)
            plan.notes.append(f"planning failed: {e}")
            return plan

    def _plan_inputs(self):
        st = self.state
        return (Seed.from_now_playing(st.current), st.anchor, list(st.recent_seeds), set(st.failed_keys) or None)

    def _apply_plan(self, plan: Plan, dry_run: bool, allow_queue: bool = True) -> Plan:
        st = self.state
        st.plan = plan
        if plan.seed.duration and st.current is not None and st.current.duration is None:
            st.current.duration = plan.seed.duration
        if plan.primary is not None:
            backups = ", ".join(p.track.label() for p in plan.backups)
            self.log(f"→ next up: {plan.primary.track.label()}  [{plan.source_used}, {plan.candidates_considered} candidates, {plan.elapsed:.1f}s]"
                     + (f"  backups: {backups}" if backups else ""))
            for note in plan.notes:
                self.log(f"  note: {note}")
            if not dry_run and allow_queue and self.player.supports_queue():
                self.queue_pick(plan.primary)
        else:
            self.log("⚠ could not find anything to play next: " + "; ".join(plan.notes or ["no reason given"]))
        return plan

    def plan_now(self, dry_run: bool = False, allow_queue: bool = True) -> Optional[Plan]:
        """Plan synchronously for the current song."""
        st = self.state
        if st.current is None:
            return None
        return self._apply_plan(self._compute_plan(*self._plan_inputs()), dry_run, allow_queue)

    def request_plan(self, dry_run: bool = False) -> None:
        """Plan for the current song, on the worker thread when there is one."""
        st = self.state
        if st.current is None or st.planning is not None:
            return
        if not self.background or self._closed:
            self.plan_now(dry_run=dry_run)
            return
        future: Future = Future()
        future.generation = st.generation  # type: ignore[attr-defined]
        inputs = self._plan_inputs()

        def work() -> None:
            # A daemon thread, so Ctrl+C never waits for a slow harvest to finish.
            try:
                future.set_result(self._compute_plan(*inputs))
            except BaseException as e:  # pragma: no cover - _compute_plan catches Exception
                future.set_exception(e)

        threading.Thread(target=work, name="tidal-shuffle-planner", daemon=True).start()
        st.planning = future

    def collect_plan(self, dry_run: bool = False) -> None:
        """Adopt a finished background plan if it still belongs to the current song."""
        st = self.state
        fut = st.planning
        if fut is None or not fut.done():
            return
        st.planning = None
        if getattr(fut, "generation", None) != st.generation or st.current is None:
            return
        try:
            plan = fut.result()
        except Exception as e:  # _compute_plan already catches; belt and braces
            plan = Plan(seed=Seed.from_now_playing(st.current))
            plan.notes.append(f"planning failed: {e}")
        self._apply_plan(plan, dry_run)

    def close(self) -> None:
        self._closed = True

    def queue_pick(self, pick: Pick) -> bool:
        """Hand the pick to TIDAL's own queue (gapless; needs TidaLuna)."""
        st = self.state
        if self.player.queue_next(pick.track):
            self.log(f"⏭ queued {pick.track.label()} as TIDAL's next track")
            st.queued = pick
            st.expected = pick
            return True
        self.log("  could not queue in TIDAL; will hand off near the end instead")
        return False

    def handoff(self, now: float) -> bool:
        """Start the planned pick in TIDAL. Returns True when a pick was started."""
        st = self.state
        if st.plan is None or not st.plan.picks:
            return False
        st.handed_off = True
        st.handoff_at = now
        for pick in st.plan.picks:
            outcome = self.player.play(pick.track)
            if outcome.ok:
                self.log(f"▶ playing {pick.track.label()}  via {outcome.method}")
                st.expected = pick
                self._record(pick)
                return True
            if outcome.method.startswith(("cdp", "luna")):
                self.log(f"  could not start {pick.track.label()}: {outcome.detail}; trying a backup")
                st.failed_keys.add(pick.candidate.key)
                continue
            # Deep-link fallback: we cannot verify, so assume the user (or TIDAL) takes it from here.
            self.log(f"▶ opened {pick.track.label()} in TIDAL ({outcome.method}); press play if it does not start")
            self.log(f"   {pick.track.url}")
            st.expected = pick
            return True
        self.log("⚠ none of the picks could be started")
        return False

    # -- one iteration ----------------------------------------------------------
    def _same_as_current(self, np: NowPlaying) -> bool:
        cur = self.state.current
        if cur is None:
            return False
        if np.tidal_id and cur.tidal_id:
            return np.tidal_id == cur.tidal_id
        if np.same_track(cur):
            return True
        # One reader may credit "A" where another says "A, B": same song if the titles agree.
        from .matching import normalize
        return bool(cur.tidal_id) and not np.tidal_id and normalize(np.title) == normalize(cur.title)

    def _observe(self, np: Optional[NowPlaying], now: float) -> bool:
        """Fold a now-playing snapshot into the state. Returns True if TIDAL is live."""
        st = self.state
        tidal_live = np is not None and np.is_tidal and bool(np.title)
        if not tidal_live:
            st.pending = None
            return False
        st.last_seen = now
        if st.current is not None and self._same_as_current(np):
            st.pending = None
            if np.duration is not None:
                st.current.duration = np.duration
            if np.elapsed is not None:
                st.current.elapsed, st.current.timestamp = np.elapsed, np.timestamp
                pos = np.position_at(self._wall())
                if pos is not None:
                    st.started_at = now - pos
            if np.playing is not None:
                st.current.playing = np.playing
            if np.tidal_id and not st.current.tidal_id:
                st.current.tidal_id = np.tidal_id
            return True
        # A different track. TIDAL briefly reports mixed metadata (new title with the
        # old artist, or vice versa) on transitions, so MediaRemote-only snapshots
        # must be seen twice before we believe them. The app's own footer is exact.
        if np.tidal_id or st.current is None or (st.pending is not None and np.same_track(st.pending)):
            self.on_new_track(np, now)
        else:
            st.pending = np
        return True

    def step(self, dry_run: bool = False) -> float:
        """Run one iteration; returns how long to sleep before the next one."""
        st = self.state
        cfg = self.config.player
        now = self._clock()
        np = self.nowplaying.read()
        tidal_live = self._observe(np, now)

        if tidal_live:
            self._announced_idle = False
        else:
            # Nothing from TIDAL. Either it is idle, or another app (e.g. a muted
            # Spotify harvest) briefly owns macOS's now-playing slot. Keep the
            # current track for a grace period based on its estimated remaining time.
            if st.current is not None:
                duration = st.current.duration or (st.plan.seed.duration if st.plan else None)
                if duration is not None:
                    expired = now > st.started_at + duration + 15.0
                else:
                    expired = now - st.last_seen > 60.0
                if expired:
                    self.log("TIDAL stopped; waiting for it to play again")
                    st.current, st.plan, st.expected, st.handed_off, st.queued = None, None, None, False, None
                    return cfg.idle_poll_interval
            else:
                if not self._announced_idle:
                    self.log("waiting for TIDAL to play something…")
                    self._announced_idle = True
                return cfg.idle_poll_interval

        if st.current is None:
            return cfg.idle_poll_interval

        if st.current.playing is False and not st.handed_off:
            return cfg.poll_interval  # paused: nothing to do until it resumes

        self.collect_plan(dry_run=dry_run)
        if st.plan is None and st.planning is None and (now - st.started_at) >= cfg.plan_after_seconds:
            self.request_plan(dry_run=dry_run)
            self.collect_plan(dry_run=dry_run)

        rem = self.remaining(np if tidal_live else None, now)
        if st.plan is not None and st.plan.primary is not None and not dry_run and st.queued is None:
            if rem is not None:
                if st.prepared_id != st.plan.primary.track.id and rem <= cfg.prepare_seconds:
                    st.prepared_id = st.plan.primary.track.id
                    if self.player.prepare(st.plan.primary.track):
                        self.log(f"  prepared {st.plan.primary.track.label()} ({rem:.0f}s left)")
                    # Preparing takes time; re-read the clock before deciding on the hand-off.
                    now = self._clock()
                    rem = self.remaining(None, now)
                if not st.handed_off and rem is not None and rem <= cfg.handoff_seconds:
                    self.handoff(now)
            elif st.current.duration is None and not st.handed_off and (now - st.started_at) > 20 * 60:
                self.log("no timing information for 20 minutes; skipping ahead")
                self.handoff(now)

        if st.handed_off and st.expected is not None and now - st.handoff_at > cfg.verify_seconds + 10:
            # The hand-off happened but TIDAL still reports the old track: TIDAL may
            # have ignored us. Allow another attempt on the next pass.
            self.log("hand-off not reflected by TIDAL yet; will retry")
            st.failed_keys.add(st.expected.candidate.key)
            st.handed_off = False
            st.expected = None
            st.plan = None

        if rem is not None and rem <= max(cfg.prepare_seconds, 10.0) and st.queued is None:
            return cfg.near_end_poll_interval
        return cfg.poll_interval

    def run(self, dry_run: bool = False, once: bool = False, max_iterations: Optional[int] = None) -> None:
        iterations = 0
        try:
            while True:
                delay = self.step(dry_run=dry_run)
                iterations += 1
                if once and self.state.plan is not None:
                    return
                if max_iterations is not None and iterations >= max_iterations:
                    return
                if self.state.planning is not None:
                    delay = min(delay, self.config.player.near_end_poll_interval)
                self._sleep(max(0.05, delay))
        finally:
            self.close()

    def skip_now(self) -> bool:
        """Plan (if needed) and start the next pick immediately."""
        st = self.state
        if st.current is None:
            self._observe(self.nowplaying.read(), self._clock())
        if st.current is None:
            return False
        if st.queued is not None and self.player.press("next"):
            # The pick is already next in TIDAL's queue: just move on to it.
            self.log(f"⏭ skipping to {st.queued.track.label()}")
            return True
        if st.plan is None or not st.plan.picks:
            self.plan_now(allow_queue=False)
        st.queued = None
        return self.handoff(self._clock())
