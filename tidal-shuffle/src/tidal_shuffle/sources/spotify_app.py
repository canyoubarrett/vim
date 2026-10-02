"""Spotify desktop app as a recommendation source (AppleScript + Accessibility, no API key).

How a harvest works:

1. Make sure Spotify is running (launched hidden if needed) and is not
   playing something of yours; it is never interrupted.
2. Find the Spotify id of the song TIDAL is playing: a local cache, then the
   lookups configured in ``spotify.app.id_lookups`` (Spotify Web API,
   ListenBrainz, Spotify's own search page driven through Accessibility, Odesli).
3. Mute Spotify, start that song's **Song Radio**
   (``play track X in context spotify:station:track:X``) and skip through the
   station, reading every track that comes up. Falls back to Spotify's
   autoplay when the station does not start.
4. Check that Spotify really started the song we asked for, pause Spotify and
   put its volume back.

The skip-and-read loop runs inside one osascript process and costs roughly
half a second per song.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from ..activity import busy
from ..applescript import AppleScriptError, ScriptRunner, quote
from ..cache import DiskCache
from ..config import SpotifyAppConfig
from ..matching import artist_similarity, normalize, primary_artist, same_song
from ..models import Candidate, Seed
from .base import tag
from ..lru import BoundedDict

SPOTIFY_BUNDLE = "com.spotify.client"
US = "\x1f"
DEFAULT_APP_PATHS = ("/Applications/Spotify.app", "~/Applications/Spotify.app")


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
            set tid to (id of current track) as text
        end try
    end tell
end timeout
set AppleScript's text item delimiters to ASCII character 31
return {ps, vol as text, tid} as text
""" % {"bid": SPOTIFY_BUNDLE}

CURRENT_SCRIPT = GUARD + """
with timeout of 5 seconds
    tell application id "%(bid)s"
        set tid to ""
        set tn to ""
        set ta to ""
        try
            set tid to (id of current track) as text
            set tn to (name of current track) as text
            set ta to (artist of current track) as text
        end try
        set ps to player state as string
    end tell
end timeout
set AppleScript's text item delimiters to ASCII character 31
return {tid, tn, ta, ps} as text
""" % {"bid": SPOTIFY_BUNDLE}

MUTE_SCRIPT = GUARD + """
tell application id "%(bid)s" to set sound volume to 0
return "ok"
""" % {"bid": SPOTIFY_BUNDLE}

READY_SCRIPT = """
with timeout of 2 seconds
    tell application id "%(bid)s" to return player state as string
end timeout
""" % {"bid": SPOTIFY_BUNDLE}

HIDE_SCRIPT = 'tell application "System Events" to set visible of process "Spotify" to false'

HARVEST_SCRIPT = """
-- Time is counted in 0.1 s ticks rather than with `current date`, which only
-- has one-second resolution. Pauses and text conversion go through the two
-- small handlers below so they always run in this script, never inside
-- Spotify's `tell` block.
on pauseFor(secs)
    delay secs
end pauseFor

on txt(v)
    try
        if v is missing value then return ""
        return v as text
    on error
        return ""
    end try
end txt

on harvest(seedURI, stationURI, wanted, stepTicks, firstTicks, adTicks, budgetTicks, skipDelay, origVol, muteIt, restoreIt, hideIt, useStation)
    set US to ASCII character 31
    set outLines to {}
    set found to 0
    set ticks to 0
    tell application id "%(bid)s"
        if origVol < 0 then set origVol to sound volume
        if muteIt then set sound volume to 0
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
    if hideIt then
        -- `play track` brings Spotify to the front on recent versions; put it back.
        try
            tell application "System Events" to set visible of process "Spotify" to false
        end try
    end if
    my pauseFor(1.0)
    tell application id "%(bid)s"
        set prevId to seedURI
        set seedName to ""
        set seedArtist to ""
        try
            set prevId to my txt(id of current track)
            set seedName to my txt(name of current track)
            set seedArtist to my txt(artist of current track)
        end try
        set seedLine to "SEED" & US & prevId & US & seedName & US & seedArtist
        repeat while found < wanted
            if ticks > budgetTicks then
                set end of outLines to "ERR" & US & "time-budget"
                exit repeat
            end if
            next track
            set waited to 0
            set curId to prevId
            -- A freshly started station can take several seconds to load, so the
            -- first skip gets a longer window and is repeated while we wait.
            set limitTicks to stepTicks
            if found = 0 then set limitTicks to firstTicks
            repeat
                my pauseFor(0.1)
                set waited to waited + 1
                try
                    set curId to my txt(id of current track)
                end try
                if curId is not prevId then exit repeat
                if waited >= limitTicks then exit repeat
                if found = 0 and (waited mod stepTicks) = 0 then next track
            end repeat
            set ticks to ticks + waited
            if curId is prevId then
                set end of outLines to "ERR" & US & "no-advance"
                exit repeat
            end if
            if curId starts with "spotify:ad:" then
                set adWaited to 0
                repeat
                    my pauseFor(0.5)
                    set adWaited to adWaited + 5
                    try
                        set curId to my txt(id of current track)
                    end try
                    if curId does not start with "spotify:ad:" then exit repeat
                    if adWaited >= adTicks then exit repeat
                end repeat
                set ticks to ticks + adWaited
                if curId starts with "spotify:ad:" then
                    set end of outLines to "ERR" & US & "ad-timeout"
                    exit repeat
                end if
            end if
            set n to my txt(name of current track)
            if n is "" then
                my pauseFor(0.2)
                set n to my txt(name of current track)
            end if
            set rec to curId & US & n & US & my txt(artist of current track) & US & my txt(album of current track) & US & my txt(duration of current track) & US & my txt(popularity of current track) & US & my txt(album artist of current track)
            set end of outLines to rec
            set found to found + 1
            set prevId to curId
            if skipDelay > 0 then
                my pauseFor(skipDelay)
                set ticks to ticks + (skipDelay * 10)
            end if
        end repeat
        pause
        if restoreIt and origVol >= 0 then set sound volume to origVol
    end tell
    set AppleScript's text item delimiters to linefeed
    return seedLine & linefeed & (outLines as text)
end harvest

return harvest(%(seed)s, %(station)s, %(wanted)d, %(step_ticks)d, %(first_ticks)d, %(ad_ticks)d, %(budget_ticks)d, %(skip_delay)s, %(orig_volume)d, %(mute)s, %(restore)s, %(hide)s, %(use_station)s)
"""

RESTORE_SCRIPT = GUARD + """
tell application id "%(bid)s"
    try
        pause
    end try
    %(volume_line)s
end tell
return "ok"
"""


def _parse_duration_ms(value: str) -> Optional[float]:
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return ms / 1000.0 if ms > 3000 else ms


def _id_key(seed: Seed) -> str:
    return f"{normalize(seed.title)}|{normalize(primary_artist(seed.artist))}"


class SpotifyAppSource:
    name = "spotify-app"

    def __init__(self, cfg: SpotifyAppConfig, runner: Optional[ScriptRunner], log: Optional[Callable[[str], None]] = None,
                 catalog=None, id_lookups: Sequence = (), ui=None, id_cache: Optional[DiskCache] = None,
                 app_paths: Optional[Sequence[str]] = None,
                 run: Optional[Callable[..., object]] = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.runner = runner
        self.log = log or (lambda m: None)
        self.catalog = catalog
        self.id_lookups = list(id_lookups)
        self.ui = ui
        self.id_cache = id_cache
        if app_paths is None:
            app_paths = [cfg.app_path] if cfg.app_path else list(DEFAULT_APP_PATHS)
        self.app_paths = [Path(p).expanduser() for p in app_paths]
        self._run = run
        self._sleep = sleep
        self._clock = clock
        self._dead: Optional[str] = None
        self._station_works: Optional[bool] = None
        self._cache = BoundedDict(100)
        self._bad_ids: set[str] = set()
        self.last_lookup: str = ""
        self._ui_touched = False
        self._launched_by_us = False
        self._busy_volume: Optional[int] = None
        self._station_failures = 0
        self._lock = threading.Lock()   # Spotify can only run one harvest at a time
        self._cancelled = False

    # -- availability ---------------------------------------------------------
    def installed(self) -> bool:
        return any(p.exists() for p in self.app_paths)

    def available(self) -> tuple[bool, str]:
        if not self.cfg.enabled:
            return False, "disabled in config (spotify.app.enabled)"
        if self.runner is None:
            return False, "osascript not available (macOS only)"
        if not self.installed():
            return False, "Spotify app not found (set spotify.app.app_path if it is not in /Applications)"
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

    def current(self) -> dict:
        out = self._osa(CURRENT_SCRIPT, timeout=8.0)
        if out.strip() == "not-running":
            return {}
        parts = (out.split(US) + ["", "", "", ""])[:4]
        return {"id": parts[0].strip(), "name": parts[1].strip(), "artist": parts[2].strip(), "state": parts[3].strip()}

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
                if self._dead:  # Automation access was refused; waiting will not help
                    raise
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

    def _restore(self, volume: Optional[int]) -> None:
        """Pause Spotify and put its volume back after an interrupted harvest."""
        line = f"set sound volume to {int(volume)}" if (volume is not None and self.cfg.restore) else ""
        try:
            self.runner.run(RESTORE_SCRIPT % {"bid": SPOTIFY_BUNDLE, "volume_line": line}, timeout=10.0)
        except AppleScriptError as e:
            self.log(f"could not restore Spotify after the harvest: {e}")

    def ensure_running(self) -> dict:
        st = self.state()
        if not st.get("running"):
            self.log("launching Spotify (hidden) for the harvest")
            self._launch_hidden()
            self._launched_by_us = True
            st = self.state()
        return st

    def _should_quit(self) -> bool:
        q = self.cfg.quit_after
        return q is True or (q == "auto" and self._launched_by_us)

    def cancel(self) -> None:
        """The song changed: stop a harvest that is no longer needed (it restores Spotify itself)."""
        if self._busy_volume is not None and hasattr(self.runner, "stop_all"):
            self._cancelled = True
            if self.runner.stop_all():
                self.log("stopped the Spotify harvest for the previous song")

    def abort(self) -> None:
        """Called on Ctrl+C: pause Spotify and restore its volume if a harvest is running."""
        if self._busy_volume is not None or self._ui_touched:
            self._restore(self._busy_volume)
            self._busy_volume = None

    # -- finding the seed on Spotify -------------------------------------------
    def _lookup_order(self) -> list[str]:
        return list(self.cfg.id_lookups)

    def _ui_lookup(self, seed: Seed) -> Optional[str]:
        """Search Spotify's own UI for the song, press play (muted), read its id."""
        if self.ui is None:
            return None
        ok, reason = self.ui.available()
        if not ok:
            self.log(f"Spotify search via the UI unavailable: {reason}")
            return None
        before = self.current().get("id", "")
        self._osa(MUTE_SCRIPT, timeout=8.0)
        self._ui_touched = True
        try:
            button = self.ui.find_and_play(seed.title, seed.artist)
        except Exception as e:
            self.log(f"Spotify UI search failed: {e}")
            return None
        if button is None:
            return None
        deadline = self._clock() + 6.0
        while self._clock() < deadline:
            cur = self.current()
            tid = cur.get("id", "")
            if tid.startswith("spotify:track:") and tid != before and same_song(cur.get("name", ""), cur.get("artist", ""), button.title, button.artist):
                return tid.rsplit(":", 1)[-1]
            self._sleep(0.3)
        self.log("Spotify did not start the song chosen on its search page")
        return None

    def spotify_id_for(self, seed: Seed) -> Optional[str]:
        """The Spotify track id for the seed, or None. Sets ``last_lookup``."""
        self.last_lookup = ""
        if seed.spotify_id:
            self.last_lookup = "given"
            return seed.spotify_id
        key = _id_key(seed)
        if self.id_cache is not None:
            cached = self.id_cache.get(key)
            if cached and cached not in self._bad_ids:
                self.last_lookup = "cache"
                seed.spotify_id = cached
                return cached
        by_name = {getattr(l, "name", ""): l for l in self.id_lookups}
        for name in self._lookup_order():
            sid = None
            if name == "spotify-ui":
                sid = self._ui_lookup(seed)
            elif name in by_name:
                lookup = by_name[name]
                ok, reason = lookup.available()
                if not ok:
                    continue
                try:
                    sid = lookup.lookup(seed)
                except Exception as e:
                    self.log(f"{name} lookup failed: {e}")
                    sid = None
            if sid and sid not in self._bad_ids:
                self.last_lookup = name
                seed.spotify_id = sid
                return sid
        return None

    # backwards compatible helper
    def spotify_uri_for(self, seed: Seed) -> Optional[str]:
        sid = self.spotify_id_for(seed)
        return f"spotify:track:{sid}" if sid else None

    # -- harvest --------------------------------------------------------------
    def _harvest_script(self, seed_uri: str, wanted: int, use_station: bool, orig_volume: Optional[int] = None) -> str:
        station = "spotify:station:track:" + seed_uri.rsplit(":", 1)[-1]
        return HARVEST_SCRIPT % {
            "bid": SPOTIFY_BUNDLE, "seed": quote(seed_uri), "station": quote(station), "wanted": int(wanted),
            "step_ticks": 20, "first_ticks": 100, "ad_ticks": 450, "budget_ticks": int(self.cfg.max_seconds * 10),
            "skip_delay": f"{float(self.cfg.skip_delay):.2f}",
            "orig_volume": int(orig_volume) if orig_volume is not None else -1,
            "mute": "true" if self.cfg.mute else "false",
            "restore": "true" if self.cfg.restore else "false",
            "hide": "true" if self.cfg.hide_window else "false",
            "use_station": "true" if use_station else "false",
        }

    def _parse(self, out: str, seed_uri: str) -> tuple[list[Candidate], Optional[str], Optional[dict]]:
        cands: list[Candidate] = []
        error: Optional[str] = None
        seed_meta: Optional[dict] = None
        for line in out.splitlines():
            parts = line.split(US)
            if not parts or not parts[0]:
                continue
            if parts[0] == "SEED":
                parts += [""] * 4
                seed_meta = {"id": parts[1], "name": parts[2], "artist": parts[3]}
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
        return cands, error, seed_meta

    def harvest(self, seed_uri: str, wanted: int, orig_volume: Optional[int] = None) -> tuple[list[Candidate], Optional[dict]]:
        """Play the seed's song radio and read what comes up. Spotify must not be busy."""
        if seed_uri in self._cache:
            return list(self._cache[seed_uri]), None
        methods = ["station", "autoplay"] if self.cfg.seed_method == "auto" else [self.cfg.seed_method]
        if self._station_works is False and self._station_failures >= 2 and "autoplay" in methods:
            methods = ["autoplay"]
        collected: list[Candidate] = []
        seed_meta: Optional[dict] = None
        started = self._clock()
        completed = False
        try:
            for method in methods:
                script = self._harvest_script(seed_uri, wanted, use_station=(method == "station"), orig_volume=orig_volume)
                completed = False
                out = self._osa(script, timeout=self.cfg.max_seconds + 60)
                completed = True
                cands, error, meta = self._parse(out, seed_uri)
                seed_meta = meta or seed_meta
                if error:
                    self.log(f"Spotify harvest ({method}) stopped early: {error} after {len(cands)} songs")
                if cands:
                    collected = cands
                    if method == "station":
                        self._station_works = True
                        self._station_failures = 0
                    break
                if method == "station" and error == "no-advance":
                    self._station_failures += 1
                    self._station_works = False
                    self.log("song radio did not start; falling back to autoplay")
        finally:
            if not completed:
                # The script was killed (Ctrl+C, timeout, error) before it could
                # pause Spotify and restore its volume itself.
                self._restore(orig_volume)
        self.log(f"Spotify harvest: {len(collected)} songs in {self._clock() - started:.1f}s")
        if collected:  # an ad or a slow station is no reason to give up on this song for good
            self._cache[seed_uri] = list(collected)
        return collected, seed_meta

    def _seed_matches(self, seed: Seed, meta: Optional[dict]) -> bool:
        if not meta or not meta.get("name"):
            return True  # nothing to compare against
        if same_song(seed.title, seed.artist, meta["name"], meta.get("artist", "")):
            return True
        # A different recording by the same artist still gives a sensible radio.
        return artist_similarity(seed.artist, [meta.get("artist", "")]) >= 0.8

    # -- Source protocol ------------------------------------------------------
    def candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        with self._lock:
            self._cancelled = False
            return self._candidates(seeds, limit)

    def _candidates(self, seeds: Sequence[Seed], limit: int) -> list[Candidate]:
        seed = seeds[0]
        # While Spotify plays (muted), it owns macOS's now-playing slot. Cover the
        # longest the harvest can take, launch included.
        busy_for = self.cfg.max_seconds + 60 + self.cfg.launch_timeout + 30
        with busy("spotify-harvest", seconds=busy_for, linger=5.0):
            try:
                st = self.ensure_running()
            except SpotifyAppError as e:
                self.log(f"Spotify app unavailable: {e}")
                return []
            if st.get("state") == "playing" and st.get("track") and not st["track"].startswith("spotify:ad:"):
                self.log("Spotify is playing something; not interrupting it")
                return []
            orig_volume = st.get("volume")
            self._busy_volume = orig_volume
            self._ui_touched = False
            harvested = False
            try:
                sid = self.spotify_id_for(seed)
                if not sid:
                    self.log(f"could not find {seed.label()} on Spotify")
                    return []
                uri = f"spotify:track:{sid}"
                cands, meta = self.harvest(uri, max(limit, self.cfg.harvest), orig_volume=orig_volume)
                harvested = True
            except SpotifyAppError as e:
                if not self._cancelled:
                    self.log(f"Spotify app harvest failed: {e}")
                return []
            finally:
                if self._ui_touched and not harvested:
                    self._restore(orig_volume)  # the UI search started a song, muted
                self._busy_volume = None
                self._ui_touched = False
                self._hide()
                if self._should_quit():
                    # Spotify stays macOS's "now playing" app while it is open, which would
                    # send your media keys to it instead of TIDAL.
                    self._quit()
                    self._launched_by_us = False
        if not self._seed_matches(seed, meta):
            self.log(f"Spotify played {meta.get('name')} — {meta.get('artist')} for {seed.label()}; ignoring that radio")
            self._bad_ids.add(sid)
            self._cache.pop(uri, None)
            return []
        if self.id_cache is not None and self.last_lookup not in ("cache", "given"):
            self.id_cache.set(_id_key(seed), sid)
            self.id_cache.flush()
        n = max(1, len(cands))
        out = []
        for i, c in enumerate(cands):
            c = Candidate(**{**c.__dict__})
            c.score = 1.0 - 0.5 * (i / n)
            out.append(c)
        return tag(out[:limit], self.name)
