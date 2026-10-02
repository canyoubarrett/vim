"""The full-screen view: lyric layout, rendering at any size, the scene."""

import types

from rich.console import Console

from tidal_shuffle.config import load_config
from tidal_shuffle.loop import LoopState
from tidal_shuffle.lyrics import LyricLine, Lyrics, parse_lrc
from tidal_shuffle.models import Candidate, NowPlaying, Pick, TidalTrack, TIDAL_BUNDLE_ID
from tidal_shuffle.tui import ScreenRenderable, ShuffleTUI, fmt_time, lyric_rows, lyrics_grid
from tidal_shuffle.visualizer import AlterEraScene, art_to_dots, load_art

LRC = "[00:10.00]one\n[00:20.00]two\n[00:30.00]three\n[00:40.00]four\n[00:50.00]five"


def test_lyric_rows_centre_the_line_being_sung():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True, source="TIDAL")
    rows = lyric_rows(lyr, 31.0, 200, 40, 5)
    assert [r[0] for r in rows] == ["one", "two", "three", "four", "five"]
    assert rows[2][2] is True and all(not r[2] for i, r in enumerate(rows) if i != 2)   # "three" is bold
    rows = lyric_rows(lyr, 51.0, 200, 40, 5)
    assert [r[0] for r in rows] == ["three", "four", "five", "", ""]


def test_count_in_before_the_first_line():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True)
    rows = lyric_rows(lyr, 5.0, 200, 40, 7)
    assert "●" in rows[2][0] and "○" in rows[2][0]
    assert rows[3][0] == "one"


def test_unsynced_lyrics_follow_the_song_progress():
    lyr = Lyrics(lines=[LyricLine(None, f"line {i}") for i in range(100)], synced=False)
    top = lyric_rows(lyr, 0.0, 200.0, 40, 5)
    end = lyric_rows(lyr, 200.0, 200.0, 40, 5)
    assert top[2][0] == "line 0" and end[2][0] == "line 99"


def test_long_lines_wrap_and_grid_keeps_its_size():
    lyr = Lyrics(lines=[LyricLine(1.0, "word " * 30)], synced=True)
    grid = lyrics_grid(lyr, 2.0, 100, 30, 8)
    assert len(grid) == 8 and all(len(r) == 30 for r in grid)
    assert sum(1 for r in grid if "".join(c[0] for c in r).strip()) >= 5


def test_fmt_time():
    assert fmt_time(None) == "-:--" and fmt_time(65.7) == "1:05" and fmt_time(-3) == "0:00"


def test_logo_art_and_dots():
    big, small = load_art()
    assert len(big) > 30 and len(small) > 15
    dots = art_to_dots(small)
    xs = [x for x, _ in dots]
    assert len(dots) > 100 and abs(min(xs) + max(xs)) < 1e-6   # centred


def test_scene_frames_fit_any_size_and_rest_when_paused():
    scene = AlterEraScene(seed=2)
    for w, h in ((20, 6), (80, 24), (160, 50)):
        g = scene.frame(w, h, 1.0)
        assert len(g) == h and all(len(r) == w for r in g)
    scene.frame(80, 24, 2.0, playing=False)
    heads = [d.head for d in scene._drops]
    b = scene.frame(80, 24, 3.0, playing=False)
    assert [d.head for d in scene._drops] == heads   # paused: the rain stands still
    scene.frame(80, 24, 3.5, playing=True)
    assert [d.head for d in scene._drops] != heads
    logo = lambda g: sum(1 for row in g for cell in row if "⠀" < cell[0] <= "⣿")
    assert logo(b) > 50


def test_logo_floats_smoothly():
    scene = AlterEraScene(seed=1)
    poses = [scene.logo_pose(t / 10) for t in range(100)]
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
    return ShuffleTUI(loop, cfg, lyrics=svc, scene=AlterEraScene(seed=4), clock=lambda: 1000.0, wall=lambda: 5e4)


def render(tui, w, h):
    c = Console(width=w, height=h, record=True, color_system="truecolor", force_terminal=True, file=open("/dev/null", "w"))
    c.print(ScreenRenderable(tui))
    return c.export_text()


def test_screen_with_lyrics_visualizer_and_tiny_terminal():
    lyr = Lyrics(lines=parse_lrc("[01:20.00]Waiting in a car\n[01:30.00]Waiting for a ride"), synced=True, source="TIDAL")
    tui = make_tui(lyr)
    tui.log("→ next up: Strangers — Kosheen")
    out = render(tui, 100, 40)
    assert "Midnight City" in out and "1:23" in out and "Strangers — Kosheen" in out
    assert "Lyrics · TIDAL" in out and "Waiting in a car" in out and "next up" in out
    tui.toggle_view()
    out = render(tui, 100, 40)
    assert "Alter Era" in out and "Waiting in a car" not in out
    assert "display error" not in render(make_tui(None), 100, 40)
    assert "Alter Era · no lyrics" in render(make_tui(None), 100, 40)
    assert "looking for lyrics" in render(make_tui("pending"), 100, 40)
    small = render(make_tui(lyr), 50, 12)
    assert "Midnight City" in small and "display error" not in small
    idle = render(make_tui(None, current=False), 80, 30)
    assert "waiting for TIDAL" in idle
