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
    "radio edit", "extended", "dub", "version", "mono", "stereo", "reprise",
    "orchestral", "unplugged", "8d", "nightcore", "commentary", "rehearsal",
)

# Tags that are harmless when they appear on the catalog side only.
SOFT_TAGS = {"remaster", "remastered", "mono", "stereo", "version", "radio edit"}

# Artist names that signal a knock-off recording rather than the real thing.
KNOCKOFF_ARTIST_WORDS = (
    "karaoke", "tribute", "cover band", "in the style of", "made famous",
    "originally performed", "backing track", "sing-along", "ringtone",
    "8d audio", "lullaby", "kidz", "piano version", "music box",
)

_FEAT_RE = re.compile(r"\s*[\(\[]?\s*(?:feat\.?|featuring|ft\.?|with)\s+[^\)\]]*[\)\]]?", re.IGNORECASE)
# Only parentheticals that follow some other text count as decorations;
# a title that *starts* with one ("(Nothing but) Flowers") keeps it.
_PAREN_RE = re.compile(r"(?<=\S)\s*[\(\[][^\)\]]*[\)\]]")
_DASH_SUFFIX_RE = re.compile(r"\s+[-–—]\s+.*$")
_NON_WORD_RE = re.compile(r"[^0-9a-z ]+")
_WS_RE = re.compile(r"\s+")
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\+|/|;|\bfeat\b\.?|\bfeaturing\b|\bft\b\.?|\bvs\b\.?|\bx\b|\bwith\b|\band\b)\s*",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ").replace("+", " and ")
    text = text.replace("'", "").replace("’", "")
    text = _NON_WORD_RE.sub(" ", text)
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


def title_tags(title: str) -> set[str]:
    """Version tags (live, remix, ...) found in the decorations of a title."""
    if not title:
        return set()
    decorations = []
    decorations.extend(m.group(0) for m in _PAREN_RE.finditer(title))
    m = _DASH_SUFFIX_RE.search(strip_featuring(title))
    if m:
        decorations.append(m.group(0))
    text = normalize(" ".join(decorations))
    found = set()
    for tag in VERSION_TAGS:
        if re.search(rf"\b{re.escape(tag)}\b", text):
            found.add(tag)
    # "mix" only counts when it is not part of "remix" already handled above.
    if "remix" in found:
        found.discard("mix")
    return found


def split_artists(artist: str) -> list[str]:
    """Split a credit string like ``"A, B & C feat. D"`` into individual names."""
    if not artist:
        return []
    parts = [p.strip() for p in _ARTIST_SPLIT_RE.split(artist) if p and p.strip()]
    return parts or [artist.strip()]


def primary_artist(artist: str) -> str:
    parts = split_artists(artist)
    return parts[0] if parts else (artist or "")


def looks_like_knockoff(title: str, artist: str) -> bool:
    text = normalize(f"{title} {artist}")
    return any(word in text for word in KNOCKOFF_ARTIST_WORDS)


def _token_set(text: str) -> set[str]:
    return set(normalize(text).split())


def similarity(a: str, b: str) -> float:
    """Blend of character-level ratio and token overlap, 0..1."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    # Containment helps with "Song" vs "Song (Deluxe Mix Thing)".
    containment = 1.0 if (na in nb or nb in na) else 0.0
    return max(ratio, 0.5 * ratio + 0.5 * jaccard, 0.85 * containment)


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
        best = max(best, similarity(cand_primary, tp))
    # Whole-string comparison catches "Simon & Garfunkel" style names that the
    # splitter tears apart.
    best = max(best, similarity(candidate_artist, " ".join(track_artists)))
    for a in track_artists:
        best = max(best, similarity(candidate_artist, a))
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
    t_core = similarity(core_title(cand_title), core_title(track_title))
    t_full = similarity(strip_featuring(cand_title), strip_featuring(track_title))
    title_score = max(t_core, t_full)
    artist_score = artist_similarity(cand_artist, list(track_artists))

    score = 0.6 * title_score + 0.4 * artist_score

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
    return score_match(title_a, artist_a, title_b, [artist_b]) >= 0.8
