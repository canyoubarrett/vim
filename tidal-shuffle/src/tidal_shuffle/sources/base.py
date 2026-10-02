"""Common interface for recommendation sources."""

from __future__ import annotations

from typing import Optional, Protocol, Sequence, runtime_checkable

from ..models import Candidate, Seed


class SourceUnavailable(RuntimeError):
    """A source cannot be used right now (missing key, app not installed...)."""


@runtime_checkable
class Source(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """Return ``(ok, reason)``. ``reason`` explains a ``False``."""

    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        """Return up to ``limit`` candidates for the seed(s), most relevant first.

        Sources that only understand one seed use ``seeds[0]``.
        """


def tag(cands: list[Candidate], source: str) -> list[Candidate]:
    """Fill in ``source`` and ``rank`` for a freshly fetched list."""
    for i, c in enumerate(cands):
        c.source = c.source or source
        c.rank = i
    return cands


def dedupe(cands: Sequence[Candidate]) -> list[Candidate]:
    seen: set = set()
    out: list[Candidate] = []
    for c in cands:
        if c.key in seen or not c.title or not c.artist:
            continue
        seen.add(c.key)
        out.append(c)
    return out


class StaticSource:
    """A source backed by a fixed list; handy for tests and dry runs."""

    name = "static"

    def __init__(self, cands: Optional[list[Candidate]] = None, name: str = "static", ok: bool = True, reason: str = ""):
        self._cands = list(cands or [])
        self.name = name
        self._ok = ok
        self._reason = reason
        self.calls: list[tuple[list[Seed], int]] = []

    def available(self) -> tuple[bool, str]:
        return self._ok, self._reason

    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        self.calls.append((list(seeds), limit))
        return tag([Candidate(**{**c.__dict__}) for c in self._cands[:limit]], self.name)
