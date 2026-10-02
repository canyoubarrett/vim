"""Spotify desktop app as a recommendation source (AppleScript, no API key).

How it works: Spotify is launched hidden and muted, the seed song's *Song
Radio* is started (``play track X in context spotify:station:track:X``), and
we skip through the station reading each track that comes up. Spotify is then
paused and its volume restored. The whole harvest runs inside one osascript
process and typically takes 0.5 s per song.

Needs: Spotify installed and logged in on this Mac, and Automation permission
for the terminal that runs Tidal Shuffle (macOS asks the first time).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from ..activity import busy
from ..applescript import AppleScriptError, ScriptRunner, quote
from ..config import SpotifyAppConfig
from ..models import Candidate, Seed
from .base import tag
from .odesli import OdesliMapper

SPOTIFY_BUNDLE = "com.spotify.client"
US = "\x1f"


class SpotifyAppError(RuntimeError):
    pass


GUARD = f'if not (application id "{SPOTIFY_BUNDLE}" is running) then return "not-running"\n'

STATE_SCRIPT = GUARD + """
with timeout of 5 seconds
    tell application id "%(bid)s"
        set ps to player state as string
        set vol to sound volume
        set tid to ""
        try
            set tid to id of current track
        end try
    end tell
end timeout
set AppleScript's text item delimiters to ASCII character 31
return {ps, vol, tid} as text
""" % {"bid": SPOTIFY_BUNDLE}

READY_SCRIPT = """
with timeout of 2 seconds
    tell application id "%(bid)s" to return player state as string
end timeout
""" % {"bid": SPOTIFY_BUNDLE}

HIDE_SCRIPT = 'tell application "System Events" to set visible of process "Spotify" to false'

HARVEST_SCRIPT = """
on harvest(seedURI, stationURI, wanted, stepTimeout, adTimeout, muteIt, useStation)
    set US to ASCII character 31
    set outLines to {}
    set prevVol to -1
    tell application id "%(bid)s"
        if muteIt then
            set prevVol to sound volume
            set sound volume to 0
        end if
        try
            set shuffling to false
            set repeating to false
        end try
        with timeout of 45 seconds
            if useStation then
                play track seedURI in context stationURI
            else
                play track seedURI
            end if
        end timeout
    end tell
    delay 1.0
    tell application id "%(bid)s"
        set prevId to seedURI
        try
            set prevId to id of current track
        end try
        set startedAt to current date
        repeat while (count of outLines) < wanted
            if ((current date) - startedAt) > %(max_seconds)d then
                set end of outLines to "ERR" & US & "time-budget"
                exit repeat
            end if
            next track
            set t0 to current date
            set curId to prevId
            repeat
                delay 0.1
                try
                    set curId to id of current track
                end try
                if curId is not prevId then exit repeat
                if ((current date) - t0) >= stepTimeout then exit repeat
            end repeat
            if curId is prevId then
                set end of outLines to "ERR" & US & "no-advance"
                exit repeat
            end if
            if curId starts with "spotify:ad:" then
                set a0 to current date
                repeat
                    delay 0.5
                    set curId to id of current track
                    if curId does not start with "spotify:ad:" then exit repeat
                    if ((current date) - a0) >= adTimeout then exit repeat
                end repeat
                if curId starts with "spotify:ad:" then
                    set end of outLines to "ERR" & US & "ad-timeout"
                    exit repeat
                end if
            end if
            set n to name of current track
            if n is "" then
                delay 0.2
                set n to name of current track
            end if
            set rec to curId & US & n & US & (artist of current track) & US & (album of current track) & US & (duration of current track) & US & (popularity of current track) & US & (album artist of current track)
            set end of outLines to rec
            set prevId to curId
        end repeat
        pause
        if prevVol >= 0 then set sound volume to prevVol
    end tell
    set AppleScript's text item delimiters to linefeed
    return outLines as text
end harvest

return harvest(%(seed)s, %(station)s, %(wanted)d, %(step_timeout)s, %(ad_timeout)s, %(mute)s, %(use_station)s)
"""


def _parse_duration_ms(value: str) -> Optional[float]:
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return ms / 1000.0 if ms > 3000 else ms


class SpotifyAppSource:
    name = "spotify-app"

    def __init__(self, cfg: SpotifyAppConfig, runner: Optional[ScriptRunner], log: Optional[Callable[[str], None]] = None,
                 catalog=None, mapper: Optional[OdesliMapper] = None, api_lookup: Optional[Callable[[Seed], Optional[str]]] = None,
                 app_paths: Sequence[str] = ("/Applications/Spotify.app", "~/Applications/Spotify.app"),
                 run: Optional[Callable[..., object]] = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.runner = runner
        self.log = log or (lambda m: None)
        self.catalog = catalog
        self.mapper = mapper
        self.api_lookup = api_lookup
        self.app_paths = [Path(p).expanduser() for p in app_paths]
        self._run = run
        self._sleep = sleep
        self._clock = clock
        self._dead: Optional[str] = None
        self._station_works: Optional[bool] = None
        self._cache: dict[str, list[Candidate]] = {}

    # -- availability ---------------------------------------------------------
    def installed(self) -> bool:
        return any(p.exists() for p in self.app_paths)

    def available(self) -> tuple[bool, str]:
        if not self.cfg.enabled:
            return False, "disabled in config (spotify.app.enabled)"
        if self.runner is None:
            return False, "osascript not available (macOS only)"
        if not self.installed():
            return False, "Spotify app not found in /Applications"
        if self._dead:
            return False, self._dead
        return True, ""

    # -- AppleScript plumbing -------------------------------------------------
    def _osa(self, script: str, timeout: float = 15.0) -> str:
        try:
            return self.runner.run(script, timeout=timeout)
        except AppleScriptError as e:
            msg = str(e)
            if "-1743" in msg:
                self._dead = ("macOS denied Automation access to Spotify. Allow it in System Settings → "
                              "Privacy & Security → Automation for your terminal, then try again")
                raise SpotifyAppError(self._dead) from None
            if "-1712" in msg:
                raise SpotifyAppError("Spotify did not answer in time") from None
            raise SpotifyAppError(msg) from None

    def state(self) -> dict:
        out = self._osa(STATE_SCRIPT, timeout=8.0)
        if out.strip() == "not-running":
            return {"running": False}
        parts = out.split(US)
        if len(parts) < 3:
            return {"running": True, "state": "unknown", "volume": None, "track": ""}
        try:
            vol = int(float(parts[1]))
        except ValueError:
            vol = None
        return {"running": True, "state": parts[0].strip(), "volume": vol, "track": parts[2].strip()}

    def _launch_hidden(self) -> None:
        import subprocess

        runner = self._run or subprocess.run
        runner(["open", "-gj", "-b", SPOTIFY_BUNDLE], capture_output=True, text=True, timeout=15)
        deadline = self._clock() + self.cfg.launch_timeout
        while self._clock() < deadline:
            try:
                self._osa(READY_SCRIPT, timeout=4.0)
                break
            except SpotifyAppError:
                self._sleep(0.5)
        else:
            raise SpotifyAppError("Spotify did not start in time")
        self._sleep(1.0)
        self._hide()

    def _hide(self) -> None:
        if not self.cfg.hide_window:
            return
        try:
            self.runner.run(HIDE_SCRIPT, timeout=5.0)
        except AppleScriptError:
            pass  # needs Accessibility permission; purely cosmetic

    def _quit(self) -> None:
        try:
            self.runner.run(f'tell application id "{SPOTIFY_BUNDLE}" to quit', timeout=10.0)
        except AppleScriptError:
            pass

    def ensure_running(self) -> dict:
        st = self.state()
        if not st.get("running"):
            self.log("launching Spotify (hidden) for the harvest")
            self._launch_hidden()
            st = self.state()
        return st

    # -- seed mapping ---------------------------------------------------------
    def spotify_uri_for(self, seed: Seed) -> Optional[str]:
        if seed.spotify_id:
            return f"spotify:track:{seed.spotify_id}"
        if self.api_lookup is not None:
            try:
                sid = self.api_lookup(seed)
            except Exception as e:
                self.log(f"Spotify API lookup failed: {e}")
                sid = None
            if sid:
                seed.spotify_id = sid
                return f"spotify:track:{sid}"
        if self.mapper is not None:
            if not seed.tidal_id and self.catalog is not None:
                try:
                    self.catalog.resolve_seed(seed)
                except Exception as e:
                    self.log(f"could not resolve seed on TIDAL: {e}")
            if seed.tidal_id:
                sid = self.mapper.spotify_id_for_tidal(seed.tidal_id)
                if sid:
                    seed.spotify_id = sid
                    return f"spotify:track:{sid}"
        return None

    # -- harvest --------------------------------------------------------------
    def _harvest_script(self, seed_uri: str, wanted: int, use_station: bool) -> str:
        station = "spotify:station:track:" + seed_uri.rsplit(":", 1)[-1]
        return HARVEST_SCRIPT % {
            "bid": SPOTIFY_BUNDLE, "seed": quote(seed_uri), "station": quote(station), "wanted": int(wanted),
            "step_timeout": "2.0", "ad_timeout": "45", "mute": "true" if self.cfg.mute else "false",
            "use_station": "true" if use_station else "false", "max_seconds": int(self.cfg.max_seconds),
        }

    def _parse(self, out: str, seed_uri: str) -> tuple[list[Candidate], Optional[str]]:
        cands: list[Candidate] = []
        error: Optional[str] = None
        for line in out.splitlines():
            parts = line.split(US)
            if not parts or not parts[0]:
                continue
            if parts[0] == "ERR":
                error = parts[1] if len(parts) > 1 else "error"
                break
            if len(parts) < 4 or parts[0] == seed_uri or not parts[1].strip():
                continue
            uri, name, artist, album = parts[0], parts[1].strip(), parts[2].strip(), parts[3].strip()
            if not artist:
                continue
            duration = _parse_duration_ms(parts[4]) if len(parts) > 4 else None
            try:
                popularity = int(float(parts[5])) if len(parts) > 5 and parts[5] else None
            except ValueError:
                popularity = None
            cands.append(Candidate(title=name, artist=artist, album=album or None, duration=duration,
                                   popularity=popularity, spotify_id=uri.rsplit(":", 1)[-1],
                                   extra={"album_artist": parts[6].strip() if len(parts) > 6 else None}))
        return cands, error

    def harvest(self, seed_uri: str, wanted: int) -> list[Candidate]:
        """Run the Spotify harvest for a ``spotify:track:`` URI."""
        if seed_uri in self._cache:
            return list(self._cache[seed_uri])
        st = self.ensure_running()
        if st.get("state") == "playing" and st.get("track") and not st["track"].startswith("spotify:ad:"):
            raise SpotifyAppError("Spotify is already playing something; not interrupting it")
        methods = ["station", "autoplay"] if self.cfg.seed_method == "auto" else [self.cfg.seed_method]
        if self._station_works is False and "autoplay" in methods:
            methods = ["autoplay"]
        collected: list[Candidate] = []
        started = self._clock()
        with busy("spotify-harvest", seconds=self.cfg.max_seconds + 10):
            try:
                for method in methods:
                    script = self._harvest_script(seed_uri, wanted, use_station=(method == "station"))
                    out = self._osa(script, timeout=self.cfg.max_seconds + 60)
                    cands, error = self._parse(out, seed_uri)
                    if error:
                        self.log(f"Spotify harvest ({method}) stopped early: {error} after {len(cands)} songs")
                    if cands:
                        collected = cands
                        if method == "station":
                            self._station_works = True
                        break
                    if method == "station" and error == "no-advance":
                        self._station_works = False
                        self.log("song radio did not start; falling back to autoplay")
            finally:
                self._hide()
                if self.cfg.quit_after:
                    self._quit()
        self.log(f"Spotify harvest: {len(collected)} songs in {self._clock() - started:.1f}s")
        self._cache[seed_uri] = list(collected)
        return collected

    # -- Source protocol ------------------------------------------------------
    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        seed = seeds[0]
        uri = self.spotify_uri_for(seed)
        if not uri:
            self.log(f"could not map {seed.label()} to a Spotify track")
            return []
        try:
            cands = self.harvest(uri, max(limit, self.cfg.harvest))
        except SpotifyAppError as e:
            self.log(f"Spotify app harvest failed: {e}")
            return []
        n = max(1, len(cands))
        out = []
        for i, c in enumerate(cands):
            c = Candidate(**{**c.__dict__})
            c.score = 1.0 - 0.5 * (i / n)
            out.append(c)
        return tag(out[:limit], self.name)
