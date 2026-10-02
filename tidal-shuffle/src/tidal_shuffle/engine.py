"""The brain: seed -> candidates -> filters -> Tidal match -> ordered picks."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, Sequence

from .config import AppConfig
from .history import HistoryStore
from .matching import looks_like_knockoff, same_song, shares_artist
from .models import Candidate, Pick, Seed, TidalTrack
from .picker import PickContext, order_candidates
from .sources.base import Source, dedupe

Logger = Callable[[str], None]


class Catalog(Protocol):
    """What the engine needs from TIDAL."""

    def resolve_seed(self, seed: Seed) -> Seed:
        """Return the seed enriched with ``tidal_id``/``isrc``/``duration`` when found."""

    def match(self, cand: Candidate) -> Optional[TidalTrack]:
        """Find the TIDAL track for a candidate, or ``None``."""


@dataclass
class Plan:
    seed: Seed
    picks: list[Pick] = field(default_factory=list)
    source_used: str = ""
    sources_tried: list[str] = field(default_factory=list)
    candidates_considered: int = 0
    notes: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def primary(self) -> Optional[Pick]:
        return self.picks[0] if self.picks else None

    @property
    def backups(self) -> list[Pick]:
        return self.picks[1:]


class Engine:
    def __init__(
        self,
        config: AppConfig,
        sources: Sequence[Source],
        catalog: Catalog,
        history: HistoryStore,
        rng: Optional[random.Random] = None,
        log: Optional[Logger] = None,
    ):
        self.config = config
        self.sources = list(sources)
        self.catalog = catalog
        self.history = history
        self.rng = rng or random.Random()
        self.log = log or (lambda msg: None)
        self._unavailable_reported: set[str] = set()

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        """Ask sources to stop work for a song that is no longer playing."""
        for src in self.sources:
            cancel = getattr(src, "cancel", None)
            if cancel:
                try:
                    cancel()
                except Exception:
                    pass

    def effective_seeds(self, current: Seed, anchor: Optional[Seed], recent: Sequence[Seed]) -> list[Seed]:
        mode = self.config.shuffle.seed
        if mode == "anchor" and anchor is not None:
            return [anchor]
        if mode == "window":
            window = [s for s in list(recent)[-4:]]
            seeds = [current] + [s for s in reversed(window) if s.key != current.key]
            return seeds[:5]
        return [current]

    def _gather(self, seeds: list[Seed], plan: Plan, everything: bool = False) -> list[Candidate]:
        """Candidates from the sources in order, stopping at the first that gives
        enough (unless blending); ``everything`` asks the sources not tried yet."""
        shuffle = self.config.shuffle
        pool: list[Candidate] = []
        for src in self.sources:
            if everything and src.name in plan.sources_tried:
                continue
            ok, reason = src.available()
            if not ok:
                if src.name not in self._unavailable_reported:
                    self.log(f"source {src.name} unavailable: {reason}")
                    self._unavailable_reported.add(src.name)
                continue
            plan.sources_tried.append(src.name)
            try:
                cands = src.candidates(seeds, shuffle.candidates)
            except Exception as e:  # a flaky source must never kill the loop
                self.log(f"source {src.name} failed: {e}")
                plan.notes.append(f"{src.name}: {e}")
                continue
            for c in cands:
                c.source = c.source or src.name
            if cands:
                self.log(f"source {src.name}: {len(cands)} candidates")
                plan.source_used = plan.source_used or src.name
            pool.extend(cands)
            if not everything and not shuffle.blend and len(pool) >= 3:
                break
        return pool

    def _clean(self, pool: list[Candidate], avoid: list[Seed], exclude_keys: Optional[set] = None) -> list[Candidate]:
        out: list[Candidate] = []
        for c in dedupe(pool):
            if exclude_keys and c.key in exclude_keys:
                continue  # e.g. a pick that TIDAL just refused to play
            if any(same_song(c.title, c.artist, s.title, s.artist) for s in avoid):
                continue
            if looks_like_knockoff(c.title, c.artist):
                continue
            out.append(c)
        return out

    def _context(self, seed: Seed) -> PickContext:
        shuffle = self.config.shuffle
        return PickContext(
            seed_artist=seed.artist,
            recent_keys=self.history.recent_keys(shuffle.avoid_repeats_for, shuffle.avoid_repeats_days),
            recent_tidal_ids=self.history.recent_tidal_ids(shuffle.avoid_repeats_for, shuffle.avoid_repeats_days),
            recent_artists=self.history.recent_artists(max(shuffle.artist_cooldown, 1)),
            artist_cooldown=shuffle.artist_cooldown,
            allow_seed_artist=shuffle.allow_seed_artist,
            min_duration=shuffle.min_duration,
            max_duration=shuffle.max_duration,
            allow_explicit=shuffle.allow_explicit,
        )

    def _choose(self, pool: list[Candidate], ctx: PickContext, plan: Plan) -> None:
        """Order the pool and match it on TIDAL until enough picks are found."""
        plan.candidates_considered = len(pool)
        plan.notes = [n for n in plan.notes if not n.startswith(("none of ", "no candidates", "allowing", "ignoring", "nothing"))]
        if not pool:
            plan.notes.append("no candidates from any source")
            return
        ordered, note = order_candidates(pool, ctx, self.config.shuffle.strategy, self.rng)
        if note:
            plan.notes.append(note)
        wanted = max(1, self.config.shuffle.lookahead)
        tried = 0
        seen_ids: set[str] = {p.track.id for p in plan.picks}
        allow_repeats = note == "allowing repeats"
        for cand in ordered:
            if len(plan.picks) >= wanted:
                break
            tried += 1
            try:
                track = self.catalog.match(cand)
            except Exception as e:
                self.log(f"TIDAL match failed for {cand.label()}: {e}")
                track = None
            if track is None or track.id in seen_ids:
                continue  # unknown on TIDAL, or the same TIDAL track as an earlier pick
            if not allow_repeats and (track.id in ctx.recent_tidal_ids or track.key in ctx.recent_keys):
                continue  # heard recently under a slightly different title ("... (Remastered)")
            if not ctx.allow_seed_artist and ctx.seed_artist and \
                    shares_artist(track.artists or [track.artist], ctx.seed_artist):
                continue  # TIDAL credits the artist playing now: never back to back
            if not self.config.shuffle.allow_explicit and track.explicit:
                continue
            if track.duration is not None and not (self.config.shuffle.min_duration <= track.duration <= self.config.shuffle.max_duration):
                continue
            cand.tidal_id = track.id
            seen_ids.add(track.id)
            plan.picks.append(Pick(candidate=cand, track=track,
                                   reason=f"{cand.source} #{cand.rank + 1}, score {cand.score:.2f}"))
            if tried > wanted * 8:
                break
        if not plan.picks:
            plan.notes.append(f"none of {tried} candidates could be found on TIDAL")

    def plan(self, current: Seed, anchor: Optional[Seed] = None, recent: Sequence[Seed] = (),
             exclude_keys: Optional[set] = None) -> Plan:
        """Decide what to play after ``current``."""
        started = time.monotonic()
        plan = Plan(seed=current)
        try:
            current = self.catalog.resolve_seed(current)
            plan.seed = current
        except Exception as e:
            self.log(f"could not resolve seed on TIDAL: {e}")
            plan.notes.append(f"seed unresolved: {e}")

        seeds = self.effective_seeds(current, anchor, recent)
        # Never offer the song now playing, the seeds, or the last few songs heard.
        avoid = [current] + [s for s in seeds if s is not current] + list(recent)[-3:]
        ctx = self._context(current)
        raw = self._gather(seeds, plan)
        self._choose(self._clean(raw, avoid, exclude_keys), ctx, plan)
        if not plan.picks and any(src.name not in plan.sources_tried for src in self.sources):
            # e.g. the Spotify radio was all the same artist or all heard recently
            more = self._gather(seeds, plan, everything=True)
            if more:
                plan.notes.append("trying the other sources too")
                self._choose(self._clean(raw + more, avoid, exclude_keys), ctx, plan)
        plan.elapsed = time.monotonic() - started
        return plan
