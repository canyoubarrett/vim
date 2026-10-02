"""Keeping Spotify hidden: the decisions, with the window server faked."""

from tidal_shuffle.spotify_guard import SpotifyGuard


class Desk:
    def __init__(self):
        self.windows = [("Terminal", 10, 0), ("TIDAL", 20, 0)]
        self.hidden, self.activated = [], []
        self.t = 0.0


def guard(desk, should=True):
    flag = {"on": should}
    g = SpotifyGuard(lambda: flag["on"], windows=lambda: list(desk.windows), hide=desk.hidden.append,
                     activate=desk.activated.append, clock=lambda: desk.t)
    return g, flag


def test_spotify_stealing_the_front_is_hidden_and_focus_goes_back():
    desk = Desk()
    g, _ = guard(desk)
    assert g.tick() is False and desk.hidden == []          # terminal in front, no Spotify
    desk.windows.insert(0, ("Spotify", 30, 0))              # `play track` brought it forward
    desk.t = 1.0
    assert g.tick() is True
    assert desk.hidden == [30] and desk.activated == [10]   # hidden, terminal back in front


def test_spotify_behind_other_windows_is_hidden_without_stealing_focus():
    desk = Desk()
    desk.windows.append(("Spotify", 30, 0))
    g, _ = guard(desk)
    assert g.tick() is True and desk.hidden == [30] and desk.activated == []


def test_left_alone_when_not_in_use_and_no_double_hides():
    desk = Desk()
    desk.windows.insert(0, ("Spotify", 30, 0))
    g, flag = guard(desk, should=False)
    assert g.tick() is False and desk.hidden == []          # your own Spotify, between harvests
    flag["on"] = True
    assert g.tick() is True
    assert g.tick() is False                                # the hide is on its way
    desk.t = 1.0
    assert g.tick() is True and len(desk.hidden) == 2


def test_menu_bar_items_do_not_count():
    desk = Desk()
    desk.windows.insert(0, ("Spotify", 30, 25))             # a status-bar item, not a window
    g, _ = guard(desk)
    assert g.tick() is False
