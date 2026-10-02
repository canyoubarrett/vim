"""Fuzzy title/artist matching used to map songs between catalogs.

Everything here is pure Python (stdlib only) so it is fast to unit test and
behaves identically on every platform.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, Optional, Sequence

# Words that mark an alternative version of a song. If the candidate's title
# does not carry the tag but the catalog hit does, it is almost certainly the
# wrong recording (a live take, a karaoke cover, a remix...).
VERSION_TAGS = (
    "live", "remix", "mix", "edit", "acoustic", "instrumental", "karaoke",
    "cover", "tribute", "demo", "remaster", "remastered", "sped up", "slowed",
    "radio edit", "original mix", "extended", "dub", "version", "mono", "stereo",
    "reprise", "orchestral", "unplugged", "8d", "nightcore", "commentary", "rehearsal",
)

# Tags that are harmless when they appear on the catalog side only.
SOFT_TAGS = {"remaster", "remastered", "mono", "stereo", "version", "radio edit", "original mix"}

# Words in an artist name (or a title's decorations) that signal a knock-off
# recording rather than the real thing.
KNOCKOFF_WORDS = (
    "karaoke", "tribute", "cover band", "covers", "in the style of", "made famous",
    "originally performed", "backing track", "sing along", "ringtone", "8d audio",
    "lullaby", "lullabies", "kidz", "piano version", "music box",
)

# Featuring credits: "(feat. X)", "[with X]", or a trailing " feat. X". The
# keyword must be a whole word ("Loft Music" and "Dancing With Myself" are titles).
_FEAT_RE = re.compile(
    r"(?:\s*[\(\[]\s*(?:feat\.?|featuring|ft\.?|with)\s+[^\)\]]*[\)\]]"
    r"|\s+(?:feat\.?|featuring|ft\.?)\s+.*$)",
    re.IGNORECASE,
)
# Only parentheticals that follow some other text count as decorations;
# a title that *starts* with one ("(Nothing but) Flowers") keeps it.
_PAREN_RE = re.compile(r"(?<=\S)\s*[\(\[][^\)\]]*[\)\]]")
_DASH_SUFFIX_RE = re.compile(r"\s+[-–—]\s+.*$")
_NON_WORD_RE = re.compile(r"[^\w ]+")  # \w is Unicode-aware: keeps 紅蓮華, 방탄소년단, Кино
_WS_RE = re.compile(r"\s+")
# Unambiguous credit separators...
_CREDIT_SPLIT_RE = re.compile(r"\s*(?:;|\bfeat\b\.?|\bfeaturing\b|\bft\b\.?|\bvs\b\.?|\bwith\b)\s*", re.IGNORECASE)
# ...and joiners that are also common inside band names ("Simon & Garfunkel").
_JOIN_SPLIT_RE = re.compile(r"\s+(?:&|and|\+|x|/)\s+", re.IGNORECASE)


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace. Keeps every script."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ").replace("+", " and ")
    text = text.replace("'", "").replace("’", "")
    text = _NON_WORD_RE.sub(" ", text).replace("_", " ")
    return _WS_RE.sub(" ", text).strip()


def strip_featuring(title: str) -> str:
    return _FEAT_RE.sub("", title or "").strip()


def core_title(title: str) -> str:
    """The title with featuring credits, parentheticals and dash suffixes removed.

    ``"Midnight City (feat. X) - 2011 Remaster"`` -> ``"Midnight City"``.
    """
    t = strip_featuring(title or "")
    t = _PAREN_RE.sub("", t)
    t = _DASH_SUFFIX_RE.sub("", t)
    t = t.strip(" -–—")
    return t or (title or "").strip()


def _decorations(title: str) -> list[str]:
    out = [m.group(0) for m in _PAREN_RE.finditer(title or "")]
    m = _DASH_SUFFIX_RE.search(strip_featuring(title or ""))
    if m:
        out.append(m.group(0))
    return out


def title_tags(title: str) -> set[str]:
    """Version tags (live, remix, ...) found in the decorations of a title."""
    if not title:
        return set()
    text = normalize(" ".join(_decorations(title)))
    found = set()
    for tag in VERSION_TAGS:
        if re.search(rf"\b{re.escape(tag)}\b", text):
            found.add(tag)
    # Compound tags swallow their parts: "remix" is not also a "mix", "radio
    # edit" is not also an "edit", and "original mix" is the plain version.
    if "remix" in found or "original mix" in found:
        found.discard("mix")
    if "radio edit" in found:
        found.discard("edit")
    return found


def _split_list(chunk: str) -> list[str]:
    commas = [c.strip() for c in chunk.split(",") if c.strip()]
    if len(commas) > 1:
        has_join = bool(_JOIN_SPLIT_RE.search(chunk))
        # "Tyler, The Creator", "Earth, Wind & Fire", "Crosby, Stills, Nash & Young"
        if any(c.lower().startswith("the ") for c in commas[1:]) or \
                (has_join and any(len(c.split()) == 1 for c in commas)):
            return [chunk.strip()]
    out: list[str] = []
    for c in commas:
        pieces = [p.strip() for p in _JOIN_SPLIT_RE.split(c) if p.strip()]
        # Split "Calvin Harris & Dua Lipa", keep "Simon & Garfunkel", "Iron & Wine".
        if len(pieces) > 1 and all(len(p.split()) >= 2 for p in pieces):
            out.extend(pieces)
        else:
            out.append(c)
    return out


def split_artists(artist: str) -> list[str]:
    """Split a credit like ``"Drake, Rihanna feat. Future"`` into individual names.

    Joiners that also occur inside band names (``&``, ``and``, ``+``, ``x``,
    ``/``) only split when every side looks like a full name.
    """
    if not artist:
        return []
    parts: list[str] = []
    for chunk in _CREDIT_SPLIT_RE.split(artist):
        chunk = chunk.strip(" ,")
        if chunk:
            parts.extend(_split_list(chunk))
    return parts or [artist.strip()]


def primary_artist(artist: str) -> str:
    parts = split_artists(artist)
    return parts[0] if parts else (artist or "")


def looks_like_knockoff(title: str, artist: str) -> bool:
    """Karaoke/tribute/lullaby versions, judged from the artist and the title's
    decorations only (the songs "Lullaby" and "Tribute" are real songs)."""
    text = f"{normalize(artist)} | {normalize(' '.join(_decorations(title)))}"
    return any(re.search(rf"\b{re.escape(normalize(w))}\b", text) for w in KNOCKOFF_WORDS)


def _token_set(text: str) -> set[str]:
    return set(normalize(text).split())


def similarity(a: str, b: str) -> float:
    """Name similarity (0..1): character ratio, token overlap, whole-word containment."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = na.split(), nb.split()
    jaccard = len(set(ta) & set(tb)) / len(set(ta) | set(tb))
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    short_str, long_str = " ".join(shorter), " ".join(longer)
    if len(shorter) == 1 and set(shorter) < set(longer):
        return max(jaccard, 0.5)  # one word of a longer name: "Japan" is not "X Japan"
    containment = 0.0
    if len(shorter) >= 2 and f" {short_str} " in f" {long_str} ":
        containment = 1.0  # "Bob Marley" in "Bob Marley & The Wailers"
    return max(ratio, 0.5 * ratio + 0.5 * jaccard, 0.85 * containment)


def title_similarity(a: str, b: str) -> float:
    """Title similarity (0..1). Stricter than :func:`similarity`: extra words
    usually mean a different song ("Revolution 9"), and one-word titles must be
    spelled nearly the same ("Hero" is not "Heroes", "Colour" is "Color")."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = na.split(), nb.split()
    sa, sb = set(ta), set(tb)
    ratio = SequenceMatcher(None, na, nb).ratio()
    jaccard = len(sa & sb) / len(sa | sb)
    if sa < sb or sb < sa:
        return jaccard
    if len(ta) == 1 and len(tb) == 1:
        return ratio if ratio >= 0.9 else ratio * 0.6
    return 0.5 * ratio + 0.5 * max(jaccard, ratio * ratio)


def _strip_the(name: str) -> str:
    n = normalize(name)
    return n[4:] if n.startswith("the ") and len(n) > 4 else n


def artist_similarity(candidate_artist: str, track_artists: Sequence[str]) -> float:
    """How well a candidate's artist credit matches a catalog track's artists."""
    if not candidate_artist or not track_artists:
        return 0.0
    cand_parts = split_artists(candidate_artist)
    cand_primary = cand_parts[0]
    track_parts: list[str] = []
    for a in track_artists:
        track_parts.extend(split_artists(a))
    best = 0.0
    for tp in track_parts:
        best = max(best, similarity(_strip_the(cand_primary), _strip_the(tp)))
    best = max(best, similarity(_strip_the(candidate_artist), _strip_the(" ".join(track_artists))))
    for a in track_artists:
        best = max(best, similarity(_strip_the(candidate_artist), _strip_the(a)))
    return best


def duration_penalty(a: Optional[float], b: Optional[float]) -> float:
    """Multiplicative penalty (0..1) for a duration mismatch in seconds."""
    if a is None or b is None or a <= 0 or b <= 0:
        return 1.0
    diff = abs(a - b)
    if diff <= 3:
        return 1.0
    if diff <= 10:
        return 0.95
    if diff <= 30:
        return 0.8
    if diff <= 60:
        return 0.6
    return 0.35


def score_match(
    cand_title: str,
    cand_artist: str,
    track_title: str,
    track_artists: Sequence[str],
    cand_duration: Optional[float] = None,
    track_duration: Optional[float] = None,
) -> float:
    """Score (0..1) how likely ``track`` is the same recording as the candidate."""
    if not cand_title or not track_title:
        return 0.0
    t_core = title_similarity(core_title(cand_title), core_title(track_title))
    t_full = title_similarity(strip_featuring(cand_title), strip_featuring(track_title))
    # An exact full title (version included) beats a match on the bare title.
    title_score = max(t_core, t_full) * (0.97 + 0.03 * t_full)
    artist_score = artist_similarity(cand_artist, list(track_artists))

    score = 0.6 * title_score + 0.4 * artist_score
    # Neither half may be carried by the other: the same title by an unrelated
    # artist is a cover, and a related artist does not make a different title right.
    if artist_score < 0.5:
        score *= artist_score / 0.5
    if title_score < 0.75:
        score *= title_score / 0.75

    cand_tags = title_tags(cand_title)
    track_tags = title_tags(track_title)
    unexpected = {t for t in (track_tags - cand_tags) if t not in SOFT_TAGS}
    missing = {t for t in (cand_tags - track_tags) if t not in SOFT_TAGS}
    if unexpected:
        score *= 0.55
    if missing:
        score *= 0.8

    if looks_like_knockoff(track_title, " ".join(track_artists)) and not looks_like_knockoff(cand_title, cand_artist):
        score *= 0.3

    score *= duration_penalty(cand_duration, track_duration)
    return max(0.0, min(1.0, score))


DEFAULT_ACCEPT_THRESHOLD = 0.72


def best_match(candidates: Iterable, scorer) -> tuple[Optional[object], float]:
    """Return ``(item, score)`` for the highest scoring item, or ``(None, 0.0)``."""
    best_item, best_score = None, 0.0
    for item in candidates:
        s = scorer(item)
        if s > best_score:
            best_item, best_score = item, s
    return best_item, best_score


def same_song(title_a: str, artist_a: str, title_b: str, artist_b: str) -> bool:
    """Loose equality used for "is this the song we just played?" checks."""
    if score_match(title_a, artist_a, title_b, [artist_b]) < 0.8:
        return False
    return (normalize(core_title(title_a)) == normalize(core_title(title_b))
            or title_similarity(strip_featuring(title_a), strip_featuring(title_b)) >= 0.9)
