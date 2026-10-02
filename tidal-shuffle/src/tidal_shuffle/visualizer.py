"""The Alter Era scene for the TUI: Everforest-aqua digital rain with the logo
floating over it.

The logo is braille art. Each braille character is a 2x4 grid of dots, so the
art is turned into individual dots once and redrawn every frame after a small
rotation and a sub-character shift. That gives quarter-row vertical motion and
a gentle tilt instead of jumping a whole character at a time. The float is a
slow bob with a faster overtone, a lazy sideways drift, and a tilt that leans
into the drift; a soft shadow below shrinks and fades as the logo rises.

The rain follows fx_matrix.py: bright heads, trails fading toward the
background, half-width katakana. It is time based, so it runs at the same
speed whatever the frame rate, and it comes to rest while the music is paused.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

Color = tuple[int, int, int]

GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜ0123456789:.=*+<>|╌╎"

# Everforest aqua, as in fx_matrix.py
BG: Color = (28, 35, 40)
HEADC: Color = (205, 228, 214)
RAINC: Color = (126, 184, 150)
LOGOC: Color = (131, 192, 146)
LOGO_HI: Color = (167, 219, 178)
SHADOW: Color = (78, 102, 92)

# braille dot bit -> (dx, dy) inside the 2x4 cell
_BITS = {0x01: (0, 0), 0x02: (0, 1), 0x04: (0, 2), 0x40: (0, 3),
         0x08: (1, 0), 0x10: (1, 1), 0x20: (1, 2), 0x80: (1, 3)}
_BIT_AT = {v: k for k, v in _BITS.items()}

ASSET = Path(__file__).parent / "assets" / "alter-era.txt"


def lerp(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def smoothstep(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def load_art(path: Optional[Path] = None) -> tuple[list[str], list[str]]:
    """The ---BIG--- and ---SMALL--- logos from an alter-era.txt style file."""
    big: list[str] = []
    small: list[str] = []
    cur = None
    try:
        text = Path(path or ASSET).read_text(encoding="utf-8")
    except OSError:
        return [], []
    for line in text.splitlines():
        if line == "---BIG---":
            cur = big
            continue
        if line == "---SMALL---":
            cur = small
            continue
        if cur is not None:
            cur.append(line)
    return big, small


def art_to_dots(art: list[str]) -> list[tuple[float, float]]:
    """Dot coordinates (x, y in dot units), centred on the art's middle."""
    dots: list[tuple[int, int]] = []
    for row, line in enumerate(art):
        for col, ch in enumerate(line):
            code = ord(ch) - 0x2800
            if 0 < code <= 0xFF:
                for bit, (dx, dy) in _BITS.items():
                    if code & bit:
                        dots.append((col * 2 + dx, row * 4 + dy))
            elif ch.strip() and not (0 <= code <= 0xFF):
                dots.append((col * 2, row * 4 + 1))  # stray non-braille mark: one dot
    if not dots:
        return []
    xs = [d[0] for d in dots]
    ys = [d[1] for d in dots]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return [(x - cx, y - cy) for x, y in dots]


@dataclass
class _Drop:
    x: int
    head: float          # row of the head (float)
    speed: float         # rows per second
    length: int          # trail length
    wait: float          # seconds before it starts falling again


class AlterEraScene:
    """Renders frames as rows of (char, color or None) cells."""

    def __init__(self, art_path: Optional[Path] = None, seed: Optional[int] = None):
        big, small = load_art(art_path)
        self.arts = [a for a in (big, small) if a]
        self._dots = {id(a): art_to_dots(a) for a in self.arts}
        self.rng = random.Random(seed)
        self._drops: list[_Drop] = []
        self._glyphs: dict[tuple[int, int], str] = {}
        self._size = (0, 0)
        self._last_t: Optional[float] = None
        self._float_t = 0.0      # time the float has been running (keeps going, slower, when paused)
        self._rain_t = 0.0
        self.shown_at: Optional[float] = None

    # -- logo --------------------------------------------------------------------
    def _pick_art(self, width: int, height: int):
        """The logo and scale that fit: the big one when it fits at 60% or more."""
        best = None
        for art in self.arts:
            aw = max(len(l) for l in art) if art else 0
            ah = len(art)
            if not aw or not ah:
                continue
            room_w, room_h = width - 6, height - 4      # margin for the float and the shadow
            scale = min(1.0, room_w / aw, room_h / ah)
            if scale >= 0.6 or (best is None and scale > 0.25):
                if best is None or scale * ah > best[1] * len(best[0]):
                    best = (art, scale)
        return best

    def logo_pose(self, t: float) -> tuple[float, float, float]:
        """(dx, dy) in dots and tilt in radians at float time t: a buoyant bob."""
        bob = 3.2 * math.sin(2 * math.pi * t / 5.4) + 0.9 * math.sin(2 * math.pi * t / 2.3 + 1.1)
        drift = 4.0 * math.sin(2 * math.pi * t / 9.7) + 1.2 * math.sin(2 * math.pi * t / 4.1 + 0.4)
        # lean into the drift: tilt follows the sideways velocity
        vel = (4.0 * 2 * math.pi / 9.7) * math.cos(2 * math.pi * t / 9.7)
        tilt = math.radians(1.6) * (vel / (4.0 * 2 * math.pi / 9.7)) + math.radians(0.6) * math.sin(2 * math.pi * t / 3.7)
        return drift, bob, tilt

    def _logo_cells(self, width: int, height: int, t: float) -> tuple[dict, float, tuple]:
        """Braille cells of the logo for this frame, plus how high it floats (0..1)
        and its footprint (left, right, bottom) in cells for the shadow."""
        pick = self._pick_art(width, height)
        if pick is None:
            return {}, 0.0, (0, 0, 0)
        art, scale = pick
        dots = self._dots[id(art)]
        dx, dy, tilt = self.logo_pose(t)
        cx = width * 2 / 2 + dx
        cy = (height - 2) * 4 / 2 + dy          # leave the bottom rows for the shadow
        c, s = math.cos(tilt), math.sin(tilt)
        cells: dict[tuple[int, int], int] = {}
        min_c, max_c, max_r = 10 ** 9, -1, -1
        for x, y in dots:
            x *= scale
            y *= scale
            px = cx + x * c - y * s
            py = cy + x * s + y * c
            ix, iy = int(round(px)), int(round(py))
            col, row = ix // 2, iy // 4
            if not (0 <= col < width and 0 <= row < height):
                continue
            key = (row, col)
            cells[key] = cells.get(key, 0) | _BIT_AT[(ix % 2, iy % 4)]
            min_c, max_c, max_r = min(min_c, col), max(max_c, col), max(max_r, row)
        rise = (3.2 + 0.9 - dy) / (2 * (3.2 + 0.9))   # 1 at the top of the bob, 0 at the bottom
        return cells, rise, (min_c, max_c, max_r)

    # -- rain ----------------------------------------------------------------------
    def _reset_rain(self, width: int, height: int) -> None:
        self._drops = []
        for x in range(width):
            if self.rng.random() < 0.55:
                self._drops.append(_Drop(x, self.rng.uniform(-height, height), self.rng.uniform(5.0, 16.0),
                                         self.rng.randint(5, max(6, height // 2)), 0.0))
        self._glyphs = {}
        self._size = (width, height)

    def _advance_rain(self, dt: float, width: int, height: int) -> None:
        for d in self._drops:
            if d.wait > 0:
                d.wait -= dt
                continue
            d.head += d.speed * dt
            if d.head - d.length > height:
                d.head = self.rng.uniform(-6, -1)
                d.speed = self.rng.uniform(5.0, 16.0)
                d.length = self.rng.randint(5, max(6, height // 2))
                d.wait = self.rng.uniform(0.0, 2.5)
        # a few trail glyphs flicker
        for _ in range(max(1, width // 6)):
            self._glyphs.pop((self.rng.randrange(max(1, height)), self.rng.randrange(max(1, width))), None)

    def _glyph(self, row: int, col: int) -> str:
        g = self._glyphs.get((row, col))
        if g is None:
            g = self.rng.choice(GLYPHS)
            self._glyphs[(row, col)] = g
        return g

    # -- frame -----------------------------------------------------------------------
    def frame(self, width: int, height: int, now: float, playing: bool = True, logo: bool = True,
              dim: float = 1.0) -> list[list[tuple[str, Optional[Color]]]]:
        """One frame: ``height`` rows of ``width`` (char, color) cells. ``logo=False``
        and a ``dim`` below 1 give a quiet backdrop (behind the lyrics)."""
        width, height = max(1, width), max(1, height)
        if (width, height) != self._size:
            self._reset_rain(width, height)
        dt = 0.0 if self._last_t is None else max(0.0, min(0.5, now - self._last_t))
        self._last_t = now
        if self.shown_at is None:
            self.shown_at = now
        rain_dt = dt if playing else 0.0                  # the rain rests while paused
        self._rain_t += rain_dt
        self._float_t += dt if playing else dt * 0.35     # the logo keeps drifting, slowly
        self._advance_rain(rain_dt, width, height)

        grid: list[list[tuple[str, Optional[Color]]]] = [[(" ", None)] * width for _ in range(height)]
        for d in self._drops:
            if d.wait > 0:
                continue
            head = int(d.head)
            for k in range(d.length + 1):
                row = head - k
                if 0 <= row < height:
                    if k == 0:
                        color = HEADC
                    else:
                        color = lerp(BG, RAINC, (1 - k / (d.length + 1)) * 0.85)
                    if dim < 1.0:
                        color = lerp(BG, color, dim)
                    grid[row][d.x] = (self._glyph(row, d.x), color)
        if not logo:
            return grid

        cells, rise, (left, right, bottom) = self._logo_cells(width, height, self._float_t)
        fade = smoothstep((now - self.shown_at) / 1.6)   # the logo fades up, like the outro
        if cells:
            # soft shadow on the "floor": wider and darker when the logo is low
            floor = min(height - 1, bottom + 2)
            half = max(2, int((right - left) / 2 * (0.62 - 0.12 * rise)))
            mid = (left + right) // 2
            shade = lerp(BG, SHADOW, (0.9 - 0.45 * rise) * fade)
            for col in range(mid - half, mid + half + 1):
                if 0 <= col < width and 0 <= floor < height:
                    edge = abs(col - mid) / max(1, half)
                    grid[floor][col] = ("▁" if edge > 0.7 else "▂", lerp(BG, shade, 1.15 - edge))
            glow = 0.5 + 0.5 * math.sin(2 * math.pi * self._float_t / 4.8)
            color = lerp(BG, lerp(LOGOC, LOGO_HI, glow * 0.6), fade)
            # the logo is solid: the rain passes behind it, not through it
            spans: dict[int, list[int]] = {}
            for (row, col) in cells:
                lo_hi = spans.setdefault(row, [col, col])
                lo_hi[0], lo_hi[1] = min(lo_hi[0], col), max(lo_hi[1], col)
            for row, (lo, hi) in spans.items():
                for col in range(lo, hi + 1):
                    if fade > 0.5 or self.rng.random() < fade * 2:
                        grid[row][col] = (" ", None)
            for (row, col), bits in cells.items():
                grid[row][col] = (chr(0x2800 + bits), color)
        return grid
