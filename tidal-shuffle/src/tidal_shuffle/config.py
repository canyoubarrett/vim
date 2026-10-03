"""Configuration: defaults <- config file <- environment <- preset <- CLI flags."""

from __future__ import annotations

import copy
import os
import re
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from .models import VibeParams
from .paths import CONFIG_DIR, CONFIG_FILE, TIDAL_SESSION_FILE

KNOWN_SOURCES = ("spotify-app", "spotify-api", "lastfm", "deezer", "tidal-radio")
DEFAULT_SOURCES = ["spotify-app", "spotify-api", "lastfm", "deezer", "tidal-radio"]
STRATEGIES = ("top", "weighted", "random", "discovery")
FLOWS = ("radio", "rising", "falling", "steady", "soundscape", "vibe")
SEED_MODES = ("current", "anchor", "window")
NOWPLAYING_BACKENDS = ("auto", "media-control", "nowplaying-cli")
PLAY_STRATEGIES = ("auto", "luna", "cdp", "open-url", "open-url-play")
MEDIA_KEY_MODES = ("focus", "always", "off")
HANDOFF_MODES = ("pause", "timed")


class ConfigError(ValueError):
    """Raised for an invalid configuration value with a human readable message."""


@dataclass
class SpotifyAppConfig:
    """Driving the Spotify *desktop app* over AppleScript (no API key needed)."""

    enabled: bool = True
    harvest: int = 25            # how many upcoming tracks to read per seed
    seed_method: str = "auto"    # auto | station | autoplay
    mute: bool = True            # set Spotify's volume to 0 while harvesting
    restore: bool = True         # put Spotify's volume back afterwards
    hide_window: bool = True     # keep Spotify out of the way when we launch it
    keep_hidden: bool = True     # hide Spotify the whole time it is used (skips the spotify-ui lookup)
    quit_after: Any = "auto"     # quit Spotify after a harvest: auto (if we launched it) | true | false
    skip_delay: float = 0.0      # extra pause after each skip (gentler on Spotify)
    launch_timeout: float = 25.0 # seconds to wait for Spotify to answer AppleScript
    max_seconds: float = 60.0    # abort a harvest that takes longer than this
    app_path: str = ""           # Spotify.app location; empty = /Applications or ~/Applications
    # How to find the TIDAL song on Spotify, in order. "spotify-ui" drives the
    # Spotify app's own search page through macOS Accessibility.
    id_lookups: list = field(default_factory=lambda: ["spotify-api", "listenbrainz", "spotify-ui", "odesli"])
    odesli_api_key: str = ""     # song.link retired its keyless API on 2026-07-31
    ui_label_prefix: str = "Play "   # Spotify's button label: "Play <song> by <artist>"
    ui_label_by: str = " by "        # change both for a non-English Spotify


@dataclass
class SpotifyConfig:
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    market: str = "US"
    app: SpotifyAppConfig = field(default_factory=SpotifyAppConfig)
    vibe: VibeParams = field(default_factory=VibeParams)

    @property
    def has_api_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret
                    and "your_" not in self.client_id and "your_" not in self.client_secret)


@dataclass
class LastfmConfig:
    api_key: Optional[str] = None
    expand_similar_artists: bool = True  # also pull top tracks of similar artists

    @property
    def configured(self) -> bool:
        return bool(self.api_key and "your_" not in self.api_key)


@dataclass
class DeezerConfig:
    enabled: bool = True


@dataclass
class UiConfig:
    screen: str = "full"          # full: full-screen view while running | plain: scrolling log
    lyrics: bool = True           # look up lyrics for the song playing
    lyrics_sources: list[str] = field(default_factory=lambda: ["tidal", "lrclib"])
    visualizer: bool = True       # the floating Alter Era logo next to the lyrics
    theme: str = "mocha"          # mocha | macchiato | frappe | latte | nord | dracula | gruvbox | ... (see README)
    color: str = "auto"           # auto | truecolor | 256 | 16: force it if the terminal under-reports
    logo_file: str = ""           # an .svg (traced into braille) or ---BIG--- / ---SMALL--- braille art
    cell_aspect: float = 0.5      # a terminal cell's width / height, so the logo keeps its proportions
    artwork: bool = True          # the album cover in the header (needs Pillow)
    art_blocks: str = "quadrant"  # quadrant: 2x2 pixels per cell | half: 1x2 (for fonts without quadrants)
    backdrop: bool = True         # rain behind the panels
    rain: float = 0.3             # how visible the rain is: 0 (not at all) .. 1 (plain to see)
    logo_style: str = "theme"     # theme | muted | filled | wireframe | pastel | neon | sunset | ocean | catppuccin | mono
    logo_motion: str = "float"    # float | gentle | lively | shapes | tide | topple | jelly | magnet | still
    lyrics_lead: float = 0.55     # show the line being sung, and its words, this many seconds early
    lyrics_ahead: str = "hide"    # lines not sung yet: hide | dim | show
    party: bool = False           # party mode: every logo colour and motion, cycling
    logo_backdrop: str = "off"    # behind the logo: off | cover | random | a picture in ~/.config/tidal-shuffle/backdrops
    backdrop_dim: float = 0.45    # how far the picture is dimmed towards the background (0..0.9)
    shuffle_view: str = "off"     # the shuffle tree: off | logo (in place of the logo) | side (of Up next)
    glass: float = 0.22           # how much of the rain shows through the panels (0 = none)
    track_poll: float = 0.5       # how often to check for a new song while the screen is up (s)
    mouse: bool = True            # click the key chips and presets (hold Option/Fn to select text)
    fps: float = 12.0


@dataclass
class TidalConfig:
    session_file: Path = field(default_factory=lambda: TIDAL_SESSION_FILE)
    radio_limit: int = 50
    search_limit: int = 10
    match_threshold: float = 0.72


@dataclass
class ShuffleConfig:
    strategy: str = "weighted"
    flow: str = "radio"               # radio | rising | falling | steady | soundscape | vibe (see flows.py)
    energy: Optional[float] = None    # steady flow: hold this energy (0-1) instead of the first song's
    energy_step: float = 0.06         # rising / falling: how much energy changes per song
    blend: bool = False
    candidates: int = 30
    avoid_repeats_for: int = 200
    avoid_repeats_days: float = 7.0
    artist_cooldown: int = 5
    allow_seed_artist: bool = False
    seed: str = "current"
    lookahead: int = 3
    min_duration: float = 60.0
    max_duration: float = 900.0
    allow_explicit: bool = True


@dataclass
class PlayerConfig:
    nowplaying_backend: str = "auto"
    handoff_mode: str = "pause"
    pause_before_end: float = 0.8
    handoff_seconds: float = 3.0
    adaptive_handoff: bool = True
    handoff_margin: float = 1.0
    prepare_seconds: float = 10.0
    poll_interval: float = 2.0
    near_end_poll_interval: float = 0.4
    plan_after_seconds: float = 4.0
    play_strategy: str = "auto"
    verify_seconds: float = 8.0
    idle_poll_interval: float = 5.0
    cdp_port: int = 9222
    tidal_app: str = "/Applications/TIDAL.app"
    auto_relaunch: bool = True
    luna_port: int = 24123
    tidal_queue: bool = False
    terminal_keys: bool = True
    media_keys: str = "focus"


@dataclass
class AppConfig:
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    shuffle: ShuffleConfig = field(default_factory=ShuffleConfig)
    player: PlayerConfig = field(default_factory=PlayerConfig)
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    lastfm: LastfmConfig = field(default_factory=LastfmConfig)
    deezer: DeezerConfig = field(default_factory=DeezerConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    tidal: TidalConfig = field(default_factory=TidalConfig)
    presets: dict = field(default_factory=dict)
    preset: Optional[str] = None
    config_path: Optional[Path] = None

    def describe(self) -> dict:
        d = asdict(self)
        d["tidal"]["session_file"] = str(self.tidal.session_file)
        d["config_path"] = str(self.config_path) if self.config_path else None
        if self.spotify.client_secret:
            d["spotify"]["client_secret"] = "***"
        if self.lastfm.api_key:
            d["lastfm"]["api_key"] = "***"
        if self.spotify.app.odesli_api_key:
            d["spotify"]["app"]["odesli_api_key"] = "***"
        return d


# ---------------------------------------------------------------------------
# Presets: named bundles of overrides. "vibe" values only matter for Spotify
# apps that still have access to the recommendations endpoint.
# ---------------------------------------------------------------------------
DEFAULT_PRESETS: dict[str, dict] = {
    "balanced": {
        "description": "Relevant but varied. Weighted random pick, 5-song artist cooldown.",
        "shuffle": {"strategy": "weighted", "artist_cooldown": 5, "candidates": 30},
    },
    "familiar": {
        "description": "Stay close to the current song; same artist allowed.",
        "shuffle": {"strategy": "top", "candidates": 15, "allow_seed_artist": True, "artist_cooldown": 2},
    },
    "discovery": {
        "description": "Favour deeper cuts and less popular picks.",
        "shuffle": {"strategy": "discovery", "candidates": 50, "artist_cooldown": 8},
        "spotify": {"vibe": {"max_popularity": 45, "min_popularity": 5}},
    },
    "wander": {
        "description": "Random walk: each pick is seeded by the previous one, uniformly random.",
        "shuffle": {"strategy": "random", "candidates": 40, "seed": "current", "artist_cooldown": 6},
    },
    "anchor": {
        "description": "Stay in orbit around the song you started with.",
        "shuffle": {"strategy": "weighted", "seed": "anchor", "candidates": 40},
    },
    "lastfm-only": {
        "description": "Use only Last.fm similarity data.",
        "sources": ["lastfm", "tidal-radio"],
    },
    "spotify-only": {
        "description": "Use only Spotify (desktop app first, then the Web API).",
        "sources": ["spotify-app", "spotify-api"],
    },
    "tidal-only": {
        "description": "Use only TIDAL's own track radio (no extra accounts needed).",
        "sources": ["tidal-radio"],
    },
    "late-night-drive": {
        "description": "Moody electronic for night driving (Spotify API tuning).",
        "spotify": {"vibe": {"energy": 0.6, "valence": 0.4, "tempo": 110, "genres": ["synthwave", "indie"]}},
    },
    "workout": {
        "description": "High energy (Spotify API tuning).",
        "spotify": {"vibe": {"energy": 0.9, "valence": 0.7, "min_popularity": 30, "genres": ["edm", "hip-hop", "pop"]}},
    },
    "chill": {
        "description": "Low-key background music: holds a calm energy level.",
        "shuffle": {"flow": "steady", "energy": 0.3},
        "spotify": {"vibe": {"energy": 0.3, "valence": 0.5, "acousticness": 0.7, "genres": ["acoustic", "indie-folk", "lo-fi"]}},
    },
    "radio": {
        "description": "The song radio as it comes, closest songs first.",
        "shuffle": {"flow": "radio", "strategy": "top"},
    },
    "warm-up": {
        "description": "Energy rises a little with every song.",
        "shuffle": {"flow": "rising", "strategy": "weighted"},
    },
    "wind-down": {
        "description": "Energy falls a little with every song (evenings, falling asleep).",
        "shuffle": {"flow": "falling", "strategy": "weighted"},
    },
    "steady": {
        "description": "One energy level, the first song's, all session.",
        "shuffle": {"flow": "steady", "strategy": "weighted"},
    },
    "soundscape": {
        "description": "Stay in the first song's soundscape: its energy, mood, texture and tempo.",
        "shuffle": {"flow": "soundscape", "strategy": "weighted"},
    },
    "vibe": {
        "description": "Songs with the same mood and energy as the one playing.",
        "shuffle": {"flow": "vibe", "strategy": "weighted"},
    },
}


EXAMPLE_CONFIG = """\
# Tidal Shuffle configuration. Copy to ~/.config/tidal-shuffle/config.yaml
# Every key is optional; the values shown are the defaults unless noted.

# Recommendation sources, in priority order. The first source that returns
# candidates wins, unless shuffle.blend is true (then they are merged).
#   spotify-app  - drives the Spotify desktop app on this Mac via AppleScript.
#                  No API key needed; Spotify must be installed and logged in.
#   spotify-api  - Spotify Web API (needs client_id/client_secret below).
#   lastfm       - Last.fm track similarity (needs lastfm.api_key).
#   deezer       - Deezer's public, keyless track/artist radio.
#   tidal-radio  - TIDAL's own track radio (always available once logged in).
sources:
  - spotify-app
  - spotify-api
  - lastfm
  - deezer
  - tidal-radio

shuffle:
  strategy: weighted        # top | weighted | random | discovery
  flow: radio               # radio | rising | falling | steady | soundscape | vibe
                            #   radio: the song radio as it is; rising / falling: each song a
                            #   little more energetic / calmer; steady: one energy level;
                            #   soundscape: the first song's overall sound; vibe: the current
                            #   song's mood and energy. Press f while running to switch.
  energy: null              # steady flow: hold this energy (0-1); null = the first song's
  energy_step: 0.06         # rising / falling: energy change per song
  blend: false              # merge candidates from every available source
  candidates: 30            # candidates to request from each source
  avoid_repeats_for: 200    # never replay a song picked in the last N picks ...
  avoid_repeats_days: 7     # ... or in the last N days
  artist_cooldown: 5        # don't repeat an artist within N picks
  allow_seed_artist: false  # may the next song be by the artist now playing?
  seed: current             # current | anchor | window (see README)
  lookahead: 3              # how many backup picks to keep ready
  min_duration: 60          # seconds; skips intros/interludes
  max_duration: 900
  allow_explicit: true

player:
  nowplaying_backend: auto  # auto | media-control | nowplaying-cli
  handoff_mode: pause       # pause: hold TIDAL at the very end, then start the pick (never cuts a song,
                            #   never lets TIDAL's own next song in; a short silence while the pick loads)
                            # timed: start the pick early enough to overlap TIDAL's start-up delay (gapless
                            #   when the guess is right, but may clip the end of a song)
  pause_before_end: 0.8     # pause mode: seconds before the end to hold TIDAL
  handoff_seconds: 3.0      # timed mode: start the next song at least this many seconds before the end
  adaptive_handoff: true    # timed mode: learn how long TIDAL takes to start a song and start earlier if needed
  handoff_margin: 1.0       # timed mode: extra seconds on top of the learned start time
  prepare_seconds: 10.0     # open the next song's page this many seconds before the end
  poll_interval: 2.0        # seconds between now-playing checks
  near_end_poll_interval: 0.4
  plan_after_seconds: 4.0   # wait this long into a song before planning the next
  play_strategy: auto       # auto | luna | cdp | open-url | open-url-play
  verify_seconds: 8.0       # how long to wait for TIDAL to confirm the new song
  cdp_port: 9222            # TIDAL is launched with --remote-debugging-port=<this>
  tidal_app: /Applications/TIDAL.app
  auto_relaunch: true       # relaunch TIDAL with the debug port if it lacks it
  luna_port: 24123          # TidaLuna API plugin port (optional client mod)
  tidal_queue: false        # experimental: queue picks in the stock app's own queue (shows a blank track)
  terminal_keys: true       # space/n/b/q in the terminal running `tidal-shuffle run`
  media_keys: focus         # focus: media keys control Tidal Shuffle while its terminal is in front | always | off

spotify:
  client_id: ""             # optional; from https://developer.spotify.com/dashboard
  client_secret: ""
  market: US
  app:
    enabled: true
    harvest: 25             # upcoming songs to read from Spotify per seed
    seed_method: auto       # auto | station | autoplay
    mute: true              # Spotify is muted while it is harvesting
    restore: true           # and its volume is put back afterwards
    hide_window: true
    keep_hidden: true       # never show Spotify while it is used; the spotify-ui lookup needs its window, so it is skipped
    quit_after: auto        # quit Spotify after a harvest if Tidal Shuffle opened it
                            # (an open Spotify would capture your media keys)
    max_seconds: 60         # give up on a harvest after this long
    app_path: ""            # set if Spotify.app is not in /Applications
    # How the song TIDAL is playing is found on Spotify, tried in order:
    #   spotify-api  - Web API search (needs the credentials below + Premium)
    #   listenbrainz - ListenBrainz's free Spotify-id index
    #   spotify-ui   - Spotify's own search page, driven through Accessibility
    #   odesli       - song.link, only with an API key
    id_lookups: [spotify-api, listenbrainz, spotify-ui, odesli]
    odesli_api_key: ""
    ui_label_prefix: "Play "  # Spotify labels track buttons "Play <song> by <artist>";
    ui_label_by: " by "       # change these two if Spotify is not in English

lastfm:
  api_key: ""               # free key: https://www.last.fm/api/account/create
  expand_similar_artists: true

deezer:
  enabled: true

ui:
  screen: full              # full: full-screen view with the logo and lyrics | plain: scrolling log
  lyrics: true              # synced lyrics from TIDAL, then LRCLIB (free, no key)
  lyrics_sources: [tidal, lrclib]
  visualizer: true          # the floating Alter Era logo next to the lyrics
  theme: mocha              # Catppuccin mocha | macchiato | frappe | latte, nord, dracula, gruvbox,
                            # gruvbox-light, tokyo-night, tokyo-storm, solarized-dark, solarized-light,
                            # one-dark, rose-pine, rose-pine-moon, rose-pine-dawn, everforest, kanagawa,
                            # monokai, github-dark  (also in the Esc menu)
  color: auto               # auto | truecolor | 256 | 16 (force it if colours look wrong or missing)
  logo_file: ""             # your own logo: an .svg, or ---BIG--- / ---SMALL--- braille art
  cell_aspect: 0.5          # terminal cell width / height (lower it if the logo looks too wide)
  artwork: true             # the album cover in the header (press a for it big)
  art_blocks: quadrant      # quadrant: 2x2 pixels per cell | half: 1x2, if your font lacks ▚ ▞ ▙ ▟
  backdrop: true            # rain falling behind the panels
  rain: 0.3                 # how visible the rain is: 0 (not at all) to 1 (plain to see)
  logo_style: theme         # theme | muted | filled | wireframe | pastel | neon | sunset | ocean |
                            # catppuccin | mono  (Esc opens the settings menu)
  logo_motion: float        # float | gentle | lively | shapes | tide | topple | jelly | magnet | still
  lyrics_lead: 0.55         # seconds early the sung words light up (more if they lag the singing)
  lyrics_ahead: hide        # lines not sung yet: hide | dim | show
  party: false              # party mode: the logo cycles through every colour and motion
  logo_backdrop: "off"      # behind the logo: off | cover | random | a picture's file name
                            # (`tidal-shuffle backdrops add` puts pictures in ~/.config/tidal-shuffle/backdrops)
  backdrop_dim: 0.45        # how far the picture is dimmed, so the logo stands out (0 to 0.9)
  shuffle_view: "off"       # watch the next song being chosen: off | logo | side  (t toggles)
  glass: 0.22               # how much of the rain shows through the panels (0 = none)
  track_poll: 0.5           # seconds between checks for a new song while the screen is up
  mouse: true               # clickable keys and presets (hold Option, or Fn in Terminal, to select text)
  fps: 12

tidal:
  session_file: ~/.config/tidal-shuffle/tidal_session.json
  radio_limit: 50
  match_threshold: 0.72

# Presets are named bundles of the settings above. `tidal-shuffle presets`
# lists the built-in ones; add your own here.
presets:
  my-evening:
    description: "Mellow, mostly new-to-me"
    shuffle:
      strategy: discovery
      artist_cooldown: 8
    sources: [lastfm, deezer, tidal-radio]
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _as_theme(v, name: str) -> str:
    """A theme name: "Rosé Pine Moon", "tokyo_night" and "frappé" are all fine."""
    from .theme import THEMES

    key = re.sub(r"[\s_]+", "-", str(v).strip().lower().replace("é", "e"))
    key = {"catppuccin": "mocha", "catppuccin-mocha": "mocha", "catppuccin-macchiato": "macchiato",
           "catppuccin-frappe": "frappe", "catppuccin-latte": "latte", "tokyonight": "tokyo-night",
           "rosepine": "rose-pine", "gruvbox-dark": "gruvbox", "github": "github-dark", "onedark": "one-dark"}.get(key, key)
    if key not in THEMES:
        raise ConfigError(f"{name}: unknown theme {v!r}; one of {', '.join(THEMES)}")
    return key


def deep_merge(base: Mapping, override: Mapping) -> dict:
    out: dict = copy.deepcopy(dict(base))
    for k, v in (override or {}).items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ConfigError(f"{name}: expected true/false, got {value!r}")


def _as_number(value: Any, name: str, kind=float, minimum=None, maximum=None):
    try:
        if isinstance(value, bool):
            raise TypeError
        v = kind(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name}: expected a number, got {value!r}") from None
    if minimum is not None and v < minimum:
        raise ConfigError(f"{name}: must be >= {minimum}, got {v}")
    if maximum is not None and v > maximum:
        raise ConfigError(f"{name}: must be <= {maximum}, got {v}")
    return v


def _as_choice(value: Any, name: str, choices) -> str:
    v = str(value).strip().lower()
    if v not in choices:
        raise ConfigError(f"{name}: {value!r} is not one of {', '.join(choices)}")
    return v


def _fill(instance, data: Mapping, prefix: str, converters: dict) -> None:
    """Assign ``data`` keys onto ``instance`` using per-field converters."""
    if not isinstance(data, Mapping):
        raise ConfigError(f"{prefix}: expected a mapping, got {type(data).__name__}")
    valid = {f.name for f in fields(instance)}
    for key, value in data.items():
        if key not in valid:
            raise ConfigError(f"{prefix}.{key}: unknown option (valid: {', '.join(sorted(valid))})")
        conv = converters.get(key)
        if conv is None:
            continue  # nested dataclass handled by caller
        setattr(instance, key, conv(value, f"{prefix}.{key}"))


def _opt_str(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _vibe_from(data: Mapping, prefix: str) -> VibeParams:
    vibe = VibeParams()
    if not isinstance(data, Mapping):
        raise ConfigError(f"{prefix}: expected a mapping")
    for key, value in data.items():
        if key == "genres":
            if isinstance(value, str):
                value = [g.strip() for g in value.split(",") if g.strip()]
            if not isinstance(value, list):
                raise ConfigError(f"{prefix}.genres: expected a list")
            vibe.genres = [str(g) for g in value]
        elif key in ("min_popularity", "max_popularity"):
            vibe.__setattr__(key, None if value is None else int(_as_number(value, f"{prefix}.{key}", int, 0, 100)))
        elif key in ("energy", "valence", "acousticness", "danceability", "instrumentalness"):
            vibe.__setattr__(key, None if value is None else _as_number(value, f"{prefix}.{key}", float, 0.0, 1.0))
        elif key == "tempo":
            vibe.tempo = None if value is None else _as_number(value, f"{prefix}.{key}", float, 0.0)
        else:
            raise ConfigError(f"{prefix}.{key}: unknown vibe option")
    return vibe


def _sources_from(value: Any, name: str) -> list[str]:
    if isinstance(value, str):
        value = [s.strip() for s in value.split(",") if s.strip()]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{name}: expected a non-empty list of source names")
    out: list[str] = []
    for s in value:
        s = str(s).strip().lower().replace("_", "-")
        aliases = {"spotify": "spotify-app", "spotifyapp": "spotify-app", "spotify-desktop": "spotify-app",
                   "spotify-web": "spotify-api", "spotifyapi": "spotify-api", "last.fm": "lastfm",
                   "tidal": "tidal-radio", "tidalradio": "tidal-radio"}
        s = aliases.get(s, s)
        if s not in KNOWN_SOURCES:
            raise ConfigError(f"{name}: unknown source {s!r} (valid: {', '.join(KNOWN_SOURCES)})")
        if s not in out:
            out.append(s)
    return out


def _section(data: Mapping, name: str) -> Mapping:
    value = data.get(name) or {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name}: expected a mapping, got {type(value).__name__}")
    return value


ID_LOOKUPS = ("spotify-api", "listenbrainz", "spotify-ui", "odesli")


def _id_lookups_from(value: Any, name: str) -> list[str]:
    if isinstance(value, str):
        value = [s.strip() for s in value.split(",") if s.strip()]
    if not isinstance(value, list):
        raise ConfigError(f"{name}: expected a list")
    out = []
    for s in value:
        s = str(s).strip().lower()
        if s not in ID_LOOKUPS:
            raise ConfigError(f"{name}: unknown lookup {s!r} (valid: {', '.join(ID_LOOKUPS)})")
        if s not in out:
            out.append(s)
    return out


def _upgrade_legacy(data: dict) -> dict:
    """Translate the v0.1 config layout into the current one."""
    data = dict(data)
    legacy = data.pop("defaults", None)
    if isinstance(legacy, Mapping):
        shuffle = dict(_section(data, "shuffle"))
        player = dict(_section(data, "player"))
        spotify = dict(_section(data, "spotify"))
        if "batch_size" in legacy:
            shuffle.setdefault("candidates", legacy["batch_size"])
        if "seconds_before_end" in legacy:
            player.setdefault("handoff_seconds", legacy["seconds_before_end"])
        if "poll_interval" in legacy:
            player.setdefault("poll_interval", legacy["poll_interval"])
        if "min_popularity" in legacy:
            vibe = dict(spotify.get("vibe") or {})
            vibe.setdefault("min_popularity", legacy["min_popularity"])
            spotify["vibe"] = vibe
        data["shuffle"], data["player"], data["spotify"] = shuffle, player, spotify
    presets = data.get("presets")
    if isinstance(presets, Mapping):
        upgraded = {}
        for name, preset in presets.items():
            if isinstance(preset, Mapping) and "vibe" in preset:
                preset = dict(preset)
                vibe = preset.pop("vibe")
                preset = deep_merge(preset, {"spotify": {"vibe": vibe}})
            upgraded[name] = preset
        data["presets"] = upgraded
    return data


def _build(data: Mapping) -> AppConfig:
    cfg = AppConfig()
    data = dict(data or {})
    top_valid = {"sources", "shuffle", "player", "spotify", "lastfm", "deezer", "ui", "tidal", "presets"}
    for key in data:
        if key not in top_valid:
            raise ConfigError(f"{key}: unknown top-level option (valid: {', '.join(sorted(top_valid))})")

    if "sources" in data:
        cfg.sources = _sources_from(data["sources"], "sources")

    _fill(cfg.shuffle, data.get("shuffle") or {}, "shuffle", {
        "strategy": lambda v, n: _as_choice(v, n, STRATEGIES),
        "flow": lambda v, n: _as_choice(v, n, FLOWS),
        "energy": lambda v, n: None if v is None else _as_number(v, n, float, 0, 1),
        "energy_step": lambda v, n: _as_number(v, n, float, 0.01, 0.3),
        "blend": _as_bool,
        "candidates": lambda v, n: int(_as_number(v, n, int, 1, 500)),
        "avoid_repeats_for": lambda v, n: int(_as_number(v, n, int, 0, 100000)),
        "avoid_repeats_days": lambda v, n: _as_number(v, n, float, 0),
        "artist_cooldown": lambda v, n: int(_as_number(v, n, int, 0, 1000)),
        "allow_seed_artist": _as_bool,
        "seed": lambda v, n: _as_choice(v, n, SEED_MODES),
        "lookahead": lambda v, n: int(_as_number(v, n, int, 1, 20)),
        "min_duration": lambda v, n: _as_number(v, n, float, 0),
        "max_duration": lambda v, n: _as_number(v, n, float, 1),
        "allow_explicit": _as_bool,
    })
    _fill(cfg.player, data.get("player") or {}, "player", {
        "nowplaying_backend": lambda v, n: _as_choice(v, n, NOWPLAYING_BACKENDS),
        "handoff_seconds": lambda v, n: _as_number(v, n, float, 0, 120),
        "handoff_margin": lambda v, n: _as_number(v, n, float, 0, 10),
        "handoff_mode": lambda v, n: _as_choice(v, n, HANDOFF_MODES),
        "pause_before_end": lambda v, n: _as_number(v, n, float, 0, 10),
        "poll_interval": lambda v, n: _as_number(v, n, float, 0.2, 60),
        "near_end_poll_interval": lambda v, n: _as_number(v, n, float, 0.1, 10),
        "plan_after_seconds": lambda v, n: _as_number(v, n, float, 0, 600),
        "prepare_seconds": lambda v, n: _as_number(v, n, float, 0, 120),
        "play_strategy": lambda v, n: _as_choice(v, n, PLAY_STRATEGIES),
        "verify_seconds": lambda v, n: _as_number(v, n, float, 0, 60),
        "idle_poll_interval": lambda v, n: _as_number(v, n, float, 0.5, 120),
        "cdp_port": lambda v, n: int(_as_number(v, n, int, 1024, 65535)),
        "tidal_app": lambda v, n: str(v).strip() or "/Applications/TIDAL.app",
        "auto_relaunch": _as_bool,
        "adaptive_handoff": _as_bool,
        "tidal_queue": _as_bool,
        "terminal_keys": _as_bool,
        "media_keys": lambda v, n: _as_choice(v, n, MEDIA_KEY_MODES),
        "luna_port": lambda v, n: int(_as_number(v, n, int, 1, 65535)),
    })
    spotify = dict(_section(data, "spotify"))
    app_data = spotify.pop("app", None)
    vibe_data = spotify.pop("vibe", None)
    _fill(cfg.spotify, spotify, "spotify", {
        "client_id": _opt_str, "client_secret": _opt_str,
        "market": lambda v, n: (str(v).strip().upper() or "US"),
    })
    if app_data is not None:
        _fill(cfg.spotify.app, app_data, "spotify.app", {
            "enabled": _as_bool,
            "harvest": lambda v, n: int(_as_number(v, n, int, 1, 200)),
            "seed_method": lambda v, n: _as_choice(v, n, ("auto", "station", "autoplay")),
            "mute": _as_bool, "restore": _as_bool, "hide_window": _as_bool, "keep_hidden": _as_bool,
            "quit_after": lambda v, n: "auto" if str(v).strip().lower() == "auto" else _as_bool(v, n),
            "skip_delay": lambda v, n: _as_number(v, n, float, 0, 10),
            "launch_timeout": lambda v, n: _as_number(v, n, float, 1, 300),
            "max_seconds": lambda v, n: _as_number(v, n, float, 5, 600),
            "app_path": lambda v, n: str(v or "").strip(),
            "id_lookups": _id_lookups_from,
            "odesli_api_key": lambda v, n: str(v or "").strip(),
            "ui_label_prefix": lambda v, n: str(v),
            "ui_label_by": lambda v, n: str(v),
        })
    if vibe_data is not None:
        cfg.spotify.vibe = _vibe_from(vibe_data, "spotify.vibe")
    _fill(cfg.lastfm, data.get("lastfm") or {}, "lastfm", {"api_key": _opt_str, "expand_similar_artists": _as_bool})
    _fill(cfg.deezer, data.get("deezer") or {}, "deezer", {"enabled": _as_bool})
    _fill(cfg.ui, data.get("ui") or {}, "ui", {
        "screen": lambda v, n: _as_choice(v, n, ("full", "plain")),
        "lyrics": _as_bool,
        "lyrics_sources": lambda v, n: [_as_choice(x, n, ("tidal", "lrclib")) for x in (v if isinstance(v, list) else str(v).split(","))],
        "visualizer": _as_bool,
        "color": lambda v, n: _as_choice(str(v).lower(), n, ("auto", "truecolor", "256", "16")),
        "theme": lambda v, n: _as_theme(v, n),
        "logo_file": lambda v, n: str(v or ""),
        "cell_aspect": lambda v, n: _as_number(v, n, float, 0.2, 1.25),
        "artwork": _as_bool,
        "art_blocks": lambda v, n: _as_choice(str(v).lower(), n, ("quadrant", "half")),
        "backdrop": _as_bool,
        "rain": lambda v, n: _as_number(v, n, float, 0.0, 1.0),
        "logo_style": lambda v, n: _as_choice(str(v).lower(), n, ("theme", "muted", "filled", "wireframe", "pastel",
                                                                 "neon", "sunset", "ocean", "catppuccin", "mono")),
        "logo_motion": lambda v, n: _as_choice(str(v).lower(), n, ("float", "gentle", "lively", "shapes", "tide",
                                                                  "topple", "jelly", "magnet", "party", "still")),
        "lyrics_lead": lambda v, n: _as_number(v, n, float, -1.0, 3.0),
        "lyrics_ahead": lambda v, n: _as_choice(str(v).lower(), n, ("hide", "dim", "show")),
        "party": _as_bool,
        "logo_backdrop": lambda v, n: str(v or "off"),
        "backdrop_dim": lambda v, n: _as_number(v, n, float, 0.0, 0.9),
        "shuffle_view": lambda v, n: _as_choice(str(v).lower(), n, ("off", "logo", "side")),
        "glass": lambda v, n: _as_number(v, n, float, 0.0, 0.6),
        "track_poll": lambda v, n: _as_number(v, n, float, 0.2, 10),
        "mouse": _as_bool,
        "fps": lambda v, n: _as_number(v, n, float, 1, 30),
    })
    _fill(cfg.tidal, data.get("tidal") or {}, "tidal", {
        "session_file": lambda v, n: Path(str(v)).expanduser(),
        "radio_limit": lambda v, n: int(_as_number(v, n, int, 1, 100)),
        "search_limit": lambda v, n: int(_as_number(v, n, int, 1, 50)),
        "match_threshold": lambda v, n: _as_number(v, n, float, 0, 1),
    })
    presets = data.get("presets") or {}
    if not isinstance(presets, Mapping):
        raise ConfigError("presets: expected a mapping of name -> settings")
    cfg.presets = dict(presets)
    if cfg.shuffle.min_duration > cfg.shuffle.max_duration:
        raise ConfigError("shuffle.min_duration must be <= shuffle.max_duration")
    return cfg


def default_config_path() -> Path:
    """The config file used when none is given: $TIDAL_SHUFFLE_CONFIG or ~/.config/tidal-shuffle/config.yaml."""
    from . import paths

    env = os.environ.get("TIDAL_SHUFFLE_CONFIG")
    return Path(env).expanduser() if env else paths.CONFIG_FILE


def read_config_file(path: Optional[Path] = None) -> tuple[dict, Optional[Path]]:
    """Return the raw mapping from the YAML file (empty if none) and its path.

    Only the implicit default may be missing; a path you named explicitly (with
    ``--config`` or ``TIDAL_SHUFFLE_CONFIG``) must exist.
    """
    explicit = path is not None or bool(os.environ.get("TIDAL_SHUFFLE_CONFIG"))
    path = Path(path).expanduser() if path else default_config_path()
    if not path.exists():
        if explicit:
            raise ConfigError(f"{path}: config file not found")
        return {}, None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from None
    if not isinstance(data, Mapping):
        raise ConfigError(f"{path}: top level must be a mapping")
    return dict(data), path


def env_overrides(env: Mapping[str, str]) -> dict:
    out: dict = {}
    key = env.get("LASTFM_API_KEY")
    if key:
        out["lastfm"] = {"api_key": key}
    cid = env.get("SPOTIFY_CLIENT_ID") or env.get("SPOTIPY_CLIENT_ID")
    sec = env.get("SPOTIFY_CLIENT_SECRET") or env.get("SPOTIPY_CLIENT_SECRET")
    if cid or sec:
        out["spotify"] = {k: v for k, v in (("client_id", cid), ("client_secret", sec)) if v}
    return out


def all_presets(file_presets: Optional[Mapping] = None) -> dict:
    presets = dict(DEFAULT_PRESETS)
    for name, p in (file_presets or {}).items():
        presets[str(name)] = p
    return presets


def load_config(
    path: Optional[Path] = None,
    preset: Optional[str] = None,
    overrides: Optional[Mapping] = None,
    env: Optional[Mapping[str, str]] = None,
) -> AppConfig:
    """Build the effective configuration.

    Precedence (lowest to highest): built-in defaults, config file,
    environment variables, the chosen preset, explicit ``overrides`` (CLI).
    """
    env = os.environ if env is None else env
    raw, used_path = read_config_file(path)
    raw = _upgrade_legacy(raw)
    merged = deep_merge(raw, env_overrides(env))
    presets = all_presets(raw.get("presets") if isinstance(raw.get("presets"), Mapping) else {})
    if preset:
        if preset not in presets:
            raise ConfigError(f"Unknown preset {preset!r}. Available: {', '.join(sorted(presets))}")
        preset_data = dict(presets[preset] or {})
        preset_data.pop("description", None)
        merged = deep_merge(merged, preset_data)
    if overrides:
        merged = deep_merge(merged, dict(overrides))
    merged["presets"] = presets
    cfg = _build(merged)
    cfg.preset = preset
    cfg.config_path = used_path
    return cfg


def write_example_config(path: Optional[Path] = None, overwrite: bool = False) -> Path:
    path = Path(path).expanduser() if path else default_config_path()
    if path.exists() and not overwrite:
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_CONFIG)
    try:
        os.chmod(path, 0o600)  # it will hold API keys
    except OSError:
        pass
    return path


__all__ = [
    "AppConfig", "ConfigError", "DEFAULT_PRESETS", "EXAMPLE_CONFIG", "KNOWN_SOURCES",
    "PlayerConfig", "ShuffleConfig", "SpotifyAppConfig", "SpotifyConfig", "LastfmConfig",
    "DeezerConfig", "TidalConfig", "all_presets", "deep_merge", "load_config",
    "read_config_file", "write_example_config", "CONFIG_DIR", "CONFIG_FILE",
]
