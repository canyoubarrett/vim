"""Album art for the TUI, drawn with block characters.

Two ways to draw a picture into terminal cells:

* half blocks: each cell shows two pixels, "▀" in the top pixel's colour on
  the bottom pixel's colour;
* quadrant blocks (the default): each cell shows four pixels, 2x2, with the
  quarter-block character (▘ ▝ ▖ ▗ ▚ ▞ ▌ ▐ ▀ ▄ ▙ ▟ ▛ ▜) whose two-colour split
  matches them best; twice the horizontal detail of half blocks.

In a 256-colour terminal (Terminal.app) the cover is first dithered
(Floyd-Steinberg) to the 256-colour palette, so gradients and faces come out
as fine grain instead of flat bands.

Covers come from TIDAL (the album of the song playing), are fetched in the
background and kept on disk; Pillow does the resizing. Without Pillow, or
without a cover, a gradient tile with a note stands in.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any, Callable, Optional

Color = tuple[int, int, int]


def _pil():
    try:
        from PIL import Image  # noqa: F401
        return Image
    except ImportError:
        return None


class ArtworkService:
    def __init__(self, catalog, cache_dir: Optional[Path] = None, fetch: Optional[Callable[[str], bytes]] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.catalog = catalog
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._fetch_bytes = fetch or self._download
        self.log = log or (lambda m: None)
        self._lock = threading.Lock()
        self._images: dict[str, Any] = {}        # song key -> PIL image | None | "pending"
        self._cells: dict = {}                   # (song key, w, h) -> grid

    @staticmethod
    def _download(url: str) -> bytes:
        from .http import make_client

        with make_client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.content

    def available(self) -> bool:
        return _pil() is not None and self.catalog is not None

    def get(self, key: str, tidal_id: Optional[str], title: str, artist: str):
        """The cover (a PIL image), None (none to be had) or "pending"."""
        if not self.available():
            return None
        with self._lock:
            if key in self._images:
                return self._images[key]
            self._images[key] = "pending"
        threading.Thread(target=self._load, args=(key, tidal_id, title, artist), name="tidal-shuffle-art",
                         daemon=True).start()
        return "pending"

    def _load(self, key: str, tidal_id: Optional[str], title: str, artist: str) -> None:
        img = None
        try:
            if not tidal_id:
                track, _ = self.catalog.find(title, artist)
                tidal_id = track.id if track else None
            if tidal_id:
                raw = self.catalog.raw_track(tidal_id)
                album = getattr(raw, "album", None)
                if album is not None and getattr(album, "cover", None):
                    img = self._image_for(str(getattr(album, "id", tidal_id)), album.image(320))
        except Exception as e:
            self.log(f"album art: {e}")
        with self._lock:
            self._images[key] = img
            if len(self._images) > 200:
                self._images.pop(next(iter(self._images)))

    def _image_for(self, album_id: str, url: str):
        Image = _pil()
        path = self.cache_dir / f"{album_id}.jpg" if self.cache_dir else None
        data = None
        if path is not None and path.exists():
            data = path.read_bytes()
        if data is None:
            data = self._fetch_bytes(url)
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                except OSError:
                    pass
        return Image.open(io.BytesIO(data)).convert("RGB")

    def cells(self, key: str, image, width: int, height: int, mode: str = "quadrant", dither: bool = False) -> list:
        """The image as ``height`` rows of ``width`` cells."""
        memo = (key, width, height, mode, dither)
        if memo in self._cells:
            return self._cells[memo]
        grid = detail_cells(image, width, height, mode, dither=dither)
        if len(self._cells) > 50:
            self._cells.clear()
        self._cells[memo] = grid
        return grid


_PALETTE_IMAGE = None


def _palette_image():
    """A Pillow palette image of the 240 fixed colours of the 256-colour palette
    (the first 16 depend on the terminal's theme, so they are left out)."""
    global _PALETTE_IMAGE
    if _PALETTE_IMAGE is None:
        Image = _pil()
        cube = (0, 95, 135, 175, 215, 255)
        colours = [(cube[r], cube[g], cube[b]) for r in range(6) for g in range(6) for b in range(6)]
        colours += [(8 + 10 * i,) * 3 for i in range(24)]
        colours += [colours[0]] * (256 - len(colours))
        pal = Image.new("P", (1, 1))
        pal.putpalette([v for c in colours for v in c])
        _PALETTE_IMAGE = pal
    return _PALETTE_IMAGE


def _prepare(image, w: int, h: int, dither: bool):
    """Resize to w x h pixels; dithered to the 256-colour palette if asked."""
    Image = _pil()
    img = image.convert("RGB")
    if img.size != (max(1, w), max(1, h)):
        img = img.resize((max(1, w), max(1, h)), Image.LANCZOS if hasattr(Image, "LANCZOS") else 1)
    if dither:
        fs = getattr(getattr(Image, "Dither", Image), "FLOYDSTEINBERG", 3)
        img = img.quantize(palette=_palette_image(), dither=fs).convert("RGB")
    return img


# quadrant characters by which quarters show the foreground: bits TL=8, TR=4, BL=2, BR=1
QUADRANTS = {0b1000: "▘", 0b0100: "▝", 0b0010: "▖", 0b0001: "▗", 0b1100: "▀", 0b0011: "▄",
             0b1010: "▌", 0b0101: "▐", 0b1001: "▚", 0b0110: "▞", 0b1110: "▛", 0b1101: "▜",
             0b1011: "▙", 0b0111: "▟", 0b1111: "█"}
# the seven ways to split four pixels into two groups (and the complements are the same split)
_SPLITS = (0b1000, 0b0100, 0b0010, 0b0001, 0b1100, 0b1010, 0b1001)


def _mean(cols: list) -> Color:
    n = len(cols)
    return (sum(c[0] for c in cols) // n, sum(c[1] for c in cols) // n, sum(c[2] for c in cols) // n)


def quadrant_blocks(image, width: int, height: int, dither: bool = False) -> list:
    """Rows of cells for a PIL image at 2x2 pixels per cell: for each cell, the
    split of its four pixels into two colours that loses the least."""
    img = _prepare(image, width * 2, height * 2, dither)
    px = img.load()
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            quad = (tuple(px[2 * x, 2 * y][:3]), tuple(px[2 * x + 1, 2 * y][:3]),
                    tuple(px[2 * x, 2 * y + 1][:3]), tuple(px[2 * x + 1, 2 * y + 1][:3]))
            best = None
            for mask in _SPLITS:
                fg = [quad[i] for i in range(4) if mask & (8 >> i)]
                bg = [quad[i] for i in range(4) if not mask & (8 >> i)]
                cf, cb = _mean(fg), _mean(bg)
                err = sum((p[0] - cf[0]) ** 2 + (p[1] - cf[1]) ** 2 + (p[2] - cf[2]) ** 2 for p in fg)
                err += sum((p[0] - cb[0]) ** 2 + (p[1] - cb[1]) ** 2 + (p[2] - cb[2]) ** 2 for p in bg)
                if best is None or err < best[0]:
                    best = (err, mask, cf, cb)
            _, mask, cf, cb = best
            if cf == cb:
                row.append(("▀", cf, False, cb))
            else:
                row.append((QUADRANTS[mask], cf, False, cb))
        rows.append(row)
    return rows


# braille dot bit for each of a cell's 2x4 pixels, by (x, y)
_BRAILLE = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
            (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}
# pixels per cell, across and down, for each level of detail
DETAIL_PIXELS = {"half": (1, 2), "quadrant": (2, 2), "sextant": (2, 3), "octant": (2, 4), "braille": (2, 4)}
DETAILS = ("half", "quadrant", "sextant", "octant", "braille")


def _block_table(first: int, count: int, others: dict) -> dict:
    """Block characters by which of a cell's pixels they fill (bit 2*row + column,
    the way Unicode numbers sextants and octants), from a run of code points
    that skips the patterns other characters already draw."""
    table = dict(others)
    cp = first
    for mask in range(count):
        if mask not in table:
            table[mask] = chr(cp)
            cp += 1
    return table


# 2x3: Symbols for Legacy Computing (Unicode 13); halves and the full block are older characters
SEXTANTS = _block_table(0x1FB00, 64, {0: " ", 21: "▌", 42: "▐", 63: "█"})
# 2x4: Unicode 16's octants, and the older characters for the patterns they leave out
OCTANTS = _block_table(0x1CD00, 256, {
    0: " ", 1: "\U0001CEA8", 2: "\U0001CEAB", 3: "\U0001FB82", 5: "▘", 10: "▝", 15: "▀", 20: "\U0001FBE6",
    40: "\U0001FBE7", 63: "\U0001FB85", 64: "\U0001CEA3", 80: "▖", 85: "▌", 90: "▞", 95: "▛",
    128: "\U0001CEA0", 160: "▗", 165: "▚", 170: "▐", 175: "▜", 192: "▂", 240: "▄", 245: "▙", 250: "▟",
    252: "▆", 255: "█"})
BLOCK_TABLES = {"sextant": SEXTANTS, "octant": OCTANTS}


def drawable_details(mode: str = "auto", env: Optional[dict] = None) -> tuple:
    """The detail levels this terminal shows. Sixth and eighth blocks are new
    characters that most fonts lack (Terminal.app draws them as boxes with
    question marks); terminals that draw block characters themselves show
    them. ``mode``: auto (by terminal), all, or basic (never the new ones)."""
    import os

    if mode == "all":
        return DETAILS
    basic = ("half", "quadrant", "braille")
    if mode == "basic":
        return basic
    env = os.environ if env is None else env
    prog, term = env.get("TERM_PROGRAM", ""), env.get("TERM", "")
    if prog == "ghostty" or "ghostty" in term or "kitty" in term or env.get("KITTY_WINDOW_ID"):
        return DETAILS
    if prog in ("WezTerm", "iTerm.app"):
        return ("half", "quadrant", "sextant", "braille")
    return basic


def split_cell(pts: list, table: dict):
    """One cell from its pixels (row by row, two across): the pixels are split
    into two colours along the channel they differ most in, refined once,
    and drawn as the block character for that split. ``None`` for a flat cell."""
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    k = max(range(3), key=lambda i: hi[i] - lo[i])
    if hi[k] - lo[k] < 6:
        return None
    cut = (lo[k] + hi[k]) / 2
    on = [p[k] > cut for p in pts]
    for _ in range(2):                                 # 2-means: move pixels to the nearer colour
        a = [p for p, o in zip(pts, on) if o]
        b = [p for p, o in zip(pts, on) if not o]
        if not a or not b:
            break
        ca, cb = _mean(a), _mean(b)
        new = [(p[0] - ca[0]) ** 2 + (p[1] - ca[1]) ** 2 + (p[2] - ca[2]) ** 2
               < (p[0] - cb[0]) ** 2 + (p[1] - cb[1]) ** 2 + (p[2] - cb[2]) ** 2 for p in pts]
        if new == on:
            break
        on = new
    a = [p for p, o in zip(pts, on) if o]
    b = [p for p, o in zip(pts, on) if not o]
    if not a or not b:
        return None
    mask = 0
    for i, o in enumerate(on):
        if o:
            mask |= 1 << i
    return table[mask], _mean(a), _mean(b), mask


def fine_blocks(image, width: int, height: int, detail: str = "octant", dither: bool = False) -> list:
    """Rows of cells at 2x3 (sextant) or 2x4 (octant) pixels per cell: solid
    blocks, finer than quarter blocks (terminals that draw these characters
    themselves, like Ghostty, kitty, WezTerm and iTerm2, show them best)."""
    dx, dy = DETAIL_PIXELS[detail]
    table = BLOCK_TABLES[detail]
    img = _prepare(image, width * dx, height * dy, dither)
    px = img.load()
    rows = []
    for y in range(height):
        row = []
        y0 = y * dy
        for x in range(width):
            x0 = x * dx
            pts = [px[x0 + i, y0 + j][:3] for j in range(dy) for i in range(dx)]
            got = split_cell(pts, table)
            if got is None:
                row.append((" ", None, False, _mean(pts)))
            else:
                row.append((got[0], got[1], False, got[2]))
        rows.append(row)
    return rows


def braille_blocks(image, width: int, height: int, dither: bool = False) -> list:
    """Rows of cells at 2x4 pixels per cell, the finest a terminal draws: each
    cell's eight pixels are split into lighter and darker, the lighter drawn
    as braille dots over the darker as background."""
    img = _prepare(image, width * 2, height * 4, dither)
    return braille_from(img.load(), width, height)


def braille_from(px, width: int, height: int, x_off: int = 0) -> list:
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            pts = [((dx, dy), tuple(px[x_off + 2 * x + dx, 4 * y + dy][:3])) for dy in range(4) for dx in range(2)]
            lum = [(0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]) for _, c in pts]
            lo, hi = min(lum), max(lum)
            if hi - lo < 10:                       # flat: one colour
                c = _mean([c for _, c in pts])
                row.append((" ", None, False, c))
                continue
            cut = (lo + hi) / 2
            light = [c for (_, c), l in zip(pts, lum) if l > cut]
            dark = [c for (_, c), l in zip(pts, lum) if l <= cut]
            bits = 0
            for ((dx, dy), _), l in zip(pts, lum):
                if l > cut:
                    bits |= _BRAILLE[(dx, dy)]
            row.append((chr(0x2800 + bits), _mean(light), False, _mean(dark)))
        rows.append(row)
    return rows


def detail_cells(image, width: int, height: int, detail: str = "quadrant", dither: bool = False) -> list:
    """A picture as cells at the chosen detail: half, quadrant, sextant, octant or braille."""
    if detail in BLOCK_TABLES:
        return fine_blocks(image, width, height, detail, dither)
    if detail == "braille":
        return braille_blocks(image, width, height, dither)
    if detail == "half":
        return half_blocks(image, width, height, dither)
    return quadrant_blocks(image, width, height, dither)


def cell_average(cell) -> Color:
    """The colour a cell looks from a distance (what goes behind a logo drawn over it)."""
    ch = cell[0]
    fg = cell[1] if len(cell) > 1 else None
    bg = cell[3] if len(cell) > 3 else None
    if bg is None:
        return fg or (0, 0, 0)
    if fg is None or ch == " ":
        return bg
    if "⠀" <= ch <= "⣿":
        share = bin(ord(ch) - 0x2800).count("1") / 8 * 0.6      # dots cover only part of the cell
    elif ch == "▀" or ch == "▄":
        share = 0.5
    elif ch in _SHARE:
        share = _SHARE[ch]
    else:
        share = {"▘": .25, "▝": .25, "▖": .25, "▗": .25, "▌": .5, "▐": .5, "▚": .5, "▞": .5,
                 "▛": .75, "▜": .75, "▙": .75, "▟": .75, "█": 1.0}.get(ch, 0.5)
    return (int(bg[0] + (fg[0] - bg[0]) * share), int(bg[1] + (fg[1] - bg[1]) * share),
            int(bg[2] + (fg[2] - bg[2]) * share))


_SHARE = {ch: bin(mask).count("1") / 6 for mask, ch in SEXTANTS.items() if ch != " "}
_SHARE.update({ch: bin(mask).count("1") / 8 for mask, ch in OCTANTS.items() if ch != " "})


def half_blocks(image, width: int, height: int, dither: bool = False) -> list:
    """Rows of ("▀", top colour, False, bottom colour) cells for a PIL image."""
    img = _prepare(image, width, height * 2, dither)
    px = img.load()
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            top = tuple(px[x, 2 * y][:3])
            bottom = tuple(px[x, 2 * y + 1][:3])
            row.append(("▀", top, False, bottom))
        rows.append(row)
    return rows


def placeholder(width: int, height: int, a: Color, b: Color, ink: Color) -> list:
    """A diagonal gradient tile with a note in the middle, for songs without art."""
    def mix(t: float) -> Color:
        return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))
    rows = []
    span = max(1, width + height * 2)
    for y in range(height):
        row = []
        for x in range(width):
            top = mix((x + 2 * y) / span)
            bottom = mix((x + 2 * y + 1) / span)
            row.append(("▀", top, False, bottom))
        rows.append(row)
    if width >= 3 and height >= 1:
        cy, cx = height // 2, width // 2
        _, top, _, bottom = rows[cy][cx]
        rows[cy][cx] = ("♪", ink, True, bottom)
    return rows
