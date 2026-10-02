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
    assert split_artists("Drake, Rihanna feat. Future") == ["Drake", "Rihanna", "Future"]
    assert split_artists("Calvin Harris & Dua Lipa") == ["Calvin Harris", "Dua Lipa"]
    assert primary_artist("Drake feat. Rihanna") == "Drake"
    assert primary_artist("Daft Punk, Pharrell Williams") == "Daft Punk"
    for band in ("Tyler, The Creator", "Earth, Wind & Fire", "Simon & Garfunkel", "AC/DC", "Lil Nas X",
                 "X Ambassadors", "Of Monsters and Men", "Iron & Wine", "Florence + The Machine",
                 "Crosby, Stills, Nash & Young", "Belle and Sebastian"):
        assert primary_artist(band) == band, band
    assert artist_similarity("Tyler, The Creator", ["Tyler, The Creator"]) == 1.0
    assert artist_similarity("X Japan", ["Japan"]) < 0.8
    assert artist_similarity("Earth, Wind & Fire", ["Earth"]) < 0.8


def test_similarity_bounds_and_containment():
    assert similarity("Hello", "Hello") == 1.0
    assert similarity("", "Hello") == 0.0
    assert similarity("Bob Marley", "Bob Marley & The Wailers") >= 0.8
    assert similarity("Japan", "X Japan") < 0.8
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



# Cases measured by the matching review -------------------------------------------------------

def test_featuring_needs_a_whole_word():
    for title in ("Loft Music", "Left Hand Free", "Lift Me Up", "Drift Away", "Gift of a Friend", "Dancing With Myself"):
        assert strip_featuring(title) == title and core_title(title) == title
    assert strip_featuring("Song (with Ariana Grande)") == "Song"
    assert strip_featuring("Song feat. Someone Else") == "Song"
    assert score_match("Loft Music", "The Weeknd", "Losers", ["The Weeknd", "Labrinth"]) < 0.72


def test_short_and_prefix_titles_are_different_songs():
    pairs = [("ME!", "Mean", "Taylor Swift"), ("One", "One Tree Hill", "U2"), ("Hero", "Heroes", "David Bowie"),
             ("i", "Institutionalized", "Kendrick Lamar"), ("Home", "Home Again", "Michael Kiwanuka"),
             ("Revolution", "Revolution 9", "The Beatles")]
    for a, b, artist in pairs:
        assert score_match(a, artist, b, [artist]) < 0.72, (a, b)
        assert not same_song(a, artist, b, artist), (a, b)
    assert score_match("Colour", "A", "Color", ["A"]) > 0.8  # spelling variants still match


def test_non_latin_titles_match_and_keep_their_keys():
    from tidal_shuffle.models import Candidate
    assert normalize("紅蓮華") and normalize("방탄소년단") and normalize("Группа крови")
    assert score_match("紅蓮華", "LiSA", "紅蓮華", ["LiSA"], 230, 230) > 0.95
    assert score_match("봄날", "방탄소년단", "봄날", ["방탄소년단"]) > 0.95
    assert Candidate("봄날", "방탄소년단").key != Candidate("피 땀 눈물", "방탄소년단").key


def test_cover_by_an_unrelated_artist_is_rejected():
    for cover in ("The Hit Co.", "The Cover Crew", "The Rock Heroes", "Studio Allstars", "Top 40 Hits"):
        assert score_match("Hey Jude", "The Beatles", "Hey Jude", [cover], 431, 431) < 0.72, cover


def test_radio_edit_and_original_mix_are_the_plain_song():
    assert score_match("Blinding Lights", "The Weeknd", "Blinding Lights (Radio Edit)", ["The Weeknd"], 200, 200) > 0.9
    assert score_match("Levels", "Avicii", "Levels (Original Mix)", ["Avicii"], 199, 199) > 0.9
    assert score_match("Levels", "Avicii", "Levels (Extended Mix)", ["Avicii"]) < 0.72


def test_knockoff_detector_ignores_real_song_titles():
    for title, artist in (("Lullaby", "The Cure"), ("Tribute", "Tenacious D"), ("Karaoke", "Drake"),
                          ("Ringtone", "100 gecs"), ("Music Box Dancer", "Frank Mills"), ("Attribute", "Someone")):
        assert not looks_like_knockoff(title, artist), title
    assert looks_like_knockoff("Hey Jude", "Sing-Along Kids")
    assert looks_like_knockoff("Hey Jude (Karaoke Version)", "Anyone")
    assert looks_like_knockoff("Hey Jude", "The Beatles Tribute Band")


def test_exact_version_wins_ties():
    a = score_match("Shine On You Crazy Diamond (Pts. 6-9)", "Pink Floyd", "Shine On You Crazy Diamond (Pts. 6-9)", ["Pink Floyd"])
    b = score_match("Shine On You Crazy Diamond (Pts. 6-9)", "Pink Floyd", "Shine On You Crazy Diamond (Pts. 1-5)", ["Pink Floyd"])
    assert a > b
