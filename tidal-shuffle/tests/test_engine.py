import random

from tidal_shuffle.config import load_config
from tidal_shuffle.engine import Engine
from tidal_shuffle.history import HistoryStore
from tidal_shuffle.models import Candidate, Seed, TidalTrack
from tidal_shuffle.sources.base import StaticSource


class FakeCatalog:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.matched = []
        self.resolved = []

    def resolve_seed(self, seed):
        self.resolved.append(seed)
        seed.tidal_id = "seed-id"
        return seed

    def match(self, cand):
        self.matched.append(cand.title)
        if cand.title in self.missing:
            return None
        return TidalTrack(id=f"t-{cand.title}", title=cand.title, artist=cand.artist, duration=cand.duration or 200)


def make_engine(tmp_path, sources, overrides=None, catalog=None):
    cfg = load_config(overrides=overrides, env={})
    return Engine(cfg, sources, catalog or FakeCatalog(), HistoryStore(tmp_path / "h.json"), rng=random.Random(1), log=lambda m: None)


def cand(title, artist="Artist " + "x", score=0.8, dur=200):
    return Candidate(title, artist, score=score, duration=dur)


def test_first_source_with_candidates_wins(tmp_path):
    empty = StaticSource([], name="spotify-app")
    lastfm = StaticSource([cand("A", "A1"), cand("B", "B1"), cand("C", "C1"), cand("D", "D1")], name="lastfm")
    tidal = StaticSource([cand("Z", "Z1")], name="tidal-radio")
    eng = make_engine(tmp_path, [empty, lastfm, tidal], {"shuffle": {"strategy": "top", "lookahead": 2}})
    plan = eng.plan(Seed("Seed", "Someone"))
    assert plan.source_used == "lastfm"
    assert plan.sources_tried == ["spotify-app", "lastfm"]
    assert [p.track.title for p in plan.picks] == ["A", "B"]
    assert plan.primary.track.id == "t-A"
    assert tidal.calls == []


def test_unavailable_source_is_skipped_and_blend_merges(tmp_path):
    down = StaticSource([cand("X", "X1")], name="spotify-api", ok=False, reason="no creds")
    s1 = StaticSource([cand("A", "A1", 0.9)], name="lastfm")
    s2 = StaticSource([cand("B", "B1", 0.95)], name="tidal-radio")
    eng = make_engine(tmp_path, [down, s1, s2], {"shuffle": {"strategy": "top", "blend": True, "lookahead": 3}})
    plan = eng.plan(Seed("Seed", "Someone"))
    assert plan.sources_tried == ["lastfm", "tidal-radio"]
    assert sorted(p.track.title for p in plan.picks) == ["A", "B"]
    assert plan.candidates_considered == 2


def test_seed_itself_and_knockoffs_are_dropped(tmp_path):
    src = StaticSource([cand("Seed", "Someone"), cand("Seed (Karaoke Version)", "Karaoke Band"), cand("Real", "R1")], name="lastfm")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top"}})
    plan = eng.plan(Seed("Seed", "Someone"))
    assert [p.track.title for p in plan.picks] == ["Real"]


def test_history_avoids_repeats_and_records_nothing_itself(tmp_path):
    src = StaticSource([cand("A", "A1", 0.9), cand("B", "B1", 0.8)], name="lastfm")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "lookahead": 1}})
    eng.history.add("A", "A1", tidal_id="t-A")
    plan = eng.plan(Seed("Seed", "Someone"))
    assert plan.primary.track.title == "B"
    assert len(eng.history) == 1


def test_unmatched_candidates_are_skipped(tmp_path):
    src = StaticSource([cand("A", "A1", 0.9), cand("B", "B1", 0.8), cand("C", "C1", 0.7)], name="lastfm")
    catalog = FakeCatalog(missing={"A"})
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "lookahead": 2}}, catalog)
    plan = eng.plan(Seed("Seed", "Someone"))
    assert [p.track.title for p in plan.picks] == ["B", "C"]
    assert catalog.matched == ["A", "B", "C"]


def test_no_candidates_yields_empty_plan_with_note(tmp_path):
    eng = make_engine(tmp_path, [StaticSource([], name="lastfm")])
    plan = eng.plan(Seed("Seed", "Someone"))
    assert plan.picks == []
    assert any("no candidates" in n for n in plan.notes)


def test_source_exception_does_not_abort(tmp_path):
    class Boom:
        name = "boom"
        def available(self): return True, ""
        def candidates(self, seeds, limit): raise RuntimeError("kaboom")
    good = StaticSource([cand("A", "A1")], name="lastfm")
    eng = make_engine(tmp_path, [Boom(), good], {"shuffle": {"strategy": "top"}})
    plan = eng.plan(Seed("Seed", "Someone"))
    assert plan.primary.track.title == "A"
    assert any("kaboom" in n for n in plan.notes)


def test_seed_modes(tmp_path):
    src = StaticSource([cand("A", "A1")], name="lastfm")
    cur, anchor, older = Seed("Cur", "C"), Seed("Anchor", "A"), Seed("Old", "O")
    eng = make_engine(tmp_path, [src], {"shuffle": {"seed": "anchor"}})
    eng.plan(cur, anchor=anchor)
    assert src.calls[-1][0][0].title == "Anchor"
    eng = make_engine(tmp_path, [src], {"shuffle": {"seed": "window"}})
    eng.plan(cur, recent=[older, anchor])
    assert [s.title for s in src.calls[-1][0]] == ["Cur", "Anchor", "Old"]
    eng = make_engine(tmp_path, [src], {"shuffle": {"seed": "current"}})
    eng.plan(cur, anchor=anchor, recent=[older])
    assert [s.title for s in src.calls[-1][0]] == ["Cur"]


def test_explicit_and_duration_filters_apply_to_matched_track(tmp_path):
    class Cat(FakeCatalog):
        def match(self, cand):
            t = super().match(cand)
            if cand.title == "E":
                t.explicit = True
            if cand.title == "L":
                t.duration = 5000
            return t
    src = StaticSource([cand("E", "E1", 0.9), cand("L", "L1", 0.8), cand("OK", "O1", 0.7)], name="lastfm")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "allow_explicit": False, "lookahead": 3}}, Cat())
    plan = eng.plan(Seed("Seed", "Someone"))
    assert [p.track.title for p in plan.picks] == ["OK"]


def test_exclude_keys_skips_a_failed_pick(tmp_path):
    src = StaticSource([cand("A", "A1", 0.9), cand("B", "B1", 0.8)], name="lastfm")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "lookahead": 1}})
    plan = eng.plan(Seed("Seed", "Someone"), exclude_keys={("a", "a1")})
    assert plan.primary.track.title == "B"



def test_song_heard_under_a_versioned_title_is_not_picked_again(tmp_path):
    class Cat(FakeCatalog):
        def match(self, cand):
            if cand.title == "Come Together":
                return TidalTrack(id="T1", title="Come Together (Remastered 2009)", artist="The Beatles", duration=259)
            return super().match(cand)
    src = StaticSource([cand("Come Together", "The Beatles", 0.9), cand("Something Else", "Other", 0.5)], name="lastfm")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "lookahead": 2}}, Cat())
    eng.history.add("Come Together (Remastered 2009)", "The Beatles", tidal_id="T1")
    plan = eng.plan(Seed("Seed", "Someone"))
    assert [p.track.id for p in plan.picks] == ["t-Something Else"]


def test_two_candidates_for_one_tidal_track_make_one_pick(tmp_path):
    class Cat(FakeCatalog):
        def match(self, cand):
            if cand.title.startswith("Come Together"):
                return TidalTrack(id="T9", title="Come Together", artist="The Beatles", duration=259)
            return super().match(cand)
    src = StaticSource([cand("Come Together", "The Beatles", 0.9), cand("Come Together - Remastered 2009", "The Beatles", 0.8),
                        cand("Third", "C1", 0.5)], name="lastfm")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "lookahead": 3}}, Cat())
    plan = eng.plan(Seed("Seed", "Someone"))
    assert [p.track.id for p in plan.picks] == ["T9", "t-Third"]


def test_tidal_match_crediting_the_artist_playing_now_is_skipped(tmp_path):
    class Credits(FakeCatalog):
        def match(self, c):
            t = super().match(c)
            if c.title == "Remix":
                t.artist, t.artists = "DJ Someone", ["DJ Someone", "Seed Artist"]
            return t
    src = StaticSource([cand("Remix", "DJ Someone", 0.95), cand("B", "B1"), cand("C", "C1")], name="spotify-app")
    eng = make_engine(tmp_path, [src], {"shuffle": {"strategy": "top", "lookahead": 1}}, catalog=Credits())
    plan = eng.plan(Seed("Seed", "Seed Artist"))
    assert plan.primary.track.title == "B"


def test_radio_of_only_the_same_artist_falls_back_to_the_next_source(tmp_path):
    same = StaticSource([cand(f"S{i}", "Seed Artist") for i in range(5)], name="spotify-app")
    lastfm = StaticSource([cand("Other", "Someone Else")], name="lastfm")
    eng = make_engine(tmp_path, [same, lastfm], {"shuffle": {"strategy": "top", "lookahead": 1}})
    plan = eng.plan(Seed("Seed", "Seed Artist"))
    assert plan.primary.track.title == "Other"
    assert "trying the other sources too" in plan.notes


def test_the_choice_is_traced_step_by_step(tmp_path):
    src = StaticSource([cand("One", "A1"), cand("Two", "A2"), cand("Two", "A2"), cand("Seed", "Seed Artist")],
                       name="lastfm")
    eng = make_engine(tmp_path, [src, StaticSource([cand("X", "Y")], name="deezer")],
                      {"shuffle": {"strategy": "top", "lookahead": 2}})
    plan = eng.plan(Seed("Seed", "Seed Artist"))
    rows = eng.trace.flat()
    labels = [n.label for _, n, _, _ in rows]
    details = {n.label: n.detail for _, n, _, _ in rows}
    assert labels[0] == "after Seed — Seed Artist" and eng.trace.finished is not None
    assert "sources" in labels and "lastfm" in labels and "deezer" in labels
    assert details["deezer"] == "not needed"                              # the first source gave enough
    assert "4 → 2" in details["pool"] and "repeats in the radio" in details["pool"]
    assert any(l.startswith("order: top") for l in labels) and "find on TIDAL" in labels
    assert labels[-1] == f"pick: {plan.picks[0].track.label()}"
    assert all(n.status != "running" for _, n, _, _ in rows)              # everything ended
