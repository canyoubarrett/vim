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


def test_vector_logo_from_the_svg():
    from tidal_shuffle.visualizer import ASSET_SVG, parse_svg_paths
    lines = parse_svg_paths(ASSET_SVG.read_text())
    assert len(lines) == 21
    # the circle (two half arcs) closes on itself and is round
    circle = lines[-1]
    xs, ys = [p[0] for p in circle], [p[1] for p in circle]
    assert abs((max(xs) - min(xs)) - 30.37) < 0.5 and abs((max(ys) - min(ys)) - 30.37) < 0.5
    scene = LogoScene()
    assert scene.polylines
    for w, h in ((30, 14), (50, 26), (120, 50)):
        g = scene.frame(w, h, 3.0)
        dots = sum(1 for row in g for c in row if "⠀" < c[0] <= "⣿")
        assert len(g) == h and all(len(r) == w for r in g) and dots > 20
    # bigger panel, bigger logo
    small = sum(1 for row in LogoScene().frame(40, 20, 3.0) for c in row if "⠀" < c[0] <= "⣿")
    big = sum(1 for row in LogoScene().frame(120, 50, 3.0) for c in row if "⠀" < c[0] <= "⣿")
    assert big > small * 2


def test_braille_text_art_still_works(tmp_path):
    from tidal_shuffle.visualizer import ASSET
    scene = LogoScene(art_path=ASSET)
    assert not scene.polylines and scene.arts
    g = scene.frame(60, 30, 3.0)
    assert sum(1 for row in g for c in row if "⠀" < c[0] <= "⣿") > 50


def test_plain_lyrics_get_estimated_timing():
    plain = Lyrics(lines=[LyricLine(None, t) for t in ["one", "two", "", "three", "four"]], synced=False, source="LRCLIB")
    est = plain.estimate_timing(200.0)
    assert est.synced and est.estimated
    times = [l.time for l in est.lines]
    assert times == sorted(times) and 5 <= times[0] <= 20 and times[-1] < 200 - 6
    assert plain.estimate_timing(None) is plain
    assert est.index_at(0.0) == -1 and est.index_at(199.0) == 4


def test_unsynced_lyrics_use_two_columns_when_they_fit():
    lines = []
    for verse in range(4):
        lines += [LyricLine(None, f"verse {verse} line {i}") for i in range(6)] + [LyricLine(None, "")]
    est = Lyrics(lines=lines, synced=False).estimate_timing(240.0)
    grid = lyrics_grid(est, 120.0, 240.0, 80, 20, MOCHA)
    text = ["".join(c[0] for c in row) for row in grid]
    assert any("verse 0 line 0" in t for t in text) and any("verse 3 line 5" in t for t in text)   # everything shown
    both = [t for t in text if "verse 0" in t and "verse 2" in t] or [t for t in text if "verse 1" in t and "verse 3" in t]
    assert both                                                       # side by side
    lit = [c for row in grid for c in row if len(c) > 3 and c[3] == MOCHA.current_bg]
    assert lit                                                        # the estimated line is highlighted
    # too long for two columns: falls back to the scrolling single column
    many = Lyrics(lines=[LyricLine(None, f"l{i}") for i in range(200)], synced=False).estimate_timing(240.0)
    grid = lyrics_grid(many, 120.0, 240.0, 80, 20, MOCHA)
    assert any(len(c) > 3 and c[3] == MOCHA.current_bg for row in grid for c in row)


def test_panel_title_says_timing_is_estimated():
    plain = Lyrics(lines=[LyricLine(None, "hello there")], synced=False, source="LRCLIB")
    out, _ = render(make_tui(plain), 120, 40)
    assert "Lyrics · LRCLIB · timing estimated" in out


def find_row(out, needle):
    for y, line in enumerate(out.splitlines()):
        if needle in line:
            return y, line.index(needle)
    raise AssertionError(f"{needle!r} not on screen")


def test_presets_menu_opens_moves_and_applies_with_keys():
    tui = make_tui(None)
    posted = []
    tui.post = posted.append
    assert tui.handle_input("presets") and tui.menu_open
    out, _ = render(tui, 120, 40)
    assert "Presets" in out and "warm-up" in out and "Energy rises" in out and "rising" in out
    assert "ENERGY & SOUND" in out and "HOW PICKS ARE CHOSEN" in out
    names = tui._preset_names()
    assert names[:3] == ["radio", "warm-up", "wind-down"] and set(names) == set(tui.presets())
    start = tui.menu_cursor
    assert tui.handle_input("down") and tui.handle_input("wheel-down") and tui.handle_input("up")
    assert tui.menu_cursor == start + 1
    assert not tui.handle_input("playpause")              # still reaches the loop with the menu open
    assert tui.handle_input("enter") and not tui.menu_open
    assert posted == [f"preset:{names[start + 1]}"]
    tui.handle_input("presets")
    assert tui.handle_input("escape") and not tui.menu_open
    assert tui.handle_input("up")                         # arrows do nothing with the menu closed
    assert not tui.handle_input("next")


def test_presets_menu_marks_the_preset_in_use_and_follows_the_cursor():
    tui = make_tui(None)
    tui.config.preset = "vibe"
    tui.handle_input("presets")
    assert tui._preset_names()[tui.menu_cursor] == "vibe"
    out, _ = render(tui, 120, 30)                       # short window: the list scrolls to the cursor
    y, _ = find_row(out, "● vibe ")
    assert "▸" in out.splitlines()[y] and "similar" not in out.splitlines()[y]
    assert "Songs with the same mood" in out.splitlines()[y]


def test_clicking_a_preset_and_the_key_chips():
    tui = make_tui(None)
    posted = []
    tui.post = posted.append
    out, _ = render(tui, 120, 40)
    y, x = find_row(out, " presets ")                   # the toolbar chip opens the menu
    assert y == 39
    assert tui.handle_input(f"click:{x + 2}:{y + 1}") and tui.menu_open
    out, _ = render(tui, 120, 40)
    y, x = find_row(out, "wind-down")
    assert tui.handle_input(f"click:{x + 1}:{y + 1}")
    assert posted == ["preset:wind-down"] and not tui.menu_open
    out, _ = render(tui, 120, 40)
    y, x = find_row(out, " n  next ")
    tui.handle_input(f"click:{x + 2}:{y + 1}")
    y, x = find_row(out, "flow: ")
    tui.handle_input(f"click:{x + 1}:{y + 1}")
    tui.handle_input("click:1:2")                        # nothing there: ignored
    assert posted == ["preset:wind-down", "next", "flow"]


def test_wide_screen_shows_up_next_and_album_art_placeholder():
    tui = make_tui(None)
    pick = tui.loop.state.plan.primary
    pick.candidate.extra = {"energy": 0.7}
    tui.loop.state.plan.picks = [pick]
    tui.history = types.SimpleNamespace(recent=lambda n: [types.SimpleNamespace(title="Intro", artist="The xx",
                                                                                source="spotify-app")])
    out, svg = render(tui, 150, 40)
    assert "Up next" in out and "RECENTLY PLAYED" in out and "Intro" in out
    assert "▰" in out and "PLAYING" in out and "♪" in out
    assert "display error" not in out


def test_half_blocks_and_placeholder():
    from PIL import Image

    from tidal_shuffle.artwork import half_blocks, placeholder

    img = Image.new("RGB", (4, 4), (255, 0, 0))
    for x in range(4):
        for y in range(2, 4):
            img.putpixel((x, y), (0, 0, 255))
    grid = half_blocks(img, 4, 2)
    assert len(grid) == 2 and len(grid[0]) == 4
    assert grid[0][0] == ("▀", (255, 0, 0), False, (255, 0, 0))
    assert grid[1][0] == ("▀", (0, 0, 255), False, (0, 0, 255))
    tile = placeholder(10, 5, (0, 0, 0), (200, 200, 200), (1, 2, 3))
    assert len(tile) == 5 and all(len(r) == 10 for r in tile)
    assert tile[2][5][0] == "♪" and tile[0][0][1] != tile[4][9][3]


def test_artwork_service_fetches_in_the_background_and_caches(tmp_path):
    import io
    import time

    from PIL import Image

    from tidal_shuffle.artwork import ArtworkService

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "JPEG")
    album = types.SimpleNamespace(id=77, cover="abc", image=lambda size: f"https://img/{size}")
    catalog = types.SimpleNamespace(raw_track=lambda tid: types.SimpleNamespace(album=album),
                                    find=lambda t, a: (types.SimpleNamespace(id="5"), 1.0))
    fetched = []

    def fetch(url):
        fetched.append(url)
        return buf.getvalue()

    svc = ArtworkService(catalog, tmp_path, fetch=fetch)
    assert svc.get("k", None, "T", "A") == "pending"
    for _ in range(100):
        img = svc.get("k", None, "T", "A")
        if img != "pending":
            break
        time.sleep(0.02)
    assert img is not None and img.size == (8, 8)
    assert fetched == ["https://img/320"] and (tmp_path / "77.jpg").exists()
    again = ArtworkService(catalog, tmp_path, fetch=fetch)       # from the disk cache
    again._load("k", "5", "T", "A")
    assert again.get("k", "5", "T", "A").size == (8, 8) and len(fetched) == 1
    grid = svc.cells("k", img, 6, 3)
    assert len(grid) == 3 and svc.cells("k", img, 6, 3) is grid


def test_preset_sections_put_your_own_presets_last():
    from tidal_shuffle.tui import preset_sections

    sections = preset_sections({"balanced": {}, "my-evening": {}, "warm-up": {}, "radio": {}})
    assert sections == [("Energy & sound", ["radio", "warm-up"]), ("How picks are chosen", ["balanced"]),
                        ("Your presets", ["my-evening"])]
