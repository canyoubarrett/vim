"""The floating Alter Era logo for the TUI.

The logo is braille art. Each braille character is a 2x4 grid of dots, so the
art is turned into individual dots once and redrawn every frame after a small
rotation and a sub-character shift. That gives quarter-row vertical motion and
a gentle tilt instead of jumping a whole character at a time. The float is a
slow bob with a faster overtone, a lazy sideways drift, and a tilt that leans
into the drift; a soft shadow below shrinks and fades as the logo rises, and
the colour breathes slowly between two theme colours.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

Color = tuple[int, int, int]

# braille dot bit -> (dx, dy) inside the 2x4 cell
_BITS = {0x01: (0, 0), 0x02: (0, 1), 0x04: (0, 2), 0x40: (0, 3),
         0x08: (1, 0), 0x10: (1, 1), 0x20: (1, 2), 0x80: (1, 3)}
_BIT_AT = {v: k for k, v in _BITS.items()}

ASSET = Path(__file__).parent / "assets" / "alter-era.txt"

# Catppuccin Mocha defaults (the TUI passes its theme's colours)
LOGO: Color = (203, 166, 247)      # mauve
GLOW: Color = (245, 194, 231)      # pink
SHADOW: Color = (49, 50, 68)       # surface0
BG: Color = (30, 30, 46)           # base


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


class LogoScene:
    """Renders frames as rows of (char, colour or None) cells."""

    def __init__(self, art_path: Optional[Path] = None, logo: Color = LOGO, glow: Color = GLOW,
                 shadow: Color = SHADOW, bg: Color = BG):
        big, small = load_art(art_path)
        self.arts = [a for a in (big, small) if a]
        self._dots = {id(a): art_to_dots(a) for a in self.arts}
        self.logo, self.glow, self.shadow, self.bg = logo, glow, shadow, bg
        self._last_t: Optional[float] = None
        self._float_t = 0.0      # float time: runs at full speed while playing, slowly while paused
        self.shown_at: Optional[float] = None

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

    @staticmethod
    def logo_pose(t: float) -> tuple[float, float, float]:
        """(dx, dy) in dots and tilt in radians at float time t: a buoyant bob."""
        bob = 3.2 * math.sin(2 * math.pi * t / 5.4) + 0.9 * math.sin(2 * math.pi * t / 2.3 + 1.1)
        drift = 4.0 * math.sin(2 * math.pi * t / 9.7) + 1.2 * math.sin(2 * math.pi * t / 4.1 + 0.4)
        # lean into the drift: tilt follows the sideways velocity
        lean = math.cos(2 * math.pi * t / 9.7)
        tilt = math.radians(1.6) * lean + math.radians(0.6) * math.sin(2 * math.pi * t / 3.7)
        return drift, bob, tilt

    def _logo_cells(self, width: int, height: int, t: float) -> tuple[dict, float, tuple]:
        """Braille cells of the logo for this frame, how high it floats (0..1),
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

    def frame(self, width: int, height: int, now: float, playing: bool = True) -> list[list[tuple[str, Optional[Color]]]]:
        """One frame: ``height`` rows of ``width`` (char, colour) cells."""
        width, height = max(1, width), max(1, height)
        dt = 0.0 if self._last_t is None else max(0.0, min(0.5, now - self._last_t))
        self._last_t = now
        if self.shown_at is None:
            self.shown_at = now
        self._float_t += dt if playing else dt * 0.35     # paused: it keeps drifting, slowly

        grid: list[list[tuple[str, Optional[Color]]]] = [[(" ", None)] * width for _ in range(height)]
        cells, rise, (left, right, bottom) = self._logo_cells(width, height, self._float_t)
        if not cells:
            return grid
        fade = smoothstep((now - self.shown_at) / 1.6)   # the logo fades up
        # soft shadow on the "floor": wider and darker when the logo is low
        floor = min(height - 1, bottom + 2)
        half = max(2, int((right - left) / 2 * (0.62 - 0.12 * rise)))
        mid = (left + right) // 2
        shade = lerp(self.bg, self.shadow, (1.0 - 0.4 * rise) * fade)
        for col in range(mid - half, mid + half + 1):
            if 0 <= col < width and 0 <= floor < height:
                edge = abs(col - mid) / max(1, half)
                grid[floor][col] = ("▁" if edge > 0.7 else "▂", lerp(self.bg, shade, 1.2 - edge))
        glow = 0.5 + 0.5 * math.sin(2 * math.pi * self._float_t / 4.8)
        color = lerp(self.bg, lerp(self.logo, self.glow, glow * 0.45), fade)
        for (row, col), bits in cells.items():
            grid[row][col] = (chr(0x2800 + bits), color)
        return grid


AlterEraScene = LogoScene  # the earlier name
