import random

import pytest

from tidal_shuffle.models import Candidate
from tidal_shuffle.picker import PickContext, filter_candidates, order_candidates


def cands():
    return [
        Candidate("Song A", "Artist 1", source="s", score=0.9, rank=0, tidal_id="1", duration=200, popularity=80),
        Candidate("Song B", "Artist 2", source="s", score=0.8, rank=1, tidal_id="2", duration=200, popularity=60),
        Candidate("Song C", "Artist 3", source="s", score=0.7, rank=2, tidal_id="3", duration=200, popularity=20),
        Candidate("Song D", "Artist 1", source="s", score=0.6, rank=3, tidal_id="4", duration=200, popularity=5),
    ]


def test_top_strategy_is_deterministic_and_relevance_ordered():
    ordered, note = order_candidates(cands(), PickContext(), "top")
    assert [c.title for c in ordered] == ["Song A", "Song B", "Song C", "Song D"]
    assert note == ""


def test_history_filter_removes_recent_by_id_and_by_key():
    ctx = PickContext(recent_tidal_ids={"1"}, recent_keys={("song b", "artist 2")})
    ordered, note = order_candidates(cands(), ctx, "top")
    assert [c.title for c in ordered] == ["Song C", "Song D"]
    assert note == ""


def test_artist_cooldown_and_relaxation_ladder():
    ctx = PickContext(recent_artists=["Artist 1", "Artist 2", "Artist 3"], artist_cooldown=5)
    ordered, note = order_candidates(cands(), ctx, "top")
    # Everyone is in cooldown, so the ladder relaxes it.
    assert len(ordered) == 4
    assert note == "ignoring artist cooldown"


def test_seed_artist_excluded_unless_allowed():
    ctx = PickContext(seed_artist="Artist 1")
    ordered, _ = order_candidates(cands(), ctx, "top")
    assert all(c.artist != "Artist 1" for c in ordered)
    ctx.allow_seed_artist = True
    ordered, _ = order_candidates(cands(), ctx, "top")
    assert ordered[0].artist == "Artist 1"


def test_everything_recent_falls_back_to_allowing_repeats():
    ctx = PickContext(recent_tidal_ids={"1", "2", "3", "4"})
    ordered, note = order_candidates(cands(), ctx, "top")
    assert len(ordered) == 4
    assert note == "allowing repeats"


def test_duration_filter_is_hard():
    ctx = PickContext(min_duration=60, max_duration=180)
    survivors, note = filter_candidates(cands(), ctx)
    assert survivors == []
    assert note == "nothing playable"


def test_weighted_prefers_relevant_but_varies():
    rng = random.Random(7)
    firsts = [order_candidates(cands(), PickContext(), "weighted", rng)[0][0].title for _ in range(300)]
    assert firsts.count("Song A") > firsts.count("Song D")
    assert len(set(firsts)) >= 3


def test_discovery_prefers_obscure():
    rng = random.Random(3)
    firsts = [order_candidates(cands(), PickContext(), "discovery", rng)[0][0].title for _ in range(300)]
    assert firsts.count("Song D") > firsts.count("Song A")


def test_random_is_a_permutation_and_dedupes():
    rng = random.Random(1)
    dup = cands() + [Candidate("Song A", "Artist 1", tidal_id="1")]
    ordered, _ = order_candidates(dup, PickContext(), "random", rng)
    assert sorted(c.title for c in ordered) == ["Song A", "Song B", "Song C", "Song D"]


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        order_candidates(cands(), PickContext(), "bogus")


def test_allow_seed_artist_wins_over_the_cooldown():
    ctx = PickContext(seed_artist="Artist 1", allow_seed_artist=True, recent_artists=["Artist 1"], artist_cooldown=3)
    ordered, note = order_candidates(cands(), ctx, "top")
    assert ordered[0].artist == "Artist 1" and note == ""


def test_never_the_seed_artist_back_to_back_even_when_nothing_else_is_left():
    only_seed_artist = [
        Candidate("Song A", "Artist 1", source="s", score=0.9, rank=0, duration=200),
        Candidate("Song B", "Artist 1 feat. Guest", source="s", score=0.8, rank=1, duration=200),
        Candidate("Song C", "Guest, Artist 1", source="s", score=0.7, rank=2, duration=200),
    ]
    ordered, note = order_candidates(only_seed_artist, PickContext(seed_artist="Artist 1"), "top")
    assert ordered == [] and note == "nothing playable"
    ctx = PickContext(seed_artist="Artist 1", allow_seed_artist=True)
    assert len(order_candidates(only_seed_artist, ctx, "top")[0]) == 3


def test_featured_seed_artist_counts_as_the_same_artist():
    pool = [Candidate("Song A", "Santana feat. Buddy Miles", score=0.9, rank=0, duration=200),
            Candidate("Song B", "Jimi Hendrix", score=0.5, rank=1, duration=200)]
    ordered, _ = order_candidates(pool, PickContext(seed_artist="Buddy Miles"), "top")
    assert [c.title for c in ordered] == ["Song B"]


def test_cooldown_covers_every_credited_artist():
    pool = [Candidate("Song A", "Guest feat. Artist 2", score=0.9, rank=0, duration=200),
            Candidate("Song B", "Artist 3", score=0.5, rank=1, duration=200)]
    ctx = PickContext(recent_artists=["The Artist 2"], artist_cooldown=5)
    ordered, note = order_candidates(pool, ctx, "top")
    assert [c.title for c in ordered] == ["Song B"] and note == ""
