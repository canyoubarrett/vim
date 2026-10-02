"""The floating Alter Era logo for the TUI.

The logo is drawn in braille: each braille character is a 2x4 grid of dots.
By default it comes from the vector original (assets/alter-era.svg): its
lines and arcs are traced into dots every frame at the size the panel allows,
so it is crisp at any size and a tilt or a quarter-row shift costs nothing in
quality. A braille text art file (---BIG--- / ---SMALL---) also works: its
dots are taken as they are. The float is a
slow bob with a faster overtone, a lazy sideways drift, and a tilt that leans
into the drift; a soft shadow below shrinks and fades as the logo rises, and
the colour breathes slowly between two theme colours.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

Color = tuple[int, int, int]

# braille dot bit -> (dx, dy) inside the 2x4 cell
_BITS = {0x01: (0, 0), 0x02: (0, 1), 0x04: (0, 2), 0x40: (0, 3),
         0x08: (1, 0), 0x10: (1, 1), 0x20: (1, 2), 0x80: (1, 3)}
_BIT_AT = {v: k for k, v in _BITS.items()}

ASSET = Path(__file__).parent / "assets" / "alter-era.txt"
ASSET_SVG = Path(__file__).parent / "assets" / "alter-era.svg"

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


_TOKEN = re.compile(r"[MLHVAZmlhvaz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _arc_points(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2, step: float = 1.0) -> list:
    """Points along an SVG elliptical arc (endpoint parametrisation, SVG spec F.6.5)."""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if bool(large) == bool(sweep):
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(2, int(abs(dt) * max(rx, ry) / step) + 1)
    pts = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        pts.append((cx + rx * cp * math.cos(t) - ry * sp * math.sin(t),
                    cy + rx * sp * math.cos(t) + ry * cp * math.sin(t)))
    pts[-1] = (x2, y2)
    return pts


def parse_svg_paths(text: str) -> list[list[tuple[float, float]]]:
    """Polylines from every <path d="..."> (M L H V A Z, absolute and relative)."""
    polylines: list[list[tuple[float, float]]] = []
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', text):
        tokens = _TOKEN.findall(d)
        i, cmd = 0, None
        x = y = sx = sy = 0.0
        cur: list[tuple[float, float]] = []

        def num():
            nonlocal i
            v = float(tokens[i])
            i += 1
            return v
        while i < len(tokens):
            if tokens[i].isalpha():
                cmd = tokens[i]
                i += 1
                if cmd in "Zz":
                    if cur:
                        cur.append((sx, sy))
                    x, y = sx, sy
                    continue
            if cmd is None:
                break
            rel = cmd.islower()
            c = cmd.upper()
            if c == "M":
                nx, ny = num(), num()
                x, y = (x + nx, y + ny) if rel else (nx, ny)
                if len(cur) > 1:
                    polylines.append(cur)
                cur = [(x, y)]
                sx, sy = x, y
                cmd = "l" if rel else "L"     # further pairs are line-tos
            elif c == "L":
                nx, ny = num(), num()
                x, y = (x + nx, y + ny) if rel else (nx, ny)
                cur.append((x, y))
            elif c == "H":
                nx = num()
                x = x + nx if rel else nx
                cur.append((x, y))
            elif c == "V":
                ny = num()
                y = y + ny if rel else ny
                cur.append((x, y))
            elif c == "A":
                rx, ry, rot, large, sweep, nx, ny = (num() for _ in range(7))
                if rel:
                    nx, ny = x + nx, y + ny
                cur.extend(_arc_points(x, y, rx, ry, rot, int(large), int(sweep), nx, ny))
                x, y = nx, ny
            else:
                i += 1   # unsupported command: skip a token
        if len(cur) > 1:
            polylines.append(cur)
    return polylines


class LogoScene:
    """Renders frames as rows of (char, colour or None) cells."""

    def __init__(self, art_path: Optional[Path] = None, logo: Color = LOGO, glow: Color = GLOW,
                 shadow: Color = SHADOW, bg: Color = BG, cell_aspect: float = 0.5):
        """``art_path``: an .svg (traced) or a braille text art file; default: the
        bundled vector logo. ``cell_aspect``: a terminal cell's width / height."""
        self.polylines: list = []
        path = Path(art_path) if art_path else ASSET_SVG
        if path.suffix.lower() == ".svg":
            try:
                self.polylines = parse_svg_paths(path.read_text(encoding="utf-8"))
            except OSError:
                self.polylines = []
        if self.polylines:
            pts = [p for line in self.polylines for p in line]
            self._vb = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        # a dot is (2 * cell_aspect) as wide as it is tall; compensate so the logo keeps its shape
        self.dot_ratio = max(0.4, min(2.5, 2 * cell_aspect))
        big, small = load_art(None if (path.suffix.lower() == ".svg") else path) if not self.polylines else ([], [])
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

    def _vector_cells(self, width: int, height: int, t: float) -> tuple[dict, float, tuple]:
        """Trace the vector logo into braille cells at this frame's pose."""
        x0, y0, x1, y1 = self._vb
        bw, bh = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        avail_w = max(4, (width - 4) * 2)
        avail_h = max(4, (height - 3) * 4 - 10)          # room for the bob and the shadow
        scale = min(avail_w * self.dot_ratio / bw, avail_h / bh)   # dots (vertical) per unit
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy, tilt = self.logo_pose(t)
        c, s = math.cos(tilt), math.sin(tilt)
        cx = width * 2 / 2 + dx
        cy = (height - 2) * 4 / 2 + dy
        dots: set = set()
        for line in self.polylines:
            prev = None
            for ux, uy in line:
                # centre, tilt, scale (x in dot widths), place
                vx, vy = (ux - mx) * scale, (uy - my) * scale
                px = cx + (vx * c - vy * s) / self.dot_ratio
                py = cy + (vx * s + vy * c)
                if prev is not None:
                    qx, qy = prev
                    n = max(1, int(max(abs(px - qx), abs(py - qy)) * 2))
                    for k in range(1, n + 1):
                        dots.add((int(round(qx + (px - qx) * k / n)), int(round(qy + (py - qy) * k / n))))
                else:
                    dots.add((int(round(px)), int(round(py))))
                prev = (px, py)
        cells: dict[tuple[int, int], int] = {}
        min_c, max_c, max_r = 10 ** 9, -1, -1
        for ix, iy in dots:
            col, row = ix // 2, iy // 4
            if 0 <= col < width and 0 <= row < height:
                cells[(row, col)] = cells.get((row, col), 0) | _BIT_AT[(ix % 2, iy % 4)]
                min_c, max_c, max_r = min(min_c, col), max(max_c, col), max(max_r, row)
        rise = (3.2 + 0.9 - dy) / (2 * (3.2 + 0.9))
        return cells, rise, (min_c, max_c, max_r)

    def _logo_cells(self, width: int, height: int, t: float) -> tuple[dict, float, tuple]:
        """Braille cells of the logo for this frame, how high it floats (0..1),
        and its footprint (left, right, bottom) in cells for the shadow."""
        if self.polylines:
            return self._vector_cells(width, height, t)
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
