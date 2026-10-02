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

from .lyrics import Lyrics, LyricsService
from .theme import Theme, theme as make_theme
from .visualizer import LogoScene, lerp

KEYS_LINE = "space play/pause · n next pick · f flow · p presets · l lyrics · q quit"

# toolbar chips: (key, label, action); actions "cmd:<loop command>" or "ui:<screen action>"
CHIPS = [("space", "play/pause", "cmd:playpause"), ("n", "next", "cmd:next"), ("f", "flow", "cmd:flow"),
         ("p", "presets", "ui:presets"), ("l", "lyrics", "ui:view"), ("q", "quit", "cmd:quit")]
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


def _line_color(kind: str, th: Theme):
    if kind.startswith("past:"):
        return lerp(th.past, th.bg, min(0.7, (int(kind[5:]) - 1) / 8))
    if kind.startswith("next:"):
        return lerp(th.text, th.past, min(1.0, (int(kind[5:]) - 1) / 8))
    if kind == "countin":
        return th.title
    return th.text


def two_column_grid(lyrics: Lyrics, position: Optional[float], width: int, height: int, th: Theme) -> Optional[list]:
    """All the lyrics at once, in two columns (or one, if that fits), split at a
    verse break; the current line inverted. None when they do not fit."""
    col_w = (width - 4) // 2

    def wrapped(wrap_at: int) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for i, line in enumerate(lyrics.lines):
            for part in (textwrap.wrap(line.text.strip(), max(8, wrap_at)) or [""]):
                out.append((part, i))
        while out and not out[0][0]:
            out.pop(0)
        while out and not out[-1][0]:
            out.pop()
        return out

    rows = wrapped(width - 8)                 # one column, if everything fits
    if not rows:
        return None
    current = lyrics.index_at(position or 0.0) if lyrics.synced else -1
    grid = [[(" ", None)] * width for _ in range(height)]

    def paint(column: list, x0: int, w: int, top: int) -> None:
        block = max((len(t) for t, i in column if i == current), default=0)
        for r, (text, i) in enumerate(column):
            y = top + r
            if y >= height:
                return
            start = x0 + max(0, (w - len(text)) // 2)
            row = grid[y]
            if i == current and current >= 0:
                lo = x0 + max(0, (w - block) // 2 - 2)
                for c in range(lo, min(x0 + w, lo + block + 4)):
                    row[c] = (" ", th.current_fg, True, th.current_bg)
                for k, ch in enumerate(text):
                    row[start + k] = (ch, th.current_fg, True, th.current_bg)
            else:
                kind = "plain" if current < 0 else (f"past:{current - i}" if i < current else f"next:{i - current}")
                color = _line_color(kind, th)
                for k, ch in enumerate(text):
                    row[start + k] = (ch, color)

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


def lyrics_grid(lyrics: Lyrics, position: Optional[float], duration: Optional[float], width: int, height: int,
                th: Theme) -> list:
    """Lyric rows centred in the panel; the line being sung is inverted.
    Lyrics without real timing are shown whole, in two columns, when they fit."""
    if lyrics.estimated or not lyrics.synced:
        whole = two_column_grid(lyrics, position, width, height, th)
        if whole is not None:
            return whole
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
            color = _line_color(kind, th)
            for i, ch in enumerate(text):
                row[start + i] = (ch, color)
        grid[r] = row
    return grid


class ShuffleTUI:
    """State and rendering for the full-screen view; also routes keys and clicks."""

    def __init__(self, loop, config, lyrics: Optional[LyricsService] = None, scene: Optional[LogoScene] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 theme: Optional[Theme] = None, artwork=None, history=None,
                 post: Optional[Callable[[str], None]] = None,
                 presets: Optional[Callable[[], dict]] = None):
        self.loop = loop
        self.config = config
        self.lyrics = lyrics
        self.th = theme or make_theme(getattr(getattr(config, "ui", None), "theme", "mocha"))
        if scene is not None:
            scene.logo, scene.glow, scene.shadow, scene.bg = self.th.logo, self.th.logo_glow, self.th.shadow, self.th.bg
        self.scene = scene
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
            self.menu_open = False if self.menu_open else (self.open_menu() or True)
        elif kind == "ui" and arg == "view":
            self.toggle_view()
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
        """The cover of the song playing (or a placeholder), ``rows`` tall and square."""
        from .artwork import placeholder

        w = rows * 2
        p = self.th.p
        cur = self.loop.state.current
        img = None
        if cur is not None and self.artwork is not None:
            img = self.artwork.get(f"{cur.artist}|{cur.title}", cur.tidal_id, cur.title, cur.artist)
        if img is None or img == "pending":
            grid = placeholder(w, rows, p["mauve"], p["blue"], p["crust"])
        else:
            grid = self.artwork.cells(f"{cur.artist}|{cur.title}", img, w, rows)
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
        title = self.gradient_text(" Tidal Shuffle ", [p["mauve"], p["pink"], p["peach"]])
        subtitle = f"{self.config.preset or 'no preset'} · {self.config.shuffle.strategy} · {st.picks_played} picks"
        return self._panel(grid, title, subtitle=subtitle)

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
        if not lyr.synced:
            # no timing from the source: guess it from the song's length, so the
            # lyrics still follow along (and show it in the title)
            key = (id(lyr), duration)
            if self._estimate_key != key:
                self._estimate_key, self._estimate = key, lyr.estimate_timing(duration)
            lyr = self._estimate
        title = f"Lyrics · {lyr.source}" + (" · timing estimated" if lyr.estimated else ("" if lyr.synced else " (not synced)"))
        th = self.th
        return self._panel(GridView(lambda w, h: lyrics_grid(lyr, pos, duration, w, h, th)), title, padding=(0, 0))

    def up_next_panel(self) -> Panel:
        """The pick and its backups, then what played recently."""
        th, p = self.th, self.th.p
        st = self.loop.state
        text = Text(no_wrap=True, overflow="ellipsis")
        picks = list(st.plan.picks) if st.plan is not None else []
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

    def body(self, width: int, height: int = 0, top_row: int = HEADER_H):
        """Logo and lyrics side by side (and Up next when there is room); the logo
        alone when there are no lyrics; the preset menu when it is open."""
        if self.menu_open:
            return self.presets_panel(height, top_row)
        lyr = self.current_lyrics() if self.view == "auto" else None
        have = isinstance(lyr, Lyrics) and bool(lyr.lines)
        side = width >= 130
        if not have:
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
            main = self.logo_panel(caption)
            if not side:
                return main
            row = Layout()
            row.split_row(Layout(main, ratio=1), Layout(self.up_next_panel(), size=40))
            return row
        if width < 90 or self.scene is None:
            return self.lyrics_panel(lyr)          # narrow window: the lyrics get the room
        row = Layout()
        parts = [Layout(self.logo_panel("Alter Era"), ratio=2), Layout(self.lyrics_panel(lyr), ratio=3)]
        if side:
            parts.append(Layout(self.up_next_panel(), size=40))
        row.split_row(*parts)
        return row

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
        for key, label, action in CHIPS:
            if action == "cmd:flow":
                label = f"flow: {self.config.shuffle.flow}"
            if action == "ui:presets" and self.menu_open:
                label = "close presets"
            chip = f" {key} "
            seg = f" {label}   "
            if x + len(chip) + len(seg) > width:
                break
            text.append(chip, style(p["crust"], True, p["mauve"] if action != "cmd:quit" else p["overlay1"]))
            text.append(seg, style(th.subtle, False, th.bg))
            hits.append((row, x, x + len(chip) + len(seg) - 2, action))
            x += len(chip) + len(seg)
        text.append(" " * max(0, width - x), style(None, False, th.bg))
        self._toolbar_hits = hits
        return text

    def render(self, width: int = 100, height: int = 40):
        try:
            layout = Layout()
            self._menu_hits, self._toolbar_hits = [], []
            if height < 14:
                layout.split_column(Layout(self.header(width), size=HEADER_H),
                                    Layout(self.footer(max(3, height - HEADER_H - 1))),
                                    Layout(self.toolbar(height - 1, width), size=1))
            else:
                foot = 8 if height >= 34 else 6
                body_h = height - HEADER_H - foot - 1
                layout.split_column(Layout(self.header(width), size=HEADER_H),
                                    Layout(self.body(width, body_h, HEADER_H), size=body_h),
                                    Layout(self.footer(foot), size=foot),
                                    Layout(self.toolbar(height - 1, width), size=1))
            self._hits = self._menu_hits + self._toolbar_hits
            return layout
        except Exception as e:  # never let a render error take the screen down
            return Text(f"display error: {e}")


class ScreenRenderable:
    """Lets Rich ask for the layout at the console's current size."""

    def __init__(self, tui: ShuffleTUI):
        self.tui = tui

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.tui.render(options.max_width, options.height or console.size.height)
