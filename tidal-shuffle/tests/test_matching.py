from tidal_shuffle.matching import (
    artist_similarity, core_title, normalize, primary_artist, score_match,
    similarity, split_artists, strip_featuring, title_tags, same_song, looks_like_knockoff,
)


def test_normalize_strips_accents_punctuation_and_case():
    assert normalize("Beyoncé – Déjà Vu!") == "beyonce deja vu"
    assert normalize("Simon & Garfunkel") == "simon and garfunkel"
    assert normalize("Don't Stop Me Now") == "dont stop me now"


def test_core_title_removes_decorations():
    assert core_title("Midnight City (feat. Someone) - 2011 Remaster") == "Midnight City"
    assert core_title("Blinding Lights [Radio Edit]") == "Blinding Lights"
    assert core_title("Intro") == "Intro"
    assert core_title("(Nothing but) Parentheses") == "(Nothing but) Parentheses"


def test_strip_featuring_variants():
    assert strip_featuring("Song (feat. A & B)") == "Song"
    assert strip_featuring("Song ft. A") == "Song"
    assert strip_featuring("Song featuring A") == "Song"


def test_title_tags_detects_versions():
    assert title_tags("Song (Live at Wembley)") == {"live"}
    assert "remix" in title_tags("Song - Some DJ Remix")
    assert "mix" not in title_tags("Song - Some DJ Remix")
    assert title_tags("Song") == set()
    assert "karaoke" in title_tags("Song (Karaoke Version)")


def test_split_and_primary_artist():
    assert split_artists("A, B & C feat. D") == ["A", "B", "C", "D"]
    assert primary_artist("Drake feat. Rihanna") == "Drake"
    assert primary_artist("Tyler, The Creator") == "Tyler"  # known limitation; whole-string compare covers it
    assert artist_similarity("Tyler, The Creator", ["Tyler, The Creator"]) == 1.0


def test_similarity_bounds_and_containment():
    assert similarity("Hello", "Hello") == 1.0
    assert similarity("", "Hello") == 0.0
    assert similarity("Hello", "Hello (Deluxe Edition Mix)") >= 0.8
    assert similarity("Completely different", "Nothing alike here") < 0.5


def test_score_match_exact_is_high():
    assert score_match("Midnight City", "M83", "Midnight City", ["M83"], 243, 244) > 0.95


def test_score_match_penalises_live_and_karaoke():
    live = score_match("Midnight City", "M83", "Midnight City (Live)", ["M83"])
    assert live < 0.65
    karaoke = score_match("Hey Jude", "The Beatles", "Hey Jude (Karaoke Version)", ["Karaoke Hits"])
    assert karaoke < 0.3


def test_score_match_tolerates_remaster_and_feat_credit():
    s = score_match("Come Together", "The Beatles", "Come Together - Remastered 2009", ["The Beatles"], 259, 260)
    assert s > 0.9
    s2 = score_match("Fancy (feat. Charli XCX)", "Iggy Azalea", "Fancy", ["Iggy Azalea", "Charli XCX"], 200, 200)
    assert s2 > 0.9


def test_score_match_duration_mismatch_penalty():
    close = score_match("Song", "Artist", "Song", ["Artist"], 200, 202)
    far = score_match("Song", "Artist", "Song", ["Artist"], 200, 320)
    assert close > far
    assert far < 0.7


def test_same_song_and_knockoff():
    assert same_song("Blinding Lights", "The Weeknd", "Blinding Lights", "The Weeknd")
    assert not same_song("Blinding Lights", "The Weeknd", "Save Your Tears", "The Weeknd")
    assert looks_like_knockoff("Hey Jude", "Karaoke Universe")
    assert not looks_like_knockoff("Hey Jude", "The Beatles")
