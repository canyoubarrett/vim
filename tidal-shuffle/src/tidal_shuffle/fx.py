"""The animated backdrop behind the panels, and the compositor that lays the
panels over it.

Rich lays out one box at a time and paints every cell; to have a living
background *behind* the boxes, the screen is composed here instead: the
backdrop is drawn first (aurora curtains, twinkling stars, the odd shooting
star, slow bokeh drifting up), then every panel is rendered by Rich on its own
and laid on top. Panel cells in the theme's base colour are "glass": they
take a little of the backdrop's colour, so the aurora glows faintly through.
A panel can be laid down part-transparent (``opacity``), which is how panels
fade in and out. Panel borders pick up the light around them, and a soft
sheen travels along them.

Everything is a pure function of time, so frames are cheap to reason about
and never jump: pausing slows the sky down rather than stopping it.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

from rich.cells import cell_len

Color = tuple[int, int, int]
Cell = tuple  # (char, fg, bold, bg)

BOX = set("─│╭╮╰╯┌┐└┘├┤┬┴┼━┃")


def lerp(a: Color, b: Color, t: float) -> Color:
    if t <= 0:
        return a
    if t >= 1:
        return b
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def add(a: Color, b: Color, t: float) -> Color:
    """Additive light: ``a`` brightened by ``b`` at strength ``t``."""
    return (min(255, int(a[0] + b[0] * t)), min(255, int(a[1] + b[1] * t)), min(255, int(a[2] + b[2] * t)))


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


class Backdrop:
    """The sky behind the panels."""

    def __init__(self, palette: dict, light: bool = False):
        self.p = palette
        self.light = light                       # Catppuccin Latte: a pale sky
        self._t = 0.0
        self._last: Optional[float] = None

    def advance(self, now: float, playing: bool = True) -> float:
        dt = 0.0 if self._last is None else max(0.0, min(0.5, now - self._last))
        self._last = now
        self._t += dt * (1.0 if playing else 0.25)
        return self._t

    def colors(self, energy: float) -> list[Color]:
        """Aurora colours: cool for calm music, warm for energetic."""
        p = self.p
        if energy < 0.35:
            return [p["teal"], p["blue"], p["sapphire"]]
        if energy < 0.65:
            return [p["mauve"], p["blue"], p["teal"]]
        return [p["pink"], p["mauve"], p["peach"]]

    def frame(self, w: int, h: int, now: float, energy: float = 0.5, playing: bool = True) -> list[list[list]]:
        """``h`` rows of ``w`` mutable cells [char, fg, bold, bg]."""
        t = self.advance(now, playing)
        p = self.p
        top, bottom = (p["crust"], p["base"]) if not self.light else (p["base"], p["mantle"])
        speed = 0.55 + 0.9 * energy
        cols = self.colors(energy)
        strength = 0.5 if not self.light else 0.2
        # aurora ribbons: a centre line per column, computed once per frame
        ribbons = []
        for k, col in enumerate(cols):
            phase = k * 2.1
            centre = []
            curtain = []
            for x in range(w):
                u = x / max(1, w)
                cy = h * (0.18 + 0.1 * k + 0.09 * math.sin(u * 5.3 + t * 0.21 * speed + phase)
                          + 0.04 * math.sin(u * 13.1 - t * 0.37 * speed + phase * 1.7))
                centre.append(cy)
                c = 0.55 + 0.45 * math.sin(u * 31.0 + t * 0.8 * speed + phase * 3.1)
                c *= 0.6 + 0.4 * math.sin(u * 7.0 - t * 0.33 + phase)
                curtain.append(max(0.0, c))
            ribbons.append((col, centre, curtain, max(1.5, h * 0.05), h * (0.22 + 0.05 * k)))
        rows = []
        cols_x = range(0, w, 2)               # the sky is smooth: work out every other column
        for y in range(h):
            v = y / max(1, h - 1)
            br = top[0] + (bottom[0] - top[0]) * v
            bgc = top[1] + (bottom[1] - top[1]) * v
            bb = top[2] + (bottom[2] - top[2]) * v
            row = []
            for x in cols_x:
                r, g, b = br, bgc, bb
                for col, centre, curtain, thick, hang in ribbons:
                    d = y - centre[x]
                    i = math.exp(-(d / thick) ** 2) if d < 0 else math.exp(-d / hang)
                    i *= curtain[x] * strength
                    if i > 0.007:
                        r += (col[0] - r) * i
                        g += (col[1] - g) * i
                        b += (col[2] - b) * i
                bg = (int(r), int(g), int(b))
                row.append([" ", None, False, bg])
                if x + 1 < w:
                    row.append([" ", None, False, bg])
            rows.append(row)
        self._stars(rows, w, h, t)
        self._bokeh(rows, w, h, t, cols)
        self._shooting_star(rows, w, h, t)
        return rows

    def _stars(self, rows, w, h, t) -> None:
        p = self.p
        n = max(4, w * h // 55)
        for i in range(n):
            x = int(_hash(i, 1) * w)
            y = int(_hash(i, 2) * h * 0.85)
            tw = 0.5 + 0.5 * math.sin(t * (0.8 + 2.2 * _hash(i, 3)) + 6.3 * _hash(i, 4))
            if tw < 0.15:
                continue
            kind = _hash(i, 5)
            ch = "✦" if kind > 0.94 else ("+" if kind > 0.85 else ("•" if kind > 0.7 else "·"))
            cell = rows[y][x]
            color = lerp(cell[3], p["rosewater"] if kind > 0.85 else p["lavender"], 0.25 + 0.75 * tw)
            cell[0], cell[1] = ch, color

    def _bokeh(self, rows, w, h, t, cols) -> None:
        n = max(3, w // 12)
        for i in range(n):
            rise = 0.6 + 1.4 * _hash(i, 11)
            y = h - ((t * rise + _hash(i, 12) * (h + 6)) % (h + 6)) + 3
            x = _hash(i, 13) * w + 2.5 * math.sin(t * 0.4 + i)
            yi, xi = int(y), int(x)
            if 0 <= yi < h and 0 <= xi < w:
                col = cols[i % len(cols)]
                fade = math.sin(math.pi * max(0.0, min(1.0, (h - y) / h)))
                cell = rows[yi][xi]
                cell[0] = "●" if _hash(i, 14) > 0.6 else "∙"
                cell[1] = lerp(cell[3], col, 0.25 + 0.35 * fade)
                if 0 <= xi + 1 < w:   # a soft halo
                    rows[yi][xi + 1][3] = lerp(rows[yi][xi + 1][3], col, 0.08 * fade)
                if 0 <= xi - 1:
                    rows[yi][xi - 1][3] = lerp(rows[yi][xi - 1][3], col, 0.08 * fade)

    def _shooting_star(self, rows, w, h, t) -> None:
        period = 11.0
        k = int(t // period)
        age = t - k * period
        if age > 1.1 or w < 20:
            return
        x0 = _hash(k, 21) * w * 0.7 + w * 0.05
        y0 = _hash(k, 22) * h * 0.35
        travel = age / 1.1
        head_x = x0 + travel * w * 0.45
        head_y = y0 + travel * h * 0.22
        fade = math.sin(math.pi * travel)
        for j in range(14):
            x = int(head_x - j * 1.6)
            y = int(head_y - j * 1.6 * 0.49)
            if 0 <= y < h and 0 <= x < w:
                cell = rows[y][x]
                cell[0] = "━" if j else "✦"
                cell[1] = lerp(cell[3], self.p["rosewater"], fade * (1 - j / 14))


class Canvas:
    """Cells to paint panels onto, over a backdrop."""

    def __init__(self, cells: list, base_bg: Color, text: Color, glass: float = 0.2):
        self.cells = cells
        self.h = len(cells)
        self.w = len(cells[0]) if cells else 0
        self.base_bg = base_bg
        self.text = text
        self.glass = glass
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
            for seg in line:
                if seg.control:
                    continue
                fg, bold, bg = self._parts(seg.style)
                for ch in seg.text:
                    if cx >= end:
                        break
                    wd = self._width(ch)
                    if cx < 0:
                        cx += wd
                        continue
                    under = row[cx]
                    sky = under[3]
                    if bg is None or bg == base:
                        # glass: the backdrop glows through (in steps of 4, so that
                        # neighbouring cells share a colour and the output stays small)
                        g = lerp(base, sky, glass)
                        cbg = (g[0] & ~3, g[1] & ~3, g[2] & ~3)
                    else:
                        cbg = bg
                    cfg = fg or self.text
                    if opacity < 0.999:
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

    def sheen(self, t: float, border: Color, light: Color) -> None:
        """Panel borders catch the light: the backdrop's glow, and a sheen
        travelling diagonally across the screen."""
        for y, row in enumerate(self.cells):
            for x, cell in enumerate(row):
                if cell[0] in BOX and cell[1] == border:
                    s = math.sin((x * 0.5 + y) * 0.09 - t * 0.9)
                    k = max(0.0, s) ** 10 * 0.75
                    cell[1] = lerp(add(border, cell[3], 0.35), light, k)


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
