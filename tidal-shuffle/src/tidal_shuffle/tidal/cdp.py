"""Drive the TIDAL desktop app through the Chrome DevTools Protocol (CDP).

The TIDAL macOS app is an Electron shell around the web player at
``https://desktop.tidal.com``. Launched with ``--remote-debugging-port`` it
exposes CDP on 127.0.0.1, which lets us run JavaScript inside the player:
navigate to a track page without interrupting audio, click that track's play
button, and read the footer (title, artist, numeric track id, play state).

``tidal://track/<id>`` links only *navigate* the app; they never start
playback. CDP is the only non-invasive way to make the stock app play a
specific track, and the approach is shared with several open-source projects.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

DEFAULT_PORT = 9222
DEFAULT_APP = "/Applications/TIDAL.app"

# DOM hooks in the TIDAL web player. These are version dependent; if TIDAL
# changes its markup, `tidal-shuffle inspect` shows what is there now.
SELECTORS: dict[str, str] = {
    "row": "[data-test=tracklist-row]",
    "row_play": "[data-test=play-button]",
    "hero_play": 'button[aria-label="Play"]',
    "footer": "[data-test=footer-player]",
    "footer_title": "[data-test=footer-track-title]",
    "footer_artist": "[data-test=footer-artist-name]",
    "controls": "[data-test=play-controls]",
    "pause": "[data-test=pause]",
    "play": "[data-test=play]",
    "next": "[data-test=next]",
    "previous": "[data-test=previous]",
}


class CdpError(RuntimeError):
    pass


@dataclass
class CdpNowPlaying:
    title: Optional[str] = None
    artist: Optional[str] = None
    artists: list[str] = field(default_factory=list)
    track_id: Optional[str] = None
    playing: Optional[bool] = None
    position: Optional[float] = None
    duration: Optional[float] = None
    path: Optional[str] = None


@dataclass
class PlayOutcome:
    ok: bool
    method: str = ""
    observed_id: Optional[str] = None
    detail: str = ""


def _parse_clock(text: str) -> Optional[float]:
    parts = text.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60.0 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600.0 + nums[1] * 60.0 + nums[2]
    return None


class CdpConnection:
    """A minimal JSON-RPC-over-WebSocket client for one CDP page target."""

    def __init__(self, ws_url: str, timeout: float = 10.0):
        import websocket  # websocket-client; imported lazily

        # Chromium rejects CDP upgrades that carry an Origin header, and the
        # debug port is loopback only, so never route it through a proxy.
        self._ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True,
                                               http_no_proxy=["127.0.0.1", "localhost", "::1"])
        self._next_id = 0

    def call(self, method: str, params: Optional[dict] = None, timeout: float = 10.0) -> dict:
        self._next_id += 1
        msg_id = self._next_id
        self._ws.settimeout(timeout)
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv()
            except Exception as e:
                # The message was delivered; resending could click twice.
                raise CdpError(f"{method}: no reply ({e})") from None
            if not raw:
                continue
            msg = json.loads(raw)
            if msg.get("id") != msg_id:
                continue  # an event or a stale reply
            if "error" in msg:
                raise CdpError(f"{method}: {msg['error'].get('message', msg['error'])}")
            return msg.get("result", {})
        raise CdpError(f"{method}: timed out")

    def evaluate(self, expression: str, timeout: float = 10.0) -> Any:
        res = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                             "awaitPromise": True}, timeout=timeout)
        if res.get("exceptionDetails"):
            text = res["exceptionDetails"].get("text", "JavaScript exception")
            exc = res["exceptionDetails"].get("exception", {}).get("description", "")
            raise CdpError(f"{text}: {exc}"[:300])
        return res.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _default_http_get(url: str, timeout: float) -> str:
    with _LOOPBACK_OPENER.open(url, timeout=timeout) as resp:  # loopback only, never proxied
        return resp.read().decode("utf-8", "replace")


class TidalCdp:
    """High level operations on the TIDAL app via CDP."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host: str = "127.0.0.1",
        app_path: str = DEFAULT_APP,
        selectors: Optional[dict[str, str]] = None,
        http_get: Callable[[str, float], str] = _default_http_get,
        connect: Callable[[str], Any] = CdpConnection,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen: Callable[..., Any] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.port = port
        self.host = host
        self.app_path = app_path
        self.sel = dict(SELECTORS, **(selectors or {}))
        self._http_get = http_get
        self._connect = connect
        self._run = run
        self._popen = popen
        self._sleep = sleep
        self._clock = clock
        self.log = log or (lambda m: None)
        self._conn: Any = None
        self._store_works = False
        self._store_failures = 0

    # -- process / endpoint -------------------------------------------------
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def alive(self) -> bool:
        try:
            body = self._http_get(f"{self.base_url}/json/version", 1.5)
        except Exception:
            return False
        return "Browser" in body or "TIDAL" in body or "Electron" in body

    def targets(self) -> list[dict]:
        try:
            return json.loads(self._http_get(f"{self.base_url}/json", 3.0))
        except Exception as e:
            raise CdpError(f"could not list CDP targets: {e}") from None

    def page_ws_url(self) -> Optional[str]:
        best = None
        for t in self.targets():
            if t.get("type") != "page":
                continue
            url = t.get("url", "")
            if "tidal.com" in url:
                return t.get("webSocketDebuggerUrl")
            best = best or t.get("webSocketDebuggerUrl")
        return best

    def app_running(self) -> bool:
        if shutil.which("pgrep") is None:
            return False
        try:
            r = self._run(["pgrep", "-f", "TIDAL.app/Contents/MacOS/TIDAL"], capture_output=True, text=True, timeout=5)
        except Exception:
            return False
        return r.returncode == 0

    def launch(self, relaunch_if_running: bool = True, wait: float = 25.0) -> bool:
        """Make sure TIDAL is running with the debug port; returns ``alive()``."""
        if self.alive():
            return True
        if self.app_running():
            if not relaunch_if_running:
                return False
            self.log("TIDAL is running without the debug port; relaunching it")
            try:
                self._run(["osascript", "-e", 'tell application "TIDAL" to quit'], capture_output=True, text=True, timeout=10)
            except Exception as e:
                self.log(f"could not quit TIDAL: {e}")
            deadline = self._clock() + 15
            while self.app_running() and self._clock() < deadline:
                self._sleep(0.5)
        self._popen(["open", "-a", self.app_path, "--args", f"--remote-debugging-port={self.port}",
                     f"--remote-debugging-address={self.host}"])
        deadline = self._clock() + wait
        while self._clock() < deadline:
            if self.alive():
                self._sleep(1.0)  # give the renderer a moment to load the player
                return True
            self._sleep(0.5)
        return False

    # -- javascript plumbing --------------------------------------------------
    def _connection(self) -> Any:
        if self._conn is None:
            ws_url = self.page_ws_url()
            if not ws_url:
                raise CdpError("no TIDAL page target; is the app running with --remote-debugging-port?")
            self._conn = self._connect(ws_url)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def evaluate(self, js: str, timeout: float = 10.0) -> Any:
        """Run JavaScript in the player. Retried once only when the request never
        left (stale socket); a missing reply is not retried, because the script
        may have run (clicking Play twice would pause the song)."""
        for attempt in range(2):
            try:
                return self._connection().evaluate(js, timeout=timeout)
            except CdpError:
                self.close()
                raise
            except Exception as e:  # connecting or sending failed: nothing ran
                self.close()
                if attempt == 1:
                    raise CdpError(f"CDP connection failed: {e}") from None
        raise CdpError("unreachable")

    def _js_sel(self) -> str:
        return json.dumps(self.sel)

    # -- player state ---------------------------------------------------------
    def now_playing(self) -> Optional[CdpNowPlaying]:
        js = f"""
        (() => {{
          const S = {self._js_sel()};
          const q = s => document.querySelector(s);
          const footer = q(S.footer);
          const titleEl = q(S.footer_title);
          const title = titleEl ? (titleEl.textContent || '').trim() : null;
          const artists = Array.from(document.querySelectorAll(S.footer_artist)).map(e => (e.textContent || '').trim()).filter(Boolean);
          let id = null;
          const scopes = [footer, titleEl ? titleEl.closest('a') : null, titleEl];
          for (const sc of scopes) {{
            if (!sc) continue;
            const links = sc.tagName === 'A' ? [sc] : Array.from(sc.querySelectorAll('a[href*="/track/"]'));
            for (const a of links) {{
              const m = (a.getAttribute('href') || '').match(/\\/track\\/(\\d+)/);
              if (m) {{ id = m[1]; break; }}
            }}
            if (id) break;
          }}
          const playing = !!q(S.controls + ' ' + S.pause) || !!q('button[aria-label="Pause"]');
          const paused = !!q(S.controls + ' ' + S.play) || !!q(S.controls + ' button[aria-label="Play"]');
          const times = [];
          if (footer) {{
            for (const el of footer.querySelectorAll('*')) {{
              if (el.children.length === 0) {{
                const t = (el.textContent || '').trim();
                if (/^\\d{{1,2}}:\\d{{2}}(:\\d{{2}})?$/.test(t)) times.push(t);
              }}
            }}
          }}
          return {{title, artists, id, playing, paused, times, path: location.pathname, hasFooter: !!footer}};
        }})()
        """
        data = self.evaluate(js)
        if not isinstance(data, dict):
            return None
        np = CdpNowPlaying(title=data.get("title") or None,
                           artists=list(data.get("artists") or []),
                           track_id=data.get("id") or None,
                           path=data.get("path"))
        np.artist = np.artists[0] if np.artists else None
        if data.get("playing"):
            np.playing = True
        elif data.get("paused"):
            np.playing = False
        times = [t for t in (data.get("times") or []) if _parse_clock(t) is not None]
        if len(times) >= 2:
            np.position = _parse_clock(times[0])
            np.duration = _parse_clock(times[-1])
        if not np.title and not np.track_id:
            return None
        return np

    def current_path(self) -> str:
        return str(self.evaluate("location.pathname") or "")

    # -- navigation & playback ------------------------------------------------
    def _page_js(self, marker: str, track_id: Optional[str], body: str, title: Optional[str] = None) -> str:
        """Wrap ``body`` with the helpers every page script shares.

        ``marker`` names the snippet (tests dispatch on it). TIDAL may redirect
        ``/track/<id>`` to another route, so the path the app lands on after our
        navigation is remembered in ``window.__tidalShuffleNav`` and counts as
        "on the track's page" too.
        """
        tid = json.dumps(str(int(track_id))) if track_id else "null"
        ttl = json.dumps(title or "")
        return f"""
        (() => {{ /*ts:{marker}*/
          const S = {self._js_sel()};
          const ID = {tid};
          const TITLE = {ttl};
          const want = ID ? '/track/' + ID : null;
          const pathRe = ID ? new RegExp('/track/' + ID + '(/|$)') : null;
          const idRe = ID ? new RegExp('(^|[^0-9])' + ID + '([^0-9]|$)') : null;
          const inChrome = el => !!(el.closest(S.footer) || el.closest(S.controls) || el.closest('footer') || el.closest('nav'));
          const landed = () => {{
            if (!ID) return false;
            if (pathRe.test(location.pathname)) return true;
            const n = window.__tidalShuffleNav;
            if (!n || n.id !== ID) return false;
            if (location.pathname === n.path) return true;
            if (Date.now() - n.t < 8000) {{ n.path = location.pathname; return true; }}  // the app redirected
            return false;
          }};
          const norm = t => (t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
          // the page really is about this track: its own address, a link to it, or its title as a heading
          const showsTrack = () => {{
            if (!ID) return false;
            if (pathRe.test(location.pathname)) return true;
            const links = Array.from(document.querySelectorAll('a[href]')).filter(a => !inChrome(a));
            if (links.some(a => pathRe.test((a.getAttribute('href') || '').split('?')[0]))) return true;
            const t = norm(TITLE);
            return !!t && Array.from(document.querySelectorAll('h1, h2, [data-test*=title]'))
              .some(h => !inChrome(h) && norm(h.textContent) === t);
          }};
          const rows = () => Array.from(document.querySelectorAll(S.row)).filter(r => !inChrome(r));
          const strong = r => r.innerHTML.includes(want + '"') || r.innerHTML.includes(want + '?') || r.innerHTML.includes(want + '/')
                         || [r, ...r.querySelectorAll('*')].some(e => Array.from(e.attributes).some(a => a.value === ID || a.value === want));
          const rowFor = () => {{
            if (!ID) return null;
            const rs = rows();
            return rs.find(strong) || rs.find(r => r.innerHTML.includes(want)) || rs.find(r => idRe.test(r.outerHTML)) || null;
          }};
          const playIn = r => r.querySelector(S.row_play) || r.querySelector('button[aria-label^="Play"]')
                           || Array.from(r.querySelectorAll('[data-test]')).find(e => /(^|-)play(-button)?$/.test(e.getAttribute('data-test')));
          const isPlayish = el => {{
            const dt = (el.getAttribute('data-test') || '').toLowerCase();
            const al = (el.getAttribute('aria-label') || '').trim();
            const tx = (el.textContent || '').trim();
            if (/list|queue|back|next|later|pause|speed|mode/.test(dt)) return false;
            return /(^|-)play(-button|-all|-track)?$/.test(dt) || /^play($|\\s)/i.test(al) || (el.tagName === 'BUTTON' && /^play$/i.test(tx));
          }};
          const hero = () => {{
            const seen = new Set();
            const sels = [S.hero_play, '[data-test=play-button]', '[data-test*=play]', 'button[aria-label^="Play"]', 'button'];
            for (const sel of sels) {{
              for (const el of document.querySelectorAll(sel)) {{
                if (seen.has(el)) continue;
                seen.add(el);
                if (!inChrome(el) && !el.closest(S.row) && isPlayish(el)) return el;
              }}
            }}
            return null;
          }};
          {body}
        }})()
        """

    def navigate_to_track(self, track_id: str, return_status: bool = False):
        """Route the single-page app to ``/track/<id>`` without reloading."""
        js = self._page_js("navigate", track_id, """
          const n = window.__tidalShuffleNav;
          if (pathRe.test(location.pathname) || (n && n.id === ID && location.pathname === n.path)) return 'already';
          const before = location.pathname;
          window.__tidalShuffleNav = {id: ID, path: want, t: Date.now()};
          history.pushState({}, '', want);
          window.dispatchEvent(new PopStateEvent('popstate', {state: {}}));
          if (location.pathname === want) return 'pushed';
          if (location.pathname !== before) {  // the app redirected the track route
            window.__tidalShuffleNav.path = location.pathname;
            return 'pushed';
          }
          return 'failed';
        """)
        status = self.evaluate(js)
        return status if return_status else status in ("pushed", "already")

    def rows_ready(self, track_id: Optional[str] = None):
        """``True`` when the track's row (or the track page's own play button) is
        rendered, ``"other"`` when only unrelated rows are, ``False`` otherwise."""
        js = self._page_js("rows_ready", track_id, """
          const onPage = landed();
          if (ID && rowFor()) return true;
          if (ID && onPage && hero()) return true;
          if (!ID && (rows().length || hero())) return true;
          return rows().length ? 'other' : false;
        """)
        result = self.evaluate(js)
        return result if result in (True, "other") else False

    def wait_for_rows(self, track_id: Optional[str], timeout: float) -> bool:
        start = self._clock()
        deadline = start + timeout
        grace = start + min(3.0, timeout / 2)
        while True:
            try:
                ready = self.rows_ready(track_id)
            except CdpError as e:
                self.log(f"rows check failed: {e}")
                ready = False
            if ready is True:
                return True
            if ready == "other" and self._clock() >= grace:
                return True  # the page rendered a tracklist; fall back to its first row
            if self._clock() >= deadline:
                return False
            self._sleep(0.25)

    def click_play_for_track(self, track_id: str, title: Optional[str] = None) -> str:
        """Click the play control for the track; returns the method used ('' = none found).

        The page's own play button is only clicked when the page shows that
        track: if TIDAL took us somewhere else, that button would play
        something else entirely."""
        js = self._page_js("click", track_id, """
          const row = rowFor();
          if (row) {
            const b = playIn(row);
            if (b) { b.click(); return 'row'; }
            row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true, view: window}));
            return 'row-dblclick';
          }
          if (!landed()) return '';
          const h = hero();
          if (h && showsTrack()) { h.click(); return 'hero'; }
          if (h) return 'not-this-track';
          const rs = rows();
          if (rs.length && pathRe.test(location.pathname)) {
            const b = playIn(rs[0]);
            if (b) b.click(); else rs[0].dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true, view: window}));
            return 'first-row';
          }
          return '';
        """, title=title)
        return str(self.evaluate(js) or "")

    # TIDAL's web player keeps its state in a Redux store; TidaLuna's
    # MediaItem.play() is a dispatch of playQueue/ADD_NOW. The store is found
    # through React's fiber tree (the Provider's ``store`` prop).
    _FIND_STORE = """
          const findStore = () => {
            if (window.__tidalShuffleStore) return window.__tidalShuffleStore;
            const els = [document.getElementById('wimp'), document.getElementById('root'), ...document.querySelectorAll('body > div')];
            for (const el of els) {
              if (!el) continue;
              const key = Object.keys(el).find(k => k.startsWith('__reactContainer$') || k.startsWith('__reactFiber$'));
              let start = key ? el[key] : (el._reactRootContainer && el._reactRootContainer._internalRoot && el._reactRootContainer._internalRoot.current);
              const stack = [start];
              let n = 0;
              while (stack.length && n < 20000) {
                const f = stack.pop();
                n++;
                if (!f || typeof f !== 'object') continue;
                const p = f.memoizedProps;
                const st = p && (p.store || (p.value && p.value.store));
                if (st && typeof st.dispatch === 'function' && typeof st.getState === 'function') {
                  window.__tidalShuffleStore = st;
                  return st;
                }
                if (f.sibling) stack.push(f.sibling);
                if (f.child) stack.push(f.child);
              }
            }
            return null;
          };
    """

    def store_play(self, track_id: str) -> str:
        """Ask TIDAL's own play queue to play the track now. Returns ``'ok'``,
        ``'no-store'``, ``'no-queue'``, ``'not-loaded'`` (TIDAL does not know the
        track yet: open its page first) or an error text."""
        js = self._page_js("store_play", track_id, self._FIND_STORE + """
          const st = findStore();
          if (!st) return 'no-store';
          const s = st.getState() || {};
          if (!s.playQueue) return 'no-queue';
          // TIDAL only plays tracks it has loaded: an id it does not know yet makes
          // it move on to its own next track first. Its page loads it.
          const items = s.content && s.content.mediaItems;
          if (items && typeof items === 'object' && !items[ID] && !items[Number(ID)]) return 'not-loaded';
          try {
            st.dispatch({type: 'playQueue/ADD_NOW', payload: {context: {type: 'UNKNOWN'}, mediaItemIds: [Number(ID)], fromIndex: 0}});
          } catch (e) { return 'error: ' + e; }
          return 'ok';
        """)
        return str(self.evaluate(js) or "")

    # Reads TIDAL's play queue: {cur, next} track ids, or null when its shape is unknown.
    _QUEUE_IDS = """
          const queueIds = (st) => {
            const q = (st.getState() || {}).playQueue;
            if (!q) return null;
            const els = Array.isArray(q.elements) ? q.elements : (Array.isArray(q.items) ? q.items : null);
            const i = typeof q.currentIndex === 'number' ? q.currentIndex : (typeof q.index === 'number' ? q.index : null);
            if (!els || i === null) return null;
            const idOf = e => {
              if (!e) return null;
              const v = e.mediaItemId ?? e.id ?? (e.mediaItem && e.mediaItem.id) ?? (e.item && e.item.id);
              return v === undefined || v === null ? null : String(v);
            };
            return {cur: idOf(els[i]), next: idOf(els[i + 1])};
          };
          const footerId = () => {
            const f = document.querySelector(S.footer) || document;
            const t = document.querySelector(S.footer_title);
            const a = (t && t.closest('a')) || f.querySelector('a[href*="/track/"]');
            const m = a && (a.getAttribute('href') || '').match(/\\/track\\/(\\d+)/);
            return m ? m[1] : null;
          };
    """

    def store_queue_next(self, track_id: str) -> str:
        """Put the track right after the current one in TIDAL's own queue, so TIDAL
        moves to it by itself (gapless). Returns ``'ok'`` only when the queue then
        shows it as next; never dispatches when the queue's shape is not understood."""
        js = self._page_js("store_queue", track_id, self._FIND_STORE + self._QUEUE_IDS + """
          const st = findStore();
          if (!st) return 'no-store';
          const before = queueIds(st);
          if (!before || !before.cur) return 'unreadable';
          const shown = footerId();
          if (shown && shown !== before.cur) return 'unreadable';
          if (before.next === ID) return 'ok';
          try {
            st.dispatch({type: 'playQueue/ADD_NEXT', payload: {context: {type: 'UNKNOWN'}, mediaItemIds: [Number(ID)]}});
          } catch (e) { return 'error: ' + e; }
          return (async () => {
            for (let i = 0; i < 10; i++) {
              const after = queueIds(st);
              if (after && after.next === ID) return 'ok';
              await new Promise(r => setTimeout(r, 200));
            }
            return 'not-next';
          })();
        """)
        return str(self.evaluate(js, timeout=15.0) or "")

    def store_next_id(self) -> Optional[str]:
        """The track TIDAL's queue will play next, when it can be read."""
        js = self._page_js("store_next", None, self._FIND_STORE + self._QUEUE_IDS + """
          const st = findStore();
          const q = st ? queueIds(st) : null;
          return q ? q.next : null;
        """)
        res = self.evaluate(js)
        return str(res) if res else None

    def press(self, control: str) -> bool:
        if control not in ("play", "pause", "next", "previous"):
            raise ValueError(control)
        js = f"""
        (() => {{ /*ts:press*/
          const S = {self._js_sel()};
          const label = {json.dumps(control.capitalize())};
          const b = document.querySelector(S.controls + ' ' + S[{json.dumps(control)}])
                 || document.querySelector(S.controls + ' button[aria-label="' + label + '"]')
                 || document.querySelector('button[aria-label="' + label + '"]');
          if (!b) return false;
          b.click();
          return true;
        }})()
        """
        return bool(self.evaluate(js))

    def prepare(self, track_id: str, timeout: float = 15.0) -> bool:
        """Navigate to the track page ahead of time so the hand-off is instant."""
        try:
            status = self.navigate_to_track(track_id, return_status=True)
            if status not in ("pushed", "already"):
                self.log(f"could not navigate TIDAL to track {track_id}")
                return False
            if status == "already" and self.rows_ready(track_id) in (True, "other"):
                return True  # prepared earlier: do not wait again at hand-off time
        except CdpError as e:
            self.log(f"navigate failed: {e}")
            return False
        return self.wait_for_rows(track_id, timeout)

    def _verify(self, track_id: str, title: Optional[str], timeout: float, method: str) -> PlayOutcome:
        """Wait for the footer to show the track (by id, or by title when the
        footer carries no track link)."""
        from ..matching import normalize

        deadline = self._clock() + timeout
        observed: Optional[str] = None
        while self._clock() < deadline:
            try:
                np = self.now_playing()
            except CdpError:
                np = None
            if np is not None and np.playing is not False:
                observed = np.track_id or (f"title:{np.title}" if np.title else None)
                if np.track_id == track_id:
                    return PlayOutcome(True, method, np.track_id)
                if np.track_id is None and title and np.title and normalize(np.title) == normalize(title):
                    return PlayOutcome(True, method, None, "matched by title")
            self._sleep(0.4)
        return PlayOutcome(False, method, observed, "footer never showed the requested track")

    def _try_store(self, track_id: str, title: Optional[str], verify_timeout: float) -> Optional[PlayOutcome]:
        if self._store_failures >= 3:
            return None
        res = self._store_play_loaded(track_id)
        if res == "not-loaded":
            return None                           # not a failure of the queue: click the page's button instead
        if res != "ok":
            self.log(f"play queue: {res}")
            self._store_failures = 3 if res in ("no-store", "no-queue") else self._store_failures + 1
            return None
        out = self._verify(track_id, title, verify_timeout, "queue")
        self._store_failures = 0 if out.ok else self._store_failures + 1
        self._store_works = out.ok
        return out

    def _store_play_loaded(self, track_id: str, timeout: float = 4.0) -> str:
        """``store_play``, opening the track's page first when TIDAL has not
        loaded the track yet (otherwise it skips to its own next track)."""
        try:
            res = self.store_play(track_id)
            if res != "not-loaded":
                return res
            self.navigate_to_track(track_id)
            deadline = self._clock() + timeout
            while self._clock() < deadline:
                self._sleep(0.25)
                res = self.store_play(track_id)
                if res != "not-loaded":
                    return res
            return "not-loaded"
        except CdpError as e:
            return f"error: {e}"

    def play_track(self, track_id: str, verify_timeout: float = 8.0, prepare_timeout: float = 15.0,
                   title: Optional[str] = None) -> PlayOutcome:
        """Make the app play ``track_id`` and confirm it from the footer.

        Clicks the track's play button on its page; if that is not possible or
        does not take, asks TIDAL's play queue directly. Whichever worked last
        is tried first next time.
        """
        track_id = str(track_id)
        if self._store_works:
            out = self._try_store(track_id, title, verify_timeout)
            if out is not None and out.ok:
                return out
        problems = []
        observed: Optional[str] = None
        tried = ""
        if self.prepare(track_id, prepare_timeout):
            try:
                method = self.click_play_for_track(track_id, title)
            except CdpError as e:
                method = ""
                problems.append(f"click failed: {e}")
            if method == "not-this-track":
                problems.append("TIDAL showed another page, not the track's (its play button was left alone)")
                method = ""
            elif method:
                out = self._verify(track_id, title, verify_timeout, method)
                if out.ok:
                    return out
                observed, tried = out.observed_id, method
                problems.append(f"{method}: {out.detail}")
            elif not problems:
                problems.append("no play button found on the track page")
        else:
            problems.append("track page did not load")
        if not self._store_works:
            out = self._try_store(track_id, title, verify_timeout)
            if out is not None:
                if out.ok:
                    return out
                observed, tried = out.observed_id or observed, tried or "queue"
                problems.append(f"queue: {out.detail}")
        return PlayOutcome(False, tried, observed, "; ".join(problems))

    # -- TidaLuna (optional client mod) ---------------------------------------
    def has_luna(self) -> bool:
        """True when the page runs the TidaLuna mod, which exposes a real player API."""
        try:
            return bool(self.evaluate("typeof window.luna !== 'undefined' && !!window.luna.lib && !!window.luna.lib.PlayState"))
        except CdpError:
            return False

    def luna_queue_next(self, track_id: str) -> bool:
        js = f"(() => {{ luna.lib.PlayState.playNext([{int(track_id)}]); return 'ok'; }})()"
        return self.evaluate(js) == "ok"

    def luna_play_now(self, track_id: str) -> bool:
        js = (f"luna.lib.MediaItem.fromId({int(track_id)}).then(m => {{ if (!m) throw new Error('no item'); "
              f"m.play(); return 'ok'; }})")
        return self.evaluate(js, timeout=15.0) == "ok"

    def luna_state(self) -> dict:
        js = """
        (() => {
          const ps = luna.lib.PlayState;
          const q = ps.playQueue || {};
          const cur = (q.elements || [])[q.currentIndex] || null;
          return {playing: !!ps.playing, state: ps.state || null,
                  currentIndex: q.currentIndex ?? null, queueLength: (q.elements || []).length,
                  currentId: cur ? String(cur.mediaItemId ?? cur.id ?? '') : null};
        })()
        """
        data = self.evaluate(js)
        return data if isinstance(data, dict) else {}

    # -- diagnostics ----------------------------------------------------------
    def watch_actions(self) -> str:
        """Start recording what TIDAL's store does (action types and the shape of
        their payloads), to learn how the app starts a song in its current version."""
        js = "(() => { /*ts:watch*/" + self._FIND_STORE + """
          const st = findStore();
          if (!st) return 'no-store';
          window.__tsActions = [];
          if (!st.__tsWrapped) {
            const orig = st.dispatch.bind(st);
            st.dispatch = (a) => {
              try {
                if (a && typeof a === 'object' && window.__tsActions) {
                  let p = '';
                  try { p = JSON.stringify(a.payload, (k, v) => (typeof v === 'string' && v.length > 80) ? v.slice(0, 80) : v); } catch (e) { p = '?'; }
                  window.__tsActions.push({t: Date.now(), type: String(a.type), payload: (p || '').slice(0, 600)});
                  if (window.__tsActions.length > 400) window.__tsActions.shift();
                }
              } catch (e) {}
              return orig(a);
            };
            st.__tsWrapped = true;
          }
          return 'ok';
        })()"""
        return str(self.evaluate(js) or "")

    def recorded_actions(self) -> list:
        data = self.evaluate("(() => { /*ts:watched*/ return window.__tsActions || []; })()")
        return data if isinstance(data, list) else []


    def inspect(self, track_id: Optional[str] = None) -> dict:
        """Describe what the player DOM looks like right now (for debugging).

        With ``track_id`` it also reports how the play logic sees that track's
        page: the matching row, the play controls it would consider, the store.
        """
        js = self._page_js("inspect", track_id, self._FIND_STORE + """
          const attrs = el => Array.from(el.querySelectorAll('[data-test]')).map(e => e.getAttribute('data-test'));
          const uniq = a => Array.from(new Set(a));
          const clip = (t, n) => (t || '').replace(/<svg[\\s\\S]*?<\\/svg>/g, '<svg/>').replace(/\\s+/g, ' ').slice(0, n);
          const describe = el => ({
            tag: el.tagName.toLowerCase(), dataTest: el.getAttribute('data-test'), aria: el.getAttribute('aria-label'),
            text: clip(el.textContent, 40), inFooter: inChrome(el), inRow: !!el.closest(S.row), cls: clip(el.className && el.className.baseVal === undefined ? el.className : '', 60),
          });
          const footer = document.querySelector(S.footer);
          const rs = rows();
          const row = rowFor();
          const h = hero();
          const main = document.querySelector('main') || document.body;
          let store = null;
          try {
            const st = findStore();
            if (st) {
              const s = st.getState() || {};
              store = {keys: Object.keys(s).slice(0, 60), playQueue: s.playQueue ? Object.keys(s.playQueue).slice(0, 30) : null};
            }
          } catch (e) { store = {error: String(e)}; }
          const playish = Array.from(document.querySelectorAll('button, [role=button], [data-test]'))
            .filter(e => /play/i.test((e.getAttribute('data-test') || '') + ' ' + (e.getAttribute('aria-label') || '') + ' ' + (e.tagName === 'BUTTON' ? e.textContent : '')))
            .slice(0, 40).map(describe);
          return {
            path: location.pathname,
            title: document.title,
            onTrackPage: landed(),
            counts: Object.fromEntries(Object.entries(S).map(([k, v]) => [k, document.querySelectorAll(v).length])),
            rowCount: rs.length,
            trackRowFound: !!row,
            trackRowHtml: row ? clip(row.outerHTML, 1500) : null,
            firstRowHtml: !row && rs.length ? clip(rs[0].outerHTML, 1500) : null,
            heroButton: h ? describe(h) : null,
            playControls: playish,
            mainDataTest: uniq(attrs(main)).slice(0, 120),
            footerDataTest: footer ? uniq(attrs(footer)) : null,
            footerText: footer ? (footer.innerText || '').slice(0, 300) : null,
            buttonLabels: uniq(Array.from(document.querySelectorAll('button[aria-label]')).map(b => b.getAttribute('aria-label'))).slice(0, 80),
            reactRoot: [document.getElementById('wimp'), document.getElementById('root'), ...document.querySelectorAll('body > div')]
              .filter(Boolean).map(el => (el.id || el.className || el.tagName) + ':' + Object.keys(el).filter(k => k.startsWith('__react')).map(k => k.split('$')[0]).join(',')).slice(0, 8),
            store,
            luna: typeof window.luna !== 'undefined',
          };
        """)
        data = self.evaluate(js, timeout=20.0)
        return data if isinstance(data, dict) else {"raw": data}
