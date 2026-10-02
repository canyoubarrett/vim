# Tidal Shuffle

A smarter shuffle for the **TIDAL macOS app**, powered by the **Spotify app
on your Mac**. Tidal Shuffle watches what TIDAL is playing, asks Spotify for
that song's radio, picks the next song from it, finds it on TIDAL and makes
TIDAL play it just before the current song ends. No Spotify
API key or Premium needed: it drives the Spotify desktop app the way you
would.

```
 TIDAL app ── what's playing ──►  tidal-shuffle  ──► Spotify app (hidden, muted)
     ▲                              │   1. find the song on Spotify
     │                              │   2. start its Song Radio, read what comes up
     │                              │   3. pick one, find it on TIDAL
     └──── "play this next" ────────┘   4. hand off just before the song ends
```

Last.fm, Deezer and TIDAL's own radio are there as fallbacks, or as the
main source if you prefer.

## What you need

* macOS (Sonoma, Sequoia or Tahoe) with the [TIDAL app](https://tidal.com/download)
* the Spotify app, logged in (a free account works)
* Python 3.10+
* `brew install media-control` (tells Tidal Shuffle what TIDAL is playing)

## Install

You need [Homebrew](https://brew.sh). Then, in Terminal:

```bash
git clone -b claude/blissful-pasteur-dw57cr https://github.com/canyoubarrett/vim.git ~/tidal-shuffle-src
cd ~/tidal-shuffle-src/tidal-shuffle
./install.sh
tidal-shuffle login         # TIDAL device-link login: approve the URL it prints
tidal-shuffle doctor        # checks every moving part and says how to fix it
```

`install.sh` makes a private Python environment in `.venv` (installing
Python 3.12 with Homebrew if yours is older than 3.10, as the one built
into macOS is), installs `media-control`, and links the `tidal-shuffle`
command into Homebrew's `bin`. Run it again after pulling updates. macOS
has no `pip` command, so use the installer, or a venv and
`python3 -m pip install -e .` if you prefer to do it by hand.

`tidal-shuffle config init` writes an optional config file to
`~/.config/tidal-shuffle/config.yaml`.

### macOS permissions

The first runs trigger three prompts, all under *System Settings → Privacy
& Security*. Allow them for the terminal app you run Tidal Shuffle from:

* **Automation → Spotify**: to start the song radio and read its songs.
* **Automation → System Events**: to keep Spotify's window hidden.
* **Accessibility**: to use Spotify's search page when the song cannot be
  found any other way (see below), and for the media keys while Tidal
  Shuffle's window is in front.

## Run it

```bash
tidal-shuffle run                         # follow TIDAL, keep picking
tidal-shuffle run --preset discovery      # deeper cuts
tidal-shuffle run --strategy top          # stay closest to Spotify's radio order
tidal-shuffle test                        # show the picks for the current song, play nothing
tidal-shuffle next                        # skip to a fresh pick right now
tidal-shuffle harvest "Midnight City" "M83"   # try the Spotify engine on any song
```

Play anything in TIDAL. A few seconds into the song, Tidal Shuffle asks
Spotify for the song's radio in the background, chooses the next song plus
two backups, and hands it to TIDAL. Skip to something else yourself and it
simply follows your choice.

**The screen.** In a terminal, `run` takes over the window, in
[Catppuccin](https://catppuccin.com) colours (Mocha; `ui.theme: macchiato`,
`frappe` or `latte` for the other flavors):

* at the top, the song playing, a progress bar, and the next pick;
* on the left, the Alter Era logo, floating: it bobs, drifts and tilts, its
  colour breathes, and its shadow shrinks as it rises. It is traced from the
  vector original (`assets/alter-era.svg`) into braille at whatever size the
  panel allows, so it stays crisp; if it looks too wide or narrow in your
  font, adjust `ui.cell_aspect` (a cell's width / height, 0.5 by default);
* on the right, the **lyrics**, scrolling with the song, the line being
  sung shown inverted on a solid bar (TIDAL's own synced lyrics first, then
  [LRCLIB](https://lrclib.net), free and keyless, which is searched again
  with a plainer title and the main artist when only plain lyrics turned
  up). Lyrics without timing get estimated timing: the lines are spread over
  the song after a short intro, longer lines getting more time and verse
  breaks counting as pauses, and the title says "timing estimated"; they are
  shown whole, in two columns split at a verse break when needed, with the
  estimated line highlighted, or scrolled along when even two columns are
  too few. Lyrics are cached in
  `~/.config/tidal-shuffle/cache/lyrics.json`. A song without lyrics gives
  the logo the whole width, and so does `l`; a narrow window gives the
  lyrics the whole width;
* at the bottom, the log and the keys.

`tidal-shuffle run --plain` (or `ui.screen: plain`) keeps the scrolling log
instead. `ui.logo_file` points at your own logo, an `.svg` (paths with
lines and arcs) or `---BIG---` / `---SMALL---` braille art; `ui.lyrics`, `ui.lyrics_sources`, `ui.visualizer` and `ui.fps`
tune the rest.

**Keys.** While `tidal-shuffle run` is in front:

| key | does |
|-----|------|
| `space` (or ⏯) | pause / play TIDAL |
| `n` (or ⏭) | skip to a fresh pick (chosen in the background if none is ready; the other keys keep working) |
| `b` (or ⏮) | TIDAL's previous track |
| `l` | logo alone / logo and lyrics |
| `q` | stop Tidal Shuffle |
| `?` | list the keys |

The keyboard's media keys normally go to TIDAL whatever window is in front.
While the Tidal Shuffle terminal window is the frontmost app, Tidal Shuffle
takes them over instead, so ⏭ means "next pick" rather than TIDAL's own next
track; in any other app they control TIDAL as usual. This needs the
Accessibility permission for your terminal (the same one the Spotify search
uses). Headphone and Touch Bar buttons always go straight to TIDAL.
`player.media_keys: always` takes the keys over everywhere, `off` never;
`player.terminal_keys: false` turns the letter keys off.

**Timing.** Tidal Shuffle opens the pick's page about ten seconds before
the end. About 0.8 s before the end it pauses TIDAL, so TIDAL can neither
move on to its own next song nor have the song cut short, and starts the
pick; there is a short silence while TIDAL loads it.
`player.handoff_mode: timed` instead presses play early enough to overlap
TIDAL's start-up delay (measured on your Mac, the median of the last five
hand-offs, plus `handoff_margin`; never less than `handoff_seconds`). That
is gapless when TIDAL is consistent but clips the end of a song when it is
not. The measurements are kept in `~/.config/tidal-shuffle/timing.json`.

Diagrams of how the shuffle works (PDF): [the loop](docs/shuffle-loop.pdf),
[from 30 radio songs to one pick](docs/shuffle-funnel.pdf),
[shuffle modes](docs/shuffle-modes.pdf), [hand-off timing](docs/shuffle-timing.pdf),
or [all four](docs/tidal-shuffle-how-it-works.pdf).

## How the Spotify engine works

1. **Find the TIDAL song on Spotify.** AppleScript can play a Spotify song
   but cannot search, so Tidal Shuffle needs the song's Spotify id. It tries,
   in the order set by `spotify.app.id_lookups`:
   * `spotify-api`: the Spotify Web API, if you configured credentials and
     the app's owner has Premium (required since 2026);
   * `listenbrainz`: ListenBrainz's free Spotify-id index (no key);
   * `spotify-ui`: **Spotify's own search page**. Tidal Shuffle opens
     `spotify:search:<song artist>`, finds the button labelled
     "Play <song> by <artist>" through macOS Accessibility, presses it with
     Spotify muted, and reads the id;
   * `odesli`: song.link, only with an API key (its free API closed on
     2026-07-31).

   Ids found are cached for six months in `~/.config/tidal-shuffle/cache/`.
2. **Harvest the song radio.** Spotify is launched hidden if needed and
   muted. Tidal Shuffle starts the song's Song Radio, skips through it and
   reads each song (about half a second per song; ads are waited out). If
   the radio does not start, it falls back to Spotify's autoplay.
3. **Check and clean up.** It confirms Spotify started the song it asked
   for, pauses Spotify and restores its volume. If Tidal Shuffle opened
   Spotify, it quits it again. While Spotify is open, macOS sends your
   keyboard's play/pause key to Spotify instead of TIDAL. Ctrl+C mid-harvest
   also puts Spotify back.

Spotify is never interrupted: if you are listening to something in Spotify,
the harvest is skipped and the next source is used. Note that the harvested
songs may show up in Spotify's "recently played".

**Check it on your Mac:**

```bash
tidal-shuffle spotify-ui                             # can Tidal Shuffle see Spotify's interface?
tidal-shuffle spotify-ui --find "Midnight City - M83"   # search, press play (muted), report the id
tidal-shuffle harvest "Midnight City" "M83"           # full harvest with a log of each step
```

If Spotify is not in English, set `spotify.app.ui_label_prefix` and
`ui_label_by` to the words your Spotify uses on track buttons. For
example, a Spanish Spotify says "Reproducir *song* de *artist*". Use
`"Reproducir "` and `" de "`.

## How TIDAL is controlled

TIDAL has no public playback API, and `tidal://track/<id>` links only
*open* a song, they never start it. The TIDAL app is a shell around TIDAL's
web player. When it is launched with a debug port, Tidal Shuffle can open the
song's page inside the app, press its play button and read the player bar
to confirm the switch.

`tidal-shuffle run` takes care of this. If TIDAL is running without the
port, Tidal Shuffle quits and reopens it once; your login is kept. To do it
yourself:

```bash
osascript -e 'tell application "TIDAL" to quit'
open -a /Applications/TIDAL.app --args --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1
```

The port only listens on your own Mac (127.0.0.1). Set
`player.auto_relaunch: false` to launch TIDAL yourself. One-shot commands
like `next` never relaunch TIDAL.

Without the port, Tidal Shuffle falls back to opening the song with
`tidal://track/<id>` and asks you to press play.

With the port, a song is started by opening its page and pressing its play
button (its row in the track list, or the page's own Play button). If no
button can be found, or pressing it does not start the song, Tidal Shuffle
asks TIDAL's play queue to play it directly, and keeps using whichever
worked. `tidal-shuffle playtest "Title - Artist"` shows which method works
on your Mac. If none does, run `tidal-shuffle inspect "Title - Artist"`: it
opens that song's page and prints what the play logic sees there (paste it
into a bug report). The selectors are in `src/tidal_shuffle/tidal/cdp.py`.

**Gapless (optional):** with the community mod
[TidaLuna](https://github.com/Inrixia/TidaLuna) and its API plugin, Tidal
Shuffle hands each pick to TIDAL's own queue as the *next* track instead.
`player.tidal_queue: true` tries the same with the stock app's queue; it is
off because the stock app shows the pick as a blank entry and stops there.
Either way, if TIDAL has not moved on to the queued pick a couple of seconds
after the song ends, Tidal Shuffle starts it itself.

## Sources

| source        | what it is                                                                    | needs                    |
|---------------|-------------------------------------------------------------------------------|--------------------------|
| `spotify-app` | the Spotify app's Song Radio, as described above                              | Spotify app, logged in   |
| `spotify-api` | Spotify Web API (recommendations only for pre-2024 apps; otherwise related artists or same-genre search) | client id + secret, Premium owner |
| `lastfm`      | Last.fm `track.getSimilar`, widened to similar artists for obscure songs       | free API key             |
| `deezer`      | Deezer's keyless artist radio                                                  | nothing                  |
| `tidal-radio` | TIDAL's own track radio                                                        | your TIDAL login         |

Sources are tried in the order listed under `sources:`. The first one that
returns songs wins; `shuffle.blend: true` merges them all.
`tidal-shuffle sources --seed "Song - Artist"` shows what each one suggests.

## Choosing how it shuffles

Settings live under `shuffle:` in the config file. These have command-line
flags too: `--strategy`, `--artist-cooldown`, `--allow-seed-artist`,
`--seed-mode` and `--blend`.

* `strategy`: `top` (Spotify's radio order), `weighted` (random, biased
  toward the top; the default), `random`, `discovery` (deeper, less popular
  picks)
* `artist_cooldown`: no artist twice within N songs (5). If that leaves
  nothing to play it is relaxed, but the next point never is.
* `allow_seed_artist`: may the next song be by the artist playing now? Off
  by default: never the same artist back to back. Every credited artist
  counts ("Santana feat. Buddy Miles" is not played after Buddy Miles), on
  both the Spotify credit and the TIDAL track. If a source has nothing else,
  the next source is asked instead.
* `avoid_repeats_for` / `avoid_repeats_days`: how long a song you heard,
  picked or chosen yourself, is kept out
* `seed`: `current` (each song seeds the next), `anchor` (stay around the
  song you started with), `window` (seed from the last few songs; Spotify
  API only)
* `candidates`, `lookahead`, `min_duration`, `max_duration`, `allow_explicit`

Presets bundle these. `tidal-shuffle presets` lists `balanced`, `familiar`,
`discovery`, `wander`, `anchor`, `spotify-only`, `lastfm-only`,
`tidal-only` and the Spotify API tuning presets. Add your own under
`presets:`.

Picks are matched to TIDAL by ISRC when available and otherwise by title,
artist and length. Live, karaoke and remix versions are rejected unless the
pick asked for them.

## All commands

| command                         | what it does                                              |
|---------------------------------|-----------------------------------------------------------|
| `run [--plain]`                 | follow TIDAL and keep picking, with the logo and lyrics   |
| `test`                          | plan once for the current song, play nothing              |
| `next`                          | pick and start a next song right now                      |
| `harvest "Title" "Artist"`      | run the Spotify engine once and list what it found        |
| `spotify-ui [--find "A - B"]`   | check that the Spotify app's interface can be used        |
| `doctor`                        | check dependencies, permissions, logins and the debug port |
| `login [--force]`               | TIDAL device-link login                                   |
| `presets`                       | list presets                                              |
| `sources --seed "A - B"`        | what every source suggests for a song                     |
| `history [--clear] [-n N]`      | songs heard and picked                                    |
| `config init / show / path`     | manage the config file                                    |
| `now`                           | what each now-playing reader reports                      |
| `playtest [id or "A - B"]`      | make TIDAL play a track and report which method worked    |
| `inspect [id or "A - B"]`       | dump the TIDAL player page (optionally a song's page)     |

Commands that read settings take `--config PATH`; `TIDAL_SHUFFLE_CONFIG` sets the default.

## Troubleshooting

* **"could not find … on Spotify"**: none of the id lookups found the song.
  Run `tidal-shuffle spotify-ui --find "Song - Artist"`. If it reports that
  Accessibility is missing, allow your terminal and restart it. If it sees
  no track buttons, your Spotify may use other button words (see above).
* **"macOS denied Automation access to Spotify"**: System Settings →
  Privacy & Security → Automation → your terminal → Spotify.
* **Spotify pops up**: Tidal Shuffle hides it right after it comes forward.
  That needs the System Events permission.
* **Songs open in TIDAL but do not start**: TIDAL is not reachable on its
  debug port. Let `run` relaunch it, or launch it as shown above.
* **Nothing is detected as playing**: install `media-control`.
  `nowplaying-cli` also works, but it cannot always tell TIDAL from Spotify.
* **Picks feel samey**: try `--strategy discovery`, raise `artist_cooldown`,
  or blend in `lastfm` and `deezer`.

## Development

```bash
python3 -m pip install -e ".[dev]"   # inside .venv
pytest                                    # unit tests, any platform
cd tests/e2e/fake_tidal && npm install    # once, for the end-to-end tests
pytest tests/e2e                          # about a minute
```

The end-to-end tests run the real `tidal-shuffle run`, `doctor`, `test`,
`harvest`, `playtest` and other commands against a simulated Mac. TIDAL is
a web player in jsdom, reached over the DevTools protocol. Fake
`osascript`, `media-control`, `open` and `pgrep` binaries stand in for
Spotify and macOS. The macOS-only pieces still need the real thing:
`doctor`, `spotify-ui`, `harvest` and `playtest` are the on-device checks.

## License

MIT
