"""Shuffle flows: how the next song should relate to the one playing.

The song radio decides *which* songs are candidates; the flow decides which of
them fits the moment, from each song's audio features (see features.py):

* ``radio``       follow the song radio as it is (no audio features needed)
* ``rising``      each song a little more energetic than the last (warm-up)
* ``falling``     each song a little calmer than the last (wind-down)
* ``steady``      keep one energy level: ``shuffle.energy``, or the first song's
* ``soundscape``  stay close to the *first* song's overall sound: energy, mood,
                  acoustic or electronic, instrumental, tempo; no drifting
* ``vibe``        stay close to the *current* song's mood and energy; the
                  mood can drift slowly over a long session

A flow gives every candidate a fit between 0 and 1; the pick strategy
(top / weighted / random / discovery) then weighs fit against how close to
the top of the radio a song is. Songs with no audio features get a low fit,
so they are still possible but rarely chosen; if none of the candidates has
features, the flow steps aside and the plain radio order is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .features import Features

FLOWS = ("radio", "rising", "falling", "steady", "soundscape", "vibe")
FLOW_HELP = {
    "radio": "the song radio as it is",
    "rising": "each song a little more energetic",
    "falling": "each song a little calmer",
    "steady": "one energy level throughout",
    "soundscape": "the same overall sound as the first song",
    "vibe": "the same mood and energy as the current song",
}
LOW, HIGH = 0.08, 0.96
UNKNOWN_FIT = 0.3


@dataclass
class FlowResult:
    fits: dict = field(default_factory=dict)        # candidate key -> fit 0..1
    target: Optional[float] = None                  # target energy, when the flow has one
    note: str = ""


def _gauss(x: float, width: float) -> float:
    return math.exp(-(x / width) ** 2)


def score(flow: str, candidates: dict, seed: Optional[Features], anchor: Optional[Features],
          level: Optional[float] = None, step: float = 0.06, last_target: Optional[float] = None) -> FlowResult:
    """``candidates``: key -> Features or None. Returns fits for the flow."""
    if flow == "radio" or not candidates:
        return FlowResult()
    known = {k: f for k, f in candidates.items() if f is not None}
    if not known:
        return FlowResult(note=f"{flow}: no audio features for these songs; following the song radio")
    res = FlowResult()
    if flow in ("rising", "falling", "steady"):
        if flow == "steady":
            base = level if level is not None else (anchor.energy if anchor else (seed.energy if seed else last_target))
            target = base
        else:
            base = seed.energy if seed else last_target
            if base is None:
                base = sum(f.energy for f in known.values()) / len(known)   # the radio's own average
            target = base + step if flow == "rising" else base - step
        if target is None:
            return FlowResult(note=f"{flow}: energy of the current song unknown; following the song radio")
        target = max(LOW, min(HIGH, target))
        res.target = target
        for k, f in candidates.items():
            res.fits[k] = UNKNOWN_FIT if f is None else _gauss(f.energy - target, 0.12)
        res.note = f"{flow}: energy {'?' if base is None else f'{base:.2f}'} → {target:.2f} ({len(known)}/{len(candidates)} songs rated)"
        return res
    if flow == "soundscape":
        ref = anchor or seed
        width, only = 0.16, None
    else:  # vibe
        ref = seed or anchor
        width, only = 0.14, ("energy", "valence", "danceability")
    if ref is None:
        return FlowResult(note=f"{flow}: no audio features for the reference song; following the song radio")
    for k, f in candidates.items():
        res.fits[k] = UNKNOWN_FIT if f is None else _gauss(f.distance(ref, only), width)
    res.target = ref.energy
    res.note = f"{flow}: close to {'the first song' if flow == 'soundscape' and anchor else 'the current song'} ({len(known)}/{len(candidates)} songs rated)"
    return res
