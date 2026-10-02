from types import SimpleNamespace

import pytest

from tidal_shuffle.spotify_ui import SpotifyUI, SpotifyUIError, split_play_label


def test_split_play_label_handles_by_in_titles():
    assert split_play_label("Play Midnight City by M83") == [("Midnight City", "M83")]
    readings = split_play_label("Play Stand by Me by Ben E. King")
    assert ("Stand by Me", "Ben E. King") in readings and ("Stand", "Me by Ben E. King") in readings
    assert split_play_label("Pause") == [] and split_play_label("Play Liked Songs") == []


class El:
    def __init__(self, role, label="", children=()):
        self.role, self.label, self.children = role, label, list(children)


class FakeAX:
    def __init__(self, root, trusted=True):
        self.root, self._trusted, self.pressed = root, trusted, []
    def trusted(self):
        return self._trusted
    def app_element(self, pid):
        return self.root
    def attribute(self, el, name):
        return {"AXRole": el.role, "AXDescription": el.label, "AXChildren": el.children}.get(name)
    def press(self, el):
        self.pressed.append(el.label)
        return True


def page():
    rows = [El("AXButton", "Play Midnight City (Live) by M83"), El("AXButton", "Play Midnight City by M83"),
            El("AXButton", "Play Midnight City by Karaoke Stars"), El("AXButton", "Play Liked Songs")]
    return El("AXApplication", "", [El("AXWindow", "Spotify", [El("AXGroup", "", rows), El("AXButton", "Pause")])])


def runner(calls, pid="4242"):
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=pid + "\n")
    return run


def test_find_and_play_picks_the_studio_version():
    calls = []
    ax = FakeAX(page())
    ui = SpotifyUI(ax=ax, run=runner(calls), sleep=lambda s: None, clock=lambda: 0.0)
    b = ui.find_and_play("Midnight City", "M83")
    assert b.label == "Play Midnight City by M83" and ax.pressed == ["Play Midnight City by M83"]
    assert ["open", "-g", "spotify:search:Midnight%20City%20M83"] in calls


def test_find_and_play_gives_up_without_a_match():
    t = {"now": 0.0}
    def sleep(s): t["now"] += s
    ax = FakeAX(page())
    ui = SpotifyUI(ax=ax, run=runner([]), sleep=sleep, clock=lambda: t["now"])
    assert ui.find_and_play("Something Else", "Nobody", wait=2) is None and ax.pressed == []


def test_needs_permission_and_running_spotify():
    with pytest.raises(SpotifyUIError, match="Accessibility"):
        SpotifyUI(ax=FakeAX(page(), trusted=False), run=runner([])).find_and_play("a", "b")
    def no_pid(cmd, **kw):
        return SimpleNamespace(returncode=1, stdout="")
    with pytest.raises(SpotifyUIError, match="not running"):
        SpotifyUI(ax=FakeAX(page()), run=no_pid).find_and_play("a", "b")


def test_walk_respects_node_limit_and_dump():
    wide = El("AXApplication", "", [El("AXButton", f"Play Song {i} by Band") for i in range(50)])
    ui = SpotifyUI(ax=FakeAX(wide), run=runner([]), max_nodes=10)
    assert len(list(ui.walk(wide))) == 10
    assert ui.dump(limit=5)[0] == ("AXButton", "Play Song 0 by Band")


def test_localised_labels():
    root = El("AXApplication", "", [El("AXButton", "Reproducir Lucía de Joan Manuel Serrat")])
    ui = SpotifyUI(ax=FakeAX(root), run=runner([]), sleep=lambda s: None, clock=lambda: 0.0,
                   label_pattern=r"^Reproducir (?P<rest>.+)$", by_word=" de ")
    assert ui.find_and_play("Lucía", "Joan Manuel Serrat").title == "Lucía"


def test_without_pyobjc_the_ui_is_unavailable(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "ApplicationServices":
            raise ImportError("no pyobjc")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    ok, reason = SpotifyUI().available()
    assert not ok and "pyobjc" in reason
