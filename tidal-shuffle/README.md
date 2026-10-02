# Tidal Shuffle

A smarter shuffle for the **TIDAL macOS app**. It watches what TIDAL is
playing, picks a related next song from the recommendation source you prefer
(the Spotify desktop app's song radio, the Spotify Web API, Last.fm, Deezer or
TIDAL's own radio), and makes TIDAL play it when the current song ends. Run it
once and the music never stops.

```
┌──────────────────────┐   now playing (media-control / TIDAL's own player page)
│   TIDAL macOS app    │ ─────────────────────────────────────────────┐
│   (the player)       │                                              ▼
└──────────▲───────────┘                                   ┌───────────────────────┐
           │  "play this next"                             │     tidal-shuffle     │
           │  (DevTools protocol, or TidaLuna queue)       │  1. seed = current    │
           └───────────────────────────────────────────────│  2. ask sources       │
                                                           │  3. filter + pick     │
   sources: spotify-app · spotify-api · lastfm · deezer    │  4. match on TIDAL    │
            tidal-radio                                    │  5. hand off in time  │
                                                           └───────────────────────┘
```

## Requirements

* macOS (Sonoma, Sequoia or Tahoe) with the [TIDAL desktop app](https://tidal.com/download)
* Python 3.10+
* `brew install media-control` — reads what macOS reports as "now playing"
  (`nowplaying-cli` works as a fallback, but cannot tell apps apart)
* Optional, pick any:
  * the **Spotify desktop app**, logged in (free works) — for the `spotify-app` source
  * a free [Last.fm API key](https://www.last.fm/api/account/create) — for `lastfm`
  * Spotify Web API credentials — for `spotify-api` (see the note below)
  * nothing at all — `deezer` and `tidal-radio` need no accounts

## Install

```bash
cd tidal-shuffle
pip install -e .            # or: pipx install ./tidal-shuffle
brew install media-control
tidal-shuffle login         # TIDAL device-link login, opens a URL
tidal-shuffle config init   # writes ~/.config/tidal-shuffle/config.yaml
tidal-shuffle doctor        # checks every moving part and tells you what to fix
```

Put your optional keys in the config file (or in the environment:
`LASTFM_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`). The file
holds secrets, so `chmod 600 ~/.config/tidal-shuffle/config.yaml`.

## Run it

```bash
tidal-shuffle run                      # follow TIDAL, keep picking
tidal-shuffle run --preset discovery   # deeper cuts
tidal-shuffle run --source spotify-app,lastfm --strategy top
tidal-shuffle test                     # dry run: show the picks for the current song
tidal-shuffle next                     # skip to a fresh pick right now
```

Play anything in TIDAL. A few seconds into the song, Tidal Shuffle plans the
next one (and two backups), opens its page in TIDAL shortly before the end,
and presses play about two seconds before the song finishes. If you skip to
something else yourself, it simply reseeds from your choice.

### How TIDAL is controlled (read this once)

TIDAL has no public playback API, and `tidal://track/<id>` links only
*navigate* the app to a song, they never start it. The reliable way to start a
specific song in the stock app is Chromium's DevTools Protocol: the app is an
Electron shell around the TIDAL web player, and when launched with a debug
port, Tidal Shuffle can open the song's page and click its play button from
the inside, then confirm the switch from the player footer.

`tidal-shuffle run` takes care of this: if TIDAL is running without the port,
it quits and relaunches it once (your login persists). To do it by hand:

```bash
osascript -e 'tell application "TIDAL" to quit'
open -a /Applications/TIDAL.app --args --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1
```

The port only listens on 127.0.0.1. Set `player.auto_relaunch: false` if you
would rather launch TIDAL yourself.

If TIDAL is not reachable this way, Tidal Shuffle falls back to opening the
song with `tidal://track/<id>` and tells you to press play. Run
`tidal-shuffle playtest` to see which method works on your machine, and
`tidal-shuffle inspect` to dump the player page if the web player's markup has
changed (the selectors live in `src/tidal_shuffle/tidal/cdp.py`).

**Optional, gapless:** if you run the community mod
[TidaLuna](https://github.com/Inrixia/TidaLuna) with its API plugin, Tidal
Shuffle detects it and instead hands the pick to TIDAL's own queue as the
*next* track, so TIDAL crossfades into it exactly like a normal queue.

## Sources

| source        | what it is                                                                                           | needs                                  |
|---------------|------------------------------------------------------------------------------------------------------|----------------------------------------|
| `spotify-app` | Starts the song's **Song Radio** in the Spotify desktop app (muted, hidden) and reads what comes up  | Spotify app, logged in                 |
| `spotify-api` | Spotify Web API: recommendations when your app still has them, else "<song> Radio" playlist, related artists, same-genre search | client id + secret |
| `lastfm`      | `track.getSimilar`, widened to similar artists' top tracks for obscure songs                         | free API key                           |
| `deezer`      | Deezer's keyless artist radio and related artists                                                    | nothing                                |
| `tidal-radio` | TIDAL's own track radio                                                                              | your TIDAL login                       |

Sources are tried in the order listed under `sources:` in the config; the
first one that returns candidates wins. Set `shuffle.blend: true` to merge
them all. `tidal-shuffle sources --seed "Song - Artist"` shows what each would
suggest. The Spotify desktop harvest is the richest free source and the one
that behaves most like Spotify's own radio.

### Using the Spotify desktop app as the engine

The first time, macOS asks you to allow your terminal to control Spotify
(Automation) and, for hiding its window, System Events (Accessibility). Both
are in *System Settings → Privacy & Security*. The harvest takes about half a
second per song; it runs early in the current TIDAL song so there is plenty of
time. Spotify is muted and paused again afterwards; set
`spotify.app.quit_after: true` if you prefer it quit. While Spotify is
harvesting, macOS briefly reports *it* as the now-playing app — Tidal Shuffle
reads TIDAL's own player page when the debug port is up, so this never
confuses it.

Try it directly: `tidal-shuffle harvest "Midnight City" "M83"`.

Without Spotify API credentials, the current TIDAL song is mapped to its
Spotify id through [Odesli](https://odesli.co) (song.link), which is keyless
and rate limited to about ten lookups a minute, enough for one per song.

### Spotify Web API, honestly

Spotify removed the recommendations and related-artists endpoints for apps
created after November 2024 and, since early 2026, requires a Premium account
to use development-mode apps. Tidal Shuffle probes what your app can reach and
degrades automatically; with a new app you get the "<song> Radio" playlist
when search still returns it, related artists or same-genre tracks, and the
artist's own top tracks. The `energy` / `mood` / `genres` tuning and the
`late-night-drive`, `workout` and `chill` presets only act on apps that still
have the recommendations endpoint. The `spotify-app` source needs none of
this.

## How it shuffles

Everything lives under `shuffle:` in the config (or on the command line):

* `strategy` — `top` (closest to the seed), `weighted` (random, biased toward
  relevance; the default), `random` (uniform), `discovery` (favours deeper,
  less popular picks)
* `artist_cooldown` — no artist twice within N picks; `allow_seed_artist`
  decides whether the next song may be by the artist now playing
* `avoid_repeats_for` / `avoid_repeats_days` — the play history window
* `seed` — `current` (each pick seeds the next: a random walk), `anchor`
  (stay in orbit around the song you started with), `window` (seed from the
  last few songs together; Spotify API only)
* `candidates`, `lookahead`, `min_duration`, `max_duration`, `allow_explicit`

Presets bundle these: `tidal-shuffle presets` lists `balanced`, `familiar`,
`discovery`, `wander`, `anchor`, `spotify-only`, `lastfm-only`, `tidal-only`
and the Spotify-tuning ones. Define your own under `presets:` in the config.

Picks are fuzzy-matched to TIDAL by ISRC first and then by title, artist and
duration, with live, karaoke and remix versions rejected unless the source
asked for them.

## All commands

| command                     | what it does                                                  |
|-----------------------------|---------------------------------------------------------------|
| `run`                       | follow TIDAL and keep picking                                 |
| `test`                      | plan once for the current song, play nothing                  |
| `next`                      | pick and start a next song right now                          |
| `doctor`                    | check dependencies, permissions, logins, the debug port       |
| `login [--force]`           | TIDAL device-link login                                       |
| `presets`                   | list presets                                                  |
| `sources --seed "A - B"`    | what every source suggests for a song                         |
| `history [--clear] [-n N]`  | what Tidal Shuffle played                                     |
| `config init|show|path`     | manage the config file                                        |
| `now`                       | what each now-playing backend reports                         |
| `playtest [id | "A - B"]`   | try to make TIDAL play a track, report which method worked    |
| `inspect`                   | dump the TIDAL player page (for fixing selectors)             |
| `harvest "Title" "Artist"`  | run the Spotify desktop harvest once                          |

## Troubleshooting

* **"TIDAL is not reachable over its debug port"** — quit TIDAL and let
  `tidal-shuffle run` relaunch it, or launch it yourself with the command
  above. `tidal-shuffle doctor` shows the state.
* **Songs are opened but do not start** — you are on the deep-link fallback;
  see the previous point. `tidal-shuffle playtest` prints what each method
  does.
* **"could not map … to a Spotify track"** — the `spotify-app` source needs the
  song's Spotify id. It comes from the Spotify API when configured, otherwise
  from Odesli; very new or regional releases may be missing there, in which
  case the next source takes over.
* **"macOS denied Automation access to Spotify"** — System Settings →
  Privacy & Security → Automation → your terminal → Spotify.
* **now playing shows nothing** — install `media-control`; if you only have
  `nowplaying-cli`, make sure nothing else is playing, because it cannot tell
  TIDAL and Spotify apart.
* **Picks are not great** — try `--preset discovery`, raise
  `artist_cooldown`, put `spotify-app` first in `sources`, or use
  `--strategy top` for a tighter radio.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite runs on any platform; macOS-only parts (osascript, the
DevTools driver, media-control) are exercised through fakes. `tidal-shuffle
doctor`, `now`, `playtest`, `inspect` and `harvest` are the on-device checks.

## License

MIT
