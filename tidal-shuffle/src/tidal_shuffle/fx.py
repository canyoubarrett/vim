"""The rain behind the panels, and the compositor that lays the panels over it.

Rich lays out one box at a time and paints every cell; to have a living
background *behind* the boxes, the screen is composed here instead: the rain
is drawn first, then every panel is rendered by Rich on its own and laid on
top. Panel cells in the theme's base colour are "glass": they take a little
of the sky's colour and the rain behind shows through them, faintly. A panel
can be laid down part-transparent (``opacity``), which is how panels fade in
and out.

The rain is a pure function of time, so frames never jump: pausing slows it
down rather than stopping it.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

from rich.cells import cell_len

Color = tuple[int, int, int]
Cell = tuple  # (char, fg, bold, bg)



def lerp(a: Color, b: Color, t: float) -> Color:
    if t <= 0:
        return a
    if t >= 1:
        return b
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def _hash(*xs: int) -> float:
    """A stable pseudo-random number in [0, 1) for integer inputs."""
    h = 2166136261
    for x in xs:
        h = ((h ^ (x & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0x5BD1E995) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 4294967296.0


def spring(x: float, v: float, target: float, dt: float, omega: float) -> tuple[float, float]:
    """One step of a critically damped spring: smooth start, smooth stop, no
    overshoot, and it follows a target that changes half way without a jolt."""
    if dt <= 0:
        return x, v
    f = 1.0 + 2.0 * dt * omega
    oo = omega * omega
    det = 1.0 / (f + dt * dt * oo)
    nx = (f * x + dt * v + dt * dt * oo * target) * det
    nv = (v + dt * oo * (target - x)) * det
    return nx, nv


# braille bit for the dot at (dx, dy) of a 2x4 cell
_BIT_AT = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
           (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}


class Backdrop:
    """Rain behind the panels, over a night-sky gradient.

    Two depths: far drops dim, short and slow, near drops brighter, longer and
    faster, all slanting a little in the wind. They are drawn in braille dots
    (2x4 per cell), so they fall smoothly, a quarter of a row at a time. The
    rain follows the music: a drizzle for calm songs, heavier for energetic
    ones (eased, so it never changes all at once). Paused, it falls in slow
    motion."""

    def __init__(self, palette: dict, light: bool = False):
        self.p = palette
        self.light = light                       # Catppuccin Latte: a pale sky
        self._t = 0.0
        self._last: Optional[float] = None
        self._density = 0.75

    def advance(self, now: float, playing: bool = True) -> float:
        dt = 0.0 if self._last is None else max(0.0, min(0.5, now - self._last))
        self._last = now
        self._t += dt * (1.0 if playing else 0.25)
        return dt

    def frame(self, w: int, h: int, now: float, energy: float = 0.5, playing: bool = True) -> list[list[list]]:
        """``h`` rows of ``w`` mutable cells [char, fg, bold, bg]."""
        dt = self.advance(now, playing)
        t = self._t
        p = self.p
        target = 0.55 + 0.6 * max(0.0, min(1.0, energy))
        if dt == 0:
            self._density = target                # first frame: no easing from nothing
        else:
            self._density += (target - self._density) * min(1.0, dt / 3.0)
        top, bottom = (p["crust"], p["base"]) if not self.light else (p["base"], p["mantle"])
        rows = []
        for y in range(h):
            bg = lerp(top, bottom, y / max(1, h - 1))
            rows.append([[" ", None, False, bg] for _ in range(w)])
        far = lerp(top, p["overlay0"], 0.55 if not self.light else 0.35)
        near = lerp(p["overlay2"], p["sky"], 0.25)
        layers = (
            # count, speed (dots/s), length (dots), colour, slant (dots across per dot down)
            (w * h / 7.0, 30.0, 3, far, 0.10),
            (w * h / 26.0, 58.0, 6, near, 0.16),
        )
        bits: dict = {}
        color: dict = {}
        H = h * 4
        for li, (count, speed, length, col, slant) in enumerate(layers):
            n = int(count * self._density)
            span_x = w * 2 + slant * H
            for i in range(n):
                spd = speed * (0.85 + 0.3 * _hash(i, li, 4))
                total = H + length + 8
                pos = (t * spd + _hash(i, li, 2) * total) % total
                x0 = _hash(i, li, 1) * span_x - slant * H
                for k in range(length):
                    yd = pos - k
                    if 0 <= yd < H:
                        xd = int(x0 + slant * yd)
                        yi = int(yd)
                        cx, cy = xd // 2, yi // 4
                        if 0 <= cx < w:
                            key = (cy, cx)
                            bits[key] = bits.get(key, 0) | _BIT_AT[(xd % 2, yi % 4)]
                            if li or key not in color:
                                color[key] = col
        for (cy, cx), b in bits.items():
            cell = rows[cy][cx]
            cell[0], cell[1] = chr(0x2800 + b), color[(cy, cx)]
        return rows


class Canvas:
    """Cells to paint panels onto, over a backdrop."""

    def __init__(self, cells: list, base_bg: Color, text: Color, glass: float = 0.2):
        self.cells = cells
        self.h = len(cells)
        self.w = len(cells[0]) if cells else 0
        self.base_bg = base_bg
        self.text = text
        self.glass = glass
        self.see = min(1.0, glass * 1.4)        # how clearly the rain shows through glass
        self._style_cache: dict = {}
        self._widths: dict = {}

    def _parts(self, st):
        hit = self._style_cache.get(st)
        if hit is None:
            fg = bg = None
            bold = False
            if st is not None:
                if st.color is not None:
                    fg = tuple(st.color.get_truecolor())
                if st.bgcolor is not None:
                    bg = tuple(st.bgcolor.get_truecolor())
                bold = bool(st.bold)
                if st.reverse:
                    fg, bg = bg, fg
            hit = (fg, bold, bg)
            self._style_cache[st] = hit
        return hit

    def _width(self, ch: str) -> int:
        if ch < "̀":
            return 1
        wd = self._widths.get(ch)
        if wd is None:
            wd = cell_len(ch)
            self._widths[ch] = wd
        return wd

    def blit(self, lines: Iterable, x: int, y: int, w: int, h: int, opacity: float = 1.0) -> None:
        """Lay Rich-rendered ``lines`` (lists of Segments) into the box at x, y."""
        if opacity <= 0.01:
            return
        cells, base, glass = self.cells, self.base_bg, self.glass
        for r, line in enumerate(lines):
            if r >= h:
                break
            yy = y + r
            if not 0 <= yy < self.h:
                continue
            row = cells[yy]
            cx = x
            end = min(self.w, x + w)
            # the rain shows through open glass only, never between words
            text = "".join(seg.text for seg in line if not seg.control)
            k = -1
            for seg in line:
                if seg.control:
                    continue
                fg, bold, bg = self._parts(seg.style)
                for ch in seg.text:
                    k += 1
                    if cx >= end:
                        break
                    wd = self._width(ch)
                    if cx < 0:
                        cx += wd
                        continue
                    under = row[cx]
                    sky = under[3]
                    glassy = bg is None or bg == base
                    if glassy:
                        cbg = lerp(base, sky, glass)        # glass: tinted by the sky behind
                    else:
                        cbg = bg
                    cfg = fg or self.text
                    if (ch == " " and glassy and under[0] != " " and opacity >= 0.999
                            and text[max(0, k - 2):k + 3].strip() == ""):
                        # glass: the rain behind shows through, faintly
                        row[cx] = [under[0], lerp(cbg, under[1] or cbg, self.see), False, cbg]
                    elif opacity < 0.999:
                        nbg = lerp(sky, cbg, opacity)
                        if ch == " ":
                            # a faded panel lets what is under it show, dimmed by the panel
                            row[cx] = [under[0], lerp(nbg, under[1] or nbg, 1 - opacity) if under[1] else None,
                                       under[2], nbg]
                        else:
                            row[cx] = [ch, lerp(nbg, cfg, opacity), bold, nbg]
                    else:
                        row[cx] = [ch, cfg, bold, cbg]
                    if wd == 2 and cx + 1 < end:
                        row[cx + 1] = ["", None, False, row[cx][3]]
                    cx += wd


def segments(cells: list, style_of: Callable) -> Iterable:
    """Rich Segments for a canvas, one run per change of colour."""
    from rich.segment import Segment

    for row in cells:
        run: list[str] = []
        key = None
        for ch, fg, bold, bg in row:
            if not ch:
                continue
            if ch == " " and key is not None and key[2] == bg:
                run.append(ch)                   # a space only needs the background
                continue
            k = (fg, bold, bg) if ch != " " else (None, False, bg)
            if k != key and run:
                yield Segment("".join(run), style_of(*key))
                run = []
            key = k
            run.append(ch)
        if run:
            yield Segment("".join(run), style_of(*key))
        yield Segment.line()
