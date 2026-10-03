"""The full-screen view for `tidal-shuffle run`, in Catppuccin colours.

    ╭ Tidal Shuffle ──────────────────────────────────── weighted · 12 picks ╮
    │ ▶ Midnight City — M83   Hurry Up, We're Dreaming                        │
    │ 1:23 ━━━━━━━━━━━━━━━━●─────────────────────────────────────────── 4:03 │
    │ next ▸ Strangers — Kosheen  · spotify-app                               │
    ╰─────────────────────────────────────────────────────────────────────────╯
    ╭ Alter Era ─────────────╮╭ Lyrics · TIDAL ──────────────────────────────╮
    │        ⢀⣀⣠⠤⠤⢤⣀⣀       ││            Waiting in a car                  │
    │      ⣠⠞⠉      ⠈⠙⢦⡀     ││ ███  Waiting for a ride in the dark  ███     │
    │      (floating logo)   ││          The night city grows                │
    ╰────────────────────────╯╰──────────────────────────────────────────────╯
    ╭ log ────────────────────────────────────────────────────────────────────╮
    │ 21:04:12 → next up: Strangers — Kosheen [spotify-app, 30 candidates]   │
    ╰────── space play/pause · n next pick · b back · l lyrics · q quit ─────╯

The logo floats on the left and the lyrics scroll on the right, the line being
sung shown inverted. With no lyrics the logo gets the whole width; `l` shows
the logo alone. Rendering runs on Rich's refresh thread and only reads the
loop's state, so a slow render can never delay a hand-off.
"""

from __future__ import annotations

import textwrap
import threading
import time
from collections import deque
from typing import Callable, Optional

from rich.color import Color
from rich.console import Console, ConsoleOptions, RenderResult
from rich.layout import Layout
from rich.panel import Panel
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .fx import Backdrop, Canvas, segments, spring
from .lyrics import Lyrics, LyricsService
from .theme import Theme, theme as make_theme
from .visualizer import LogoScene, lerp, smoothstep

KEYS_LINE = "space play/pause · n next pick · f flow · p presets · l lyrics · a cover · q quit"

# toolbar chips: (key, label, action); actions "cmd:<loop command>" or "ui:<screen action>"
CHIPS = [("space", "play/pause", "cmd:playpause"), ("n", "next", "cmd:next"), ("f", "flow", "cmd:flow"),
         ("p", "presets", "ui:presets"), ("l", "lyrics", "ui:view"), ("a", "cover", "ui:art"),
         ("t", "tree", "ui:tree"), ("esc", "settings", "ui:settings"), ("q", "quit", "cmd:quit")]

# The settings menu (Esc): (section, ui setting, [(value, label, description)])
def _theme_items() -> list:
    from .theme import THEME_LABELS, THEMES

    return [(name, THEME_LABELS.get(name, name), "") for name in THEMES]


SETTINGS = [
    ("Theme", "theme", _theme_items()),
    ("Party mode", "party", [
        (False, "Off", ""),
        (True, "On", "every logo colour and motion, gliding, apart and together"),
    ]),
    ("Logo colours", "logo_style", [
        ("theme", "Theme", "the theme's lilac, breathing"),
        ("muted", "Muted", "softer and greyer"),
        ("filled", "Logo colours, filled", "the logo's own colours, filled in"),
        ("wireframe", "Logo colours, outlines", "the logo's lines in its own colours"),
        ("pastel", "Pastel, filled", "the logo's colours, softened"),
        ("neon", "Neon outlines", "bright, glowing lines"),
        ("sunset", "Sunset, filled", "golds, corals and magentas"),
        ("ocean", "Ocean, filled", "blues and aquas"),
        ("catppuccin", "Catppuccin, filled", "the theme's own colours"),
        ("mono", "Black and white", ""),
    ]),
    ("Logo version", "logo_version", [
        ("lines", "Lines", "the line drawing; filled colours get dark edges"),
        ("flat", "Flat", "solid shapes in the logo's colours, no outlines"),
    ]),
    ("Logo detail", "logo_detail", [
        ("half", "Low", "filled colours in half blocks, 1×2 pixels a character"),
        ("quadrant", "Medium", "quarter blocks, 2×2"),
        ("sextant", "High", "sixth blocks, 2×3"),
        ("octant", "Highest", "eighth blocks, 2×4: as fine as characters go"),
    ]),
    ("Logo motion", "logo_motion", [
        ("float", "Float", "bob, drift and tilt"),
        ("gentle", "Gentle", "slower and smaller"),
        ("lively", "Lively", "bigger and quicker"),
        ("shapes", "Shapes", "every shape floats on its own"),
        ("tide", "Tide", "drifts apart and back together, slowly"),
        ("topple", "Topple", "falls apart as it leans, swings back together"),
        ("jelly", "Jelly", "the pieces lag behind on springs and wobble"),
        ("magnet", "Magnet", "pushed apart now and then, snapping back"),
        ("still", "Still", "no motion"),
    ]),
    ("Logo size", "logo_size", [("<slider>", "Size", "← → the logo on its own (no backdrop)")]),
    ("Shuffle tree", "shuffle_view", [
        ("off", "Off", ""),
        ("logo", "In place of the logo", "watch the next song being chosen (t)"),
        ("side", "In place of Up next", "in a wide window"),
    ]),
    ("Rain", "rain", [
        (0.0, "Off", ""), (0.3, "Faint", "barely there"), (0.6, "Soft", ""), (1.0, "Clear", ""),
    ]),
    ("Lyrics not sung yet", "lyrics_ahead", [
        ("hide", "Hidden", "each line appears when it is sung"),
        ("dim", "Dimmed", "faint until sung"),
        ("show", "Shown", "read ahead"),
    ]),
    ("Lyrics timing", "lyrics_lead", [
        (0.3, "Later", "if the highlight runs ahead of the singing"),
        (0.55, "Normal", ""),
        (0.8, "Earlier", "if the highlight lags the singing"),
        (1.1, "Earliest", ""),
    ]),
    ("Backdrop look", "backdrop_zoom", [("<slider>", "Zoom", "← → zoom out to see more of the picture, or in")]),
    ("Backdrop look", "backdrop_dim", [("<slider>", "Dim", "← → how far the picture fades back behind the logo")]),
    ("Backdrop look", "logo_size_stage", [("<slider>", "Logo", "← → how big the logo stands on a backdrop")]),
    ("Backdrop look", "logo_floor", [("<slider>", "Floor", "← → how far down the stage's floor is")]),
    ("Picture detail", "picture_detail", [
        ("half", "Low", "half blocks, 1×2 pixels a character"),
        ("quadrant", "Medium", "quarter blocks, 2×2 pixels a character"),
        ("sextant", "High", "sixth blocks, 2×3 pixels a character"),
        ("octant", "Highest", "eighth blocks, 2×4 pixels a character: as fine as characters go"),
        ("braille", "Dots", "braille dots, 2×4 pixels a character (grainier)"),
    ]),
    # pictures of your own follow these (see stages.py)
    ("Logo backdrop", "logo_backdrop", [
        ("off", "Off", ""),
        ("cover", "Album cover", "the song's cover, softened"),
        ("random", "A different picture each song", "from your backdrops"),
    ]),
]
SETTING_ITEMS = [(key, value, label, desc, section) for section, key, values in SETTINGS
                 for value, label, desc in values]
# settings adjusted with ← →: (lowest, highest, step)
SLIDERS = {"backdrop_zoom": (0.3, 2.0, 0.1), "backdrop_dim": (0.0, 0.9, 0.05), "logo_size": (0.3, 1.0, 0.05),
           "logo_size_stage": (0.25, 1.0, 0.05), "logo_floor": (0.5, 1.0, 0.02)}
BACKDROP_SLIDERS = ("backdrop_zoom", "backdrop_dim", "logo_size_stage", "logo_floor")
# settings shown live in the preview while the cursor is on them
PREVIEWED = ("theme", "party", "logo_style", "logo_version", "logo_detail", "logo_motion", "shuffle_view", "rain",
             "logo_backdrop", "picture_detail")
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# the Alter Era logo's colours, for the title
TITLE_COLORS = [(253, 192, 0), (250, 167, 110), (243, 124, 104), (136, 128, 222), (0, 255, 230), (10, 180, 155)]
HEADER_H = 7

# the preset menu's sections, in order; presets of your own come last
PRESET_GROUPS = [
    ("Energy & sound", ("radio", "warm-up", "wind-down", "steady", "soundscape", "vibe", "chill")),
    ("How picks are chosen", ("balanced", "familiar", "discovery", "wander", "anchor")),
    ("Sources", ("lastfm-only", "spotify-only", "tidal-only")),
    ("Spotify tuning", ("late-night-drive", "workout")),
]


def preset_sections(names) -> list:
    """``[(section, [names])]`` for the preset menu, in display order."""
    left = list(names)
    out = []
    for label, members in PRESET_GROUPS:
        group = [n for n in members if n in left]
        if group:
            out.append((label, group))
            left = [n for n in left if n not in group]
    if left:
        out.append(("Your presets", left))
    return out

_STYLES: dict = {}
_DEPTH = {"system": "truecolor"}
_NEAREST: dict = {}

# xterm's 256-colour palette above the 16 themeable ones: a 6x6x6 cube and 24 greys
_CUBE = (0, 95, 135, 175, 215, 255)
_PALETTE_256 = ([(16 + 36 * r + 6 * g + b, (_CUBE[r], _CUBE[g], _CUBE[b]))
                 for r in range(6) for g in range(6) for b in range(6)]
                + [(232 + i, (8 + 10 * i,) * 3) for i in range(24)])


def nearest_256(rgb) -> int:
    """The closest colour of the 256-colour palette, by a perceptual distance
    ("redmean"). Rich's own downgrade turns Catppuccin's dark blue-greys into
    pure black; this keeps them as the dark greys they nearly are."""
    hit = _NEAREST.get(rgb)
    if hit is None:
        r1, g1, b1 = rgb
        best, hit = None, 16
        for idx, (r2, g2, b2) in _PALETTE_256:
            rm = (r1 + r2) / 2
            d = (2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2
            if best is None or d < best:
                best, hit = d, idx
        _NEAREST[rgb] = hit
    return hit


def set_color_depth(system: Optional[str]) -> None:
    """Match colours to what the terminal shows ("truecolor", "256", ...)."""
    if _DEPTH["system"] != system:
        _DEPTH["system"] = system
        _STYLES.clear()


def _color(rgb):
    if not rgb:
        return None
    if _DEPTH["system"] == "256":
        return Color.from_ansi(nearest_256(tuple(rgb)))
    return Color.from_rgb(*rgb)


def style(fg=None, bold: bool = False, bg=None) -> Style:
    """Cached styles: a frame uses thousands of cells."""
    key = (fg, bold, bg)
    st = _STYLES.get(key)
    if st is None:
        st = Style(color=_color(fg), bold=bold or None, bgcolor=_color(bg))
        _STYLES[key] = st
    return st


def fmt_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-:--"
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class GridView:
    """A renderable that fills its region with cells from ``fn(width, height)``.
    A cell is ``(char, fg)`` or ``(char, fg, bold, bg)``."""

    def __init__(self, fn: Callable[[int, int], list]):
        self.fn = fn

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = options.max_width
        height = options.height or options.max_height or 10
        grid = self.fn(width, height)
        for row in grid[:height]:
            run_text, run_key = [], None
            for cell in row[:width]:
                key = (cell[1], cell[2] if len(cell) > 2 else False, cell[3] if len(cell) > 3 else None)
                if key != run_key and run_text:
                    yield Segment("".join(run_text), style(*run_key))
                    run_text = []
                run_key = key
                run_text.append(cell[0])
            if run_text:
                yield Segment("".join(run_text), style(*run_key))
            yield Segment.line()


def _wrap(text: str, width: int) -> list[tuple[str, int]]:
    """Wrapped parts of a line with each part's character offset into it."""
    out, at = [], 0
    for part in (textwrap.wrap(text, width) or [""]):
        o = text.find(part, at)
        o = at if o < 0 else o
        out.append((part, o))
        at = o + len(part)
    return out


def sung_chars(lyrics: Lyrics, idx: int, position: float, lead: float = 0.25) -> float:
    """How far the singing has got into line ``idx``, in characters: from the
    word stamps when the lyrics have them (enhanced LRC), else spread over the
    time the line is likely sung (until the next line, at a singing pace)."""
    line = lyrics.lines[idx]
    text = line.text.strip()
    n = len(text)
    if not n or line.time is None:
        return 0.0
    pos = position + lead
    nxt = next((l.time for l in lyrics.lines[idx + 1:] if l.time is not None), None)
    if line.words:
        stamps = list(line.words) + [((nxt if nxt is not None else line.words[-1][0] + 0.8), n)]
        done = 0.0
        for (t0, a0), (t1, a1) in zip(stamps, stamps[1:]):
            if pos >= t1:
                done = float(a1)
            elif pos >= t0:
                done = a0 + (a1 - a0) * (pos - t0) / max(0.05, t1 - t0)
                break
            else:
                break
        return done
    gap = (nxt - line.time) if nxt is not None else n * 0.12
    dur = max(0.6, min(gap * 0.92, max(1.5, n * 0.11)))
    return n * max(0.0, min(1.0, (pos - line.time) / dur))


def _word_starts(text: str) -> list[int]:
    """For every character, where its word starts (a space goes with the next word)."""
    starts = [0] * len(text)
    begin = 0
    for k, ch in enumerate(text):
        if ch != " " and (k == 0 or text[k - 1] == " "):
            begin = k
        starts[k] = begin
    nxt = len(text)
    for k in range(len(text) - 1, -1, -1):
        if text[k] == " ":
            starts[k] = nxt
        else:
            nxt = starts[k]
    return starts


def sweep_cells(part: str, offset: int, line_text: str, sung: float, th: Theme) -> list:
    """The cells of (part of) the line being sung: the words already reached
    are inverted (dark text on the accent colour), the rest of the line waits
    in bright text, so the inversion sweeps along the line in time."""
    starts = _word_starts(line_text)
    cells = []
    for k, ch in enumerate(part):
        o = offset + k
        lit = o < len(starts) and starts[o] <= sung
        cells.append((ch, th.current_fg, True, th.current_bg) if lit else (ch, th.text, True, None))
    return cells


def paint_current(row: list, start: int, cells: list, th: Theme) -> None:
    """Lay the line being sung into ``row`` at ``start``, with one inverted
    cell of padding either side of the sung part."""
    width = len(row)
    for k, cell in enumerate(cells):
        if 0 <= start + k < width:
            row[start + k] = cell
    lit = [k for k, c in enumerate(cells) if len(c) > 3 and c[3] is not None]
    if not lit:
        return
    pad = (" ", th.current_fg, True, th.current_bg)
    if lit[0] == 0 and start - 1 >= 0:
        row[start - 1] = pad
    if lit[-1] == len(cells) - 1 and start + len(cells) < width:
        row[start + len(cells)] = pad


def lyric_rows(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int,
               height: int, lead: float = 0.25) -> list[tuple[str, str, int]]:
    """The rows to show, centred on the line being sung: (text, kind, offset),
    kind being "current", "past:N", "next:N" (N = lines away), "plain",
    "countin" or "blank", offset where the row starts in its lyric line."""
    wrap = max(10, width - 8)
    rows: list[tuple[str, int, int]] = []          # (text, lyric line index, offset)
    starts: list[int] = []
    for i, line in enumerate(lyrics.lines):
        starts.append(len(rows))
        text = line.text.strip() or ("♪" if lyrics.synced else "")
        for part, off in _wrap(text, wrap):
            rows.append((part, i, off))
    if not rows:
        return []
    pos = position or 0.0
    if lyrics.synced:
        current = lyrics.index_at(pos, lead)
        first = starts[current] if current >= 0 else 0
        last = (starts[current + 1] if current + 1 < len(starts) else len(rows)) if current >= 0 else 1
        # centre the whole (possibly wrapped) line, but never push its start off the top
        top = min(first, first + (last - first) // 2 - height // 2)
    else:
        current = -1
        frac = (pos / duration) if duration else 0.0
        top = int(max(0.0, min(1.0, frac)) * (len(rows) - 1)) - height // 2
    out: list[tuple[str, str, int]] = []
    for r in range(top, top + height):
        if r < 0 or r >= len(rows):
            out.append(("", "blank", 0))
            continue
        text, i, off = rows[r]
        if not lyrics.synced:
            out.append((text, "plain", off))
        elif i == current:
            out.append((text, "current", off))
        elif i < current:
            out.append((text, f"past:{current - i}", off))
        else:
            out.append((text, f"next:{i - current}", off))
    # count-in before the first line: three dots filling up
    if lyrics.synced and current < 0 and lyrics.lines and lyrics.lines[0].time:
        first_t = lyrics.lines[0].time
        filled = int(3 * max(0.0, min(1.0, pos / first_t)))
        mid = height // 2
        if 0 <= mid - 1 < len(out):
            out[mid - 1] = ("● " * filled + "○ " * (3 - filled), "countin", 0)
    return out


def _line_color(kind: str, th: Theme):
    if kind.startswith("past:"):
        return lerp(th.past, th.bg, min(0.7, (int(kind[5:]) - 1) / 8))
    if kind.startswith("next:"):
        return lerp(th.text, th.past, min(1.0, (int(kind[5:]) - 1) / 8))
    if kind == "countin":
        return th.title
    return th.text


def _fade_grid(grid: list, alpha: float, th: Theme) -> list:
    """Fade a grid towards the panel colour (``alpha`` 1 = as is, 0 = gone)."""
    if alpha >= 0.999:
        return grid
    if alpha < 0.06:                       # as good as gone
        return [[(" ", None)] * len(row) for row in grid]
    out = []
    for row in grid:
        new = []
        for c in row:
            if c[0] == " " and (len(c) < 4 or c[3] is None):
                new.append(c)
                continue
            fg = lerp(th.bg, c[1] or th.text, alpha)
            bg = lerp(th.bg, c[3], alpha) if len(c) > 3 and c[3] is not None else None
            new.append((c[0], fg, (c[2] if len(c) > 2 else False) and alpha > 0.5, bg))
        out.append(new)
    return out


def two_column_grid(lyrics: Lyrics, position: Optional[float], width: int, height: int, th: Theme) -> Optional[list]:
    """All the lyrics at once, in two columns (or one, if that fits), split at a
    verse break. Nothing is highlighted: without real timing a highlight would
    be wrong as often as right. None when they do not fit."""
    col_w = (width - 4) // 2

    def wrapped(wrap_at: int) -> list[tuple[str, int, int]]:
        out: list[tuple[str, int, int]] = []
        for i, line in enumerate(lyrics.lines):
            for part, off in _wrap(line.text.strip(), max(8, wrap_at)):
                out.append((part, i, off))
        while out and not out[0][0]:
            out.pop(0)
        while out and not out[-1][0]:
            out.pop()
        return out

    rows = wrapped(width - 8)                 # one column, if everything fits
    if not rows:
        return None
    grid = [[(" ", None)] * width for _ in range(height)]

    def paint(column: list, x0: int, w: int, top: int) -> None:
        for r, (text, i, off) in enumerate(column):
            y = top + r
            if y >= height:
                return
            start = x0 + max(0, (w - len(text)) // 2)
            row = grid[y]
            for k, ch in enumerate(text):
                row[start + k] = (ch, th.text)

    if len(rows) <= height:
        paint(rows, 0, width, max(0, (height - len(rows)) // 2))
        return grid
    rows = wrapped(col_w - 4)                 # two columns, narrower lines
    if col_w < 18 or len(rows) > 2 * height:
        return None
    half = (len(rows) + 1) // 2
    split = half
    for d in range(0, 6):                      # prefer a verse break near the middle
        for k in (half + d, half - d):
            if 0 < k < len(rows) and not rows[k][0]:
                split = k
                break
        else:
            continue
        break
    left, right = rows[:split], rows[split:]
    while right and not right[0][0]:
        right.pop(0)
    if len(left) > height or len(right) > height:
        return None
    top = max(0, (height - max(len(left), len(right))) // 2)   # both columns start on the same row
    paint(left, 0, col_w, top)
    paint(right, col_w + 4, width - col_w - 4, top)
    return grid


def lyrics_fit(lyrics: Lyrics, width: int, height: int, th: Theme) -> bool:
    """Do lyrics without real timing fit the panel whole (no scrolling needed)?"""
    return two_column_grid(lyrics, 0.0, width, height, th) is not None


def lyrics_grid(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int, height: int,
                th: Theme, alpha: float = 1.0, lead: float = 0.25, ahead: str = "show") -> list:
    """Lyric rows centred in the panel; the words of the line being sung turn
    inverted as they are sung. ``ahead``: what to do with lines not sung yet
    (show, dim or hide). Lyrics without real timing are never highlighted:
    shown whole, in two columns, when they fit, else scrolled along with the
    song. ``alpha`` fades the whole thing."""
    if lyrics.estimated or not lyrics.synced:
        whole = two_column_grid(lyrics, position, width, height, th)
        if whole is not None:
            return _fade_grid(whole, alpha, th)
        lyrics = Lyrics(lines=lyrics.lines, synced=False, source=lyrics.source)   # scroll, no highlight
    grid = [[(" ", None)] * width for _ in range(height)]
    rows = lyric_rows(lyrics, position, duration, width, height, lead)
    current = lyrics.index_at(position or 0.0, lead) if lyrics.synced else -1
    sung = sung_chars(lyrics, current, position or 0.0, lead) if current >= 0 else 0.0
    for r, (text, kind, off) in enumerate(rows):
        if r >= height or (not text and kind != "current"):
            continue
        if kind.startswith("next:") and ahead == "hide":
            continue                                   # not sung yet
        text = text[:max(1, width - 2)]
        start = max(0, (width - len(text)) // 2)
        row = list(grid[r])
        if kind == "current":
            line_text = lyrics.lines[current].text.strip() if current >= 0 else text
            paint_current(row, start, sweep_cells(text, off, line_text, sung, th), th)
        else:
            color = _line_color(kind, th)
            if kind.startswith("next:") and ahead == "dim":
                color = lerp(th.past, th.bg, 0.45)
            elif kind == "plain":
                color = th.text
            for i, ch in enumerate(text):
                row[start + i] = (ch, color)
        grid[r] = row
    return _fade_grid(grid, alpha, th)


class ShuffleTUI:
    """State and rendering for the full-screen view; also routes keys and clicks."""

    def __init__(self, loop, config, lyrics: Optional[LyricsService] = None, scene: Optional[LogoScene] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 theme: Optional[Theme] = None, artwork=None, history=None,
                 post: Optional[Callable[[str], None]] = None,
                 presets: Optional[Callable[[], dict]] = None, settings_path=None, stages=None):
        self.loop = loop
        self.config = config
        self.lyrics = lyrics
        self.th = theme or make_theme(getattr(getattr(config, "ui", None), "theme", "mocha"))
        if scene is not None:
            scene.logo, scene.glow, scene.shadow, scene.bg = self.th.logo, self.th.logo_glow, self.th.shadow, self.th.bg
        self.scene = scene
        ui = getattr(config, "ui", None)
        self.settings_path = settings_path
        self.stages = stages
        if self.stages is None:
            from .stages import StageArt

            self.stages = StageArt(cover=self._cover_image)
        self.setting_items = list(SETTING_ITEMS)
        self.refresh_backdrops()
        self._preview: dict = {}          # setting -> value shown while the settings cursor is on it
        self._applied: dict = {}          # what the screen shows now, per previewed setting
        self._theme_from = self._theme_to = self.th
        self._theme_since = -1e9
        self._tree_seen: dict = {}        # trace node index -> when it unfolded (per trace)
        self._tree_id = None
        self._tree_last = 0.0
        self.settings_open = False
        self.settings_cursor = 0
        self._settings = [0.0, 0.0]
        self._settings_hits: list = []
        self._apply_logo_style()
        self.backdrop = (Backdrop(self.th.p, light=self.th.light, visibility=float(getattr(ui, "rain", 0.3)))
                         if getattr(ui, "backdrop", True) else None)
        self.glass = float(getattr(ui, "glass", 0.22))
        # transitions: (value, velocity) springs, so nothing ever jumps
        self._layout = [0.0, 0.0]     # 0: the logo alone, 1: logo and lyrics side by side
        self._content = [0.0, 0.0]    # how visible the lyrics text is
        self._menu = [0.0, 0.0]       # the preset menu
        self._layout_goal = 0.0
        self._shown: Optional[Lyrics] = None     # lyrics in the panel (the old song's, while they fade)
        self._shown_pos: tuple = (None, None)    # their position and length, frozen once their song is over
        self._hold_since: Optional[float] = None
        self._last_frame: Optional[float] = None
        self._status = "waiting"
        self._art_key = None
        self._art_prev = None
        self._art_grid = None
        self._art_since = 0.0
        self._art_mode = getattr(ui, "art_blocks", "quadrant")
        self.cover_view = False       # the cover, big, in place of the logo (a)
        self._cover = [0.0, 0.0]
        self.artwork = artwork
        self.history = history if history is not None else getattr(loop, "history", None)
        self.post = post or getattr(loop, "post", None) or (lambda cmd: None)
        self.presets = presets or (lambda: dict(getattr(config, "presets", None) or {}))
        self._clock = clock
        self._wall = wall
        self.logs: deque = deque(maxlen=400)
        self._lock = threading.Lock()
        self.view = "auto"           # auto: logo + lyrics | logo: the logo alone
        self._estimate_key = None
        self._estimate = None
        self.menu_open = False
        self.menu_cursor = 0
        self._hits: list = []        # (row, col_from, col_to, action), rebuilt on every render

    # -- inputs ------------------------------------------------------------------
    def log(self, msg: str, dim: bool = False) -> None:
        with self._lock:
            self.logs.append((time.strftime("%H:%M:%S"), str(msg), dim))

    def toggle_view(self) -> None:
        self.view = "logo" if self.view == "auto" else "auto"
        self.log("showing the logo" if self.view == "logo" else "showing the lyrics")

    def _apply_logo_style(self) -> None:
        """Give the logo the colours and motion chosen in the settings."""
        sc = self.scene
        if sc is None:
            return
        th, p = self.th, self.th.p
        from .visualizer import MOTIONS, STYLES, logo_palette

        sc.logo, sc.glow, sc.shadow, sc.bg = th.logo, th.logo_glow, th.shadow, th.bg
        sc.theme_palette = p
        style = self.setting("logo_style") or "theme"
        sc.style = style if style in STYLES else "theme"
        motion = self.setting("logo_motion") or "float"
        sc.motion = motion if motion in MOTIONS else "float"
        sc.colors = logo_palette(sc.style, p)
        if hasattr(sc, "set_version"):
            sc.set_version(self.setting("logo_version") or "lines")
        sc.detail = self.setting("logo_detail") or "quadrant"
        party = bool(self.setting("party"))
        sc.party_colors = party
        if party:
            sc.motion = "party"
        if style == "muted":
            sc.logo, sc.glow = lerp(th.logo, p["overlay1"], 0.55), lerp(th.logo_glow, p["overlay2"], 0.5)
        elif style == "mono":
            dark_bg = sum(th.bg) < 384
            sc.logo, sc.glow = ((222, 222, 222), (255, 255, 255)) if dark_bg else ((40, 40, 40), (0, 0, 0))
        else:
            sc.logo, sc.glow = th.logo, th.logo_glow

    def setting(self, key: str):
        """A setting as the screen should show it: the one being previewed, else the chosen one."""
        if key in self._preview:
            return self._preview[key]
        return getattr(getattr(self.config, "ui", None), key, None)

    def chosen(self, key: str):
        return getattr(getattr(self.config, "ui", None), key, None)

    def _sync_settings(self, now: float) -> None:
        """Bring the screen in line with the settings (chosen or previewed):
        themes blend into each other, the logo eases into its new look."""
        from .theme import blend, theme as make

        name = self.setting("theme") or "mocha"
        if self._applied.get("theme") != name:
            if self._applied.get("theme") is not None:
                self._theme_from = self.th
                self._theme_since = now
            self._theme_to = make(name)
            self._applied["theme"] = name
        k = smoothstep((now - self._theme_since) / 0.6)
        th = blend(self._theme_from, self._theme_to, k) if k < 1 else self._theme_to
        if th is not self.th:
            self.th = th
            if len(_STYLES) > 6000:
                _STYLES.clear()
            if self.backdrop is not None:
                self.backdrop.p, self.backdrop.light = th.p, th.light
            self._applied.pop("logo", None)
        logo = (self.setting("logo_style"), self.setting("logo_motion"), bool(self.setting("party")), th.name,
                self.setting("logo_version"), self.setting("logo_detail"))
        if self._applied.get("logo") != logo:
            self._apply_logo_style()
            self._applied["logo"] = logo
        rain = self.setting("rain")
        if rain is not None and self._applied.get("rain") != rain:
            if self.backdrop is None and rain > 0:
                self.backdrop = Backdrop(th.p, light=th.light, visibility=rain)
            elif self.backdrop is not None:
                self.backdrop.visibility = rain
            self._applied["rain"] = rain

    def refresh_backdrops(self) -> None:
        """The settings list, with a choice for every picture in the backdrops folder."""
        from .stages import label

        names = self.stages.names() if self.stages is not None else []
        self.setting_items = list(SETTING_ITEMS) + [
            ("logo_backdrop", n, label(n), "", "Logo backdrop") for n in names]

    def _cover_image(self):
        cur = self.loop.state.current
        if cur is None or self.artwork is None:
            return None
        return self.artwork.get(f"{cur.artist}|{cur.title}", cur.tidal_id, cur.title, cur.artist)

    def _preview_cursor(self) -> None:
        """Show the setting under the cursor, live, without choosing it yet."""
        key, value = self.setting_items[self.settings_cursor][:2]
        self._preview = {key: value} if key in PREVIEWED else {}
        if (key in BACKDROP_SLIDERS or key == "picture_detail") and (self.chosen("logo_backdrop") or "off") == "off":
            # nothing to zoom or dim yet: show a picture while the slider is adjusted
            names = self.stages.names() if self.stages is not None else []
            self._preview = dict(self._preview, logo_backdrop=names[0] if names else "cover")
        if key in ("logo_detail", "logo_version"):
            from .visualizer import FILLED_STYLES

            if key == "logo_detail" and self.chosen("logo_style") not in FILLED_STYLES and not self.chosen("party"):
                # the detail is that of filled colours: show them while choosing it
                self._preview = dict(self._preview, logo_style="filled")

    def adjust_slider(self, key: str, direction: int) -> None:
        """Move a slider setting one step (it applies at once and is remembered)."""
        from . import uistate

        lo, hi, step = SLIDERS[key]
        ui = getattr(self.config, "ui", None)
        if ui is None:
            return
        value = float(getattr(ui, key, lo) or 0.0)
        value = round(min(hi, max(lo, value + direction * step)), 2)
        setattr(ui, key, value)
        uistate.save(self.settings_path, {k: getattr(ui, k) for k in uistate.KEYS if hasattr(ui, k)})

    def slider_bar(self, key: str, cells: int = 14) -> str:
        lo, hi, _ = SLIDERS[key]
        value = float(getattr(getattr(self.config, "ui", None), key, lo) or 0.0)
        filled = int(round((value - lo) / (hi - lo) * cells))
        return "◂ " + "▰" * filled + "▱" * (cells - filled) + f" {value * 100:.0f}% ▸"

    def is_current(self, key: str, value) -> bool:
        cur = self.chosen(key)
        if isinstance(value, float) and isinstance(cur, (int, float)):
            return abs(cur - value) < 1e-6
        return cur == value

    def open_settings(self) -> None:
        self.menu_open = False
        self.refresh_backdrops()
        cur = next((i for i, it in enumerate(self.setting_items) if self.is_current(it[0], it[1])), 0)
        self.settings_cursor = cur
        self.settings_open = True
        self._preview = {}

    def close_settings(self) -> None:
        self.settings_open = False
        self._preview = {}                 # what was only previewed goes back to what was chosen

    def apply_setting(self, index: int) -> None:
        """Apply one choice of the settings menu, at once, and remember it."""
        from . import uistate

        if not 0 <= index < len(self.setting_items):
            return
        key, value, label, _, section = self.setting_items[index]
        ui = getattr(self.config, "ui", None)
        if ui is None or key in SLIDERS:
            return                                    # sliders move with ← →
        setattr(ui, key, value)
        self._preview.pop(key, None)
        self._sync_settings(self._clock())
        uistate.save(self.settings_path, {k: getattr(ui, k) for k in uistate.KEYS if hasattr(ui, k)})
        self.log(f"{section}: {label}")

    def toggle_tree(self) -> None:
        """Show or hide the shuffle tree (t), where it was last shown."""
        from . import uistate

        ui = getattr(self.config, "ui", None)
        if ui is None:
            return
        now = self.chosen("shuffle_view") or "off"
        if now == "off":
            ui.shuffle_view = getattr(self, "_tree_place", "logo")
        else:
            self._tree_place = now
            ui.shuffle_view = "off"
        uistate.save(self.settings_path, {k: getattr(ui, k) for k in uistate.KEYS if hasattr(ui, k)})
        self.log("showing the shuffle tree" if ui.shuffle_view != "off" else "hiding the shuffle tree")

    def toggle_cover(self) -> None:
        self.cover_view = not self.cover_view
        self.log("showing the album cover" if self.cover_view else "showing the logo")

    def _preset_names(self) -> list:
        """Preset names in menu order (the cursor walks this list)."""
        return [n for _, group in preset_sections(self.presets()) for n in group]

    def open_menu(self) -> None:
        names = self._preset_names()
        current = getattr(self.config, "preset", None)
        self.menu_cursor = names.index(current) if current in names else 0
        self.menu_open = True

    def choose(self, name: str) -> None:
        """Apply a preset: the loop switches to it and chooses the next song again."""
        self.menu_open = False
        self.post(f"preset:{name}")

    def act(self, action: str) -> None:
        kind, _, arg = action.partition(":")
        if kind == "cmd":
            self.post(arg)
        elif kind == "ui" and arg == "presets":
            self.settings_open = False
            self.menu_open = False if self.menu_open else (self.open_menu() or True)
        elif kind == "ui" and arg == "view":
            self.toggle_view()
        elif kind == "ui" and arg == "art":
            self.toggle_cover()
        elif kind == "ui" and arg == "settings":
            if self.settings_open:
                self.close_settings()
            else:
                self.open_settings()
        elif kind == "ui" and arg == "tree":
            self.toggle_tree()
        elif kind == "set":
            self.settings_cursor = int(arg)
            self.apply_setting(int(arg))
        elif kind == "preset":
            self.choose(arg)
        elif kind == "menu" and arg == "close":
            self.menu_open = False

    def handle_input(self, cmd: str) -> bool:
        """Keys and clicks the screen handles itself; False passes ``cmd`` on to the loop."""
        if cmd.startswith("click:"):
            try:
                _, x, y = cmd.split(":")
                col, row = int(x) - 1, int(y) - 1
            except ValueError:
                return True
            for r, c0, c1, action in list(self._hits):
                if r == row and c0 <= col < c1:
                    self.act(action)
                    break
            return True
        if cmd in ("presets",):
            self.act("ui:presets")
            return True
        if cmd == "view":
            self.toggle_view()
            return True
        if cmd == "art":
            self.toggle_cover()
            return True
        if cmd == "tree":
            self.toggle_tree()
            return True
        if cmd == "escape" and not self.menu_open:
            self.act("ui:settings")                   # Esc opens and closes the settings
            return True
        if self.settings_open:
            n = len(self.setting_items)
            if cmd in ("up", "wheel-up"):
                self.settings_cursor = max(0, self.settings_cursor - 1)
                self._preview_cursor()
            elif cmd in ("down", "wheel-down"):
                self.settings_cursor = min(n - 1, self.settings_cursor + 1)
                self._preview_cursor()
            elif cmd == "enter":
                self.apply_setting(self.settings_cursor)
            elif cmd == "quit":
                self.close_settings()
            elif cmd in ("left", "right") and self.setting_items[self.settings_cursor][0] in SLIDERS:
                self.adjust_slider(self.setting_items[self.settings_cursor][0], -1 if cmd == "left" else 1)
            elif cmd in ("left", "right"):
                # jump to the previous or next section
                # (the sliders are skipped: on a slider, ← → move the slider)
                sections = [i for i, it in enumerate(self.setting_items)
                            if (i == 0 or it[4] != self.setting_items[i - 1][4]) and it[0] not in SLIDERS]
                cur = max((i for i in sections if i <= self.settings_cursor), default=0)
                k = sections.index(cur)
                target = sections[max(0, k - 1)] if cmd == "left" else sections[min(len(sections) - 1, k + 1)]
                if cmd == "left" and self.settings_cursor != cur:
                    target = cur
                self.settings_cursor = target
                self._preview_cursor()
            else:
                return False
            return True
        if self.menu_open:
            names = self._preset_names()
            if cmd in ("up", "wheel-up"):
                self.menu_cursor = max(0, self.menu_cursor - 1)
            elif cmd in ("down", "wheel-down"):
                self.menu_cursor = min(max(0, len(names) - 1), self.menu_cursor + 1)
            elif cmd == "enter" and names:
                self.choose(names[min(self.menu_cursor, len(names) - 1)])
            elif cmd in ("escape", "quit"):
                self.menu_open = False
            elif cmd in ("left", "right"):
                pass
            else:
                return False          # play/pause, next... still work with the menu open
            return True
        return cmd in ("up", "down", "left", "right", "enter", "escape", "wheel-up", "wheel-down")

    # -- playback state ------------------------------------------------------------
    def position(self) -> tuple[Optional[float], Optional[float], Optional[bool]]:
        st = self.loop.state
        cur = st.current
        if cur is None:
            return None, None, None
        seed = st.plan.seed if st.plan is not None else None
        duration = cur.duration or (seed.duration if seed is not None else None)
        if cur.playing is False and cur.elapsed is not None:
            pos = cur.position_at(self._wall())
        else:
            pos = self._clock() - st.started_at
        if duration:
            pos = min(pos, duration)
        return max(0.0, pos), duration, cur.playing

    def current_lyrics(self):
        """Lyrics, None (none) or "pending" for the song playing."""
        cur = self.loop.state.current
        if cur is None or self.lyrics is None:
            return None
        return self.lyrics.get(cur.title, cur.artist, cur.album, cur.duration, cur.tidal_id)

    # -- small pieces ------------------------------------------------------------------
    def _panel(self, body, title, title_color=None, subtitle: str = "", padding=(0, 1)) -> Panel:
        th = self.th
        if isinstance(title, str):
            title = Text(f" {title} ", style(title_color or th.title, True)) if title else None
        return Panel(body, title=title, title_align="left",
                     subtitle=Text(f" {subtitle} ", style(th.faint)) if subtitle else None, subtitle_align="right",
                     border_style=style(th.border, False, th.bg), style=style(th.text, False, th.bg),
                     padding=padding)

    def gradient_text(self, text: str, colors: list, bold: bool = True) -> Text:
        out = Text()
        n = max(1, len(text) - 1)
        for i, ch in enumerate(text):
            t = i / n * (len(colors) - 1)
            k = min(len(colors) - 2, int(t))
            out.append(ch, style(lerp(colors[k], colors[k + 1], t - k), bold))
        return out

    def flowing_title(self, text: str) -> Text:
        """The title in the logo's colours, the gradient drifting slowly along it."""
        out = Text()
        cols = TITLE_COLORS + TITLE_COLORS[:1]              # a loop, so the drift never jumps
        shift = (self._clock() / 14.0) % 1.0
        n = len(cols) - 1
        for i, ch in enumerate(text):
            u = ((i / max(1, len(text))) * 0.6 + shift) % 1.0 * n
            k = int(u)
            out.append(ch, style(lerp(cols[k], cols[k + 1], u - k), True))
        return out

    def meter(self, value: float, cells: int = 10) -> Text:
        """An energy meter ▰▰▰▱▱ from green through yellow and peach to red."""
        p = self.th.p
        stops = [p["green"], p["yellow"], p["peach"], p["red"]]
        filled = int(round(max(0.0, min(1.0, value)) * cells))
        out = Text()
        for i in range(cells):
            if i < filled:
                t = i / max(1, cells - 1) * (len(stops) - 1)
                k = min(len(stops) - 2, int(t))
                out.append("▰", style(lerp(stops[k], stops[k + 1], t - k)))
            else:
                out.append("▱", style(p["surface2"]))
        return out

    def progress(self, pos: Optional[float], duration: Optional[float], width: int) -> Text:
        th, p = self.th, self.th.p
        left, right = fmt_time(pos), fmt_time(duration)
        bar_w = max(8, width - len(left) - len(right) - 2)
        frac = (pos / duration) if (pos is not None and duration) else 0.0
        done = int(bar_w * max(0.0, min(1.0, frac)))
        out = Text(left + " ", style(th.subtle))
        stops = [p["lavender"], p["mauve"], p["pink"]]
        for i in range(done):
            t = i / max(1, bar_w - 1) * (len(stops) - 1)
            k = min(len(stops) - 2, int(t))
            out.append("━", style(lerp(stops[k], stops[k + 1], t - k)))
        out.append("●", style(th.knob, True))
        out.append("─" * max(0, bar_w - done - 1), style(th.bar_rest))
        out.append(" " + right, style(th.subtle))
        return out

    def art(self, rows: int):
        """The cover of the song playing (or a placeholder), ``rows`` tall and
        square; a new cover dissolves in over the old one."""
        from .artwork import placeholder

        w = rows * 2
        p = self.th.p
        cur = self.loop.state.current
        img = None
        song = f"{cur.artist}|{cur.title}" if cur is not None else ""
        if cur is not None and self.artwork is not None:
            img = self.artwork.get(song, cur.tidal_id, cur.title, cur.artist)
        if img is None or img == "pending":
            key = ("placeholder", w)
            grid = placeholder(w, rows, p["mauve"], p["blue"], p["crust"])
        else:
            dither = _DEPTH["system"] == "256"
            key = (song, id(img), w, dither)
            grid = self.artwork.cells(song, img, w, rows, mode=self._art_mode, dither=dither)
        now = self._clock()
        if key != self._art_key:
            if self._art_grid is not None and len(self._art_grid) == rows:
                self._art_prev = self._art_grid
                self._art_since = now
            self._art_key = key
        self._art_grid = grid
        k = smoothstep((now - self._art_since) / 0.7) if self._art_prev is not None else 1.0
        if k < 1.0:
            old = self._art_prev
            grid = [[(c[0] if k > 0.5 else o[0], lerp(o[1], c[1], k), False, lerp(o[3], c[3], k))
                     for c, o in zip(row, orow)] for row, orow in zip(grid, old)]
        else:
            self._art_prev = None
        return GridView(lambda _w, _h: grid), w

    # -- regions ---------------------------------------------------------------------------
    def header(self, width: int) -> Panel:
        th, p = self.th, self.th.p
        st = self.loop.state
        cur = st.current
        pos, duration, playing = self.position()
        rows = HEADER_H - 2
        art, art_w = self.art(rows)
        info_w = max(20, width - 4 - art_w - 2)
        lines = Text()
        if cur is None:
            lines.append("waiting for TIDAL to play something…", style(th.subtle))
            lines.append("\n\n\n")
        else:
            badge = " ⏸ PAUSED " if playing is False else " ▶ PLAYING "
            title = cur.title[:max(4, info_w - len(badge) - 1)]
            lines.append(title, style(th.text, True))
            lines.append(" " * max(1, info_w - len(title) - len(badge)))
            lines.append(badge, style(p["crust"], True, p["yellow"] if playing is False else p["green"]))
            lines.append("\n")
            sub = cur.artist + (f"  ·  {cur.album}" if cur.album else "")
            lines.append(cur.artist[:info_w], style(p["subtext1"]))
            if cur.album and len(sub) <= info_w:
                lines.append(f"  ·  {cur.album}", style(th.faint))
            lines.append("\n\n")
            lines.append_text(self.progress(pos, duration, info_w))
        lines.append("\n")
        # next pick, and the flow with its target energy
        nxt = st.plan.primary if st.plan is not None else None
        flow = self.config.shuffle.flow
        target = getattr(st.plan, "flow_target", None) if st.plan is not None else None
        right = Text()
        right.append(f"{flow}", style(p["teal"], True))
        if target is not None and flow != "radio":
            right.append("  energy ", style(th.faint))
            right.append_text(self.meter(target, 8))
        left = Text("next ▸ ", style(th.faint))
        if st.handed_off and st.expected is not None:
            left.append(st.expected.track.label(), style(th.text))
            left.append("  starting…", style(th.subtle))
        elif nxt is not None:
            left.append(nxt.track.label(), style(th.text))
        elif st.planning is not None or (cur is not None and st.plan is None):
            left.append("choosing…", style(th.subtle))
        else:
            left.append("—", style(th.subtle))
        room = info_w - right.cell_len - 1
        if left.cell_len > room:
            left.truncate(max(8, room), overflow="ellipsis")
        lines.append_text(left)
        lines.append(" " * max(1, info_w - left.cell_len - right.cell_len))
        lines.append_text(right)
        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(width=art_w, no_wrap=True)
        grid.add_column(ratio=1)
        grid.add_row(art, lines)
        title = self.flowing_title(" Tidal Shuffle ")
        subtitle = f"{self.config.preset or 'no preset'} · {self.config.shuffle.strategy} · {st.picks_played} picks"
        return self._panel(grid, title, subtitle=subtitle)

    def logo_panel(self, caption: str) -> Panel:
        _, _, playing = self.position()
        live = playing is not False and self.loop.state.current is not None
        if self.scene is None:
            return self._panel(Text(""), caption, padding=(0, 0))
        scene = self.scene
        choice = self.setting("logo_backdrop") or "off"
        cur = self.loop.state.current
        song = f"{cur.artist}|{cur.title}" if cur is not None else ""
        name = self.stages.pick(choice, song) if self.stages is not None and choice != "off" else None
        th = self.th
        dim = float(getattr(getattr(self.config, "ui", None), "backdrop_dim", 0.45))
        aspect = float(getattr(getattr(self.config, "ui", None), "cell_aspect", 0.5))

        ui = getattr(self.config, "ui", None)

        def grid(w: int, h: int) -> list:
            art = None
            if name:
                zoom = float(getattr(ui, "backdrop_zoom", 1.0) or 1.0)
                dim_now = float(getattr(ui, "backdrop_dim", dim))
                art = self.stages.cells(name, w, h, self._clock(), th.bg, dim_now, aspect,
                                        key_extra=song if name == "cover" else None, zoom=zoom,
                                        detail=self.setting("picture_detail") or "quadrant")
            # on a stage the logo stands on the floor, fighter-sized; alone it floats, big
            if art is not None:
                scene.size = float(getattr(ui, "logo_size_stage", 0.55))
                scene.ground, scene.floor = 1.0, float(getattr(ui, "logo_floor", 0.88))
            else:
                scene.size, scene.ground = float(getattr(ui, "logo_size", 1.0)), 0.0
            logo = scene.frame(w, h, self._clock(), playing=live)
            if art is None:
                return logo
            from .stages import compose
            return compose(logo, art)
        return self._panel(GridView(grid), caption, padding=(0, 0))

    def current_trace(self):
        engine = getattr(self.loop, "engine", None)
        return getattr(engine, "trace", None)

    def tree_lines(self, width: int, height: int) -> Text:
        """The choice of the next song as a tree, unfolding one step at a time
        (each step appears in turn, fading in) and following the work live."""
        th, p = self.th, self.th.p
        tr = self.current_trace()
        text = Text(no_wrap=True, overflow="ellipsis")
        if tr is None:
            text.append("\n  waiting for the next song to be chosen…", style(th.faint))
            return text
        now = self._clock()
        if self._tree_id != id(tr):
            self._tree_id, self._tree_seen, self._tree_last = id(tr), {}, now - 1.0
        rows = tr.flat()
        for i in range(len(rows)):
            if i not in self._tree_seen:          # unfold: one new step every 0.12 s at most
                at = max(now, self._tree_last + 0.12)
                self._tree_seen[i] = at
                self._tree_last = at
        shown = [(i, r) for i, r in enumerate(rows) if self._tree_seen[i] <= now]
        if len(shown) > height:                   # keep the start and the latest steps
            shown = shown[:1] + shown[-(height - 1):]
        icons = {"done": ("✓", p["green"]), "failed": ("✗", p["red"]), "skipped": ("·", th.faint)}
        for n, (i, (depth, node, last, lasts)) in enumerate(shown):
            k = smoothstep((now - self._tree_seen[i]) / 0.35)      # fades in
            if n:
                text.append("\n")
            branch = "".join("   " if l else "│  " for l in lasts[1:]) + (("└─ " if last else "├─ ") if depth else "")
            text.append(branch, style(lerp(th.bg, th.border, k)))
            if node.status == "running":
                icon, col = SPINNER[int(now * 10) % len(SPINNER)], p["yellow"]
            elif node.kind == "pick" and node.status == "done":
                icon, col = "▶", p["mauve"]
            else:
                icon, col = icons.get(node.status, ("·", th.faint))
            text.append(icon + " ", style(lerp(th.bg, col, k), True))
            label_col = th.text if node.kind in ("seed", "step", "pick") else th.subtle
            if node.status == "skipped":
                label_col = th.faint
            text.append(node.label, style(lerp(th.bg, label_col, k), node.kind in ("seed", "step", "pick")))
            if node.detail:
                text.append("  " + node.detail, style(lerp(th.bg, th.faint if node.kind != "pick" else th.subtle, k)))
        return text

    def tree_panel(self, title: str = "Shuffle tree") -> Panel:
        tr = self.current_trace()
        sub = "choosing…" if tr is not None and tr.finished is None else ""
        tui = self

        class _Tree:
            def __rich_console__(self, console, options):
                h = options.height or options.max_height or 10
                yield tui.tree_lines(options.max_width, h)
        return self._panel(_Tree(), title, subtitle=sub)

    def cover_panel(self) -> Panel:
        """The cover of the song playing, as big as the panel allows (a)."""
        from .artwork import placeholder

        p = self.th.p
        cur = self.loop.state.current
        img = None
        song = f"{cur.artist}|{cur.title}" if cur is not None else ""
        if cur is not None and self.artwork is not None:
            img = self.artwork.get(song, cur.tidal_id, cur.title, cur.artist)
        have = img is not None and img != "pending"
        artwork = self.artwork
        mode = self._art_mode

        def grid(w: int, h: int) -> list:
            rows = max(1, min(h, w // 2))                 # square: a cell is about twice as tall as wide
            cols = rows * 2
            if have:
                pic = artwork.cells(song, img, cols, rows, mode=self.setting("picture_detail") or mode,
                                    dither=_DEPTH["system"] == "256")
            else:
                pic = placeholder(cols, rows, p["mauve"], p["blue"], p["crust"])
            left, top = (w - cols) // 2, (h - rows) // 2
            blank = [(" ", None)] * w
            out = [list(blank) for _ in range(h)]
            for r, row in enumerate(pic):
                out[top + r][left:left + cols] = row
            return out
        album = (cur.album if cur is not None and cur.album else "")
        title = "Cover" + (f" · {album}" if album else "") + ("" if have else (" · loading…" if img == "pending" else " · none"))
        return self._panel(GridView(grid), title, subtitle="a for the logo", padding=(0, 0))

    def lyrics_panel(self, lyr: Lyrics, pos: Optional[float], duration: Optional[float], alpha: float,
                     width: int = 0, height: int = 0) -> Panel:
        th = self.th
        title = f"Lyrics · {lyr.source}"
        if lyr.estimated or not lyr.synced:
            title += " · no timing"
            if width and height and not lyrics_fit(lyr, width - 2, height - 2, th):
                title += " · scrolling by estimate"
        ui = getattr(self.config, "ui", None)
        lead = float(getattr(ui, "lyrics_lead", 0.55))
        ahead = getattr(ui, "lyrics_ahead", "hide")
        return self._panel(GridView(lambda w, h: lyrics_grid(lyr, pos, duration, w, h, th, alpha=alpha, lead=lead,
                                                             ahead=ahead)), title, padding=(0, 0))

    # -- what the lyrics panel should show, and the transitions ------------------
    def wanted_lyrics(self) -> tuple[Optional[Lyrics], str]:
        """The lyrics that belong on screen right now, and why there are none.
        The song's lyrics go the moment it is over: when it ends, when a
        hand-off starts, or when TIDAL shows a different song (even before the
        loop has confirmed it)."""
        st = self.loop.state
        if st.current is None:
            return None, "waiting"
        if self.view == "logo":
            return None, "logo"
        if getattr(st, "pending", None) is not None or getattr(st, "handed_off", False):
            return None, "changing"
        pos, duration, _ = self.position()
        if duration and pos is not None and pos >= duration - 0.3:
            return None, "changing"
        lyr = self.current_lyrics()
        if lyr == "pending":
            return None, "pending"
        if isinstance(lyr, Lyrics) and lyr.lines:
            if not lyr.synced:
                # no timing from the source: guess it from the song's length, so the
                # lyrics still follow along (and say so in the title)
                key = (id(lyr), duration)
                if self._estimate_key != key:
                    self._estimate_key, self._estimate = key, lyr.estimate_timing(duration)
                lyr = self._estimate
            return lyr, "ok"
        if isinstance(lyr, Lyrics) and lyr.instrumental:
            return None, "instrumental"
        return None, "none"

    def animate(self) -> None:
        """Move the transitions one frame on. Old lyrics fade out first; the
        logo glides wider or narrower; new lyrics fade in once there is room."""
        now = self._clock()
        dt = 0.0 if self._last_frame is None else now - self._last_frame
        first = self._last_frame is None
        self._last_frame = now
        self._sync_settings(now)
        want, status = self.wanted_lyrics()
        self._status = status
        snap = first or dt <= 0                      # nothing to animate from: be there
        if want is not None and self._shown is not want and (snap or self._shown is None or self._content[0] < 0.04):
            self._shown = want                       # the old ones are gone: swap
        showing_want = want is not None and self._shown is want
        if showing_want:
            self._shown_pos = self.position()[:2]    # frozen here once the song moves on
        # the layout: room for lyrics while there are some; while a new song's are
        # being looked up, stay as we are for a few seconds instead of gliding back and forth
        if want is not None:
            self._layout_goal, self._hold_since = 1.0, None
        elif status in ("pending", "changing"):
            if self._hold_since is None:
                self._hold_since = now
            if now - self._hold_since > 4.0:
                self._layout_goal = 0.0
        else:
            self._layout_goal, self._hold_since = 0.0, None
        content_goal = 1.0 if (showing_want and self._layout[0] > 0.8) else 0.0
        menu_goal = 1.0 if self.menu_open else 0.0
        if snap:
            self._layout = [self._layout_goal, 0.0]
            self._content = [1.0 if showing_want and self._layout_goal else 0.0, 0.0]
            self._menu = [menu_goal, 0.0]
            self._cover = [1.0 if self.cover_view else 0.0, 0.0]
            self._settings = [1.0 if self.settings_open else 0.0, 0.0]
        else:
            dt = min(dt, 0.25)
            self._layout = list(spring(*self._layout, self._layout_goal, dt, 5.5))
            self._content = list(spring(*self._content, content_goal, dt, 24.0 if content_goal < 0.5 else 9.0))
            self._menu = list(spring(*self._menu, menu_goal, dt, 14.0))
            self._cover = list(spring(*self._cover, 1.0 if self.cover_view else 0.0, dt, 10.0))
            self._settings = list(spring(*self._settings, 1.0 if self.settings_open else 0.0, dt, 14.0))
        if want is None and self._content[0] < 0.01 and self._layout[0] < 0.01:
            self._shown = None

    def caption(self) -> str:
        return {"waiting": "Alter Era", "logo": "Alter Era · l for lyrics", "pending": "Alter Era · looking for lyrics…",
                "instrumental": "Alter Era · instrumental", "none": "Alter Era · no lyrics for this song"
                }.get(self._status, "Alter Era")

    def up_next_panel(self) -> Panel:
        """The pick and its backups, then what played recently."""
        th, p = self.th, self.th.p
        st = self.loop.state
        text = Text(no_wrap=True, overflow="ellipsis")
        picks = list(getattr(st.plan, "picks", None) or ([st.plan.primary] if getattr(st.plan, "primary", None) else [])) \
            if st.plan is not None else []
        if not picks:
            text.append("choosing…\n" if st.current is not None else "—\n", style(th.subtle))
        for i, pick in enumerate(picks[:3]):
            marker, color = ("▸ ", th.text) if i == 0 else ("  ", th.subtle)
            text.append(marker, style(p["mauve"], True))
            text.append(pick.track.title + "\n", style(color, i == 0))
            text.append("  " + pick.track.artist + "\n", style(th.faint if i else p["subtext1"]))
            energy = pick.candidate.extra.get("energy") if pick.candidate.extra else None
            text.append("  " + pick.source, style(th.faint))
            if energy is not None:
                text.append("  ")
                text.append_text(self.meter(energy, 6))
            text.append("\n\n" if i == 0 else "\n")
        text.append("\nRECENTLY PLAYED\n", style(th.faint, True))
        recent = self.history.recent(7) if self.history is not None else []
        cur = st.current
        for e in reversed(recent):
            if cur is not None and e.title == cur.title and e.artist == cur.artist:
                continue
            icon, color = ("✓ ", p["green"]) if e.source and e.source != "tidal" else ("· ", th.faint)
            text.append(icon, style(color))
            text.append(f"{e.title}", style(th.subtle))
            text.append(f" — {e.artist}\n", style(th.faint))
        return self._panel(text, "Up next")

    def presets_panel(self, height: int, top_row: int) -> Panel:
        """The preset menu, in sections; records where each preset is drawn so clicks find it."""
        th, p = self.th, self.th.p
        presets = self.presets()
        names = self._preset_names()
        current = getattr(self.config, "preset", None)
        self.menu_cursor = max(0, min(self.menu_cursor, len(names) - 1))
        # one display row per section label (with a gap before it) and per preset
        rows: list = []
        for label, group in preset_sections(presets):
            if rows:
                rows.append(("gap", ""))
            rows.append(("label", label))
            rows.extend(("item", n) for n in group)
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append("↑↓ / wheel move · enter / click apply · esc close   ", style(th.faint))
        text.append("● ", style(p["green"], True))
        text.append("in use\n\n", style(th.faint))
        room = max(1, height - 2 - 2)                    # panel borders, hint lines
        at = next((i for i, r in enumerate(rows) if r == ("item", names[self.menu_cursor])), 0) if names else 0
        first = min(max(0, at - room // 2), max(0, len(rows) - room))
        if first and rows[first - 1][0] == "label":
            first -= 1                                   # keep a section's label with its first preset
        hits = []
        name_w = max([len(n) for n in names] + [8]) + 2
        tag_w = 22
        for i, (kind, value) in enumerate(rows[first:first + room]):
            if kind == "gap":
                text.append("\n")
                continue
            if kind == "label":
                text.append(f"  {value.upper()}\n", style(p["overlay1"], True))
                continue
            name = value
            preset = presets.get(name) or {}
            desc = str(preset.get("description", ""))
            shuffle = preset.get("shuffle") or {}
            tags = " ".join(str(t) for t in (shuffle.get("flow"), shuffle.get("strategy")) if t)
            if not tags and preset.get("sources"):
                tags = "+".join(preset["sources"])
            tags = tags if len(tags) < tag_w - 1 else tags[:tag_w - 2] + "…"
            mark = "● " if name == current else "  "
            if name == names[self.menu_cursor]:
                sel = style(th.current_fg, True, th.current_bg)
                text.append(f" ▸{mark}{name.ljust(name_w)}{tags.ljust(tag_w)}{desc} \n", sel)
            else:
                text.append("  ")
                text.append(mark, style(p["green"], True))
                text.append(name.ljust(name_w), style(th.text, True))
                text.append(tags.ljust(tag_w), style(p["teal"]))
                text.append(desc + " \n", style(th.subtle))
            hits.append((top_row + 1 + 2 + i, 0, 10_000, f"preset:{name}"))
        self._menu_hits = hits
        return self._panel(text, "Presets", subtitle="p or esc to close")

    def settings_panel(self, height: int, top_row: int) -> Panel:
        """The settings menu, in sections; records where each choice is drawn."""
        th, p = self.th, self.th.p
        rows: list = []
        last = None
        for i, (key, value, label, desc, section) in enumerate(self.setting_items):
            if section != last:
                if rows:
                    rows.append(("gap", None))
                rows.append(("label", section))
                last = section
            rows.append(("item", i))
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append("↑↓ move · ←→ section · enter choose · esc close  ", style(th.faint))
        text.append("● ", style(p["green"], True))
        text.append("in use\n\n", style(th.faint))
        room = max(1, height - 4)
        self.settings_cursor = max(0, min(self.settings_cursor, len(self.setting_items) - 1))
        at = rows.index(("item", self.settings_cursor))
        first = min(max(0, at - room // 2), max(0, len(rows) - room))
        if first and rows[first - 1][0] == "label":
            first -= 1
        hits = []
        name_w = max(len(it[2]) for it in self.setting_items) + 2
        for r, (kind, val) in enumerate(rows[first:first + room]):
            if kind == "gap":
                text.append("\n")
                continue
            if kind == "label":
                text.append(f"  {val.upper()}\n", style(p["overlay1"], True))
                continue
            key, value, label, desc, _ = self.setting_items[val]
            pad = name_w
            if key in SLIDERS:                          # a short label, so the bar fits
                desc = self.slider_bar(key) + ("   " + desc if val == self.settings_cursor else "")
                pad = 8
            mark = "● " if self.is_current(key, value) else "  "
            if val == self.settings_cursor:
                text.append(f" ▸{mark}{label.ljust(pad)}{desc} \n", style(th.current_fg, True, th.current_bg))
            else:
                text.append("  ")
                text.append(mark, style(p["green"], True))
                text.append(label.ljust(pad), style(th.text, True))
                text.append(desc + " \n", style(th.subtle))
            x0, mw = getattr(self, "_settings_w", (0, 10_000))
            hits.append((top_row + 1 + 2 + r, x0, x0 + mw, f"set:{val}"))
        self._settings_hits = hits
        return self._panel(text, "Settings", subtitle="esc to close")

    def body_regions(self, x: int, y: int, width: int, height: int, gap: int) -> list:
        """(renderable, x, y, w, h, opacity) for the body: the logo, the lyrics
        (fading, over the logo while it glides), Up next, and the preset menu."""
        out = []
        main_w = width
        view = self.chosen("shuffle_view") or "off"
        if width >= 130:
            side_w = 40
            main_w = width - side_w - gap
            side = self.tree_panel() if view == "side" else self.up_next_panel()
            out.append((side, x + main_w + gap, y, side_w, height, 1.0))
        L = max(0.0, min(1.0, self._layout[0]))
        if main_w < 90 or self.scene is None:
            logo_w, lyr_x, lyr_w = main_w, x, main_w      # narrow: the lyrics take the whole width, over the logo
        else:
            split = int(main_w * 2 / 5)
            logo_w = int(round(main_w + (split - main_w) * L))
            lyr_x, lyr_w = x + split + gap, main_w - split - gap
        if view == "logo" or (view == "side" and width < 130):
            main = self.tree_panel()
        else:
            main = self.logo_panel(self.caption() if self._shown is None else "Alter Era")
        out.insert(0, (main, x, y, logo_w, height, 1.0))
        c = max(0.0, min(1.0, self._cover[0]))
        if c > 0.01:                                   # the cover fades in over the logo
            out.insert(1, (self.cover_panel(), x, y, logo_w, height, c))
        if self._shown is not None and L > 0.01:
            pos, duration = self._shown_pos
            alpha = max(0.0, min(1.0, self._content[0]))
            out.append((self.lyrics_panel(self._shown, pos, duration, alpha, lyr_w, height), lyr_x, y, lyr_w, height,
                        smoothstep(L / 0.55)))           # the empty glass box comes with the glide
        sm = max(0.0, min(1.0, self._settings[0]))
        if self.settings_open or sm > 0.01:
            op = sm if not self.settings_open else max(sm, 0.02)
            menu_w = width if width < 70 else max(44, min(66, width // 2))
            self._settings_w = (x, menu_w)               # for the click areas
            out.append((self.settings_panel(height, y), x, y, menu_w, height, op))
            if menu_w < width:                            # a live preview of what the cursor is on
                key = self.setting_items[self.settings_cursor][0] if self.setting_items else ""
                prev = self.tree_panel("Preview · shuffle tree") if key == "shuffle_view" else self.logo_panel("Preview")
                out.append((prev, x + menu_w + gap, y, width - menu_w - gap, height, op))
        m = max(0.0, min(1.0, self._menu[0]))
        if self.menu_open or m > 0.01:
            out.append((self.presets_panel(height, y), x, y, width, height, m if not self.menu_open else max(m, 0.02)))
        return out

    def log_line(self, msg: str, dim: bool) -> Text:
        """A log line with its leading icon coloured by kind."""
        p, th = self.th.p, self.th
        icons = {"→": p["blue"], "✓": p["green"], "⚠": p["peach"], "⏭": p["sapphire"], "▶": p["green"],
                 "⏸": p["yellow"], "♫": p["mauve"], "⏮": p["sapphire"]}
        text = Text()
        head = msg[:1]
        if head in icons:
            text.append(head, style(icons[head], True))
            msg = msg[1:]
        elif msg.startswith("flow:"):
            text.append("flow:", style(p["teal"], True))
            msg = msg[5:]
        text.append(msg, style(th.past if dim else th.subtle))
        return text

    def up_next_compact(self) -> Panel:
        """Up next for narrow windows: the pick, its backups, then what played."""
        th, p = self.th, self.th.p
        st = self.loop.state
        picks = list(getattr(st.plan, "picks", None) or ([st.plan.primary] if st.plan is not None and st.plan.primary
                                                          else [])) if st.plan is not None else []
        text = Text(no_wrap=True, overflow="ellipsis")
        if not picks:
            text.append("choosing…" if st.current is not None else "—", style(th.subtle))
        for i, pick in enumerate(picks[:3]):
            if i:
                text.append("\n")
            text.append("▸ " if i == 0 else "  ", style(p["mauve"], True))
            text.append(pick.track.title, style(th.text if i == 0 else th.subtle, i == 0))
            text.append(f" — {pick.track.artist}", style(p["subtext1"] if i == 0 else th.faint))
            energy = pick.candidate.extra.get("energy") if pick.candidate.extra else None
            if i == 0 and energy is not None:
                text.append("  ")
                text.append_text(self.meter(energy, 5))
        recent = self.history.recent(4) if self.history is not None else []
        cur = st.current
        for e in reversed(recent):
            if cur is not None and e.title == cur.title and e.artist == cur.artist:
                continue
            text.append("\n")
            text.append("✓ " if e.source and e.source != "tidal" else "· ", style(p["green"] if e.source and e.source != "tidal" else th.faint))
            text.append(f"{e.title}", style(th.faint))
        return self._panel(text, "Up next")

    def footer(self, height: int) -> Panel:
        th = self.th
        with self._lock:
            entries = list(self.logs)[-max(1, height - 2):]
        text = Text(no_wrap=True, overflow="ellipsis")
        for i, (stamp, msg, dim) in enumerate(entries):
            if i:
                text.append("\n")
            text.append(stamp + " ", style(th.faint))
            text.append_text(self.log_line(msg, dim))
        return self._panel(text, "log", title_color=th.faint)

    def toolbar(self, row: int, width: int) -> Text:
        """Clickable key chips along the bottom row."""
        th, p = self.th, self.th.p
        text = Text(" ", style(None, False, th.bg))
        x = 1
        hits = []
        chips = []
        for key, label, action in CHIPS:
            if action == "cmd:flow":
                label = f"flow: {self.config.shuffle.flow}"
            if action == "ui:presets" and self.menu_open:
                label = "close presets"
            if action == "ui:settings" and self.settings_open:
                label = "close settings"
            chips.append((key, label, action))
        # in a narrow window: short labels, then keys alone, so every key stays on the row
        short = {"play/pause": "play", "close presets": "close", "close settings": "close", "settings": "menu"}
        for spacing, shorten, bare in ((3, False, False), (2, True, False), (1, True, True)):
            need = 1 + sum(len(f" {k} ") + (0 if bare else len(" " + (short.get(l, l.split(":")[0]) if shorten else l)))
                           + spacing for k, l, _ in chips)
            if need <= width:
                break
        for key, label, action in chips:
            chip = f" {key} "
            label = short.get(label, label.split(":")[0]) if shorten else label
            seg = (" " * spacing) if bare else f" {label}" + " " * spacing
            if x + len(chip) + len(seg) > width:
                break
            text.append(chip, style(p["crust"], True, p["mauve"] if action != "cmd:quit" else p["overlay1"]))
            text.append(seg, style(th.subtle, False, th.bg))
            hits.append((row, x, x + len(chip) + len(seg) - spacing, action))
            x += len(chip) + len(seg)
        text.append(" " * max(0, width - x), style(None, False, th.bg))
        self._toolbar_hits = hits
        return text

    def energy(self) -> float:
        """How energetic the music is, for the sky: the flow's target, else the pick's."""
        plan = self.loop.state.plan
        target = getattr(plan, "flow_target", None) if plan is not None else None
        if target is not None:
            return float(target)
        pick = getattr(plan, "primary", None) if plan is not None else None
        extra = getattr(getattr(pick, "candidate", None), "extra", None) or {}
        return float(extra.get("energy", 0.5))

    def regions(self, width: int, height: int) -> list:
        """Where every panel goes: (renderable, x, y, w, h, opacity), back to front."""
        self._menu_hits, self._toolbar_hits, self._settings_hits = [], [], []
        mx = 2 if width >= 100 else (1 if width >= 60 else 0)
        my = 1 if height >= 30 else 0
        gap = 1 if height >= 30 else 0
        gap_x = 2 if width >= 100 else 1
        inner = width - 2 * mx
        out = [(self.header(inner), mx, my, inner, HEADER_H, 1.0)]
        if height < 14:
            foot_y = my + HEADER_H
            out.append((self.footer(max(3, height - foot_y - 1)), mx, foot_y, inner, max(3, height - foot_y - 1), 1.0))
        else:
            foot = 6 if height >= 34 else 5
            foot_y = height - 1 - foot
            body_y = my + HEADER_H + gap
            body_h = max(3, foot_y - gap - body_y)
            out.extend(self.body_regions(mx, body_y, inner, body_h, gap_x))
            if inner >= 126 + 4:
                out.append((self.footer(foot), mx, foot_y, inner, foot, 1.0))
            else:
                # no room for the Up next card beside the logo: it shares the log's row instead
                gap_x = 2 if width >= 100 else 1
                right = max(28, min(52, int(inner * 0.42)))
                left = inner - right - gap_x
                out.append((self.footer(foot), mx, foot_y, left, foot, 1.0))
                out.append((self.up_next_compact(), mx + left + gap_x, foot_y, right, foot, 1.0))
        out.append((self.toolbar(height - 1, width), 0, height - 1, width, 1, 1.0))
        self._hits = ((self._menu_hits if self.menu_open else []) + (self._settings_hits if self.settings_open else [])
                      + self._toolbar_hits)
        return out

    def compose(self, console: Console, options: ConsoleOptions, width: int, height: int):
        """The whole screen as Segments: the sky, then the panels over it."""
        try:
            set_color_depth(console.color_system)
            self.animate()
            th = self.th
            playing = self.loop.state.current is not None and self.loop.state.current.playing is not False
            if self.backdrop is not None:
                cells = self.backdrop.frame(width, height, self._clock(), self.energy(), playing)
            else:
                cells = [[[" ", None, False, th.bg] for _ in range(width)] for _ in range(height)]
            canvas = Canvas(cells, th.bg, th.text, glass=self.glass if self.backdrop is not None else 0.0)
            for renderable, x, y, w, h, opacity in self.regions(width, height):
                if w <= 0 or h <= 0 or opacity <= 0.01:
                    continue
                lines = console.render_lines(renderable, options.update(width=w, height=h), pad=True)
                canvas.blit(lines, x, y, w, h, opacity)
            yield from segments(canvas.cells, style)
        except Exception as e:  # never let a render error take the screen down
            yield from console.render(Text(f"display error: {e}", style(self.th.text)), options)

    def render(self, width: int = 100, height: int = 40):
        """The screen as a renderable of the given size (for previews and tests)."""
        return _Sized(self, width, height)


class _Sized:
    def __init__(self, tui: "ShuffleTUI", width: int, height: int):
        self.tui, self.width, self.height = tui, width, height

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from self.tui.compose(console, options, self.width, self.height)


class ScreenRenderable:
    """Lets Rich ask for the layout at the console's current size."""

    def __init__(self, tui: ShuffleTUI):
        self.tui = tui

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from self.tui.compose(console, options, options.max_width, options.height or console.size.height)
