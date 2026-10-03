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

Styles (``style``): ``theme`` and ``muted`` (the theme's lilac, or a soft
grey one), ``mono`` (black and white), ``wireframe`` (each line in the
logo's own colours) and ``filled`` (the logo's shapes filled in its colours,
with dark edges, drawn with quarter blocks). Motions (``motion``): ``float``,
``gentle``, ``lively``, ``still``, and ``shapes``, where every shape of the
logo floats on its own. Changing either never jumps: the motion eases from
one to the other.
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


# The Alter Era logo's own colours (from the artwork)
LOGO_COLORS: dict[str, Color] = {
    "sun": (253, 192, 0), "red": (205, 87, 87), "salmon": (243, 124, 104), "peach": (250, 167, 110),
    "cyan": (0, 255, 230), "teal": (10, 180, 155), "deep": (17, 87, 94), "eye": (110, 255, 255),
    "purple": (136, 128, 222), "ink": (35, 31, 32),
}
# for each <path> of the bundled SVG, in file order: (shape, colour)
ALTER_ERA_PATHS = ([("sun", "sun")] * 5 + [
    ("dart", "cyan"), ("salmon-lt", "salmon"), ("red", "red"), ("salmon-rt", "salmon"), ("salmon-rb", "salmon"),
    ("salmon-lb", "salmon"), ("peach-l", "peach"), ("peach-r", "peach"), ("tri", "cyan"), ("tri", "teal"),
    ("purple-l", "purple"), ("purple-r", "purple"), ("tri", "deep"), ("dart", "deep"), ("dart", "teal"),
    ("eye", "eye")])
# the coloured regions of the logo, back to front, in SVG units: (shape, colour, polygon or ("circle", cx, cy, r))
ALTER_ERA_REGIONS = [
    ("sun", "sun", ("circle", 248.0, 143.6, 74.666)),
    ("red", "red", [(229.368, 188.459), (248.651, 153.333), (269.783, 188.459)]),
    ("salmon-lt", "salmon", [(178.787, 185.203), (208.384, 177.297), (198.992, 202.456)]),
    ("salmon-rt", "salmon", [(288.216, 180.612), (320.250, 194.077), (299.353, 205.714)]),
    ("salmon-rb", "salmon", [(325.353, 257.501), (339.955, 258.411), (331.808, 270.552)]),
    ("salmon-lb", "salmon", [(172.172, 264.915), (159.287, 251.386), (178.454, 250.386)]),
    ("purple-l", "purple", [(156.578, 246.332), (174.695, 185.202), (127.984, 198.266)]),
    ("purple-r", "purple", [(325.310, 194.076), (343.668, 253.972), (372.015, 214.041)]),
    ("peach-l", "peach", [(208.403, 177.908), (233.247, 203.105), (189.589, 263.640), (172.923, 264.769)]),
    ("peach-r", "peach", [(288.267, 181.313), (264.846, 203.032), (308.732, 264.241), (330.866, 269.773)]),
    ("tri", "cyan", [(249.075, 179.547), (249.075, 237.400), (183.345, 273.113)]),
    ("tri", "teal", [(249.075, 179.547), (314.229, 272.295), (249.075, 237.400)]),
    ("tri", "deep", [(183.345, 273.113), (249.075, 237.400), (314.229, 272.295)]),
    ("dart", "deep", [(207.448, 278.950), (294.970, 278.225), (248.877, 307.606)]),
    ("dart", "cyan", [(207.448, 278.950), (248.877, 307.606), (249.218, 430.459)]),
    ("dart", "teal", [(248.877, 307.606), (294.970, 278.225), (249.218, 430.459)]),
    ("eye", "eye", ("circle", 248.226, 274.126, 15.186)),
]
STYLES = ("theme", "muted", "filled", "wireframe", "mono")
# motion: how far (1 = the classic float) and how fast it floats, and how much each shape floats on its own
MOTIONS = {
    "float": (1.0, 1.0, 0.0),
    "gentle": (0.5, 0.6, 0.0),
    "lively": (1.6, 1.5, 0.0),
    "still": (0.0, 1.0, 0.0),
    "shapes": (0.6, 0.8, 1.0),
}


def _circle_center(p1, p2, p3) -> tuple[float, float]:
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy


def piece_pose(k: int, t: float) -> tuple[float, float, float, float]:
    """(dx, dy in dots, turn in radians, spread) for shape number k at time t:
    each shape on its own slow orbit, phases spread so they never move as one."""
    ph = k * 1.7
    dx = 3.0 * math.sin(2 * math.pi * t / 6.3 + ph) + 1.0 * math.sin(2 * math.pi * t / 3.1 + 2 * ph)
    dy = 2.6 * math.sin(2 * math.pi * t / 5.1 + 1.3 * ph) + 0.8 * math.sin(2 * math.pi * t / 2.7 + ph)
    turn = math.radians(5.0) * math.sin(2 * math.pi * t / 7.7 + 0.7 * ph)
    spread = 0.06 * (0.5 + 0.5 * math.sin(2 * math.pi * t / 11.0 + ph))
    return dx, dy, turn, spread


class LogoScene:
    """Renders frames as rows of (char, colour) or (char, colour, bold, background) cells."""

    def __init__(self, art_path: Optional[Path] = None, logo: Color = LOGO, glow: Color = GLOW,
                 shadow: Color = SHADOW, bg: Color = BG, cell_aspect: float = 0.5,
                 style: str = "theme", motion: str = "float"):
        """``art_path``: an .svg (traced) or a braille text art file; default: the
        bundled vector logo. ``cell_aspect``: a terminal cell's width / height."""
        self.polylines: list = []
        path = Path(art_path) if art_path else ASSET_SVG
        if path.suffix.lower() == ".svg":
            try:
                self.polylines = parse_svg_paths(path.read_text(encoding="utf-8"))
            except OSError:
                self.polylines = []
        # the bundled logo: which shape and colour each line belongs to, and its filled regions
        bundled = path.resolve() == ASSET_SVG.resolve() and len(self.polylines) == len(ALTER_ERA_PATHS)
        self.path_meta = list(ALTER_ERA_PATHS) if bundled else [(f"path{i}", None) for i in range(len(self.polylines))]
        self.regions = list(ALTER_ERA_REGIONS) if bundled else []
        if bundled:   # the sun's centre, exactly, from its arc
            arc = self.polylines[0]
            cx, cy = _circle_center(arc[0], arc[len(arc) // 2], arc[-1])
            self.regions[0] = ("sun", "sun", ("circle", cx, cy, 74.666))
        if self.polylines:
            pts = [p for line in self.polylines for p in line]
            self._vb = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
            self._shape_centre = self._centres()
        # a dot is (2 * cell_aspect) as wide as it is tall; compensate so the logo keeps its shape
        self.dot_ratio = max(0.4, min(2.5, 2 * cell_aspect))
        big, small = load_art(None if (path.suffix.lower() == ".svg") else path) if not self.polylines else ([], [])
        self.arts = [a for a in (big, small) if a]
        self._dots = {id(a): art_to_dots(a) for a in self.arts}
        self.logo, self.glow, self.shadow, self.bg = logo, glow, shadow, bg
        self.colors = dict(LOGO_COLORS)
        self.style = style if style in STYLES else "theme"
        self.motion = motion if motion in MOTIONS else "float"
        amp, speed, pieces = MOTIONS[self.motion]
        self._amp, self._speed, self._pieces = amp, speed, pieces   # eased towards the motion's values
        self._last_t: Optional[float] = None
        self._float_t = 0.0      # float time: runs at full speed while playing, slowly while paused
        self._motion_t = 0.0     # float time scaled by the motion's speed
        self.shown_at: Optional[float] = None

    def _centres(self) -> dict:
        """The middle of each shape, in SVG units (what it turns around on its own)."""
        acc: dict = {}
        for (shape, _), line in zip(self.path_meta, self.polylines):
            xs, ys = acc.setdefault(shape, ([], []))
            xs.extend(p[0] for p in line)
            ys.extend(p[1] for p in line)
        return {k: ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2) for k, (xs, ys) in acc.items()}

    def _pick_art(self, width: int, height: int):
        """The logo and scale that fit: the big one when it fits at 60% or more."""
        best = None
        for art in self.arts:
            aw = max(len(l) for l in art) if art else 0
            ah = len(art)
            if not aw or not ah:
                continue
            room_w, room_h = width - 3, height - 2      # margin for the float and the shadow
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

    def pose(self) -> tuple[float, float, float]:
        dx, dy, tilt = self.logo_pose(self._motion_t)
        return dx * self._amp, dy * self._amp, tilt * self._amp

    def _layout(self, width: int, height: int):
        """Scale (dots per SVG unit, vertically) and the function that takes a
        point of a shape to dot coordinates, at this frame's pose."""
        x0, y0, x1, y1 = self._vb
        bw, bh = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        # as big as the panel allows, leaving just the room the float needs:
        # 5.2 dots of drift each side, 4.1 dots of bob (more when the shapes spread), and the shadow's row
        spare = 1.0 + 0.12 * self._pieces
        avail_w = max(4, ((width - 1) * 2 - 14) / spare)
        avail_h = max(4, ((height - 1) * 4 - 11) / spare)
        scale = min(avail_w * self.dot_ratio / bw, avail_h / bh)   # dots (vertical) per unit
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy, tilt = self.pose()
        c, s = math.cos(tilt), math.sin(tilt)
        cx = width * 2 / 2 + dx
        cy = (height - 1) * 4 / 2 + dy
        f = self._pieces
        ratio = self.dot_ratio
        poses = {}

        def place(shape: str):
            """The transform for one shape: its own float (when the shapes move
            on their own), then the logo's."""
            if f > 0.001:
                if shape not in poses:
                    k = sorted(self._shape_centre).index(shape) if shape in self._shape_centre else 0
                    poses[shape] = piece_pose(k, self._motion_t)
                pdx, pdy, turn, spread = poses[shape]
                gx, gy = self._shape_centre.get(shape, (mx, my))
                tc, ts = math.cos(turn * f), math.sin(turn * f)
                ox, oy = (gx - mx) * spread * f, (gy - my) * spread * f
            else:
                pdx = pdy = 0.0
                gx, gy, tc, ts, ox, oy = mx, my, 1.0, 0.0, 0.0, 0.0

            def to_dots(ux: float, uy: float) -> tuple[float, float]:
                if f > 0.001:
                    rx, ry = ux - gx, uy - gy
                    ux, uy = gx + rx * tc - ry * ts + ox, gy + rx * ts + ry * tc + oy
                vx, vy = (ux - mx) * scale, (uy - my) * scale
                return (cx + (vx * c - vy * s) / ratio + pdx * f, cy + (vx * s + vy * c) + pdy * f)
            return to_dots
        return scale, place

    def _vector_cells(self, width: int, height: int, t: float) -> tuple[dict, float, tuple]:
        """Trace the vector logo into braille cells at this frame's pose; also
        records, for the wireframe style, which colour each cell takes."""
        scale, place = self._layout(width, height)
        cells: dict[tuple[int, int], int] = {}
        self._cell_colors = {}
        min_c, max_c, max_r = 10 ** 9, -1, -1
        for (shape, colour), line in zip(self.path_meta, self.polylines):
            to_dots = place(shape)
            dots: list = []
            prev = None
            for ux, uy in line:
                px, py = to_dots(ux, uy)
                if prev is not None:
                    qx, qy = prev
                    n = max(1, int(max(abs(px - qx), abs(py - qy)) * 2))
                    for k in range(1, n + 1):
                        dots.append((int(round(qx + (px - qx) * k / n)), int(round(qy + (py - qy) * k / n))))
                else:
                    dots.append((int(round(px)), int(round(py))))
                prev = (px, py)
            for ix, iy in dots:
                col, row = ix // 2, iy // 4
                if 0 <= col < width and 0 <= row < height:
                    cells[(row, col)] = cells.get((row, col), 0) | _BIT_AT[(ix % 2, iy % 4)]
                    if colour:
                        self._cell_colors[(row, col)] = colour
                    min_c, max_c, max_r = min(min_c, col), max(max_c, col), max(max_r, row)
        dy = self.pose()[1]
        rise = (3.2 + 0.9 - dy) / (2 * (3.2 + 0.9)) if self._amp > 0.01 else 0.5
        return cells, rise, (min_c, max_c, max_r)

    def _filled_grid(self, width: int, height: int, fade: float) -> tuple[dict, tuple]:
        """The logo's regions filled in its own colours with dark edges, drawn
        at 2x2 pixels per cell (quarter blocks). Returns {(row, col): cell}."""
        from .artwork import QUADRANTS, _pil

        Image = _pil()
        if Image is None or not self.regions:
            return {}, (0, 0, 0)
        from PIL import ImageDraw

        scale, place = self._layout(width, height)
        ss = 2                                         # supersampling, for clean edges
        W, H = width * 2 * ss, height * 4 * ss          # dot space x ss
        bg = self.bg
        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)
        ink = self.colors["ink"]
        edge = max(1, int(round(scale * 1.6 * ss)))
        for shape, colour, geom in self.regions:
            to_dots = place(shape)
            fill = lerp(bg, self.colors[colour], fade)
            if isinstance(geom, tuple) and geom[0] == "circle":
                _, gx, gy, r = geom
                pts = [to_dots(gx + r * math.cos(a / 36 * 2 * math.pi), gy + r * math.sin(a / 36 * 2 * math.pi))
                       for a in range(36)]
            else:
                pts = [to_dots(x, y) for x, y in geom]
            pts = [(x * ss, y * ss) for x, y in pts]
            draw.polygon(pts, fill=fill, outline=lerp(bg, ink, fade), width=edge)
        img = img.resize((width * 2, height * 2), Image.BOX)   # dots are 2x4 per cell; quarters are 2x2
        px = img.load()
        out: dict = {}
        min_c, max_c, max_r = 10 ** 9, -1, -1
        for y in range(height):
            for x in range(width):
                quad = (px[2 * x, 2 * y], px[2 * x + 1, 2 * y], px[2 * x, 2 * y + 1], px[2 * x + 1, 2 * y + 1])
                if quad[0] == quad[1] == quad[2] == quad[3]:
                    if quad[0] == bg:
                        continue
                    out[(y, x)] = (" ", None, False, quad[0])   # a solid cell: no gaps between rows
                else:
                    best = None
                    for mask in (8, 4, 2, 1, 12, 10, 9):
                        a = [quad[i] for i in range(4) if mask & (8 >> i)]
                        b = [quad[i] for i in range(4) if not mask & (8 >> i)]
                        ca = tuple(sum(v[k] for v in a) // len(a) for k in range(3))
                        cb = tuple(sum(v[k] for v in b) // len(b) for k in range(3))
                        err = sum((v[0] - ca[0]) ** 2 + (v[1] - ca[1]) ** 2 + (v[2] - ca[2]) ** 2 for v in a)
                        err += sum((v[0] - cb[0]) ** 2 + (v[1] - cb[1]) ** 2 + (v[2] - cb[2]) ** 2 for v in b)
                        if best is None or err < best[0]:
                            best = (err, mask, ca, cb)
                    _, mask, ca, cb = best
                    if cb == bg:                       # keep the panel (glass) around the shapes
                        out[(y, x)] = (QUADRANTS[mask], ca, False, None)
                    elif ca == bg:
                        out[(y, x)] = (QUADRANTS[15 ^ mask], cb, False, None)
                    else:
                        out[(y, x)] = (QUADRANTS[mask], ca, False, cb)
                min_c, max_c, max_r = min(min_c, x), max(max_c, x), max(max_r, y)
        return out, (min_c, max_c, max_r)

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
        dx, dy, tilt = self.pose()
        cx = width * 2 / 2 + dx
        cy = (height - 1) * 4 / 2 + dy          # leave the bottom row for the shadow
        c, s = math.cos(tilt), math.sin(tilt)
        cells: dict[tuple[int, int], int] = {}
        self._cell_colors = {}
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
        rise = (3.2 + 0.9 - dy) / (2 * (3.2 + 0.9)) if self._amp > 0.01 else 0.5
        return cells, rise, (min_c, max_c, max_r)

    def _advance(self, dt: float) -> None:
        """Move time on, and ease the motion towards the chosen one's settings."""
        amp, speed, pieces = MOTIONS.get(self.motion, MOTIONS["float"])
        k = min(1.0, dt / 1.2) if dt > 0 else 0.0
        self._amp += (amp - self._amp) * k
        self._speed += (speed - self._speed) * k
        self._pieces += (pieces - self._pieces) * k
        self._motion_t += dt * self._speed

    def frame(self, width: int, height: int, now: float, playing: bool = True) -> list:
        """One frame: ``height`` rows of ``width`` cells."""
        width, height = max(1, width), max(1, height)
        dt = 0.0 if self._last_t is None else max(0.0, min(0.5, now - self._last_t))
        self._last_t = now
        if self.shown_at is None:
            self.shown_at = now
            amp, speed, pieces = MOTIONS.get(self.motion, MOTIONS["float"])
            self._amp, self._speed, self._pieces = amp, speed, pieces
        step = dt if playing else dt * 0.35        # paused: it keeps drifting, slowly
        self._float_t += step
        self._advance(step)

        grid: list = [[(" ", None)] * width for _ in range(height)]
        fade = smoothstep((now - self.shown_at) / 1.6)   # the logo fades up
        filled = self.style == "filled" and bool(self.regions)
        if filled:
            fcells, (left, right, bottom) = self._filled_grid(width, height, fade)
            cells, rise = {}, (0.5 if self._amp <= 0.01 else
                               (3.2 + 0.9 - self.pose()[1]) / (2 * (3.2 + 0.9)))
            if not fcells:
                return grid
        else:
            cells, rise, (left, right, bottom) = self._logo_cells(width, height, self._float_t)
            if not cells:
                return grid
        # soft shadow on the "floor": wider and darker when the logo is low
        floor = min(height - 1, bottom + 2)
        half = max(2, int((right - left) / 2 * (0.62 - 0.12 * rise)))
        mid = (left + right) // 2
        shade = lerp(self.bg, self.shadow, (1.0 - 0.4 * rise) * fade)
        for col in range(mid - half, mid + half + 1):
            if 0 <= col < width and 0 <= floor < height:
                edge = abs(col - mid) / max(1, half)
                grid[floor][col] = ("▁" if edge > 0.7 else "▂", lerp(self.bg, shade, 1.2 - edge))
        if filled:
            for (row, col), cell in fcells.items():
                grid[row][col] = cell
            return grid
        glow = 0.5 + 0.5 * math.sin(2 * math.pi * self._float_t / 4.8)
        color = lerp(self.bg, lerp(self.logo, self.glow, glow * 0.45), fade)
        if self.style == "wireframe" and self._cell_colors:
            shades = {k: lerp(self.bg, lerp(v, (255, 255, 255), glow * 0.12), fade) for k, v in self.colors.items()}
            for (row, col), bits in cells.items():
                key = self._cell_colors.get((row, col))
                grid[row][col] = (chr(0x2800 + bits), shades[key] if key else color)
            return grid
        for (row, col), bits in cells.items():
            grid[row][col] = (chr(0x2800 + bits), color)
        return grid


AlterEraScene = LogoScene  # the earlier name
