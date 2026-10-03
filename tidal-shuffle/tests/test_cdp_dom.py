"""Run the real CDP page scripts in jsdom against plausible TIDAL page layouts."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tidal_shuffle.tidal.cdp import TidalCdp

FAKE = Path(__file__).parent / "e2e" / "fake_tidal"
pytestmark = pytest.mark.skipif(shutil.which("node") is None or not (FAKE / "node_modules" / "jsdom").exists(),
                                reason="needs node and `npm install` in tests/e2e/fake_tidal")

FOOTER = ('<div data-test="footer-player"><div data-test="play-controls">'
          '<button aria-label="Play" data-test="play" data-mark="footer-play"></button></div></div>')


class Capture:
    """Records the JavaScript instead of running it."""

    def __init__(self):
        self.js = None

    def evaluate(self, js, timeout=10.0):
        self.js = js
        return None

    def close(self):
        pass


def snippet(method, *args):
    cap = Capture()
    cdp = TidalCdp(http_get=lambda u, t: '[{"type":"page","url":"https://desktop.tidal.com/","webSocketDebuggerUrl":"ws://x"}]',
                   connect=lambda ws: cap, sleep=lambda s: None, clock=lambda: 0.0)
    getattr(cdp, method)(*args)
    return cap.js


def run(html, steps, path="/home", setup=""):
    payload = {"html": f"<html><body><div id='wimp'><main>{html}</main>{FOOTER}</div></body></html>",
               "path": path, "setup": setup,
               "steps": [{"js": snippet(*s[:-1]) if isinstance(s[-1], int) else snippet(*s),
                          "wait": s[-1] if isinstance(s[-1], int) else 0} for s in steps]}
    r = subprocess.run(["node", str(FAKE / "dom_runner.mjs")], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# An app that renders the album's rows 50 ms after any route change, optionally
# redirecting /track/<id> to the album route first.
def app(rows_html, redirect=None):
    return f"""
      window.addEventListener('popstate', () => {{
        {"history.replaceState({}, '', " + json.dumps(redirect) + ");" if redirect else ""}
        const main = document.querySelector('main');
        main.innerHTML = '';
        setTimeout(() => {{ main.innerHTML = {json.dumps(rows_html)}; }}, 50);
      }});
    """


def test_classic_track_page_clicks_the_rows_play_button():
    rows = ('<div data-test="tracklist-row"><button data-test="play-button" data-mark="p1"></button><a href="/track/111">A</a></div>'
            '<div data-test="tracklist-row"><button data-test="play-button" data-mark="p2"></button><a href="/track/123">B</a></div>')
    out = run("", [("navigate_to_track", "123"), ("rows_ready", "123", 150), ("click_play_for_track", "123")],
              setup=app(rows))
    assert out["results"] == ["pushed", True, "row"]
    assert out["clicks"] == ["click:p2"]


def test_redirected_page_with_id_attribute_rows_and_no_buttons():
    rows = ('<div data-test="tracklist-row" data-track-id="111" data-mark="r1"><span>A</span></div>'
            '<div data-test="tracklist-row" data-track-id="123" data-mark="r2"><span>B</span></div>')
    out = run("", [("navigate_to_track", "123"), ("rows_ready", "123", 150), ("click_play_for_track", "123"),
                   ("navigate_to_track", "123")],
              setup=app(rows, redirect="/album/7"))
    assert out["path"] == "/album/7"
    assert out["results"] == ["pushed", True, "row-dblclick", "already"]
    assert out["clicks"] == ["dblclick:r2"]


def test_track_page_with_only_a_header_play_button():
    hero = ('<h1>Them Changes</h1><button aria-label="Play track" data-mark="hero"></button>'
            '<button aria-label="Add to playlist" data-mark="add"></button>')
    out = run("", [("navigate_to_track", "123"), ("rows_ready", "123", 150), ("click_play_for_track", "123")],
              setup=app(hero, redirect="/album/7/track/123"))
    assert out["results"] == ["pushed", True, "hero"]
    assert out["clicks"] == ["click:hero"]


def test_header_button_found_by_text_and_data_test():
    hero = '<button data-test="header-play-button"><span>Play</span></button><button data-test="playlist-add">Add</button>'
    out = run(hero, [("click_play_for_track", "123")], path="/track/123")
    assert out["results"] == ["hero"]
    assert out["clicks"] == ["click:BUTTON"]


def test_does_not_click_anything_on_an_unrelated_page():
    hero = '<button aria-label="Play" data-mark="hero"></button>'
    stale = "window.__tidalShuffleNav = {id: '123', path: '/track/123', t: Date.now() - 60000};"
    out = run(hero, [("rows_ready", "123"), ("click_play_for_track", "123")], path="/album/9", setup=stale)
    assert out["results"] == [False, ""]
    assert out["clicks"] == []


def test_never_clicks_the_footer_play_button():
    out = run("<p>loading</p>", [("click_play_for_track", "123")], path="/track/123")
    assert out["results"] == [""]
    assert out["clicks"] == []


STORE = """
  const store = {getState: () => ({playQueue: {elements: []}, player: {}}),
                 dispatch: (a) => { window.__dispatched.push(a); return a; }};
  const root = document.getElementById('wimp');
  root['__reactContainer$abc'] = {memoizedProps: null, child: {memoizedProps: {children: 1},
    sibling: null, child: {memoizedProps: {store, children: 2}, child: null}}};
"""


def test_store_play_dispatches_add_now():
    out = run("", [("store_play", "123")], setup=STORE)
    assert out["results"] == ["ok"]
    assert out["dispatched"] == [{"type": "playQueue/ADD_NOW",
                                  "payload": {"context": {"type": "UNKNOWN"}, "mediaItemIds": [123], "fromIndex": 0}}]


def test_store_play_waits_for_tidal_to_load_the_track():
    known = STORE.replace("player: {}", "player: {}, content: {mediaItems: {'55': {}}}")
    out = run("", [("store_play", "123"), ("store_play", "55")], setup=known)
    assert out["results"] == ["not-loaded", "ok"]
    assert [a["payload"]["mediaItemIds"] for a in out["dispatched"]] == [[55]]


def test_store_play_without_react_store():
    out = run("", [("store_play", "123")])
    assert out["results"] == ["no-store"]


def test_inspect_reports_the_track_page():
    rows = '<div data-test="tracklist-row" data-track-id="123"><button data-test="play-button"></button>B</div>'
    out = run(rows, [("inspect", "123")], path="/track/123", setup=STORE)
    info = out["results"][0]
    assert "error" not in info, info
    assert info["onTrackPage"] and info["trackRowFound"] and info["rowCount"] == 1
    assert info["store"]["playQueue"] == ["elements"]
    assert any(c["dataTest"] == "play-button" and c["inRow"] for c in info["playControls"])
    assert out["clicks"] == []


def test_redirect_to_a_page_without_the_track_clicks_nothing():
    """A play button on whatever page TIDAL went to instead would play something else."""
    hero = '<h1>New releases</h1><button aria-label="Play" data-mark="hero"></button>'
    out = run("", [("navigate_to_track", "123"), ("rows_ready", "123", 150), ("click_play_for_track", "123", "Phone Tag")],
              setup=app(hero, redirect="/home"))
    assert out["results"][-1] == "not-this-track"
    assert out["clicks"] == []


def test_redirected_page_titled_with_the_track_is_clicked():
    hero = '<h1>Phone Tag</h1><button aria-label="Play" data-mark="hero"></button>'
    out = run("", [("navigate_to_track", "123"), ("rows_ready", "123", 150), ("click_play_for_track", "123", "Phone Tag")],
              setup=app(hero, redirect="/album/7"))
    assert out["results"][-1] == "hero" and out["clicks"] == ["click:hero"]


def test_late_redirect_is_followed():
    hero = '<h1>Them Changes</h1><button aria-label="Play" data-mark="hero"></button>'
    late = """
      window.addEventListener('popstate', () => setTimeout(() => {
        history.replaceState({}, '', '/album/7');
        document.querySelector('main').innerHTML = %s;
      }, 50));
    """ % json.dumps(hero)
    out = run("", [("navigate_to_track", "123"), ("rows_ready", "123", 150),
                   ("click_play_for_track", "123", "Them Changes"), ("navigate_to_track", "123")], setup=late)
    assert out["path"] == "/album/7"
    assert out["results"] == ["pushed", True, "hero", "already"]
    assert out["clicks"] == ["click:hero"]


QUEUE_STORE = """
  const state = {playQueue: {currentIndex: 0, elements: [{mediaItemId: 500}, {mediaItemId: 501}]}};
  const store = {getState: () => state,
                 dispatch: (a) => {
                   window.__dispatched.push(a);
                   if (a.type === 'playQueue/ADD_NEXT') setTimeout(() => {   // the queue updates a moment later
                     const q = state.playQueue;
                     q.elements.splice(q.currentIndex + 1, 0, ...a.payload.mediaItemIds.map(id => ({mediaItemId: id})));
                   }, 100);
                   return a;
                 }};
  document.getElementById('wimp')['__reactContainer$q'] = {child: {memoizedProps: {store}}};
"""


def test_queue_next_is_confirmed_from_tidals_queue():
    out = run("", [("store_queue_next", "123"), ("store_next_id",)], setup=QUEUE_STORE)
    assert out["results"] == ["ok", "123"]
    assert [a["type"] for a in out["dispatched"]] == ["playQueue/ADD_NEXT"]


def test_queue_next_is_not_sent_twice():
    setup = QUEUE_STORE.replace("{mediaItemId: 501}", "{mediaItemId: 123}")
    out = run("", [("store_queue_next", "123")], setup=setup)
    assert out["results"] == ["ok"] and out["dispatched"] == []


def test_unreadable_queue_is_never_written_to():
    setup = QUEUE_STORE.replace("currentIndex: 0, elements", "pos: 0, list")
    out = run("", [("store_queue_next", "123"), ("store_next_id",)], setup=setup)
    assert out["results"] == ["unreadable", None] and out["dispatched"] == []


def test_queue_that_disagrees_with_the_footer_is_not_written_to():
    footer_link = "document.querySelector('[data-test=footer-player]').innerHTML += '<a href=\"/album/1/track/999\">x</a>';"
    out = run("", [("store_queue_next", "123")], setup=QUEUE_STORE + footer_link)
    assert out["results"] == ["unreadable"] and out["dispatched"] == []


def test_queue_next_that_does_not_take():
    setup = QUEUE_STORE.replace("if (a.type === 'playQueue/ADD_NEXT')", "if (false)")
    out = run("", [("store_queue_next", "123")], setup=setup)
    assert out["results"] == ["not-next"]



def test_watch_records_the_apps_actions():
    out = run("", [("watch_actions",), ("recorded_actions",)],
              setup=STORE + "setTimeout(() => {}, 0);")
    assert out["results"][0] == "ok"
