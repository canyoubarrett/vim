"""Backdrops behind the logo: pictures of your own (fighting-game stages,
anything), or the album cover of the song playing.

Pictures live in ~/.config/tidal-shuffle/backdrops (``tidal-shuffle
backdrops add`` copies images, folders or zips there). A picture is drawn
with half blocks, dimmed towards the theme's background so the logo stays the
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
        self._bases: dict = {}                    # (name, rows, bg, dim) -> small, dimmed picture
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
                return im.convert("RGB")
        except OSError:
            return None

    def _base(self, name: str, rows: int, bg: Color, dim: float, key_extra=None):
        """The picture scaled to twice the panel's height in half blocks (room
        to zoom in), and dimmed towards the background: made once, panned per frame."""
        key = (name, rows, bg, round(dim, 2), key_extra)
        hit = self._bases.get(key)
        if hit is not None:
            return hit
        src = self._source(name)
        if src is None:
            return None
        from PIL import Image

        h = max(2, rows * 4)
        w = max(2, int(src.width * h / src.height))
        img = src.resize((w, h), Image.LANCZOS)
        if dim > 0:
            img = Image.blend(img, Image.new("RGB", img.size, bg), max(0.0, min(0.95, dim)))
        if len(self._bases) > 12:
            self._bases.pop(next(iter(self._bases)))
        self._bases[key] = img
        return img

    def _fill(self, base, key, width: int, height: int, bg: Color):
        """The picture blurred to fill the whole panel: what shows around it
        when it is zoomed out further than the panel (instead of bars)."""
        fkey = (key, width, height, "fill")
        hit = self._bases.get(fkey)
        if hit is not None:
            return hit
        from PIL import Image, ImageFilter

        W, H = width, height * 2
        scale = max(W / base.width, H / base.height)
        cw, ch = W / scale, H / scale
        box = _clamp(((base.width - cw) / 2, (base.height - ch) / 2, (base.width + cw) / 2, (base.height + ch) / 2),
                     base.width, base.height)
        img = base.resize((max(1, W), max(1, H)), Image.BILINEAR, box=box).filter(ImageFilter.GaussianBlur(2.5))
        img = Image.blend(img, Image.new("RGB", img.size, bg), 0.45)
        self._bases[fkey] = img
        return img

    def cells(self, name: str, width: int, height: int, now: float, bg: Color, dim: float = 0.5,
              cell_aspect: float = 0.5, key_extra=None, zoom: float = 1.0) -> Optional[list]:
        """``height`` rows of ``width`` (top, bottom) colour pairs, or None.

        ``zoom`` 1 fills the panel (cropping the sides of a wide picture, which
        then pans); below 1 it zooms out, showing more of the picture, with a
        blurred copy around it; above 1 it zooms in."""
        base = self._base(name, height, bg, dim, key_extra)
        if base is None:
            return None
        from PIL import Image

        W, H = max(1, width), max(1, height * 2)      # the panel in half-block pixels
        pa = cell_aspect * 2                           # a half-block pixel's width / height
        Wb, Hb = base.width, base.height
        cover = max(H / Hb, W * pa / Wb)               # panel pixels per picture pixel, filling the panel
        sc = cover * max(0.1, zoom)
        vis_w, vis_h = min(Wb, W * pa / sc), min(Hb, H / sc)   # how much of the picture shows
        u = 0.5 - 0.5 * math.cos(2 * math.pi * now / 90.0)     # pan slowly, easing at either end
        x0 = (Wb - vis_w) * u
        y0 = (Hb - vis_h) / 2
        box = _clamp((x0, y0, x0 + vis_w, y0 + vis_h), Wb, Hb)
        pw, ph = int(round(vis_w * sc / pa)), int(round(vis_h * sc))
        if pw >= W and ph >= H:
            img = base.resize((W, H), Image.BILINEAR, box=box)
        else:
            img = self._fill(base, (name, height, bg, round(dim, 2), key_extra), width, height, bg).copy()
            part = base.resize((max(1, min(W, pw)), max(1, min(H, ph))), Image.BILINEAR, box=box)
            img.paste(part, ((W - part.width) // 2, (H - part.height) // 2))
        px = img.load()
        return [[(px[x, 2 * y], px[x, 2 * y + 1]) for x in range(width)] for y in range(height)]


def _clamp(box: tuple, w: int, h: int) -> tuple:
    """A crop box inside the picture (float rounding can put it a hair outside)."""
    x0, y0, x1, y1 = box
    x0, y0 = min(max(0.0, x0), w - 1e-3), min(max(0.0, y0), h - 1e-3)
    return (x0, y0, max(x0 + 1e-3, min(float(w), x1)), max(y0 + 1e-3, min(float(h), y1)))


def _avg(a: Color, b: Color) -> Color:
    return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2, (a[2] + b[2]) // 2)


def compose(logo: list, art: list) -> list:
    """The logo over the picture: empty cells show the picture (half blocks);
    the logo's own cells keep their character and colour and take the
    picture's colour behind them where they had none."""
    out = []
    for lrow, arow in zip(logo, art):
        row = []
        for cell, (top, bottom) in zip(lrow, arow):
            ch = cell[0]
            fg = cell[1] if len(cell) > 1 else None
            bg = cell[3] if len(cell) > 3 else None
            if ch == " " and bg is None:
                row.append(("▀", top, False, bottom))
            elif bg is None:
                row.append((ch, fg, cell[2] if len(cell) > 2 else False, _avg(top, bottom)))
            else:
                row.append(cell)
        out.append(row)
    return out
