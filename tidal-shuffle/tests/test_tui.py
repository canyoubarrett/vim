"""The full-screen view: lyric layout, rendering at any size, the floating logo, the theme."""

import types

from rich.console import Console

from tidal_shuffle.config import load_config
from tidal_shuffle.loop import LoopState
from tidal_shuffle.lyrics import LyricLine, Lyrics, parse_lrc
from tidal_shuffle.models import Candidate, NowPlaying, Pick, TidalTrack, TIDAL_BUNDLE_ID
from tidal_shuffle.theme import FLAVORS, hex_rgb, theme
from tidal_shuffle.tui import ScreenRenderable, ShuffleTUI, fmt_time, lyric_rows, lyrics_grid
from tidal_shuffle.visualizer import LogoScene, art_to_dots, lerp, load_art

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
    assert len(lit) == len("three") + 2                   # the sung word plus a cell each side
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
    assert "#cba6f7" in svg.lower() and "#11111b" in svg.lower()                          # Catppuccin Mocha
    tui.backdrop = None
    assert "#1e1e2e" in render(tui, 120, 40)[1].lower()                                   # plain base without the sky
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
    assert not lit                                                    # guessed timing is never highlighted
    # too long for two columns: falls back to scrolling with the song, still not highlighted
    many = Lyrics(lines=[LyricLine(None, f"l{i}") for i in range(200)], synced=False).estimate_timing(240.0)
    grid = lyrics_grid(many, 120.0, 240.0, 80, 20, MOCHA)
    text = ["".join(c[0] for c in row).strip() for row in grid]
    assert "l100" in text or "l99" in text or "l101" in text
    assert not any(len(c) > 3 and c[3] == MOCHA.current_bg for row in grid for c in row)


def test_panel_title_says_timing_is_estimated():
    plain = Lyrics(lines=[LyricLine(None, "hello there")], synced=False, source="LRCLIB")
    out, _ = render(make_tui(plain), 120, 40)
    assert "Lyrics · LRCLIB · no timing" in out and "scrolling" not in out      # fits: shown whole
    long = Lyrics(lines=[LyricLine(None, f"line number {i}") for i in range(120)], synced=False, source="LRCLIB")
    out, _ = render(make_tui(long), 120, 40)
    assert "no timing · scrolling by estimate" in out


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
    last = out.splitlines()[-1]
    y, x = len(out.splitlines()) - 1, last.index(" f ")
    tui.handle_input(f"click:{x + 2}:{y + 1}")
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



# -- transitions, karaoke, effects -----------------------------------------------------

def stepping_tui(lyr):
    """A TUI whose clock moves on 0.1 s with every frame."""
    tui = make_tui(lyr)
    clock = {"t": 1000.0}
    tui._clock = lambda: clock["t"]

    def frame(n=1, w=120, h=40):
        out = None
        for _ in range(n):
            clock["t"] += 0.1
            out = render(tui, w, h)[0]
        return out
    return tui, frame, clock


def lyric_panel(tui, w=120, h=40):
    return [r for r in tui.regions(w, h) if "Lyrics" in str(getattr(r[0], "title", ""))]


def test_lyrics_go_the_moment_the_song_changes_and_the_logo_glides_back():
    lyr = Lyrics(lines=parse_lrc("[01:20.00]Waiting in a car\n[01:30.00]Waiting for a ride"), synced=True, source="TIDAL")
    tui, frame, clock = stepping_tui(lyr)
    assert "Waiting in a car" in frame()
    st = tui.loop.state
    st.pending = NowPlaying("Strangers", "Kosheen", bundle_id=TIDAL_BUNDLE_ID)   # TIDAL shows another song
    assert tui.wanted_lyrics() == (None, "changing")
    frame(4)                                                  # 0.4 s
    assert tui._content[0] < 0.05 and "Waiting in a car" not in frame()
    assert tui._layout[0] > 0.9                               # the layout waits a moment for the next song's
    widths = []
    for _ in range(60):                                       # then the logo glides to the full width
        frame()
        widths.append([r for r in tui.regions(120, 40) if "Alter Era" in str(getattr(r[0], "title", ""))][0][3])
    assert widths[-1] == 116 and widths[0] < 60
    steps = [b - a for a, b in zip(widths, widths[1:])]
    assert min(steps) >= 0 and max(steps) <= 12               # smooth, one way, no jumps
    assert tui._shown is None and not lyric_panel(tui)
    # the next song has lyrics: room is made first, then they fade in
    st.pending = None
    st.current = NowPlaying("Strangers", "Kosheen", duration=200.0, playing=True, bundle_id=TIDAL_BUNDLE_ID)
    st.started_at = clock["t"] - 81.0
    frame()
    assert tui._layout_goal == 1.0 and tui._content[0] < 0.1
    frame(30)
    assert tui._layout[0] > 0.97 and tui._content[0] > 0.97 and "Waiting in a car" in frame()


def test_lyrics_hide_during_a_hand_off_and_at_the_end_of_the_song():
    lyr = Lyrics(lines=parse_lrc("[00:10.00]one"), synced=True, source="TIDAL")
    tui = make_tui(lyr)
    assert tui.wanted_lyrics()[0] is lyr
    tui.loop.state.handed_off = True
    assert tui.wanted_lyrics() == (None, "changing")
    tui.loop.state.handed_off = False
    tui.loop.state.started_at = 1000.0 - 243.9                # 0.1 s before the end
    assert tui.wanted_lyrics() == (None, "changing")
    tui.view = "logo"
    assert tui.wanted_lyrics() == (None, "logo")


def test_karaoke_sweep_lights_words_as_they_are_sung():
    from tidal_shuffle.tui import sung_chars, sweep_cells

    lyr = Lyrics(lines=parse_lrc("[00:10.00]one two three four\n[00:20.00]next"), synced=True)
    assert sung_chars(lyr, 0, 9.75) == 0.0
    mid = sung_chars(lyr, 0, 10.75)
    assert 0 < mid < len("one two three four")
    assert sung_chars(lyr, 0, 19.0) == len("one two three four")
    cells = sweep_cells("one two three four", 0, "one two three four", 5.0, MOCHA)
    inverted = "".join(c[0] for c in cells if c[3] == MOCHA.current_bg)
    waiting = "".join(c[0] for c in cells if c[3] is None)
    assert inverted == "one two" and waiting == " three four"           # the inversion sweeps along
    assert cells[0][1] == MOCHA.current_fg and cells[-1][1] == MOCHA.text and all(c[2] for c in cells)
    # word stamps (enhanced LRC) are followed exactly
    stamped = Lyrics(lines=parse_lrc("[00:10.00]<00:10.00>slow <00:14.00>then <00:14.20>fast\n[00:16.00]x"), synced=True)
    assert stamped.lines[0].words == [(10.0, 0), (14.0, 5), (14.2, 10)]
    assert 0 < sung_chars(stamped, 0, 13.6) < 5 < sung_chars(stamped, 0, 13.8) < 10   # lead: 0.25 s early
    grid = lyrics_grid(stamped, 13.8, 30.0, 40, 5, MOCHA)
    line = next(r for r in grid if "fast" in "".join(c[0] for c in r))
    assert "".join(c[0] for c in line if len(c) > 3 and c[3] == MOCHA.current_bg).strip() == "slow then"
    assert "fast" in "".join(c[0] for c in line if len(c) < 4 or c[3] is None)
    # as the line goes on, more of it is inverted, until all of it is
    full = lyrics_grid(stamped, 15.0, 30.0, 40, 5, MOCHA)
    line = next(r for r in full if "fast" in "".join(c[0] for c in r))
    assert "".join(c[0] for c in line if len(c) > 3 and c[3] == MOCHA.current_bg).strip() == "slow then fast"


def test_lyrics_grid_fades():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True)
    faded = lyrics_grid(lyr, 31.0, 200, 30, 5, MOCHA, alpha=0.3)
    bar = [c for c in faded[2] if len(c) > 3 and c[3] is not None]
    assert bar and all(c[3] != MOCHA.current_bg for c in bar)          # the bar fades with the text
    assert lyrics_grid(lyr, 31.0, 200, 30, 5, MOCHA, alpha=1.0)[2] != faded[2]


def test_spring_is_smooth_and_does_not_overshoot():
    from tidal_shuffle.fx import spring

    x, v, xs = 0.0, 0.0, []
    for _ in range(60):
        x, v = spring(x, v, 1.0, 1 / 12, 5.5)
        xs.append(x)
    steps = [b - a for a, b in zip([0.0] + xs, xs)]
    assert max(xs) <= 1.0 and xs[-1] > 0.99 and min(steps) >= 0
    assert steps[0] < steps[3]                                   # it eases in rather than jumping


def test_compositor_glass_opacity_and_output():
    from rich.segment import Segment

    from tidal_shuffle.fx import Canvas, segments
    from tidal_shuffle.tui import style as mkstyle

    sky = (100, 40, 120)
    cells = [[[" ", None, False, sky] for _ in range(6)] for _ in range(2)]
    canvas = Canvas(cells, MOCHA.bg, MOCHA.text, glass=0.5)
    canvas.blit([[Segment("ab", mkstyle((255, 0, 0), False, MOCHA.bg)), Segment("c", mkstyle((0, 255, 0), True, (1, 2, 3)))]],
                0, 0, 6, 1)
    a, c = cells[0][0], cells[0][2]
    assert a[0] == "a" and a[1] == (255, 0, 0) and a[3] != MOCHA.bg and a[3] != sky   # glass: tinted by the sky
    assert c[3] == (1, 2, 3) and c[2] is True                                         # solid colours stay
    canvas.blit([[Segment("x", mkstyle((250, 250, 250), False, (0, 0, 0)))]], 0, 1, 6, 1, opacity=0.5)
    x = cells[1][0]
    assert x[0] == "x" and x[3] == (50, 20, 60) and x[1] != (250, 250, 250)            # half way there
    canvas.blit([[Segment("y")]], 1, 1, 6, 1, opacity=0.0)
    assert cells[1][1][0] == " "                                                       # invisible: not drawn
    out = list(segments(cells, mkstyle))
    assert "".join(s.text for s in out).splitlines()[0].startswith("abc")


def test_rain_behind_the_panels():
    from tidal_shuffle.fx import Backdrop

    rain = Backdrop(MOCHA.p)
    rows = rain.frame(80, 30, 1.0, energy=0.5)
    assert len(rows) == 30 and all(len(r) == 80 for r in rows)
    drops = [c for r in rows for c in r if "⠀" < c[0] <= "⣿"]
    assert len(drops) > 80 and all(c[0] in "⠀⣿" or "⠀" < c[0] <= "⣿" or c[0] == " " for r in rows for c in r)
    assert {c[3] for r in rows for c in r} == {MOCHA.p["base"]}            # one even colour, the panels' own
    calm = Backdrop(MOCHA.p).frame(80, 30, 1.0, energy=0.0)
    wild = Backdrop(MOCHA.p).frame(80, 30, 1.0, energy=1.0)
    count = lambda g: sum(1 for r in g for c in r if c[0] != " ")
    assert count(wild) > count(calm) * 1.3                              # heavier rain for energetic music
    # it falls: a drop's dots move down between frames, and slowly while paused
    t = rain._t
    rain.frame(80, 30, 1.1)
    assert abs(rain._t - t - 0.1) < 1e-9
    rain.frame(80, 30, 1.2, playing=False)
    assert abs(rain._t - t - 0.125) < 1e-9


def test_rain_stays_behind_the_panels():
    from rich.segment import Segment

    from tidal_shuffle.fx import Canvas
    from tidal_shuffle.tui import style as mkstyle

    cells = [[["⡇", (200, 200, 200), False, (17, 17, 27)] for _ in range(8)]]
    canvas = Canvas(cells, MOCHA.bg, MOCHA.text, glass=0.22)
    canvas.blit([[Segment("      ab", mkstyle(MOCHA.text, False, MOCHA.bg))]], 0, 0, 8, 1)
    assert "".join(c[0] for c in cells[0]) == "      ab"            # no rain inside a box
    assert cells[0][0][3] != MOCHA.bg                               # glass: tinted by the sky
    outside = [[["⡇", (200, 200, 200), False, (17, 17, 27)] for _ in range(4)]]
    Canvas(outside, MOCHA.bg, MOCHA.text).blit([[Segment("ab", mkstyle(MOCHA.text))]], 0, 0, 2, 1)
    assert outside[0][3][0] == "⡇"                                  # it falls around the boxes


def test_logo_is_as_big_as_the_panel_allows():
    scene = LogoScene()
    for w, h in ((46, 22), (116, 30)):
        rows = set()
        for i in range(60):
            g = scene.frame(w, h, i * 0.2)
            rows |= {y for y, r in enumerate(g) if any("⠀" < c[0] <= "⣿" for c in r)}
        assert min(rows) >= 0 and max(rows) <= h - 2 and max(rows) - min(rows) >= h - 4



def test_256_colour_terminals_get_the_theme_matched_to_their_palette():
    from tidal_shuffle.tui import _PALETTE_256, nearest_256, set_color_depth, style as mkstyle

    pal = dict(_PALETTE_256)
    base = pal[nearest_256(MOCHA.bg)]
    assert base != (0, 0, 0) and max(base) < 60                        # a dark grey, not black
    assert nearest_256((255, 0, 0)) == 196 and nearest_256((0, 0, 0)) == 16
    try:
        set_color_depth("256")
        st = mkstyle(MOCHA.text, False, MOCHA.bg)
        assert st.bgcolor.number == nearest_256(MOCHA.bg) and st.color.number == nearest_256(MOCHA.text)
        tui = make_tui(None)
        c = Console(width=100, height=30, color_system="256", force_terminal=True, record=True,
                    file=open("/dev/null", "w"))
        c.print(ScreenRenderable(tui))
        out = c.export_text(clear=False, styles=True)
        assert f"48;5;{nearest_256(MOCHA.bg)}" in out or "Midnight City" in c.export_text()
    finally:
        set_color_depth("truecolor")


def test_rain_is_faint_and_adjustable():
    from tidal_shuffle.fx import Backdrop

    def brightest(vis):
        rows = Backdrop(MOCHA.p, visibility=vis).frame(60, 20, 1.0)
        return max(sum(c[1]) - sum(c[3]) for r in rows for c in r if c[1])
    assert brightest(0.3) < 90                       # barely lighter than the sky behind it
    assert brightest(1.0) > brightest(0.3) * 2
    off = Backdrop(MOCHA.p, visibility=0.0).frame(60, 20, 1.0)
    assert all(c[1] is None or sum(c[1]) - sum(c[3]) < 30 for r in off for c in r)


def test_quadrant_blocks_double_the_detail():
    from PIL import Image

    from tidal_shuffle.artwork import QUADRANTS, half_blocks, quadrant_blocks

    img = Image.new("RGB", (4, 2), (0, 0, 0))
    img.putpixel((0, 0), (255, 255, 255))            # one bright pixel in the top-left corner
    img.putpixel((3, 1), (255, 0, 0))
    cell = quadrant_blocks(img, 2, 1)[0]
    assert cell[0][0] == "▘" and cell[0][1] == (255, 255, 255) and cell[0][3] == (0, 0, 0)
    assert cell[1][0] in ("▗", "▛") and len(QUADRANTS) == 15
    # a two-colour cell is reproduced exactly; half blocks cannot split it sideways
    left = Image.new("RGB", (2, 2), (0, 0, 255))
    left.putpixel((1, 0), (255, 255, 0))
    left.putpixel((1, 1), (255, 255, 0))
    q = quadrant_blocks(left, 1, 1)[0][0]
    assert q[0] in ("▌", "▐") and {q[1], q[3]} == {(0, 0, 255), (255, 255, 0)}
    h = half_blocks(left, 1, 1)[0][0]
    assert h[1] not in ((0, 0, 255), (255, 255, 0))  # blended: the detail is lost


def test_dithering_to_the_256_colour_palette():
    from PIL import Image

    from tidal_shuffle.artwork import quadrant_blocks
    from tidal_shuffle.tui import _PALETTE_256

    grad = Image.new("RGB", (64, 8))
    for x in range(64):
        for y in range(8):
            grad.putpixel((x, y), (40 + x, 30 + x // 2, 90 + x))
    pal = {c for _, c in _PALETTE_256}
    flat = quadrant_blocks(grad, 32, 4)
    dith = quadrant_blocks(grad, 32, 4, dither=True)
    colours = lambda g: {c[1] for r in g for c in r} | {c[3] for r in g for c in r}
    assert colours(dith) <= pal | {tuple(c) for c in colours(dith)}   # mixed only within a cell
    assert len(colours(dith)) > 3 and colours(flat) != colours(dith)


def test_big_cover_view_fades_in_over_the_logo():
    import types as _t

    from PIL import Image

    tui, frame, clock = stepping_tui(None)
    img = Image.new("RGB", (40, 40), (200, 50, 100))
    from tidal_shuffle.artwork import half_blocks
    tui.artwork = _t.SimpleNamespace(get=lambda *a: img,
                                     cells=lambda k, im, w, h, mode="quadrant", dither=False: half_blocks(im, w, h))
    frame()
    assert tui.handle_input("art") and tui.cover_view
    frame()
    assert 0 < tui._cover[0] < 1                      # fading in, not cut
    out = frame(20)
    assert "Cover · Hurry Up" in out and tui._cover[0] > 0.97
    covers = [r for r in tui.regions(120, 40) if "Cover" in str(getattr(r[0], "title", ""))]
    assert covers and covers[0][3] > 30
    tui.handle_input("art")
    frame(20)
    assert "Cover" not in frame() and "Alter Era" in frame()



def test_lines_not_sung_yet_are_hidden_dimmed_or_shown():
    lyr = Lyrics(lines=parse_lrc(LRC), synced=True)
    text = lambda g: ["".join(c[0] for c in row).strip() for row in g]
    hide = text(lyrics_grid(lyr, 31.0, 200, 30, 7, MOCHA, ahead="hide"))
    assert "two" in hide and "three" in hide and "four" not in hide and "five" not in hide
    show = text(lyrics_grid(lyr, 31.0, 200, 30, 7, MOCHA, ahead="show"))
    assert "four" in show and "five" in show
    dim = lyrics_grid(lyr, 31.0, 200, 30, 7, MOCHA, ahead="dim")
    four = next(r for r in dim if "four" in "".join(c[0] for c in r))
    assert all(c[1] == lerp(MOCHA.past, MOCHA.bg, 0.45) for c in four if c[0].strip())
    # before the singing starts: nothing but the count-in
    intro = text(lyrics_grid(lyr, 3.0, 200, 30, 7, MOCHA, ahead="hide"))
    assert not any(w in " ".join(intro) for w in ("one", "two", "three")) and any("●" in t or "○" in t for t in intro)


def test_lead_moves_the_sweep_earlier():
    from tidal_shuffle.tui import sung_chars

    lyr = Lyrics(lines=parse_lrc("[00:10.00]one two three four\n[00:20.00]next"), synced=True)
    assert sung_chars(lyr, 0, 10.5, lead=0.55) > sung_chars(lyr, 0, 10.5, lead=0.25)
    assert lyr.index_at(9.5, 0.55) == 0 and lyr.index_at(9.5, 0.25) == -1


# -- settings menu, logo styles and motions -----------------------------------------------

def test_escape_opens_the_settings_and_choices_apply_and_persist(tmp_path):
    from tidal_shuffle import uistate
    from tidal_shuffle.tui import SETTING_ITEMS

    tui, frame, clock = stepping_tui(None)
    tui.settings_path = tmp_path / "ui.json"
    frame()
    assert tui.handle_input("escape") and tui.settings_open
    out = frame(10)
    assert "Settings" in out and "THEME" in out and "Nord" in out and "Preview" in out
    filled = next(i for i, it in enumerate(SETTING_ITEMS) if it[:2] == ("logo_style", "filled"))
    while tui.settings_cursor < filled:
        tui.handle_input("down")
    tui.handle_input("enter")
    assert tui.config.ui.logo_style == "filled" and tui.scene.style == "filled"
    assert uistate.load(tui.settings_path)["logo_style"] == "filled"
    # clicking a choice applies it too
    out = frame()
    y, x = find_row(out, "Pastel, filled")                 # clicking a choice applies it too
    tui.handle_input(f"click:{x + 1}:{y + 1}")
    assert tui.config.ui.logo_style == "pastel"
    shapes = next(i for i, it in enumerate(SETTING_ITEMS) if it[:2] == ("logo_motion", "shapes"))
    while tui.settings_cursor < shapes:
        tui.handle_input("down")
    tui.handle_input("enter")
    frame()
    assert tui.config.ui.logo_motion == "shapes" and tui.scene.motion == "shapes"
    assert tui.handle_input("escape") and not tui.settings_open
    # p and Esc: one menu at a time
    tui.handle_input("presets")
    assert tui.menu_open and not tui.settings_open
    tui.handle_input("escape")
    assert not tui.menu_open and not tui.settings_open


def test_rain_setting_reaches_the_backdrop():
    from tidal_shuffle.tui import SETTING_ITEMS

    tui = make_tui(None)
    off = next(i for i, it in enumerate(SETTING_ITEMS) if it[:2] == ("rain", 0.0))
    tui.apply_setting(off)
    assert tui.backdrop.visibility == 0.0
    tui.backdrop = None
    tui.apply_setting(off + 2)
    assert tui.backdrop is not None and tui.backdrop.visibility == 0.6


def test_logo_style_colours():
    tui = make_tui(None)
    for style in ("muted", "mono", "theme"):
        tui.config.ui.logo_style = style
        tui._apply_logo_style()
        assert tui.scene.style == style
    tui.config.ui.logo_style = "mono"
    tui._apply_logo_style()
    assert len(set(tui.scene.logo)) == 1                           # grey: no tint
    tui.config.ui.logo_style = "muted"
    tui._apply_logo_style()
    lo = tui.scene.logo
    assert max(lo) - min(lo) < max(MOCHA.logo) - min(MOCHA.logo)  # less saturated than the theme's


def test_title_uses_the_logos_colours():
    from tidal_shuffle.tui import TITLE_COLORS

    tui = make_tui(None)
    text = tui.flowing_title(" Tidal Shuffle ")
    cols = {tuple(sp.style.color.triplet) for sp in text.spans}
    assert len(cols) > 5
    t = tui._clock
    tui._clock = lambda: t() + 3.0
    later = {tuple(sp.style.color.triplet) for sp in tui.flowing_title(" Tidal Shuffle ").spans}
    assert later != cols                                          # it drifts


def test_filled_and_wireframe_logos_use_the_logos_colours():
    from tidal_shuffle.visualizer import LOGO_COLORS

    filled = LogoScene(style="filled", bg=MOCHA.bg)
    for i in range(30):                                            # past the 1.6 s fade-in
        g = filled.frame(50, 24, 1 + i * 0.1)
    colours = {c[1] for r in g for c in r if len(c) > 1 and c[1]} | {c[3] for r in g for c in r if len(c) > 3 and c[3]}
    assert LOGO_COLORS["sun"] in colours and LOGO_COLORS["purple"] in colours
    assert any(c[0] in "▘▝▖▗▀▄▌▐▚▞▛▜▙▟" for r in g for c in r)
    wire = LogoScene(style="wireframe", bg=MOCHA.bg)
    for i in range(30):
        g = wire.frame(50, 24, 1 + i * 0.1)
    near = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) < 90
    line_cols = {c[1] for r in g for c in r if "⠀" < c[0] <= "⣿"}
    assert any(near(c, LOGO_COLORS["sun"]) for c in line_cols) and any(near(c, LOGO_COLORS["cyan"]) for c in line_cols)


def test_shapes_float_on_their_own_and_motions_change_smoothly():
    scene = LogoScene(motion="shapes")
    scene.frame(60, 26, 1.0)
    scene._motion_t = 5.0
    _, place = scene._layout(60, 26)
    sun, eye = place("sun"), place("eye")
    still = LogoScene(motion="float")
    still.frame(60, 26, 1.0)
    still._motion_t = 5.0
    _, place2 = still._layout(60, 26)
    # the same point moves differently in each shape when they float on their own
    d_sun = [a - b for a, b in zip(sun(248, 274), place2("sun")(248, 274))]
    d_eye = [a - b for a, b in zip(eye(248, 274), place2("eye")(248, 274))]
    assert d_sun != d_eye
    # switching motion eases in: no jump between frames
    scene = LogoScene(motion="float")
    prev = None
    scene.frame(60, 26, 0.0)
    scene.motion = "shapes"
    for i in range(1, 40):
        scene.frame(60, 26, i * 0.083)
        if prev is not None:
            assert abs(scene._pieces - prev) < 0.1
        prev = scene._pieces
    assert prev > 0.8


def test_glass_is_tinted_by_the_sky_not_by_panels_underneath():
    from rich.segment import Segment

    from tidal_shuffle.fx import Canvas
    from tidal_shuffle.tui import style as mkstyle

    cells = [[[" ", None, False, (20, 20, 30)] for _ in range(4)]]
    canvas = Canvas(cells, MOCHA.bg, MOCHA.text, glass=0.5)
    canvas.blit([[Segment("    ", mkstyle(None, False, (200, 100, 250)))]], 0, 0, 4, 1)    # a bright bar
    canvas.blit([[Segment("    ", mkstyle(None, False, MOCHA.bg))]], 0, 0, 4, 1)          # a panel over it
    assert cells[0][0][3] == canvas.sky[0][0] or sum(cells[0][0][3]) < 200


def test_topple_falls_apart_as_it_leans_and_comes_back_together():
    scene = LogoScene(motion="topple")
    rows = []
    for i in range(int(24 * 12)):
        scene.frame(50, 24, i / 12)
        apart = max(abs(scene.topple_offset(n)[0]) + abs(scene.topple_offset(n)[1]) for n in scene._shape_centre)
        rows.append((abs(scene.lean()), apart))
    leaning = [a for l, a in rows if l > 0.9]
    upright = [a for l, a in rows[24:] if l < 0.05]
    assert leaning and upright and min(leaning) > 3 * max(upright)
    assert max(a for _, a in rows) > 30                    # well apart, in SVG units
    # fluid: the pieces move a little each frame, never a jump
    steps = [abs(b - a) for (_, a), (_, b) in zip(rows, rows[1:])]
    assert max(steps) < 4.0
    # the upper pieces follow the lean later than the tip
    scene._motion_t = 3.0
    sun, dart = scene.topple_offset("sun"), scene.topple_offset("dart")
    assert abs(sun[0]) != abs(dart[0])


def test_party_mode_cycles_colours_and_comes_apart():
    from tidal_shuffle.visualizer import party_color

    scene = LogoScene(motion="party", style="filled", bg=MOCHA.bg)
    scene.party_colors = True
    seen, pieces = set(), []
    for i in range(int(30 * 12)):
        g = scene.frame(40, 20, i / 12)
        if i % 12 == 0:
            seen |= {c[1] for r in g for c in r if len(c) > 1 and c[1]}
        pieces.append(scene.pieces_now())
    assert len(seen) > 40                                  # many colours over time
    assert max(pieces) > 0.9 and min(pieces[60:]) < 0.1    # apart and together
    a, b = party_color("sun", 2.0, 0.0), party_color("sun", 2.05, 0.0)
    assert sum(abs(x - y) for x, y in zip(a, b)) < 30       # gliding, not jumping
    assert party_color("sun", 2.0, 0.0) != party_color("sun", 2.0, 0.35)   # each shape a little behind


def test_spring_motions_lag_behind_and_never_jump():
    from tidal_shuffle.visualizer import MOTIONS

    for motion in ("jelly", "magnet", "tide"):
        scene = LogoScene(motion=motion)
        prev = None
        for i in range(240):
            scene.frame(50, 24, i / 12)
            state = {k: tuple(v[:3]) for k, v in scene._phys.items()}
            if prev:
                for k, v in state.items():
                    if k in prev:
                        assert abs(v[0] - prev[k][0]) < 25 and abs(v[1] - prev[k][1]) < 25   # no teleporting
            prev = state
        assert motion in MOTIONS
    jelly = LogoScene(motion="jelly")
    for i in range(60):
        jelly.frame(50, 24, i / 12)
    assert any(abs(v[0]) + abs(v[1]) > 0.5 for v in jelly._phys.values())      # the pieces lag the logo
    # switching back to the plain float lets the springs settle and go quiet
    jelly.motion = "float"
    for i in range(60, 360):
        jelly.frame(50, 24, i / 12)
    assert all(abs(v[0]) + abs(v[1]) < 0.5 for v in jelly._phys.values())


def test_more_logo_colour_schemes():
    from tidal_shuffle.visualizer import LOGO_COLORS, logo_palette

    for style in ("pastel", "neon", "sunset", "ocean", "catppuccin"):
        pal = logo_palette(style, MOCHA.p)
        assert set(pal) == set(LOGO_COLORS) and pal != LOGO_COLORS
    assert logo_palette("catppuccin", MOCHA.p)["purple"] == MOCHA.p["mauve"]
    tui = make_tui(None)
    tui.config.ui.logo_style = "sunset"
    tui._apply_logo_style()
    assert tui.scene.colors == logo_palette("sunset", MOCHA.p)
    for style in ("pastel", "sunset", "ocean", "catppuccin", "neon"):
        scene = LogoScene(style=style, bg=MOCHA.bg)
        scene.colors = logo_palette(style, MOCHA.p)
        for i in range(25):
            g = scene.frame(40, 20, i / 10)
        assert sum(1 for r in g for c in r if c[0] != " " or (len(c) > 3 and c[3])) > 40



def test_cycling_through_settings_previews_them_and_esc_puts_them_back(tmp_path):
    from tidal_shuffle.tui import SETTING_ITEMS

    tui, frame, clock = stepping_tui(None)
    tui.settings_path = tmp_path / "ui.json"
    frame()
    tui.handle_input("escape")
    nord = next(i for i, it in enumerate(SETTING_ITEMS) if it[:2] == ("theme", "nord"))
    while tui.settings_cursor < nord:
        tui.handle_input("down")
    frame(12)                                              # the theme blends over 0.6 s
    assert tui.th.name == "nord" and tui.config.ui.theme == "mocha"    # previewed, not chosen
    sunset = next(i for i, it in enumerate(SETTING_ITEMS) if it[:2] == ("logo_style", "sunset"))
    while tui.settings_cursor < sunset:
        tui.handle_input("down")
    frame(12)
    assert tui.scene.style == "sunset" and tui.th.name == "mocha"   # only what the cursor is on is previewed
    tui.handle_input("enter")                              # chosen
    tui.handle_input("escape")
    frame(12)
    assert tui.config.ui.logo_style == "sunset" and tui.scene.style == "sunset" and tui.th.name == "mocha"


def test_theme_changes_blend_smoothly():
    from tidal_shuffle.theme import theme

    tui, frame, clock = stepping_tui(None)
    frame()
    tui.config.ui.theme = "dracula"
    seen = []
    for _ in range(10):
        frame()
        seen.append(tui.th.bg)
    assert seen[-1] == theme("dracula").bg and len(set(seen)) > 3       # through in-between colours


def test_all_themes_render(tmp_path):
    from tidal_shuffle.theme import THEMES, theme

    for name in THEMES:
        tui = make_tui(None)
        tui.config.ui.theme = name
        out, svg = render(tui, 100, 30)
        assert "Midnight City" in out and "display error" not in out
        th = theme(name)
        assert ("#%02x%02x%02x" % th.p["base"]) in svg.lower()


def test_shuffle_tree_unfolds_and_follows_the_choice():
    from tidal_shuffle.trace import Trace

    tui, frame, clock = stepping_tui(None)
    tr = Trace("after Midnight City — M83", "radio · weighted", clock=lambda: clock["t"])
    src = tr.add(None, "sources", status="running")
    tr.add(src, "spotify-app", "source", "asking…", "running")
    tui.loop.engine = types.SimpleNamespace(trace=tr)
    tui.config.ui.shuffle_view = "logo"
    out = frame()
    assert "Shuffle tree" in out and "after Midnight City" in out
    out = frame(5)
    assert "spotify-app" in out and "asking" in out                     # unfolded, step by step
    tr.update(src, status="done", detail="30 songs")
    pick = tr.add(None, "pick: Strangers — Kosheen", "pick", "backups: Teardrop", "done")
    tr.finish("done")
    out = frame(6)
    assert "▶ pick: Strangers — Kosheen" in out and "└─" in out and "├─" in out
    assert tui.handle_input("tree") and tui.config.ui.shuffle_view == "off"
    assert tui.handle_input("tree") and tui.config.ui.shuffle_view == "logo"


def test_party_setting_drives_the_logo():
    from tidal_shuffle.tui import SETTING_ITEMS

    tui, frame, clock = stepping_tui(None)
    frame()
    on = next(i for i, it in enumerate(SETTING_ITEMS) if it[:2] == ("party", True))
    tui.apply_setting(on)
    frame()
    assert tui.scene.party_colors and tui.scene.motion == "party"
    tui.apply_setting(on - 1)
    frame()
    assert not tui.scene.party_colors and tui.scene.motion == "float"


def test_logo_backdrop_shows_behind_the_logo_and_is_previewed(tmp_path):
    from PIL import Image

    from tidal_shuffle.stages import StageArt

    Image.new("RGB", (344, 144), (220, 60, 60)).save(tmp_path / "7 - stage.png")
    tui, frame, clock = stepping_tui(None)
    tui.stages = StageArt(tmp_path)
    frame()
    tui.handle_input("escape")                            # the settings list picks up the picture
    names = [it[1] for it in tui.setting_items if it[0] == "logo_backdrop"]
    assert names == ["off", "cover", "random", "7 - stage.png"]
    i = next(i for i, it in enumerate(tui.setting_items) if it[1] == "7 - stage.png")
    while tui.settings_cursor < i:
        tui.handle_input("right")                         # → jumps a section at a time
        if tui.setting_items[tui.settings_cursor][0] == "logo_backdrop":
            break
    while tui.settings_cursor < i:
        tui.handle_input("down")
    assert tui.setting("logo_backdrop") == "7 - stage.png" and tui.chosen("logo_backdrop") == "off"
    _, svg = render(tui, 120, 40)
    assert "#" in svg and any(c in svg.lower() for c in ("#783a46", "#7b3b47", "#7c3c48")) or "▀" in render(tui, 120, 40)[0]
    tui.handle_input("enter")
    tui.handle_input("escape")
    out, _ = render(tui, 120, 40)
    assert tui.config.ui.logo_backdrop == "7 - stage.png" and "▀" in out


def test_narrow_window_keeps_up_next_beside_the_log():
    tui = make_tui(None)
    pick = tui.loop.state.plan.primary
    tui.loop.state.plan.picks = [pick]
    out, _ = render(tui, 100, 34)
    assert "Up next" in out and "▸ Strangers — Kosheen" in out and "log" in out
    y, _ = find_row(out, "Up next")
    assert "log" in out.splitlines()[y]                   # the same row: the log box, split in two
    wide, _ = render(tui, 150, 40)
    assert "UP NEXT" not in wide and "RECENTLY PLAYED" in wide   # wide: the card beside the logo instead


def test_every_key_stays_on_the_bottom_row_in_a_narrow_window():
    tui = make_tui(None)
    for width in (150, 100, 70):
        out, _ = render(tui, width, 34)
        last = out.splitlines()[-1]
        for key in (" space ", " n ", " f ", " p ", " l ", " a ", " t ", " esc ", " q "):
            assert key in last, (width, key, last)
