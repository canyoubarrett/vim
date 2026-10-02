"""The full-screen view for `tidal-shuffle run`.

    ╭ Tidal Shuffle ─────────────────────────────── weighted · 12 picks ╮
    │ ▶ Midnight City — M83                    Hurry Up, We're Dreaming │
    │ 1:23 ━━━━━━━━━━━━━━━━●──────────────────────────────────── 4:03 │
    │ next ▸ Strangers — Kosheen  · spotify-app                        │
    ╰───────────────────────────────────────────────────────────────────╯
    ╭ Lyrics · TIDAL ───────────────────────────────────────────────────╮
    │                Waiting in a car                                  │
    │          ▸  Waiting for a ride in the dark                       │
    │                The night city grows                              │
    ╰───────────────────────────────────────────────────────────────────╯
    ╭ log ──────────────────────────────────────────────────────────────╮
    │ 21:04:12 → next up: Strangers — Kosheen [spotify-app, 30 …]       │
    ╰──── space play/pause · n next pick · b back · l lyrics · q quit ──╯

Lyrics scroll with the song, the line being sung highlighted. With no lyrics
(or with `l`), the Alter Era scene plays instead. Rendering runs on Rich's
refresh thread and only reads the loop's state, so a slow render can never
delay a hand-off.
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
from rich.text import Text

from .lyrics import Lyrics, LyricsService
from .visualizer import LOGO_HI, LOGOC, RAINC, AlterEraScene, lerp

KEYS_LINE = "space play/pause · n next pick · b back · l lyrics/visualizer · q quit"

ACCENT = LOGOC
BORDER = (74, 96, 88)
DIM = (110, 128, 120)
TEXT = (204, 212, 200)
PAST = (96, 114, 106)

_STYLES: dict = {}


def style(rgb, bold: bool = False) -> Style:  # cached: a frame uses thousands of cells
    key = (rgb, bold)
    st = _STYLES.get(key)
    if st is None:
        st = Style(color=Color.from_rgb(*rgb), bold=bold) if rgb else Style()
        _STYLES[key] = st
    return st


def fmt_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-:--"
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class GridView:
    """A renderable that fills its region with cells from ``fn(width, height)``."""

    def __init__(self, fn: Callable[[int, int], list]):
        self.fn = fn

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = options.max_width
        height = options.height or options.max_height or 10
        grid = self.fn(width, height)
        for row in grid[:height]:
            run_text, run_key = [], None
            for cell in row[:width]:
                key = (cell[1], len(cell) > 2 and cell[2])   # (color, bold)
                if key != run_key and run_text:
                    yield Segment("".join(run_text), style(*run_key))
                    run_text = []
                run_key = key
                run_text.append(cell[0])
            if run_text:
                yield Segment("".join(run_text), style(*run_key))
            yield Segment.line()


def lyric_rows(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int,
               height: int) -> list[tuple[str, tuple, bool]]:
    """The rows to show: (text, color, bold), centred on the line being sung."""
    wrap = max(10, width - 6)
    rows: list[tuple[str, int]] = []          # (text, lyric line index)
    starts: list[int] = []
    for i, line in enumerate(lyrics.lines):
        starts.append(len(rows))
        text = line.text.strip() or ("♪" if lyrics.synced else "")
        for part in (textwrap.wrap(text, wrap) or [""]):
            rows.append((part, i))
    if not rows:
        return []
    pos = position or 0.0
    if lyrics.synced:
        current = lyrics.index_at(pos)
        first = starts[current] if current >= 0 else 0
        last = (starts[current + 1] if current + 1 < len(starts) else len(rows)) if current >= 0 else 1
        # centre the whole (possibly wrapped) line, but never push its start off the top
        top = min(first, first + (last - first) // 2 - height // 2)
    else:
        current = -1
        frac = (pos / duration) if duration else 0.0
        top = int(max(0.0, min(1.0, frac)) * (len(rows) - 1)) - height // 2
    out: list[tuple[str, tuple, bool]] = []
    for r in range(top, top + height):
        if r < 0 or r >= len(rows):
            out.append(("", TEXT, False))
            continue
        text, i = rows[r]
        if not lyrics.synced:
            out.append((text, TEXT, False))
        elif i == current:
            out.append((text, LOGO_HI, True))
        elif i < current:
            fade = min(1.0, (current - i) / 6)
            out.append((text, lerp(PAST, (60, 72, 68), fade), False))
        else:
            fade = min(1.0, (i - current - 1) / 8)
            out.append((text, lerp(TEXT, PAST, fade), False))
    # count-in before the first line: three dots filling up
    if lyrics.synced and current < 0 and lyrics.lines and lyrics.lines[0].time:
        first = lyrics.lines[0].time
        filled = int(3 * max(0.0, min(1.0, pos / first)))
        mid = height // 2
        if 0 <= mid - 1 < len(out):
            out[mid - 1] = ("● " * filled + "○ " * (3 - filled), ACCENT, False)
    return out


def lyrics_grid(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int, height: int,
                backdrop: Optional[list] = None) -> list:
    """Lyric rows centred over an optional backdrop grid (a faint rain)."""
    grid = backdrop if backdrop is not None else [[(" ", None)] * width for _ in range(height)]
    for r, (text, color, bold) in enumerate(lyric_rows(lyrics, position, duration, width, height)):
        if not text or r >= len(grid):
            continue
        text = text[:width]
        start = max(0, (width - len(text)) // 2)
        lo, hi = max(0, start - 2), min(width, start + len(text) + 2)
        row = list(grid[r])
        for c in range(lo, hi):                      # a clear band so the words read cleanly
            row[c] = (" ", None)
        for i, ch in enumerate(text):
            if start + i < width:
                row[start + i] = (ch, color, bold)
        grid[r] = row
    return grid


class ShuffleTUI:
    """State and rendering for the full-screen view."""

    def __init__(self, loop, config, lyrics: Optional[LyricsService] = None, scene: Optional[AlterEraScene] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        self.loop = loop
        self.config = config
        self.lyrics = lyrics
        self.scene = scene
        self._clock = clock
        self._wall = wall
        self.logs: deque = deque(maxlen=400)
        self._lock = threading.Lock()
        self.view = "auto"           # auto: lyrics when there are some | visualizer
        self.method = ""

    # -- inputs ------------------------------------------------------------------
    def log(self, msg: str, dim: bool = False) -> None:
        with self._lock:
            self.logs.append((time.strftime("%H:%M:%S"), str(msg), dim))

    def toggle_view(self) -> None:
        self.view = "visualizer" if self.view == "auto" else "auto"
        self.log("showing the visualizer" if self.view == "visualizer" else "showing lyrics when there are some")

    # -- playback state ------------------------------------------------------------
    def position(self) -> tuple[Optional[float], Optional[float], Optional[bool]]:
        st = self.loop.state
        cur = st.current
        if cur is None:
            return None, None, None
        duration = cur.duration or (st.plan.seed.duration if st.plan is not None else None)
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

    # -- rendering ---------------------------------------------------------------------
    def header(self, width: int) -> Panel:
        st = self.loop.state
        cur = st.current
        pos, duration, playing = self.position()
        lines = Text()
        if cur is None:
            lines.append("waiting for TIDAL to play something…", style(DIM))
            lines.append("\n\n")
        else:
            icon = "⏸ " if playing is False else "▶ "
            lines.append(icon, style(ACCENT, True))
            lines.append(cur.title, style(TEXT, True))
            lines.append("  —  ", style(DIM))
            lines.append(cur.artist, style(TEXT))
            if cur.album:
                lines.append(f"   {cur.album}", style(DIM))
            lines.append("\n")
            left, right = fmt_time(pos), fmt_time(duration)
            bar_w = max(10, width - 6 - len(left) - len(right) - 2)
            frac = (pos / duration) if (pos is not None and duration) else 0.0
            done = int(bar_w * max(0.0, min(1.0, frac)))
            lines.append(left + " ", style(DIM))
            lines.append("━" * done, style(ACCENT))
            lines.append("●", style(LOGO_HI, True))
            lines.append("─" * max(0, bar_w - done - 1), style(BORDER))
            lines.append(" " + right, style(DIM))
            lines.append("\n")
        nxt = st.plan.primary if st.plan is not None else None
        lines.append("next ▸ ", style(DIM))
        if st.handed_off and st.expected is not None:
            lines.append(f"{st.expected.track.label()}", style(TEXT))
            lines.append("  · starting", style(DIM))
        elif nxt is not None:
            lines.append(nxt.track.label(), style(TEXT))
            lines.append(f"  · {nxt.source}", style(DIM))
        elif st.planning is not None or (cur is not None and st.plan is None):
            lines.append("choosing…", style(DIM))
        else:
            lines.append("—", style(DIM))
        sh = self.config.shuffle
        subtitle = f"{sh.strategy} · {st.picks_played} picks"
        return Panel(lines, title=Text(" Tidal Shuffle ", style(ACCENT, True)), title_align="left",
                     subtitle=Text(f" {subtitle} ", style(DIM)), subtitle_align="right",
                     border_style=style(BORDER), padding=(0, 1))

    def body(self) -> Panel:
        pos, duration, playing = self.position()
        lyr = self.current_lyrics() if self.view == "auto" else None
        if isinstance(lyr, Lyrics) and lyr.lines:
            title = f" Lyrics · {lyr.source}" + ("" if lyr.synced else " (not synced)") + " "
            scene = self.scene
            live = playing is not False

            def draw(w, h):
                backdrop = scene.frame(w, h, self._clock(), playing=live, logo=False, dim=0.32) if scene else None
                return lyrics_grid(lyr, pos, duration, w, h, backdrop)
            return Panel(GridView(draw), title=Text(title, style(ACCENT)), title_align="left",
                         border_style=style(BORDER), padding=(0, 0))
        if self.loop.state.current is None:
            caption = " Alter Era "
        elif lyr == "pending":
            caption = " Alter Era · looking for lyrics… "
        elif self.view == "visualizer":
            caption = " Alter Era · l for lyrics "
        elif isinstance(lyr, Lyrics) and lyr.instrumental:
            caption = " Alter Era · instrumental "
        else:
            caption = " Alter Era · no lyrics for this song "
        if self.scene is None:
            return Panel(Text(""), title=Text(caption, style(DIM)), title_align="left", border_style=style(BORDER))
        scene = self.scene
        live = playing is not False and self.loop.state.current is not None
        return Panel(GridView(lambda w, h: scene.frame(w, h, self._clock(), playing=live)),
                     title=Text(caption, style(DIM)), title_align="left", border_style=style(BORDER),
                     padding=(0, 0))

    def footer(self, height: int) -> Panel:
        with self._lock:
            entries = list(self.logs)[-max(1, height - 2):]
        text = Text()
        for i, (stamp, msg, dim) in enumerate(entries):
            if i:
                text.append("\n")
            text.append(stamp + " ", style(PAST))
            text.append(msg, style(DIM if dim else TEXT))
        text.no_wrap = True
        text.overflow = "ellipsis"
        return Panel(text, title=Text(" log ", style(DIM)), title_align="left",
                     subtitle=Text(f" {KEYS_LINE} ", style(DIM)), subtitle_align="right",
                     border_style=style(BORDER), padding=(0, 1))

    def render(self, width: int = 100, height: int = 40):
        try:
            layout = Layout()
            if height < 14:
                layout.split_column(Layout(self.header(width), size=5), Layout(self.footer(max(3, height - 5))))
                return layout
            foot = 8 if height >= 30 else 6
            layout.split_column(Layout(self.header(width), size=5), Layout(self.body(), ratio=1),
                                Layout(self.footer(foot), size=foot))
            return layout
        except Exception as e:  # never let a render error take the screen down
            return Text(f"display error: {e}")


class ScreenRenderable:
    """Lets Rich ask for the layout at the console's current size."""

    def __init__(self, tui: ShuffleTUI):
        self.tui = tui

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.tui.render(options.max_width, options.height or console.size.height)
