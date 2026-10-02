"""The full-screen view: lyric layout, rendering at any size, the floating logo, the theme."""

import types

from rich.console import Console

from tidal_shuffle.config import load_config
from tidal_shuffle.loop import LoopState
from tidal_shuffle.lyrics import LyricLine, Lyrics, parse_lrc
from tidal_shuffle.models import Candidate, NowPlaying, Pick, TidalTrack, TIDAL_BUNDLE_ID
from tidal_shuffle.theme import FLAVORS, hex_rgb, theme
from tidal_shuffle.tui import ScreenRenderable, ShuffleTUI, fmt_time, lyric_rows, lyrics_grid
from tidal_shuffle.visualizer import LogoScene, art_to_dots, load_art

LRC = "[00:10.00]one\n[00:20.00]two\n[00:30.00]three\n[00:40.00]four\n[00:50.00]five"
MOCHA = theme("mocha")


def test_lyric_rows_centre_the_line_being_sung():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True, source="TIDAL")
    rows = lyric_rows(lyr, 31.0, 200, 40, 5)
    assert [r[0] for r in rows] == ["one", "two", "three", "four", "five"]
    assert [r[1] for r in rows] == ["past:2", "past:1", "current", "next:1", "next:2"]
    rows = lyric_rows(lyr, 51.0, 200, 40, 5)
    assert [r[0] for r in rows] == ["three", "four", "five", "", ""]


def test_current_line_is_inverted():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True)
    grid = lyrics_grid(lyr, 31.0, 200, 30, 5, MOCHA)
    current = grid[2]
    text = "".join(c[0] for c in current)
    assert "three" in text
    lit = [c for c in current if len(c) > 3 and c[3] == MOCHA.current_bg]
    assert len(lit) == len("three") + 4                   # the word plus two cells each side
    assert all(c[1] == MOCHA.current_fg and c[2] for c in lit)   # dark, bold text on the bar
    assert all(len(c) < 4 or c[3] is None for c in grid[1])      # other lines are not


def test_count_in_before_the_first_line():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True)
    rows = lyric_rows(lyr, 5.0, 200, 40, 7)
    assert "●" in rows[2][0] and "○" in rows[2][0]
    assert rows[3][0] == "one"


def test_unsynced_lyrics_follow_the_song_progress():
    lyr = Lyrics(lines=[LyricLine(None, f"line {i}") for i in range(100)], synced=False)
    assert lyric_rows(lyr, 0.0, 200.0, 40, 5)[2][0] == "line 0"
    assert lyric_rows(lyr, 200.0, 200.0, 40, 5)[2][0] == "line 99"


def test_long_lines_wrap_and_grid_keeps_its_size():
    lyr = Lyrics(lines=[LyricLine(1.0, "word " * 30)], synced=True)
    grid = lyrics_grid(lyr, 2.0, 100, 30, 8, MOCHA)
    assert len(grid) == 8 and all(len(r) == 30 for r in grid)
    assert sum(1 for r in grid if "".join(c[0] for c in r).strip()) >= 5


def test_fmt_time():
    assert fmt_time(None) == "-:--" and fmt_time(65.7) == "1:05" and fmt_time(-3) == "0:00"


def test_catppuccin_flavors():
    assert set(FLAVORS) == {"latte", "frappe", "macchiato", "mocha"}
    assert MOCHA.bg == hex_rgb("#1e1e2e") and MOCHA.current_bg == hex_rgb("#cba6f7")
    assert theme("latte").bg == hex_rgb("#eff1f5") and theme("nonsense").name == "mocha"
    cfg = load_config(overrides={"ui": {"theme": "Frappé"}}, env={})
    assert cfg.ui.theme == "frappe"


def test_logo_art_and_dots():
    big, small = load_art()
    assert len(big) > 30 and len(small) > 15
    dots = art_to_dots(small)
    xs = [x for x, _ in dots]
    assert len(dots) > 100 and abs(min(xs) + max(xs)) < 1e-6   # centred


def test_logo_scene_fits_any_size_has_no_rain_and_drifts_slower_when_paused():
    scene = LogoScene()
    for w, h in ((20, 6), (50, 24), (160, 50)):
        g = scene.frame(w, h, 1.0)
        assert len(g) == h and all(len(r) == w for r in g)
    g = scene.frame(60, 26, 5.0)
    chars = {c[0] for row in g for c in row}
    assert not chars & set("ｱｲｳ0123456789")                    # no rain
    assert sum(1 for row in g for c in row if "⠀" < c[0] <= "⣿") > 50   # the logo
    assert any(c[0] in "▁▂" for row in g for c in row)          # its shadow
    t0 = scene._float_t
    scene.frame(60, 26, 6.0, playing=False)
    assert 0 < scene._float_t - t0 < 0.5


def test_logo_floats_smoothly():
    poses = [LogoScene.logo_pose(t / 10) for t in range(100)]
    steps = [abs(poses[i + 1][1] - poses[i][1]) for i in range(99)]
    assert max(steps) < 1.0                       # under a quarter row per frame at 10 fps
    assert max(p[1] for p in poses) - min(p[1] for p in poses) > 4   # but it does bob


def make_tui(lyrics=None, current=True):
    cfg = load_config(env={})
    st = LoopState()
    if current:
        st.current = NowPlaying("Midnight City", "M83", album="Hurry Up", duration=244.0, playing=True,
                                bundle_id=TIDAL_BUNDLE_ID, tidal_id="1")
        st.started_at = 917.0
        st.plan = types.SimpleNamespace(primary=Pick(candidate=Candidate("Strangers", "Kosheen", source="spotify-app"),
                                                     track=TidalTrack(id="2", title="Strangers", artist="Kosheen")),
                                        seed=None)
    loop = types.SimpleNamespace(state=st)
    svc = types.SimpleNamespace(get=lambda *a: lyrics)
    return ShuffleTUI(loop, cfg, lyrics=svc, scene=LogoScene(), clock=lambda: 1000.0, wall=lambda: 5e4)


def render(tui, w, h):
    c = Console(width=w, height=h, record=True, color_system="truecolor", force_terminal=True, file=open("/dev/null", "w"))
    c.print(ScreenRenderable(tui))
    return c.export_text(clear=False), c.export_svg()


def test_screen_layouts():
    lyr = Lyrics(lines=parse_lrc("[01:20.00]Waiting in a car\n[01:30.00]Waiting for a ride"), synced=True, source="TIDAL")
    tui = make_tui(lyr)
    tui.log("→ next up: Strangers — Kosheen")
    out, svg = render(tui, 120, 40)
    assert "Midnight City" in out and "1:23" in out and "Strangers — Kosheen" in out and "next up" in out
    assert "Alter Era" in out and "Lyrics · TIDAL" in out and "Waiting in a car" in out   # side by side
    assert "#1e1e2e" in svg.lower() and "#cba6f7" in svg.lower()                          # Catppuccin Mocha
    tui.toggle_view()
    out, _ = render(tui, 120, 40)
    assert "Alter Era · l for lyrics" in out and "Waiting in a car" not in out
    out, _ = render(make_tui(lyr), 80, 40)                     # narrow: lyrics only
    assert "Lyrics · TIDAL" in out and "Alter Era" not in out
    assert "Alter Era · no lyrics" in render(make_tui(None), 120, 40)[0]
    assert "looking for lyrics" in render(make_tui("pending"), 120, 40)[0]
    small, _ = render(make_tui(lyr), 50, 12)
    assert "Midnight City" in small and "display error" not in small
    assert "waiting for TIDAL" in render(make_tui(None, current=False), 80, 30)[0]
