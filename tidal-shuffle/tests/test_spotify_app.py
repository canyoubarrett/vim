"""Spotify desktop source tests with a scripted fake osascript."""

import pytest

from tidal_shuffle.applescript import AppleScriptError
from tidal_shuffle.cache import DiskCache
from tidal_shuffle.config import SpotifyAppConfig
from tidal_shuffle.models import Seed
from tidal_shuffle.sources.spotify_app import US, SpotifyAppSource
from tidal_shuffle.spotify_ui import UIButton


class FakeSpotify:
    """Pretends to be osascript talking to Spotify."""

    def __init__(self, running=True, state="paused", volume=70, station=None, autoplay=None, seed_name=None,
                 seed_artist="S"):
        self.running = running
        self.state = state
        self.volume = volume
        self.station = station if station is not None else []
        self.autoplay = autoplay or []
        self.seed_name = seed_name
        self.seed_artist = seed_artist
        self.current = ("spotify:track:prev", "Old", "Someone")
        self.scripts = []
        self.hidden = self.quit = 0
        self.deny = False
        self.fail_harvest = False

    def run(self, script, timeout=10.0):
        self.scripts.append(script)
        if self.deny:
            raise AppleScriptError("execution error: Not authorized to send Apple events to Spotify. (-1743)")
        if "System Events" in script and "on harvest(" not in script:
            self.hidden += 1
            return ""
        if "to quit" in script:
            self.quit += 1
            self.running = False
            return ""
        if 'is running) then return "not-running"' in script and not self.running:
            return "not-running"
        if not self.running:
            raise AppleScriptError("not running")
        if "return player state as string" in script and "harvest" not in script:
            return self.state
        if "return {ps, vol, tid} as text" in script:
            return US.join([self.state, str(self.volume), self.current[0] if self.state != "stopped" else ""])
        if "return {tid, tn, ta, ps} as text" in script:
            return US.join([*self.current, self.state])
        if "set sound volume to 0" in script and 'return "ok"' in script and "pause" not in script:
            self.volume = 0
            return "ok"
        if 'return "ok"' in script and "pause" in script:  # restore
            self.state = "paused"
            import re
            m = re.search(r"set sound volume to (\d+)", script)
            if m:
                self.volume = int(m.group(1))
            return "ok"
        if "on harvest(" in script:
            if self.fail_harvest:
                raise AppleScriptError("AppleScript timed out after 120s")
            call = script.rsplit("return harvest(", 1)[1]
            args = [a.strip().strip('"') for a in call.rsplit(")", 1)[0].split(",")]
            names = ["seed", "station", "wanted", "step", "first", "ad", "budget", "skip", "orig", "mute", "restore", "hide", "use"]
            a = dict(zip(names, args))
            seed, wanted, orig, use_station = a["seed"], int(a["wanted"]), int(a["orig"]), a["use"] == "true"
            tracks = self.station if use_station else self.autoplay
            seed_name = self.seed_name if self.seed_name is not None else "Seed"
            lines = [US.join(["SEED", seed, seed_name, self.seed_artist])]
            lines += [US.join(t) for t in tracks[:wanted]]
            if not tracks:
                lines.append("ERR" + US + "no-advance")
            self.state = "paused"
            self.volume = orig if orig >= 0 else self.volume
            return "\n".join(lines)
        raise AssertionError("unexpected script: " + script[:80])


def track(i, artist="Artist %d", album="Album", dur="201000", pop="55"):
    a = artist % i if "%d" in artist else artist
    return (f"spotify:track:id{i}", f"Song {i}", a, album, dur, pop, a)


class Lookup:
    def __init__(self, name, answer=None, ok=True):
        self.name, self.answer, self.ok, self.calls = name, answer, ok, 0
    def available(self):
        return (self.ok, "" if self.ok else "off")
    def lookup(self, seed):
        self.calls += 1
        return self.answer


def make(fake, cfg=None, **kw):
    cfg = cfg or SpotifyAppConfig(harvest=5, launch_timeout=3)
    kw.setdefault("id_lookups", [Lookup("listenbrainz", "seedid")])
    return SpotifyAppSource(cfg, runner=fake, app_paths=[__file__], sleep=lambda s: None, clock=lambda: 0.0, **kw)


def test_availability_reasons(tmp_path):
    cfg = SpotifyAppConfig()
    assert SpotifyAppSource(cfg, runner=None).available()[0] is False
    assert "app_path" in SpotifyAppSource(cfg, runner=FakeSpotify(), app_paths=[str(tmp_path / "nope.app")]).available()[1]
    cfg.enabled = False
    assert "disabled" in SpotifyAppSource(cfg, runner=FakeSpotify(), app_paths=[__file__]).available()[1]
    assert make(FakeSpotify()).available() == (True, "")


def test_station_harvest_parses_tracks_and_verifies_seed():
    fake = FakeSpotify(station=[track(1), track(2), ("spotify:track:seedid", "Seed", "S", "A", "1000", "1", "S"), track(3, dur="0")])
    src = make(fake)
    cands = src.candidates([Seed("Seed", "S")], 10)
    assert [c.title for c in cands] == ["Song 1", "Song 2", "Song 3"]
    assert cands[0].spotify_id == "id1" and cands[0].duration == 201.0 and cands[0].popularity == 55
    assert cands[2].duration is None
    assert cands[0].score > cands[2].score and cands[0].source == "spotify-app" and cands[0].rank == 0
    assert fake.hidden >= 1 and fake.quit == 0 and fake.volume == 70
    n = len(fake.scripts)
    src.candidates([Seed("Seed", "S")], 10)  # cached harvest
    assert not any("on harvest(" in s for s in fake.scripts[n:])


def test_wrong_song_on_spotify_is_rejected():
    fake = FakeSpotify(station=[track(1)], seed_name="Totally Different", seed_artist="Other Band")
    src = make(fake)
    assert src.candidates([Seed("Seed", "S")], 5) == []
    assert "seedid" in src._bad_ids


def test_same_artist_different_take_is_accepted():
    fake = FakeSpotify(station=[track(1)], seed_name="Seed (Live)", seed_artist="S")
    assert [c.title for c in make(fake).candidates([Seed("Seed", "S")], 5)] == ["Song 1"]


def test_falls_back_to_autoplay_and_only_gives_up_on_song_radio_after_two_songs():
    fake = FakeSpotify(station=[], autoplay=[track(9)])
    src = make(fake)
    assert [c.title for c in src.candidates([Seed("Seed", "S")], 5)] == ["Song 9"]
    src.candidates([Seed("Other", "S", spotify_id="y")], 5)
    src.candidates([Seed("Third", "S", spotify_id="z")], 5)
    modes = [s.rsplit(",", 1)[1].strip(" )\n") for s in fake.scripts if "on harvest(" in s]
    # station+autoplay, station+autoplay, then autoplay only
    assert modes == ["true", "false", "true", "false", "false"]


def test_empty_harvests_are_not_cached():
    fake = FakeSpotify(station=[], autoplay=[])
    src = make(fake)
    assert src.candidates([Seed("Seed", "S")], 5) == []
    fake.station = [track(1)]
    assert [c.title for c in src.candidates([Seed("Seed", "S")], 5)] == ["Song 1"]


def test_quits_spotify_after_harvest_only_if_it_launched_it():
    fake = FakeSpotify(running=False, station=[track(1)])
    def run(cmd, **kw):
        fake.running = True
    src = make(fake, run=run)
    src.candidates([Seed("Seed", "S")], 5)
    assert fake.quit == 1  # we opened it, so we close it (keeps media keys on TIDAL)
    fake2 = FakeSpotify(running=True, station=[track(1)])
    make(fake2).candidates([Seed("Seed", "S")], 5)
    assert fake2.quit == 0  # you had it open: leave it alone


def test_abort_restores_spotify_mid_harvest():
    fake = FakeSpotify(station=[track(1)], volume=58)
    src = make(fake)
    src._busy_volume = 58  # as if a harvest were running on the planner thread
    fake.volume, fake.state = 0, "playing"
    src.abort()
    assert fake.volume == 58 and fake.state == "paused"


def test_launches_hidden_when_not_running():
    fake = FakeSpotify(running=False, station=[track(1)])
    launched = []
    def run(cmd, **kw):
        launched.append(cmd)
        fake.running = True
    cands = make(fake, run=run).candidates([Seed("Seed", "S")], 5)
    assert launched and launched[0][:3] == ["open", "-gj", "-b"] and len(cands) == 1


def test_does_not_interrupt_user_playing_spotify():
    fake = FakeSpotify(state="playing", station=[track(1)])
    lookup = Lookup("listenbrainz", "seedid")
    assert make(fake, id_lookups=[lookup]).candidates([Seed("Seed", "S")], 5) == []
    assert lookup.calls == 0 and not any("on harvest(" in s for s in fake.scripts)


def test_automation_denied_marks_source_dead():
    fake = FakeSpotify()
    fake.deny = True
    src = make(fake)
    assert src.candidates([Seed("Seed", "S")], 5) == []
    ok, reason = src.available()
    assert not ok and "Automation" in reason


def test_lookup_order_skips_unavailable_and_caches_result(tmp_path):
    fake = FakeSpotify(station=[track(1)])
    api = Lookup("spotify-api", "fromapi", ok=False)
    lb = Lookup("listenbrainz", "seedid")
    cache = DiskCache(tmp_path / "ids.json", ttl=1000)
    src = make(fake, id_lookups=[api, lb], id_cache=cache)
    seed = Seed("Seed", "S")
    assert len(src.candidates([seed], 5)) == 1
    assert api.calls == 0 and lb.calls == 1 and src.last_lookup == "listenbrainz" and seed.spotify_id == "seedid"
    src2 = make(FakeSpotify(station=[track(1)]), id_lookups=[lb], id_cache=DiskCache(tmp_path / "ids.json", ttl=1000))
    src2.candidates([Seed("Seed", "S")], 5)
    assert lb.calls == 1 and src2.last_lookup == "cache"


class FakeUI:
    def __init__(self, fake, ok=True, button=True):
        self.fake, self.ok, self.button, self.searched = fake, ok, button, []
    def available(self):
        return (self.ok, "" if self.ok else "no permission")
    def find_and_play(self, title, artist):
        self.searched.append((title, artist))
        if not self.button:
            return None
        self.fake.current = ("spotify:track:uiid", title, artist)
        self.fake.state = "playing"
        return UIButton(label=f"Play {title} by {artist}", title=title, artist=artist, score=0.97)


def test_spotify_ui_lookup_mutes_plays_and_reads_the_id():
    fake = FakeSpotify(station=[track(1)])
    ui = FakeUI(fake)
    cfg = SpotifyAppConfig(harvest=5, id_lookups=["listenbrainz", "spotify-ui"])
    src = make(fake, cfg=cfg, id_lookups=[Lookup("listenbrainz", None)], ui=ui)
    cands = src.candidates([Seed("Seed", "S")], 5)
    assert ui.searched == [("Seed", "S")] and src.last_lookup == "spotify-ui"
    assert any("set sound volume to 0" in s and "on harvest(" not in s for s in fake.scripts)
    harvest = [s for s in fake.scripts if "on harvest(" in s][0]
    assert '"spotify:track:uiid"' in harvest and ", 70, " in harvest  # original volume passed through
    assert len(cands) == 1 and fake.volume == 70


def test_spotify_ui_failure_restores_spotify():
    fake = FakeSpotify(station=[track(1)])
    ui = FakeUI(fake, button=False)
    cfg = SpotifyAppConfig(harvest=5, id_lookups=["spotify-ui"])
    src = make(fake, cfg=cfg, id_lookups=[], ui=ui)
    assert src.candidates([Seed("Seed", "S")], 5) == []
    assert fake.volume == 70 and fake.state == "paused"


def test_interrupted_harvest_restores_spotify():
    fake = FakeSpotify(station=[track(1)], volume=63)
    fake.fail_harvest = True
    assert make(fake).candidates([Seed("Seed", "S")], 5) == []
    assert fake.volume == 63 and fake.state == "paused"


def test_harvest_script_formatting():
    src = make(FakeSpotify(), cfg=SpotifyAppConfig(max_seconds=30, skip_delay=0.25, mute=False, restore=True))
    script = src._harvest_script("spotify:track:abc", 12, use_station=True, orig_volume=55)
    tail = script.rsplit("return harvest(", 1)[1]
    assert tail.startswith('"spotify:track:abc", "spotify:station:track:abc", 12, 20, 100, 450, 300, 0.25, 55, false, true, true, true)')
    body = script.split("on harvest(")[1]
    assert "current date" not in body and "end with timeout" not in script


def test_app_path_from_config(tmp_path):
    app = tmp_path / "Spotify.app"
    app.mkdir()
    assert SpotifyAppSource(SpotifyAppConfig(app_path=str(app)), runner=FakeSpotify()).available() == (True, "")
    assert "app_path" in SpotifyAppSource(SpotifyAppConfig(app_path=str(tmp_path / "x.app")), runner=FakeSpotify()).available()[1]


def test_quit_after_option():
    fake = FakeSpotify(station=[track(1)])
    make(fake, cfg=SpotifyAppConfig(harvest=3, quit_after=True)).candidates([Seed("Seed", "S")], 3)
    assert fake.quit == 1
    fake = FakeSpotify(running=False, station=[track(1)])
    def run(cmd, **kw):
        fake.running = True
    make(fake, cfg=SpotifyAppConfig(harvest=3, quit_after=False), run=run).candidates([Seed("Seed", "S")], 3)
    assert fake.quit == 0
