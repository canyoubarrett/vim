"""Pictures behind the logo."""

import zipfile

from PIL import Image

from tidal_shuffle.stages import StageArt, add_backdrops, compose, label, list_backdrops


def picture(path, size=(344, 144), colour=(200, 40, 40)):
    img = Image.new("RGB", size, colour)
    for x in range(size[0] // 2, size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (40, 40, 200))       # left half red, right half blue
    img.save(path)
    return path


def test_add_pictures_from_files_folders_and_zips(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    picture(src / "10 - b.png")
    picture(src / "2 - a.png")
    (src / "notes.txt").write_text("x")
    z = tmp_path / "pack.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(src / "2 - a.png", "album/1 - c.png")
        zf.writestr("album/readme.txt", "x")
    dest = tmp_path / "backdrops"
    assert add_backdrops([src, z], dest, log=lambda m: None) == 3
    assert list_backdrops(dest) == ["1 - c.png", "2 - a.png", "10 - b.png"]     # natural order
    assert label("12 - UkTleZJ.png") == "Stage 12" and label("dojo.jpg") == "dojo"


def test_cells_fill_the_panel_dimmed_and_pan_across_wide_pictures(tmp_path):
    picture(tmp_path / "1 - wide.png")
    art = StageArt(tmp_path)
    bg = (30, 30, 46)
    start = art.cells("1 - wide.png", 20, 10, 0.0, bg, dim=0.5)
    assert len(start) == 10 and all(len(r) == 20 for r in start)
    top = start[5][2][0]
    assert top[0] < 200 and top[0] > top[2]               # red, dimmed towards the background
    later = art.cells("1 - wide.png", 20, 10, 45.0, bg, dim=0.5)   # half way through the pan
    assert later[5][2][0][2] > later[5][2][0][0]          # now showing the blue side
    assert art.cells("missing.png", 20, 10, 0.0, bg) is None


def test_random_picks_one_per_song_and_cover_uses_the_album_art(tmp_path):
    for i in range(5):
        picture(tmp_path / f"{i} - p.png")
    art = StageArt(tmp_path, cover=lambda: Image.new("RGB", (64, 64), (10, 200, 10)))
    a = art.pick("random", "song-1")
    assert a in list_backdrops(tmp_path) and art.pick("random", "song-1") == a
    assert art.pick("off") is None and art.pick("cover") == "cover"
    cells = art.cells("cover", 10, 5, 0.0, (0, 0, 0), dim=0.0)
    assert cells[2][5][0][1] > 150                        # green, from the cover
    assert StageArt(tmp_path, cover=lambda: "pending").cells("cover", 10, 5, 0.0, (0, 0, 0)) is None


def test_the_logo_is_drawn_over_the_picture():
    logo = [[(" ", None), ("⣿", (255, 255, 255)), ("▘", (1, 2, 3), False, (9, 9, 9))]]
    art = [[((100, 0, 0), (0, 100, 0)), ((10, 10, 10), (30, 30, 30)), ((0, 0, 0), (0, 0, 0))]]
    out = compose(logo, art)[0]
    assert out[0] == ("▀", (100, 0, 0), False, (0, 100, 0))          # empty: the picture
    assert out[1] == ("⣿", (255, 255, 255), False, (20, 20, 20))     # the logo, the picture behind
    assert out[2] == ("▘", (1, 2, 3), False, (9, 9, 9))             # the logo's own colours stay
