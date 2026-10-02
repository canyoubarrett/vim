"""Spotify desktop harvester tests with a scripted fake osascript."""

import pytest

from tidal_shuffle.applescript import AppleScriptError
from tidal_shuffle.config import SpotifyAppConfig
from tidal_shuffle.models import Seed
from tidal_shuffle.sources.spotify_app import US, SpotifyAppError, SpotifyAppSource

US_ = US


class FakeSpotify:
    """Pretends to be osascript talking to Spotify."""

    def __init__(self, running=True, state="paused", volume=70, station_tracks=None, autoplay_tracks=None, ad_first=False):
        self.running = running
        self.state = state
        self.volume = volume
        self.station_tracks = station_tracks if station_tracks is not None else []
        self.autoplay_tracks = autoplay_tracks or []
        self.scripts = []
        self.launched = 0
        self.hidden = 0
        self.quit = 0
        self.deny = False

    def run(self, script, timeout=10.0):
        self.scripts.append(script)
        if self.deny:
            raise AppleScriptError("execution error: Not authorized to send Apple events to Spotify. (-1743)")
        if "System Events" in script:
            self.hidden += 1
            return ""
        if "to quit" in script:
            self.quit += 1
            self.running = False
            return ""
        if not self.running:
            if "is running" in script and "return \"not-running\"" in script:
                return "not-running"
            raise AppleScriptError("not running")
        if "return player state as string" in script and "harvest" not in script:
            return self.state
        if "return {ps, vol, tid} as text" in script:
            return US_.join([self.state, str(self.volume), "spotify:track:prev" if self.state != "stopped" else ""])
        if "on harvest(" in script:
            use_station = 'return harvest(' in script and ', true)' in script.rsplit("return harvest(", 1)[1]
            tracks = self.station_tracks if use_station else self.autoplay_tracks
            wanted = int(script.rsplit("return harvest(", 1)[1].split(",")[2])
            lines = []
            for t in tracks[:wanted]:
                lines.append(US_.join(t))
            if not tracks:
                lines.append("ERR" + US_ + "no-advance")
            self.state = "paused"
            return "\n".join(lines)
        raise AssertionError("unexpected script: " + script[:60])


def track(i, artist="Artist %d", album="Album", dur="201000", pop="55"):
    return (f"spotify:track:id{i}", f"Song {i}", artist % i if "%d" in artist else artist, album, dur, pop, artist % i if "%d" in artist else artist)


def make(fake, cfg=None, **kw):
    cfg = cfg or SpotifyAppConfig(harvest=5, launch_timeout=3, skip_delay=0.1)
    return SpotifyAppSource(cfg, runner=fake, app_paths=[__file__], sleep=lambda s: None, clock=lambda: 0.0, **kw)


def test_availability_reasons(tmp_path):
    cfg = SpotifyAppConfig()
    assert SpotifyAppSource(cfg, runner=None).available()[0] is False
    assert SpotifyAppSource(cfg, runner=FakeSpotify(), app_paths=[str(tmp_path / "nope.app")]).available()[1].startswith("Spotify app not found")
    cfg.enabled = False
    assert "disabled" in SpotifyAppSource(cfg, runner=FakeSpotify(), app_paths=[__file__]).available()[1]
    assert make(FakeSpotify()).available() == (True, "")


def test_station_harvest_parses_tracks():
    fake = FakeSpotify(station_tracks=[track(1), track(2), ("spotify:track:prevseed", "Seed", "S", "A", "1000", "1", "S"), track(3, dur="0")])
    src = make(fake)
    cands = src.candidates([Seed("Seed", "S", spotify_id="prevseed")], 10)
    assert [c.title for c in cands] == ["Song 1", "Song 2", "Song 3"]
    assert cands[0].spotify_id == "id1" and cands[0].duration == 201.0 and cands[0].popularity == 55
    assert cands[2].duration is None
    assert cands[0].score > cands[2].score and cands[0].source == "spotify-app" and cands[0].rank == 0
    assert fake.hidden >= 1 and fake.quit == 0
    # cached: a second call runs no harvest script
    n = len(fake.scripts)
    src.candidates([Seed("Seed", "S", spotify_id="prevseed")], 10)
    assert len(fake.scripts) == n


def test_falls_back_to_autoplay_when_station_does_not_advance():
    fake = FakeSpotify(station_tracks=[], autoplay_tracks=[track(9)])
    src = make(fake)
    cands = src.candidates([Seed("Seed", "S", spotify_id="x")], 5)
    assert [c.title for c in cands] == ["Song 9"]
    assert src._station_works is False
    # subsequent harvests skip the station attempt
    src.candidates([Seed("Other", "S", spotify_id="y")], 5)
    harvests = [s for s in fake.scripts if "on harvest(" in s]
    assert len(harvests) == 3


def test_launches_hidden_when_not_running():
    fake = FakeSpotify(running=False, station_tracks=[track(1)])
    launched = []
    def run(cmd, **kw):
        launched.append(cmd)
        fake.running = True
    src = make(fake, run=run)
    cands = src.candidates([Seed("Seed", "S", spotify_id="x")], 5)
    assert launched and launched[0][:3] == ["open", "-gj", "-b"]
    assert len(cands) == 1


def test_does_not_interrupt_user_playing_spotify():
    fake = FakeSpotify(state="playing", station_tracks=[track(1)])
    src = make(fake)
    assert src.candidates([Seed("Seed", "S", spotify_id="x")], 5) == []
    assert not any("on harvest(" in s for s in fake.scripts)


def test_automation_denied_marks_source_dead():
    fake = FakeSpotify()
    fake.deny = True
    src = make(fake)
    assert src.candidates([Seed("Seed", "S", spotify_id="x")], 5) == []
    ok, reason = src.available()
    assert not ok and "Automation" in reason


def test_seed_mapping_prefers_api_then_odesli():
    fake = FakeSpotify(station_tracks=[track(1)])
    class Mapper:
        def __init__(self): self.calls = []
        def spotify_id_for_tidal(self, tid):
            self.calls.append(tid); return "mapped"
    class Cat:
        def resolve_seed(self, seed):
            seed.tidal_id = "t1"; return seed
    mapper = Mapper()
    src = make(fake, mapper=mapper, catalog=Cat(), api_lookup=lambda seed: None)
    seed = Seed("Seed", "S")
    assert src.spotify_uri_for(seed) == "spotify:track:mapped" and mapper.calls == ["t1"]
    src2 = make(fake, mapper=mapper, api_lookup=lambda seed: "fromapi")
    assert src2.spotify_uri_for(Seed("Seed", "S")) == "spotify:track:fromapi"
    assert make(fake).candidates([Seed("Unmappable", "S")], 5) == []


def test_quit_after_option():
    fake = FakeSpotify(station_tracks=[track(1)])
    src = make(fake, cfg=SpotifyAppConfig(harvest=3, quit_after=True))
    src.candidates([Seed("Seed", "S", spotify_id="x")], 3)
    assert fake.quit == 1
