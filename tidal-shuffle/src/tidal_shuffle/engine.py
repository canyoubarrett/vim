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
    flow: str = "radio"
    flow_target: Optional[float] = None     # target energy, when the flow has one

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
        features=None,
    ):
        self.config = config
        self.sources = list(sources)
        self.catalog = catalog
        self.history = history
        self.rng = rng or random.Random()
        self.log = log or (lambda msg: None)
        self._unavailable_reported: set[str] = set()
        self.features = features                 # audio features for the flows (features.ReccoBeats)
        self._song_features: dict = {}           # seed key -> Features (the first song's, for steady/soundscape)
        self._last_target: Optional[float] = None
        self.trace = None                        # the live record of the choice being made (trace.Trace)

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
        tr = self.trace
        group = tr.add(None, "asking the other sources" if everything else "sources", "step", status="running") if tr else None
        for i, src in enumerate(self.sources):
            if everything and src.name in plan.sources_tried:
                continue
            ok, reason = src.available()
            if not ok:
                if src.name not in self._unavailable_reported:
                    self.log(f"source {src.name} unavailable: {reason}")
                    self._unavailable_reported.add(src.name)
                if tr:
                    tr.add(group, src.name, "source", f"unavailable: {reason}", "skipped")
                continue
            plan.sources_tried.append(src.name)
            node = tr.add(group, src.name, "source", "asking…", "running") if tr else None
            began = time.monotonic()
            try:
                cands = src.candidates(seeds, shuffle.candidates)
            except Exception as e:  # a flaky source must never kill the loop
                self.log(f"source {src.name} failed: {e}")
                plan.notes.append(f"{src.name}: {e}")
                if tr:
                    tr.update(node, detail=f"failed: {e}", status="failed")
                continue
            for c in cands:
                c.source = c.source or src.name
            if cands:
                self.log(f"source {src.name}: {len(cands)} candidates")
                plan.source_used = plan.source_used or src.name
            if tr:
                tr.update(node, detail=f"{len(cands)} songs · {time.monotonic() - began:.1f}s",
                          status="done" if cands else "failed")
            pool.extend(cands)
            if not everything and not shuffle.blend and len(pool) >= 3:
                if tr:
                    for rest in self.sources[i + 1:]:
                        tr.add(group, rest.name, "source", "not needed", "skipped")
                break
        if tr:
            tr.update(group, detail=f"{len(pool)} songs", status="done" if pool else "failed")
        return pool

    def _clean(self, pool: list[Candidate], avoid: list[Seed], exclude_keys: Optional[set] = None) -> list[Candidate]:
        out: list[Candidate] = []
        unique = dedupe(pool)
        dropped = {"repeats in the radio": len(pool) - len(unique), "playing or just played": 0,
                   "refused by TIDAL": 0, "look-alikes": 0}
        for c in unique:
            if exclude_keys and c.key in exclude_keys:
                dropped["refused by TIDAL"] += 1
                continue  # e.g. a pick that TIDAL just refused to play
            if any(same_song(c.title, c.artist, s.title, s.artist) for s in avoid):
                dropped["playing or just played"] += 1
                continue
            if looks_like_knockoff(c.title, c.artist):
                dropped["look-alikes"] += 1
                continue
            out.append(c)
        if self.trace:
            why = ", ".join(f"{n} {k}" for k, n in dropped.items() if n)
            self.trace.add(None, "pool", "step", f"{len(pool)} → {len(out)}" + (f"  (left out: {why})" if why else ""),
                           "done" if out else "failed")
        return out

    def _flow_fits(self, pool: list[Candidate], current: Seed, anchor: Optional[Seed], plan: Plan) -> dict:
        """How well each candidate suits the shuffle flow (empty: plain radio order)."""
        from .flows import score

        shuffle = self.config.shuffle
        plan.flow = shuffle.flow
        if shuffle.flow == "radio" or self.features is None or not pool:
            if self.trace and pool:
                self.trace.add(None, f"flow: {shuffle.flow}", "step",
                               "the radio's own order" if shuffle.flow == "radio" else "no audio features", "done")
            return {}
        ids = [c.spotify_id for c in pool if c.spotify_id]
        if current.spotify_id:
            ids.append(current.spotify_id)
        try:
            feats = self.features.features(ids)
        except Exception as e:   # never let a flow break planning
            self.log(f"audio features failed: {e}")
            feats = {}
        seed_f = feats.get(current.spotify_id) if current.spotify_id else None
        if seed_f is not None:
            self._song_features[current.key] = seed_f
            if len(self._song_features) > 500:
                self._song_features.pop(next(iter(self._song_features)))
        seed_f = seed_f or self._song_features.get(current.key)
        anchor_f = self._song_features.get(anchor.key) if anchor is not None else None
        for c in pool:
            f = feats.get(c.spotify_id) if c.spotify_id else None
            if f is not None:
                c.extra["energy"] = round(f.energy, 2)
        res = score(shuffle.flow, {c.key: (feats.get(c.spotify_id) if c.spotify_id else None) for c in pool},
                    seed_f, anchor_f, level=shuffle.energy, step=shuffle.energy_step, last_target=self._last_target)
        if res.target is not None:
            self._last_target = res.target
        plan.flow_target = res.target
        if res.note:
            plan.notes.append(res.note)
        if self.trace:
            self.trace.add(None, f"flow: {shuffle.flow}", "step", res.note or "", "done")
        return res.fits

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
        tr = self.trace
        if tr:
            order = tr.add(None, f"order: {self.config.shuffle.strategy}", "step",
                           f"{len(ordered)} songs" + (f" · {note}" if note else ""), "done")
            for c in ordered[:5]:
                fit = ctx.fit.get(c.key) if ctx.fit else None
                tr.add(order, c.label(), "candidate",
                       f"{c.source} #{c.rank + 1} · score {c.score:.2f}" + (f" · fit {fit:.2f}" if fit is not None else ""),
                       "done")
            look = tr.add(None, "find on TIDAL", "step", status="running")
        wanted = max(1, self.config.shuffle.lookahead)
        tried = 0
        seen_ids: set[str] = {p.track.id for p in plan.picks}
        allow_repeats = note == "allowing repeats"
        for cand in ordered:
            if len(plan.picks) >= wanted:
                break
            tried += 1
            node = tr.add(look, cand.label(), "candidate", "looking…", "running") if tr else None
            try:
                track = self.catalog.match(cand)
            except Exception as e:
                self.log(f"TIDAL match failed for {cand.label()}: {e}")
                track = None
            skip = None
            if track is None:
                skip = "not on TIDAL"
            elif track.id in seen_ids:
                skip = "same track as another pick"      # e.g. the same TIDAL track as an earlier pick
            elif not allow_repeats and (track.id in ctx.recent_tidal_ids or track.key in ctx.recent_keys):
                skip = "heard recently"                  # under a slightly different title ("... (Remastered)")
            elif not ctx.allow_seed_artist and ctx.seed_artist and \
                    shares_artist(track.artists or [track.artist], ctx.seed_artist):
                skip = "same artist as now"              # never back to back
            elif not self.config.shuffle.allow_explicit and track.explicit:
                skip = "explicit"
            elif track.duration is not None and not (self.config.shuffle.min_duration <= track.duration <= self.config.shuffle.max_duration):
                skip = "too long or too short"
            if skip:
                if tr:
                    tr.update(node, detail=skip, status="skipped")
                continue
            if tr:
                tr.update(node, detail="found" + (" · pick" if not plan.picks else " · backup"), status="done")
            cand.tidal_id = track.id
            seen_ids.add(track.id)
            plan.picks.append(Pick(candidate=cand, track=track,
                                   reason=f"{cand.source} #{cand.rank + 1}, score {cand.score:.2f}"))
            if tried > wanted * 8:
                break
        if tr:
            tr.update(look, detail=f"{tried} looked up, {len(plan.picks)} found", status="done" if plan.picks else "failed")
        if not plan.picks:
            plan.notes.append(f"none of {tried} candidates could be found on TIDAL")

    def plan(self, current: Seed, anchor: Optional[Seed] = None, recent: Sequence[Seed] = (),
             exclude_keys: Optional[set] = None) -> Plan:
        """Decide what to play after ``current``."""
        from .trace import Trace

        started = time.monotonic()
        plan = Plan(seed=current)
        shuffle = self.config.shuffle
        self.trace = tr = Trace(f"after {current.label()}",
                                f"{shuffle.flow} · {shuffle.strategy} · seed: {shuffle.seed}")
        try:
            current = self.catalog.resolve_seed(current)
            plan.seed = current
        except Exception as e:
            self.log(f"could not resolve seed on TIDAL: {e}")
            plan.notes.append(f"seed unresolved: {e}")
            tr.add(None, "seed", "step", f"not resolved on TIDAL: {e}", "failed")

        seeds = self.effective_seeds(current, anchor, recent)
        # Never offer the song now playing, the seeds, or the last few songs heard.
        avoid = [current] + [s for s in seeds if s is not current] + list(recent)[-3:]
        ctx = self._context(current)
        raw = self._gather(seeds, plan)
        pool = self._clean(raw, avoid, exclude_keys)
        ctx.fit = self._flow_fits(pool, current, anchor, plan)
        self._choose(pool, ctx, plan)
        if not plan.picks and any(src.name not in plan.sources_tried for src in self.sources):
            # e.g. the Spotify radio was all the same artist or all heard recently
            more = self._gather(seeds, plan, everything=True)
            if more:
                plan.notes.append("trying the other sources too")
                pool = self._clean(raw + more, avoid, exclude_keys)
                ctx.fit = self._flow_fits(pool, current, anchor, plan)
                self._choose(pool, ctx, plan)
        plan.elapsed = time.monotonic() - started
        if plan.picks:
            pick = plan.picks[0]
            tr.add(None, f"pick: {pick.track.label()}", "pick",
                   ("backups: " + ", ".join(p.track.label() for p in plan.picks[1:])) if plan.picks[1:] else "", "done")
            tr.finish("done", f"{shuffle.flow} · {shuffle.strategy} · {plan.elapsed:.1f}s")
        else:
            tr.add(None, "no pick", "pick", "; ".join(plan.notes[-2:]), "failed")
            tr.finish("failed")
        return plan
