"""Album art for the TUI, drawn with half blocks.

Each terminal cell shows two pixels: "▀" in the top pixel's colour on the
bottom pixel's colour, so a 12x6 cell area holds a 12x12 picture. Covers come
from TIDAL (the album of the song playing), are fetched in the background and
kept on disk; Pillow does the resizing. Without Pillow, or without a cover, a
gradient tile with a note stands in.
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

    def cells(self, key: str, image, width: int, height: int) -> list:
        """The image as ``height`` rows of ``width`` half-block cells."""
        memo = (key, width, height)
        if memo in self._cells:
            return self._cells[memo]
        grid = half_blocks(image, width, height)
        if len(self._cells) > 50:
            self._cells.clear()
        self._cells[memo] = grid
        return grid


def half_blocks(image, width: int, height: int) -> list:
    """Rows of ("▀", top colour, False, bottom colour) cells for a PIL image."""
    Image = _pil()
    img = image.resize((max(1, width), max(2, height * 2)), Image.LANCZOS if hasattr(Image, "LANCZOS") else 1)
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
