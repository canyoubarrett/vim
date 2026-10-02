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
from rich.text import Text

from .lyrics import Lyrics, LyricsService
from .theme import Theme, theme as make_theme
from .visualizer import LogoScene, lerp

KEYS_LINE = "space play/pause · n next pick · b back · l lyrics · q quit"

_STYLES: dict = {}


def style(fg=None, bold: bool = False, bg=None) -> Style:
    """Cached styles: a frame uses thousands of cells."""
    key = (fg, bold, bg)
    st = _STYLES.get(key)
    if st is None:
        st = Style(color=Color.from_rgb(*fg) if fg else None, bold=bold or None,
                   bgcolor=Color.from_rgb(*bg) if bg else None)
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


def lyric_rows(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int,
               height: int) -> list[tuple[str, str]]:
    """The rows to show, centred on the line being sung: (text, kind), kind being
    "current", "past:N", "next:N" (N = lines away), "plain", "countin" or "blank"."""
    wrap = max(10, width - 8)
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
    out: list[tuple[str, str]] = []
    for r in range(top, top + height):
        if r < 0 or r >= len(rows):
            out.append(("", "blank"))
            continue
        text, i = rows[r]
        if not lyrics.synced:
            out.append((text, "plain"))
        elif i == current:
            out.append((text, "current"))
        elif i < current:
            out.append((text, f"past:{current - i}"))
        else:
            out.append((text, f"next:{i - current}"))
    # count-in before the first line: three dots filling up
    if lyrics.synced and current < 0 and lyrics.lines and lyrics.lines[0].time:
        first_t = lyrics.lines[0].time
        filled = int(3 * max(0.0, min(1.0, pos / first_t)))
        mid = height // 2
        if 0 <= mid - 1 < len(out):
            out[mid - 1] = ("● " * filled + "○ " * (3 - filled), "countin")
    return out


def lyrics_grid(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int, height: int,
                th: Theme) -> list:
    """Lyric rows centred in the panel; the line being sung is inverted."""
    grid = [[(" ", None)] * width for _ in range(height)]
    rows = lyric_rows(lyrics, position, duration, width, height)
    # a wrapped current line gets one even bar, as wide as its longest row
    block = max((len(t[:max(1, width - 2)]) for t, k in rows if k == "current"), default=0)
    block_lo = max(0, (width - block) // 2 - 2)
    block_hi = min(width, block_lo + block + 4)
    for r, (text, kind) in enumerate(rows):
        if r >= height or (not text and kind != "current"):
            continue
        text = text[:max(1, width - 2)]
        start = max(0, (width - len(text)) // 2)
        row = list(grid[r])
        if kind == "current":
            for c in range(block_lo, block_hi):
                row[c] = (" ", th.current_fg, True, th.current_bg)
            for i, ch in enumerate(text):
                row[start + i] = (ch, th.current_fg, True, th.current_bg)
        else:
            if kind.startswith("past:"):
                color = lerp(th.past, th.bg, min(0.7, (int(kind[5:]) - 1) / 8))
            elif kind.startswith("next:"):
                color = lerp(th.text, th.past, min(1.0, (int(kind[5:]) - 1) / 8))
            elif kind == "countin":
                color = th.title
            else:
                color = th.text
            for i, ch in enumerate(text):
                row[start + i] = (ch, color)
        grid[r] = row
    return grid


class ShuffleTUI:
    """State and rendering for the full-screen view."""

    def __init__(self, loop, config, lyrics: Optional[LyricsService] = None, scene: Optional[LogoScene] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 theme: Optional[Theme] = None):
        self.loop = loop
        self.config = config
        self.lyrics = lyrics
        self.th = theme or make_theme(getattr(getattr(config, "ui", None), "theme", "mocha"))
        if scene is not None:
            scene.logo, scene.glow, scene.shadow, scene.bg = self.th.logo, self.th.logo_glow, self.th.shadow, self.th.bg
        self.scene = scene
        self._clock = clock
        self._wall = wall
        self.logs: deque = deque(maxlen=400)
        self._lock = threading.Lock()
        self.view = "auto"           # auto: logo + lyrics | logo: the logo alone

    # -- inputs ------------------------------------------------------------------
    def log(self, msg: str, dim: bool = False) -> None:
        with self._lock:
            self.logs.append((time.strftime("%H:%M:%S"), str(msg), dim))

    def toggle_view(self) -> None:
        self.view = "logo" if self.view == "auto" else "auto"
        self.log("showing the logo" if self.view == "logo" else "showing the lyrics")

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

    # -- pieces ---------------------------------------------------------------------
    def _panel(self, body, title: str, title_color=None, subtitle: str = "", padding=(0, 1)) -> Panel:
        th = self.th
        return Panel(body,
                     title=Text(f" {title} ", style(title_color or th.title, True)) if title else None,
                     title_align="left",
                     subtitle=Text(f" {subtitle} ", style(th.faint)) if subtitle else None, subtitle_align="right",
                     border_style=style(th.border, False, th.bg), style=style(th.text, False, th.bg),
                     padding=padding)

    def header(self, width: int) -> Panel:
        th = self.th
        st = self.loop.state
        cur = st.current
        pos, duration, playing = self.position()
        lines = Text()
        if cur is None:
            lines.append("waiting for TIDAL to play something…", style(th.subtle))
            lines.append("\n\n")
        else:
            lines.append("⏸ " if playing is False else "▶ ", style(th.paused if playing is False else th.playing, True))
            lines.append(cur.title, style(th.text, True))
            lines.append("  —  ", style(th.faint))
            lines.append(cur.artist, style(th.text))
            if cur.album:
                lines.append(f"   {cur.album}", style(th.subtle))
            lines.append("\n")
            left, right = fmt_time(pos), fmt_time(duration)
            bar_w = max(10, width - 6 - len(left) - len(right) - 2)
            frac = (pos / duration) if (pos is not None and duration) else 0.0
            done = int(bar_w * max(0.0, min(1.0, frac)))
            lines.append(left + " ", style(th.subtle))
            lines.append("━" * done, style(th.bar))
            lines.append("●", style(th.knob, True))
            lines.append("─" * max(0, bar_w - done - 1), style(th.bar_rest))
            lines.append(" " + right, style(th.subtle))
            lines.append("\n")
        nxt = st.plan.primary if st.plan is not None else None
        lines.append("next ▸ ", style(th.faint))
        if st.handed_off and st.expected is not None:
            lines.append(st.expected.track.label(), style(th.text))
            lines.append("  · starting", style(th.subtle))
        elif nxt is not None:
            lines.append(nxt.track.label(), style(th.text))
            lines.append(f"  · {nxt.source}", style(th.subtle))
        elif st.planning is not None or (cur is not None and st.plan is None):
            lines.append("choosing…", style(th.subtle))
        else:
            lines.append("—", style(th.subtle))
        subtitle = f"{self.config.shuffle.strategy} · {st.picks_played} picks"
        return self._panel(lines, "Tidal Shuffle", subtitle=subtitle)

    def logo_panel(self, caption: str) -> Panel:
        _, _, playing = self.position()
        live = playing is not False and self.loop.state.current is not None
        if self.scene is None:
            return self._panel(Text(""), caption, padding=(0, 0))
        scene = self.scene
        return self._panel(GridView(lambda w, h: scene.frame(w, h, self._clock(), playing=live)), caption,
                           padding=(0, 0))

    def lyrics_panel(self, lyr: Lyrics) -> Panel:
        pos, duration, _ = self.position()
        title = f"Lyrics · {lyr.source}" + ("" if lyr.synced else " (not synced)")
        th = self.th
        return self._panel(GridView(lambda w, h: lyrics_grid(lyr, pos, duration, w, h, th)), title, padding=(0, 0))

    def body(self, width: int):
        """Logo and lyrics side by side; the logo alone when there are none."""
        lyr = self.current_lyrics() if self.view == "auto" else None
        if not (isinstance(lyr, Lyrics) and lyr.lines):
            if self.loop.state.current is None:
                caption = "Alter Era"
            elif self.view == "logo":
                caption = "Alter Era · l for lyrics"
            elif lyr == "pending":
                caption = "Alter Era · looking for lyrics…"
            elif isinstance(lyr, Lyrics) and lyr.instrumental:
                caption = "Alter Era · instrumental"
            else:
                caption = "Alter Era · no lyrics for this song"
            return self.logo_panel(caption)
        if width < 90 or self.scene is None:
            return self.lyrics_panel(lyr)          # narrow window: the lyrics get the room
        row = Layout()
        row.split_row(Layout(self.logo_panel("Alter Era"), ratio=2), Layout(self.lyrics_panel(lyr), ratio=3))
        return row

    def footer(self, height: int) -> Panel:
        th = self.th
        with self._lock:
            entries = list(self.logs)[-max(1, height - 2):]
        text = Text()
        for i, (stamp, msg, dim) in enumerate(entries):
            if i:
                text.append("\n")
            text.append(stamp + " ", style(th.faint))
            text.append(msg, style(th.past if dim else th.subtle))
        text.no_wrap = True
        text.overflow = "ellipsis"
        return self._panel(text, "log", title_color=th.faint, subtitle=KEYS_LINE)

    def render(self, width: int = 100, height: int = 40):
        try:
            layout = Layout()
            if height < 14:
                layout.split_column(Layout(self.header(width), size=5), Layout(self.footer(max(3, height - 5))))
                return layout
            foot = 8 if height >= 30 else 6
            layout.split_column(Layout(self.header(width), size=5), Layout(self.body(width), ratio=1),
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
