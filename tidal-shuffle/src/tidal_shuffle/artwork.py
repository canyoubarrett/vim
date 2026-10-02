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
        draw = quadrant_blocks if mode == "quadrant" else half_blocks
        grid = draw(image, width, height, dither=dither)
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
    img = image.convert("RGB").resize((max(1, w), max(1, h)), Image.LANCZOS if hasattr(Image, "LANCZOS") else 1)
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
