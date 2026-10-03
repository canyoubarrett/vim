"""Backdrops behind the logo: pictures of your own (fighting-game stages,
anything), or the album cover of the song playing.

Pictures live in ~/.config/tidal-shuffle/backdrops (``tidal-shuffle
backdrops add`` copies images, folders or zips there). A picture is drawn
from its full-size original at the chosen detail (half, quarter, sixth or
eighth blocks, or braille), dimmed towards the theme's background so the logo stays the
brightest thing in the panel, and wide pictures pan slowly from side to side.
The logo is drawn over it: where the logo has no background of its own, the
picture shows through.
"""

from __future__ import annotations

import math
import random
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Optional

Color = tuple[int, int, int]
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def backdrop_dir() -> Path:
    from . import paths

    return paths.CONFIG_DIR / "backdrops"


def list_backdrops(folder: Optional[Path] = None) -> list[str]:
    """Picture file names, in a natural order ("2 - x.png" before "10 - y.png")."""
    folder = folder or backdrop_dir()
    try:
        names = [p.name for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()]
    except OSError:
        return []

    def natural(name: str):
        import re

        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]
    return sorted(names, key=natural)


def label(name: str) -> str:
    """A short name for the menu: "12 - UkTleZJ.png" -> "Stage 12"."""
    stem = Path(name).stem
    head = stem.split(" - ")[0].strip()
    return f"Stage {head}" if head.isdigit() else stem


def add_backdrops(sources: list, folder: Optional[Path] = None, log: Callable[[str], None] = print) -> int:
    """Copy pictures (files, folders, zips) into the backdrops folder."""
    folder = folder or backdrop_dir()
    folder.mkdir(parents=True, exist_ok=True)
    added = 0
    for src in sources:
        src = Path(src).expanduser()
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                if f.suffix.lower() in IMAGE_SUFFIXES and f.is_file():
                    shutil.copy2(f, folder / f.name)
                    added += 1
        elif src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as z:
                for info in z.infolist():
                    name = Path(info.filename).name
                    if info.is_dir() or not name or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    with z.open(info) as fh, open(folder / name, "wb") as out:
                        shutil.copyfileobj(fh, out)
                    added += 1
        elif src.suffix.lower() in IMAGE_SUFFIXES and src.is_file():
            shutil.copy2(src, folder / src.name)
            added += 1
        else:
            log(f"skipped {src}: not a picture, folder or zip")
    return added


class StageArt:
    """Pictures as cells for the logo panel, dimmed and slowly panning."""

    def __init__(self, folder: Optional[Path] = None, cover: Optional[Callable[[], object]] = None):
        self.folder = folder or backdrop_dir()
        self.cover = cover                        # returns the album cover (a PIL image) or None
        self._sources: dict = {}                  # name -> the picture at full size
        self._strips: dict = {}                   # settings -> (rows of cells, columns)
        self._random: dict = {}                   # song key -> picture name ("random" backdrop)

    def names(self) -> list[str]:
        return list_backdrops(self.folder)

    def pick(self, choice: str, song_key: str = "") -> Optional[str]:
        """The picture to show for a choice: a file name, "random" (a new one per song) or "cover"."""
        if not choice or choice == "off":
            return None
        if choice == "random":
            names = self.names()
            if not names:
                return None
            if song_key not in self._random:
                rng = random.Random(song_key)
                self._random[song_key] = rng.choice(names)
                if len(self._random) > 100:
                    self._random.pop(next(iter(self._random)))
            return self._random[song_key]
        return choice

    def _source(self, name: str):
        """The picture at its own full size (kept for the picture on show)."""
        hit = self._sources.get(name)
        if hit is not None and name != "cover":
            return hit
        from .artwork import _pil

        Image = _pil()
        if Image is None:
            return None
        if name == "cover":
            img = self.cover() if self.cover else None
            if img is None or img == "pending":
                return None
            from PIL import ImageFilter

            return img.convert("RGB").filter(ImageFilter.GaussianBlur(radius=max(1, img.width // 90)))
        path = self.folder / name
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
        except OSError:
            return None
        if len(self._sources) >= 2:
            self._sources.pop(next(iter(self._sources)))
        self._sources[name] = img
        return img

    def _strip(self, name: str, width: int, height: int, bg: Color, dim: float, cell_aspect: float,
               zoom: float, detail: str):
        """The picture as cells, made once from the full-size picture at the
        panel's own resolution: ``(rows, columns)``. When it is wider than the
        panel it pans: each frame shows a slice of it."""
        src = self._source(name)
        if src is None:
            return None
        from PIL import Image, ImageFilter

        from .artwork import DETAIL_PIXELS, detail_cells

        dx, dy = DETAIL_PIXELS.get(detail, (1, 2))
        W, H = max(1, width) * dx, max(1, height) * dy     # the panel, in pixels
        pa = cell_aspect * dy / dx                          # a pixel's width / its height
        Ws, Hs = src.size
        cover = max(H / Hs, W * pa / Ws)                    # pixel heights per picture pixel, filling the panel
        sc = cover * max(0.1, zoom)
        full_w, full_h = Ws * sc / pa, Hs * sc              # the whole picture, in panel pixels
        cols = max(width, int(full_w // dx))
        SW = cols * dx                                      # the strip that pans
        vis_h = min(Hs, H / sc)                             # picture rows that fit the panel's height
        y0 = (Hs - vis_h) / 2
        pw, ph = min(SW, max(1, int(round(full_w)))), min(H, max(1, int(round(full_h))))
        pic = src.resize((pw, ph), Image.LANCZOS, box=_clamp((0, y0, Ws, y0 + vis_h), Ws, Hs))
        if pw >= SW and ph >= H:
            img = pic
        else:                                               # zoomed out: a soft copy around it, not bars
            fs = max(SW / Ws, H / Hs)
            fw, fh = SW / fs, H / fs
            fill = src.resize((max(1, SW // 4), max(1, H // 4)), Image.BILINEAR,
                              box=_clamp(((Ws - fw) / 2, (Hs - fh) / 2, (Ws + fw) / 2, (Hs + fh) / 2), Ws, Hs))
            fill = fill.filter(ImageFilter.GaussianBlur(1.5)).resize((SW, H), Image.BILINEAR)
            img = Image.blend(fill, Image.new("RGB", fill.size, bg), 0.45)
            img.paste(pic, ((SW - pw) // 2, (H - ph) // 2))
        if dim > 0:
            img = Image.blend(img, Image.new("RGB", img.size, bg), max(0.0, min(0.95, dim)))
        if detail == "half":
            px = img.load()
            rows = [[(px[x, 2 * y], px[x, 2 * y + 1]) for x in range(cols)] for y in range(height)]
        else:
            rows = detail_cells(img, cols, height, detail)
        return rows, cols

    def cells(self, name: str, width: int, height: int, now: float, bg: Color, dim: float = 0.5,
              cell_aspect: float = 0.5, key_extra=None, zoom: float = 1.0, detail: str = "half") -> Optional[list]:
        """``height`` rows of ``width`` cells, or None. ``detail``: "half" gives
        (top, bottom) colour pairs (half blocks); "quadrant", "sextant",
        "octant" and "braille" give finished cells (char, fg, bold, bg).

        ``zoom`` 1 fills the panel (cropping the sides of a wide picture, which
        then pans); below 1 it zooms out, showing more of the picture, with a
        blurred copy around it; above 1 it zooms in."""
        key = (name, width, height, bg, round(dim, 2), round(cell_aspect, 3), key_extra, round(zoom, 2), detail)
        strip = self._strips.get(key)
        if strip is None:
            strip = self._strip(name, width, height, bg, dim, cell_aspect, zoom, detail)
            if strip is None:
                return None
            if len(self._strips) >= 6:
                self._strips.pop(next(iter(self._strips)))
            self._strips[key] = strip
        rows, cols = strip
        if cols <= width:
            return rows
        u = 0.5 - 0.5 * math.cos(2 * math.pi * now / 90.0)     # pan slowly, easing at either end
        off = int(round((cols - width) * u))
        return [row[off:off + width] for row in rows]


def _clamp(box: tuple, w: int, h: int) -> tuple:
    """A crop box inside the picture (float rounding can put it a hair outside)."""
    x0, y0, x1, y1 = box
    x0, y0 = min(max(0.0, x0), w - 1e-3), min(max(0.0, y0), h - 1e-3)
    return (x0, y0, max(x0 + 1e-3, min(float(w), x1)), max(y0 + 1e-3, min(float(h), y1)))


def _avg(a: Color, b: Color) -> Color:
    return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2, (a[2] + b[2]) // 2)


def compose(logo: list, art: list) -> list:
    """The logo over the picture: empty cells show the picture; the logo's
    own cells keep their character and colour and take the picture's colour
    behind them where they had none. ``art`` is (top, bottom) pairs (half
    blocks) or finished cells (quarter blocks, braille)."""
    from .artwork import cell_average

    out = []
    for lrow, arow in zip(logo, art):
        row = []
        for cell, a in zip(lrow, arow):
            if len(a) == 2:                       # (top, bottom): half blocks
                pic, behind = ("▀", a[0], False, a[1]), _avg(a[0], a[1])
            else:
                pic, behind = a, cell_average(a)
            ch = cell[0]
            fg = cell[1] if len(cell) > 1 else None
            bg = cell[3] if len(cell) > 3 else None
            if ch == " " and bg is None:
                row.append(pic)
            elif bg is None:
                row.append((ch, fg, cell[2] if len(cell) > 2 else False, behind))
            else:
                row.append(cell)
        out.append(row)
    return out
