"""Pick strategies: turn a pool of matched candidates into an ordered play list.

The engine hands this module every candidate that could be played next. The
strategy decides *which* one, and in what order the backups should be tried.
All randomness goes through an injectable ``random.Random`` so tests are
deterministic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from .matching import shares_artist
from .models import Candidate

STRATEGIES = ("top", "weighted", "random", "discovery")


@dataclass
class PickContext:
    """Everything a strategy needs to know besides the candidates themselves."""

    seed_artist: Optional[str] = None
    recent_keys: set = field(default_factory=set)
    recent_tidal_ids: set = field(default_factory=set)
    recent_artists: list = field(default_factory=list)
    artist_cooldown: int = 5
    allow_seed_artist: bool = False
    min_duration: Optional[float] = 60.0
    max_duration: Optional[float] = 900.0
    allow_explicit: bool = True
    is_explicit: Optional[Callable[[Candidate], bool]] = None
    fit: dict = field(default_factory=dict)   # candidate key -> how well it suits the flow (0..1)




def _passes_hard_filters(c: Candidate, ctx: PickContext) -> bool:
    if c.duration is not None:
        if ctx.min_duration is not None and c.duration < ctx.min_duration:
            return False
        if ctx.max_duration is not None and c.duration > ctx.max_duration:
            return False
    if not ctx.allow_explicit and ctx.is_explicit is not None and ctx.is_explicit(c):
        return False
    return True


def _is_recent(c: Candidate, ctx: PickContext) -> bool:
    if c.tidal_id and c.tidal_id in ctx.recent_tidal_ids:
        return True
    return c.key in ctx.recent_keys


def _in_cooldown(c: Candidate, ctx: PickContext) -> bool:
    if ctx.artist_cooldown <= 0:
        return False
    if ctx.allow_seed_artist and _is_seed_artist(c, ctx):
        return False  # you asked for more from the artist playing now
    return shares_artist(c.artist, ctx.recent_artists[-ctx.artist_cooldown:])


def _is_seed_artist(c: Candidate, ctx: PickContext) -> bool:
    if not ctx.seed_artist:
        return False
    return shares_artist(c.artist, ctx.seed_artist)


def filter_candidates(candidates: Sequence[Candidate], ctx: PickContext) -> tuple[list[Candidate], str]:
    """Apply filters, relaxing them step by step if they would leave nothing.

    Returns the surviving candidates and a short description of which
    relaxation level was needed (``""`` when no relaxation was necessary).
    """
    # Never the artist playing now, back to back (unless allow_seed_artist):
    # that rule is hard and is not relaxed below.
    base = [c for c in candidates if _passes_hard_filters(c, ctx)
            and (ctx.allow_seed_artist or not _is_seed_artist(c, ctx))]
    ladder: list[tuple[str, Callable[[Candidate], bool]]] = [
        ("", lambda c: not _is_recent(c, ctx) and not _in_cooldown(c, ctx)),
        ("ignoring artist cooldown", lambda c: not _is_recent(c, ctx)),
        ("allowing repeats", lambda c: True),
    ]
    for note, keep in ladder:
        survivors = [c for c in base if keep(c)]
        if survivors:
            return survivors, note
    return [], "nothing playable"


def _dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set = set()
    out: list[Candidate] = []
    for c in candidates:
        k = c.tidal_id or c.key
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def _weighted_order(cands: list[Candidate], weights: list[float], rng: random.Random) -> list[Candidate]:
    """Sample without replacement according to ``weights``."""
    pool = list(zip(cands, weights))
    out: list[Candidate] = []
    while pool:
        total = sum(w for _, w in pool)
        if total <= 0:
            out.extend(c for c, _ in pool)
            break
        r = rng.random() * total
        acc = 0.0
        for i, (c, w) in enumerate(pool):
            acc += w
            if r <= acc:
                out.append(c)
                pool.pop(i)
                break
        else:  # floating point slop
            out.append(pool.pop()[0])
    return out


def _relevance(c: Candidate) -> float:
    """Combined relevance from the source's own score and its rank."""
    score = max(0.0, min(1.0, c.score if c.score is not None else 0.5))
    rank_factor = 1.0 / (1.0 + 0.15 * max(0, c.rank))
    return max(0.02, score) * rank_factor


def order_candidates(
    candidates: Sequence[Candidate],
    ctx: PickContext,
    strategy: str = "weighted",
    rng: Optional[random.Random] = None,
) -> tuple[list[Candidate], str]:
    """Return candidates in the order they should be tried, plus a note.

    ``strategy``:

    * ``top``       – most relevant first (closest to the seed).
    * ``weighted``  – random, but biased toward relevance. The default.
    * ``random``    – uniform random among everything that passes the filters.
    * ``discovery`` – biased toward less popular / deeper-ranked candidates.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}. Choose one of: {', '.join(STRATEGIES)}")
    rng = rng or random.Random()
    cands, note = filter_candidates(_dedupe(candidates), ctx)
    if not cands:
        return [], note

    fit = ctx.fit
    if fit:
        # A flow is on: how well a song suits it counts more than its radio rank.
        f = lambda c: max(0.001, fit.get(c.key, 1.0))
        if strategy == "top":
            ordered = sorted(cands, key=lambda c: (-(f(c) ** 2 * _relevance(c) ** 0.5), c.rank))
        elif strategy == "random":
            ordered = _weighted_order(cands, [f(c) ** 2 for c in cands], rng)   # random among those that suit the flow
        elif strategy == "weighted":
            ordered = _weighted_order(cands, [f(c) ** 4 * _relevance(c) for c in cands], rng)
        else:  # discovery
            n = max(1, len(cands))
            ordered = _weighted_order(cands, [f(c) ** 3 * (0.3 + (c.rank + 1) / n) for c in cands], rng)
        return ordered, note
    if strategy == "top":
        ordered = sorted(cands, key=lambda c: (-_relevance(c), c.rank))
    elif strategy == "random":
        ordered = list(cands)
        rng.shuffle(ordered)
    elif strategy == "weighted":
        weights = [_relevance(c) ** 2 for c in cands]
        ordered = _weighted_order(cands, weights, rng)
    else:  # discovery
        n = max(1, len(cands))
        weights = []
        for c in cands:
            depth = (c.rank + 1) / n  # deeper ranks get more weight
            w = 0.3 + depth
            if c.popularity is not None:
                w *= 0.2 + (100 - max(0, min(100, c.popularity))) / 100.0
            w *= max(0.1, c.score if c.score is not None else 0.5)
            weights.append(w)
        ordered = _weighted_order(cands, weights, rng)
    return ordered, note
