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

**The app.** `install.sh` also makes **Tidal Shuffle.app** (in `/Applications`, or
`~/Applications`), with the Alter Era mark as its icon: open it from Spotlight or
Launchpad, or keep it in the Dock, and it starts the full-screen view in a Terminal
window. `tidal-shuffle app` makes it again; `--terminal iTerm` (or Ghostty, WezTerm)
opens it there instead, and `--preset NAME` starts it with a preset. The app runs
this installed copy, so `tidal-shuffle update` keeps it current.

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

* at the top, the album cover (drawn with quarter-block characters, 2x2
  pixels per cell, and dithered to the palette in 256-colour terminals such
  as Terminal.app; `ui.art_blocks: half` if your font lacks ▚ ▞ ▙ ▟; cached in
  `~/.config/tidal-shuffle/cache/art`; `ui.artwork: false` turns it off),
  the song playing with a ▶ PLAYING / ⏸ PAUSED badge, a progress bar, the
  next pick, and the flow with its target energy as a meter;
* the title in the logo's colours (sun yellow, peach, coral, purple, cyan,
  teal), the gradient drifting slowly along it;
* behind everything, one even colour (the panels' own) and rain: two depths of drops, the far ones dim and slow,
  the near ones brighter and faster, slanting a little in the wind, drawn in
  braille dots so they fall smoothly. It is a drizzle for calm songs and
  heavier for energetic ones (following the flow's target energy), and it
  falls in slow motion while paused. It is faint, barely lighter than the
  sky (`ui.rain`, 0 to 1, sets how visible; 0.3 by default), and stays
  behind the panels: inside them there is no rain, only a faint tint of the
  sky (`ui.backdrop: false` turns the rain off, `ui.glass` sets the tint,
  0 to 0.6);
* on the left, the Alter Era logo, as big as the panel allows, floating: it
  bobs, drifts and tilts, its colour breathes, and its shadow shrinks as it
  rises. It is traced from the
  vector original (`assets/alter-era.svg`) into braille at whatever size the
  panel allows, so it stays crisp; if it looks too wide or narrow in your
  font, adjust `ui.cell_aspect` (a cell's width / height, 0.5 by default);
* on the right, the **lyrics**, scrolling with the song, the line being
  sung in bright bold text. Every source is asked (TIDAL's own lyrics, then
  [LRCLIB](https://lrclib.net), free and keyless, searched again with a
  plainer title and the main artist when only plain lyrics turned up), and
  when two of them have synced lyrics that agree (same recording, no steady
  offset), their timings are averaged line by line: two independent
  timings are closer to the singing than either; word timing (enhanced LRC)
  is taken from whichever has it, and when they disagree, TIDAL's is kept.
  As each word is sung it turns inverted (dark text on the accent colour),
  so the inversion sweeps along the line in time with the song. Lines not
  sung yet are hidden by default, so nothing shows during an intro but a
  count-in (the settings can dim or show them). Lyrics without any timing
  are never highlighted (a guess would be wrong as often as right): they are
  shown whole, in two columns split at a verse break when needed, and the
  title says "no timing"; when even two columns are too few they scroll
  along with the song and the title says "scrolling by estimate". Lyrics
  are cached in
  `~/.config/tidal-shuffle/cache/lyrics.json`. A song without lyrics gives
  the logo the whole width, and so does `l`; a narrow window gives the
  lyrics the whole width;
* **Up next**: the pick and its backups with their energy, and what played
  recently, at the bottom beside the log (the bottom row splits in two);
* at the bottom, the log and a row of key chips, which can be clicked.

Nothing on the screen cuts: when a song ends, a hand-off starts or TIDAL
shows a different song, its lyrics fade out at once (the screen checks for a
new song every half second, `ui.track_poll`). If the next song has lyrics,
they fade in where the old ones were; if it has none, the lyrics panel fades
away and the logo glides over to fill the space, and glides back when lyrics
return. Covers dissolve into each other and the preset menu fades in and out.
All of this is drawn cell by cell in true colour; if your terminal struggles
to keep up (Terminal.app can), lower `ui.fps` or turn off `ui.backdrop`.

**Colours in Terminal.app.** Terminal.app always shows 256 colours, but it
never tells programs whether it can show 24-bit ("true") colour, and when
it cannot, 24-bit colour codes leave the screen without colour. So in
Terminal.app, Tidal Shuffle uses 256 colours, with every theme colour matched
to the closest one in Terminal's palette by eye (dark blue-greys stay dark
greys instead of turning black). To see what your terminal can show, run:

```bash
tidal-shuffle colors
```

It prints rows of colour swatches. If the true-colour rows show the theme's
colours and a smooth blend, set `ui: {color: truecolor}` in the config (or
try it once with `tidal-shuffle run --color truecolor`). If no row shows
colours, check Terminal's profile, and that `NO_COLOR` is not set in your
shell (`run` also says so in its log). iTerm2, Ghostty, WezTerm and kitty
announce true colour and show the exact colours.

**Settings menu.** Press Esc (or click `esc settings`) for the settings.
The menu takes the left half and a live preview the right: whatever the
cursor is on is shown at once (a theme recolours the whole screen, a logo
colour or motion plays in the preview, the shuffle tree shows the choice
being made), Enter or a click chooses it, and Esc puts back whatever was
only previewed. Choices are remembered between runs (in
`~/.config/tidal-shuffle/ui.json`; they override the config file's `ui:`
section):

* **Theme** for the whole screen (`ui.theme`), blending smoothly from one to
  the next: Catppuccin Mocha, Macchiato, Frappé and Latte, Nord, Dracula,
  Gruvbox and Gruvbox Light, Tokyo Night and Tokyo Night Storm, Solarized
  Dark and Light, One Dark, Rosé Pine, Rosé Pine Moon and Rosé Pine Dawn,
  Everforest, Kanagawa, Monokai, GitHub Dark;
* **Logo backdrop** (`ui.logo_backdrop`): a picture behind the logo,
  dimmed so the logo stands out, wide ones panning slowly from side to
  side. Two sliders under **Backdrop look** (← → on them) set the zoom
  (`ui.backdrop_zoom`: 1 fills the panel, down to 0.3 zooms out to show more
  of the picture with a soft blurred copy around it, up to 2 zooms in) and
  how far it is dimmed (`ui.backdrop_dim`); two more set how big the logo
  stands on it (`ui.logo_size_stage`: smaller, fighter-sized, by default) and
  how far down the stage's floor is (`ui.logo_floor`). The picture can be: the album cover of the song playing (softened),
  any picture of your own, or a different one of yours with each song. Add
  pictures (files, folders or zips) with
  `tidal-shuffle backdrops add ~/Downloads/stages.zip`; they are kept in
  `~/.config/tidal-shuffle/backdrops`; in the settings they are folded
  away behind one entry, **Your pictures**: Enter unfolds them (and folds
  them away again), and a picture is shown once the cursor rests on it
  (`tidal-shuffle backdrops list` lists them). In the settings, ← → jump
  from section to section;
* **Picture detail** (`ui.picture_detail`), for backdrops and the big cover,
  in steps: Low (half blocks, 1×2 pixels a character), Medium (quarter
  blocks, 2×2), High (sixth blocks, 2×3), Highest (eighth blocks, 2×4: as
  fine as characters go) and Dots (braille, 2×4, grainier). Pictures are
  drawn from the full-size original. High and Highest use newer block
  characters that most fonts lack (Terminal.app shows boxes with question
  marks), so they are only offered in terminals that draw them themselves:
  Ghostty and kitty (both), WezTerm and iTerm2 (High). If your font has
  them, `ui.block_glyphs: all` offers them anyway. For more pixels still, make the terminal's
  font smaller (⌘−): every character is that many more pixels;
* **Logo version** (`ui.logo_version`): the line drawing, or the flat
  version (solid shapes in the logo's colours, no outlines), and **Logo
  detail** (`ui.logo_detail`): how finely the filled colours are drawn, in
  the same steps (the preview shows the logo filled while you choose);
* **Logo size** (`ui.logo_size`): the logo on its own, from as big as fits
  down;
* **Spotify API**: type or paste the client ID and client secret of your
  Spotify developer app (developer.spotify.com/dashboard → your app →
  Settings). They are kept in `~/.config/tidal-shuffle/spotify.json`,
  readable only by you, take effect at once, and are checked with Spotify
  (the result shows beside **Check**); the secret is never shown. They
  replace `spotify.client_id` / `client_secret` in the config file; the
  `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` environment variables still
  win. While typing, keys are text (Enter saves, Esc cancels, Ctrl+U clears);
* **Party mode** (`ui.party`): the logo glides through every colour scheme,
  each shape a little behind the next so the colours ripple across it, while
  its pieces drift apart and back together and now and then topple;
* **Shuffle tree** (`ui.shuffle_view`, or `t`): watch the next song being
  chosen, in place of the logo, or (130 columns or more) beside it. The tree unfolds step
  by step as the work happens: the song it starts from, each source asked
  (how many songs, how long, or why it was skipped), the pool and what was
  left out (repeats, songs just played, look-alikes), the flow and its
  target energy, the order and the top candidates with their scores, each
  candidate looked up on TIDAL (found, or why not: not on TIDAL, heard
  recently, same artist as now, explicit, too long), and the pick with its
  backups;

* **Logo colours**: the theme's lilac, a muted grey one, the logo's own
  colours filled in (drawn with quarter blocks, with dark edges) or as
  outlines, pastel, neon outlines, sunset, ocean, the theme's Catppuccin
  accents, or black and white (`ui.logo_style`);
* **Logo motion** (`ui.logo_motion`): float, gentle, lively, still;
  shapes (every shape floats on its own); tide (slowly drifts apart and
  back together); topple (a long, even sway: as it leans over the pieces
  slide away, each following the lean a little late, the upper ones
  furthest, and they roll back together as it rights itself); jelly (the pieces hang on springs, lag
  behind the logo's movement and wobble); magnet (pushed apart now and then,
  snapping back). The pieces move on damped springs, so they have weight:
  they trail behind, overshoot a little and settle; and switching eases
  from one motion into the other;
* **Rain**: off, faint, soft or clear (`ui.rain`);
* **Lyrics not sung yet**: shown to read ahead (the default), dimmed, or
  hidden until each line is sung (`ui.lyrics_ahead`);
* **Lyrics timing**: how early the sung words light up, if they lag or run
  ahead of the singing (`ui.lyrics_lead`, 0.55 s by default).

**Presets menu.** Press `p` (or click the `p presets` chip) to open the
preset menu over the logo and lyrics. Presets are grouped (energy & sound,
how picks are chosen, sources, Spotify tuning, then your own), each with its
flow and pick style and a one-line description; ● marks the one in use.
Move with ↑ ↓ or the mouse wheel and apply with Enter, or just click one.
The switch happens straight away: the next song is chosen again with the
new preset (unless it is already starting), and the header shows the new
preset's name. Esc or `p` closes the menu. Clicking needs mouse reporting,
which is on by default (`ui.mouse: false` turns it off); to select text
in the window while it is on, hold Option (iTerm2) or Fn (Terminal).

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
| `f` | next shuffle flow (radio → rising → falling → steady → soundscape → vibe) |
| `p` | open / close the presets menu (↑ ↓ or wheel, Enter or click to apply, Esc to close) |
| `l` | logo alone / logo and lyrics |
| `a` | the album cover, big, in place of the logo (and back) |
| `esc` | the settings menu (logo colours and motion, rain, lyrics) |
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

## Shuffle flows: how each song follows the last

The song radio decides which songs are candidates; the **flow** decides which
of them suits the moment, from each song's audio features (energy, mood,
danceability, acousticness, instrumentalness, tempo):

| flow | preset | what it does |
|------|--------|--------------|
| `radio` | `radio` | the song radio as it is (the default) |
| `rising` | `warm-up` | each song a little more energetic than the last |
| `falling` | `wind-down` | each song a little calmer than the last |
| `steady` | `steady`, `chill` | one energy level: the first song's, or `--energy 0.7` |
| `soundscape` | `soundscape` | stays close to the *first* song's overall sound (acoustic or electronic, instrumental, tempo, mood) without drifting |
| `vibe` | `vibe` | stays close to the *current* song's mood and energy |

```bash
tidal-shuffle run --flow rising              # or --preset warm-up
tidal-shuffle run --flow steady --energy 0.4
tidal-shuffle run --preset soundscape
```

Press `f` while running to switch flows; the next pick is chosen again
straight away, and the header shows the flow and its target energy
(`rising → energy 0.62`) and each pick's energy.
`shuffle.energy_step` (0.06) sets how fast `rising` and `falling` move.

Spotify no longer gives audio features to new apps, so they come from
[ReccoBeats](https://reccobeats.com) (free, no key), looked up by the
Spotify ids the radio harvest already has, and cached for half a year.
Songs without features are still possible but rarely picked; when none of
the candidates has any, or ReccoBeats cannot be reached, the flow steps
aside and the plain song radio is used (the log says so).

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
* `plan_ahead` (on): while the pick is still to come, the song after it is
  chosen too, in the background, so when the pick starts its own next song
  is ready at once: pressing next again and again never waits
* `lookup_workers` (4): candidates are looked up on TIDAL this many at a
  time (taken strictly in order), instead of one after another

Presets bundle these; pick one with `--preset NAME`, or while running from
the presets menu (`p`). `tidal-shuffle presets` lists `balanced`, `familiar`,
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
| `colors`                        | show which colours this terminal can display              |
| `backdrops add PATH...`         | add pictures (files, folders, zips) to show behind the logo |
| `backdrops list`                | list the pictures                                         |
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
* **Spotify pops up**: with `spotify.app.keep_hidden: true` (the default)
  a guard hides Spotify within about a tenth of a second whenever it shows
  up while Tidal Shuffle is using it (or started it), and hands the focus
  back to the app you were in, so your keys keep working. A Spotify you
  opened yourself is left alone between harvests. The `spotify-ui` lookup
  needs Spotify's search page on screen, so it is skipped while Spotify is
  kept hidden; set `keep_hidden: false` to allow it.
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
