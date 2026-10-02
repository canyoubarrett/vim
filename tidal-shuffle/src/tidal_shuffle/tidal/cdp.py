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
            raw = self._ws.recv()
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
        for attempt in range(2):
            try:
                return self._connection().evaluate(js, timeout=timeout)
            except CdpError:
                raise
            except Exception as e:  # socket dropped, target gone, ...
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
    def navigate_to_track(self, track_id: str) -> bool:
        """Route the single-page app to ``/track/<id>`` without reloading."""
        js = f"""
        (() => {{
          const target = '/track/{int(track_id)}';
          if (location.pathname === target) return 'already';
          history.pushState({{}}, '', target);
          window.dispatchEvent(new PopStateEvent('popstate', {{state: {{}}}}));
          return location.pathname === target ? 'pushed' : 'failed';
        }})()
        """
        return self.evaluate(js) in ("pushed", "already")

    def rows_ready(self, track_id: Optional[str] = None):
        """``True`` when the track's row is rendered, ``"other"`` when rows are
        rendered but none mentions the track, ``False`` when nothing is there."""
        js = f"""
        (() => {{
          const S = {self._js_sel()};
          const rows = Array.from(document.querySelectorAll(S.row));
          if (!rows.length) return false;
          const want = {json.dumps('/track/' + str(track_id)) if track_id else 'null'};
          if (want && !rows.some(r => r.innerHTML.includes(want))) return 'other';
          return rows.some(r => r.querySelector(S.row_play)) || !!document.querySelector(S.hero_play);
        }})()
        """
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

    def click_play_for_track(self, track_id: str) -> str:
        """Click the play button for the track row; returns the method used."""
        js = f"""
        (() => {{
          const S = {self._js_sel()};
          const want = '/track/{int(track_id)}';
          const rows = Array.from(document.querySelectorAll(S.row));
          let row = rows.find(r => r.innerHTML.includes(want + '"') || r.innerHTML.includes(want + '?') || r.innerHTML.includes(want + '/'))
                 || rows.find(r => r.innerHTML.includes(want));
          let method = 'row';
          if (!row && rows.length && location.pathname === want) {{ row = rows[0]; method = 'first-row'; }}
          if (row) {{
            const b = row.querySelector(S.row_play);
            if (b) {{ b.click(); return method; }}
            const dbl = new MouseEvent('dblclick', {{bubbles: true, cancelable: true, view: window}});
            row.dispatchEvent(dbl);
            return 'row-dblclick';
          }}
          const hero = document.querySelector(S.hero_play);
          if (hero && location.pathname === want) {{ hero.click(); return 'hero'; }}
          return '';
        }})()
        """
        return str(self.evaluate(js) or "")

    def press(self, control: str) -> bool:
        if control not in ("play", "pause", "next", "previous"):
            raise ValueError(control)
        js = f"""
        (() => {{
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
            if not self.navigate_to_track(track_id):
                self.log(f"could not navigate TIDAL to track {track_id}")
                return False
        except CdpError as e:
            self.log(f"navigate failed: {e}")
            return False
        return self.wait_for_rows(track_id, timeout)

    def play_track(self, track_id: str, verify_timeout: float = 8.0, prepare_timeout: float = 15.0) -> PlayOutcome:
        """Make the app play ``track_id`` and confirm it from the footer."""
        track_id = str(track_id)
        if not self.prepare(track_id, prepare_timeout):
            return PlayOutcome(False, "", None, "track page did not load")
        try:
            method = self.click_play_for_track(track_id)
        except CdpError as e:
            return PlayOutcome(False, "", None, f"click failed: {e}")
        if not method:
            return PlayOutcome(False, "", None, "no play button found on the track page")
        deadline = self._clock() + verify_timeout
        observed: Optional[str] = None
        while self._clock() < deadline:
            try:
                np = self.now_playing()
            except CdpError:
                np = None
            if np is not None:
                observed = np.track_id
                if np.track_id == track_id and np.playing is not False:
                    return PlayOutcome(True, method, observed)
            self._sleep(0.4)
        return PlayOutcome(False, method, observed, "footer never showed the requested track")

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
    def inspect(self) -> dict:
        """Describe what the player DOM looks like right now (for debugging)."""
        js = f"""
        (() => {{
          const S = {self._js_sel()};
          const attrs = el => Array.from(el.querySelectorAll('[data-test]')).map(e => e.getAttribute('data-test'));
          const uniq = a => Array.from(new Set(a));
          const footer = document.querySelector(S.footer);
          const row = document.querySelector(S.row);
          const labels = Array.from(document.querySelectorAll('button[aria-label]')).map(b => b.getAttribute('aria-label'));
          return {{
            path: location.pathname,
            title: document.title,
            counts: Object.fromEntries(Object.entries(S).map(([k, v]) => [k, document.querySelectorAll(v).length])),
            footerDataTest: footer ? uniq(attrs(footer)) : null,
            footerText: footer ? (footer.innerText || '').slice(0, 300) : null,
            firstRowDataTest: row ? uniq(attrs(row)) : null,
            buttonLabels: uniq(labels).slice(0, 60),
            luna: typeof window.luna !== 'undefined',
          }};
        }})()
        """
        data = self.evaluate(js)
        return data if isinstance(data, dict) else {"raw": data}
