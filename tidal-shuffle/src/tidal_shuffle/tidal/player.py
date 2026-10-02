"""Make the TIDAL desktop app play a track, using the best method available."""

from __future__ import annotations

import subprocess
import time
from typing import Callable, Optional

from ..config import PlayerConfig
from ..models import TidalTrack
from .cdp import CdpError, PlayOutcome, TidalCdp
from .luna import LunaApi


class TidalPlayer:
    """Facade over the available ways of making TIDAL play a track.

    Methods, in order of preference:

    * ``luna-api``      – TidaLuna API plugin on localhost: real queue control (gapless)
    * ``cdp-luna``      – TidaLuna present, driven through the DevTools Protocol
    * ``cdp``           – stock app via DevTools Protocol: navigate + click play + verify
    * ``open-url``      – ``open tidal://track/<id>``: only navigates the app
    * ``open-url-play`` – same, with ``?play=true`` appended (unverified upstream)
    """

    def __init__(self, config: PlayerConfig, cdp: Optional[TidalCdp] = None, luna: Optional[LunaApi] = None,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 log: Optional[Callable[[str], None]] = None):
        self.config = config
        self.cdp = cdp
        self.luna = luna
        self._run = run
        self._sleep = sleep
        self._clock = clock
        self.log = log or (lambda m: None)
        self._cdp_ok: Optional[bool] = None
        self._luna_ok: Optional[bool] = None
        self._cdp_luna: Optional[bool] = None

    # ------------------------------------------------------------------
    def cdp_available(self, refresh: bool = False) -> bool:
        if self.cdp is None or self.config.play_strategy in ("open-url", "open-url-play"):
            return False
        if self._cdp_ok is None or refresh:
            self._cdp_ok = self.cdp.alive()
        return bool(self._cdp_ok)

    def luna_available(self, refresh: bool = False) -> bool:
        if self.luna is None or self.config.play_strategy not in ("auto", "luna"):
            return False
        if self._luna_ok is None or refresh:
            self._luna_ok = self.luna.alive()
        return bool(self._luna_ok)

    def cdp_luna_available(self) -> bool:
        if not self.cdp_available():
            return False
        if self._cdp_luna is None:
            self._cdp_luna = self.cdp.has_luna()
        return bool(self._cdp_luna)

    def supports_queue(self) -> bool:
        """Can we hand TIDAL a "play this next" instead of a hard cut-over?"""
        return self.luna_available() or self.cdp_luna_available()

    def queue_next(self, track: TidalTrack) -> bool:
        if self.luna_available():
            if self.luna.play_next(track.id):
                return True
            self._luna_ok = None
        if self.cdp_luna_available():
            try:
                return self.cdp.luna_queue_next(track.id)
            except CdpError as e:
                self.log(f"luna queue failed: {e}")
        return False

    def ensure_ready(self, allow_relaunch: bool = True) -> str:
        """Prepare the preferred method at startup; returns the method name.

        ``allow_relaunch=False`` never quits a running TIDAL (one-shot commands
        must not stop the music they are about to act on).
        """
        strategy = self.config.play_strategy
        if strategy in ("auto", "luna") and self.luna is not None and self.luna.alive():
            self._luna_ok = True
            if strategy == "luna" or self.cdp is None or not self.cdp.alive():
                return "luna-api"  # never relaunch a TIDAL that already answers through TidaLuna
            self._cdp_ok = True
            return "luna-api"
        if strategy == "luna":
            raise RuntimeError("TidaLuna API plugin not reachable (is TIDAL running with TidaLuna and its API plugin?)")
        if strategy in ("auto", "cdp") and self.cdp is not None:
            if self.cdp.alive():
                self._cdp_ok = True
                return "luna-api" if self._luna_ok else ("cdp-luna" if self.cdp_luna_available() else "cdp")
            if self.config.auto_relaunch:
                if self.cdp.launch(relaunch_if_running=allow_relaunch):
                    self._cdp_ok = True
                    self._luna_ok = None
                    return "luna-api" if self.luna_available() else ("cdp-luna" if self.cdp_luna_available() else "cdp")
                self.log("could not start TIDAL with the debug port")
            self._cdp_ok = False
            if self._luna_ok:
                return "luna-api"
            if strategy == "cdp":
                raise RuntimeError(
                    "TIDAL is not reachable over CDP. Quit TIDAL and run: "
                    f"open -a {self.config.tidal_app} --args --remote-debugging-port={self.config.cdp_port} "
                    "--remote-debugging-address=127.0.0.1")
        return "open-url-play" if strategy == "open-url-play" else "open-url"

    def method(self) -> str:
        if self.luna_available():
            return "luna-api"
        if self.cdp_available():
            return "cdp-luna" if self.cdp_luna_available() else "cdp"
        return "open-url-play" if self.config.play_strategy == "open-url-play" else "open-url"

    # ------------------------------------------------------------------
    def prepare(self, track: TidalTrack) -> bool:
        """Navigate to the track's page early (CDP only) so play is instant later."""
        if not self.cdp_available():
            return False
        try:
            window = self.config.prepare_seconds - self.config.handoff_seconds - 1.0
            return bool(self.cdp.prepare(track.id, timeout=min(15.0, max(2.0, window))))
        except CdpError as e:
            self.log(f"prepare failed: {e}")
            self._cdp_ok = None
            return False

    def _open(self, url: str) -> bool:
        try:
            r = self._run(["open", "-g", url], capture_output=True, text=True, timeout=10)
        except Exception as e:
            self.log(f"open failed: {e}")
            return False
        return r.returncode == 0

    def _verify_luna(self, track: TidalTrack, method: str) -> PlayOutcome:
        deadline = self._clock() + self.config.verify_seconds
        observed = None
        while self._clock() < deadline:
            try:
                if method == "luna-api":
                    observed = self.luna.current_track_id()
                else:
                    st = self.cdp.luna_state()
                    observed = st.get("currentId") or None
                    if observed is None:
                        np = self.cdp.now_playing()
                        observed = np.track_id if np else None
            except Exception:
                observed = None
            if observed == track.id:
                return PlayOutcome(True, method, observed)
            self._sleep(0.4)
        return PlayOutcome(False, method, observed, "TIDAL did not switch to the requested track")

    def play(self, track: TidalTrack) -> PlayOutcome:
        method = self.method()
        if method == "luna-api":
            if self.luna.play_now(track.id):
                out = self._verify_luna(track, method)
                if out.ok:
                    return out
                self.log(f"Luna play failed for {track.label()}: {out.detail}")
            else:
                self.log("Luna API did not accept the play request")
            self._luna_ok = None
            method = "cdp-luna" if self.cdp_luna_available() else ("cdp" if self.cdp_available() else "open-url")
        if method == "cdp-luna":
            try:
                if self.cdp.luna_play_now(track.id):
                    out = self._verify_luna(track, method)
                    if out.ok:
                        return out
                    self.log(f"Luna (CDP) play failed for {track.label()}: {out.detail}")
            except CdpError as e:
                self.log(f"Luna (CDP) play errored: {e}")
            method = "cdp"
        if method == "cdp":
            try:
                out = self.cdp.play_track(track.id, verify_timeout=self.config.verify_seconds)
            except CdpError as e:
                out = PlayOutcome(False, "cdp", None, str(e))
                self._cdp_ok = None
            out.method = f"cdp/{out.method}" if out.method and not out.method.startswith("cdp") else (out.method or "cdp")
            if out.ok:
                return out
            self.log(f"CDP play failed for {track.label()}: {out.detail}")
            # CDP is reachable but this track could not be started: let the caller try a
            # backup instead of navigating TIDAL around with deep links.
            return out
        url = track.deep_link + ("?play=true" if method == "open-url-play" or self.config.play_strategy == "open-url-play" else "")
        ok = self._open(url)
        return PlayOutcome(False, method, None,
                           "opened the track in TIDAL; playback must be confirmed by now-playing" if ok else "open failed")

    def press(self, control: str) -> bool:
        if self.cdp_available():
            try:
                return self.cdp.press(control)
            except CdpError as e:
                self.log(f"press {control} failed: {e}")
        return False
