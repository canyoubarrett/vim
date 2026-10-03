# Tidal Shuffle: developer handoff

Everything needed to pick up development of Tidal Shuffle: what it is, how it
is built, how the pieces fit together at run time, how to work on it safely,
and what is open. Written at version **0.13.0** (3 October 2026).

For *using* the app, see the README and the manuals in `docs/manual/`
(one-page operation card and the 15-page engineering and operation manual).
This document is for whoever changes the code next.

---

## 1. What it is

A smarter shuffle for the **TIDAL desktop app on macOS**. TIDAL's shuffle plays
a list in random order; Tidal Shuffle instead watches the song TIDAL is playing,
chooses a related next song (mostly from **Spotify's song radio**, read from the
Spotify desktop app running hidden and muted), finds it in the TIDAL catalog,
and makes TIDAL play it at the moment the current song ends.

It is a Python command-line program (`tidal-shuffle`) with a full-screen
terminal interface (Rich): now playing, synced lyrics, an animated Alter Era
logo, the log, Up next, a settings menu with live previews, a "shuffle tree"
that shows each choice being made, themes, backdrops and more. A small
`Tidal Shuffle.app` opens that view in Terminal from the Dock.

**Brand:** Alter Era (the user's company). The logo is in
`src/tidal_shuffle/assets/` (`alter-era.svg` line drawing, `alter-era-flat.svg`
solid shapes).

**Status:** feature-rich and well tested against fakes (421 tests), but the
parts that touch the real TIDAL app, macOS and Spotify can only be verified on
the user's Mac. See §9 for what is unverified.

---

## 2. Where things are

The repository is `canyoubarrett/vim`; the project lives in the `tidal-shuffle/`
folder. All work is on branch **`claude/blissful-pasteur-dw57cr`** (no pull
request; the user installs from this branch, see the README's install
commands).

```
tidal-shuffle/
├── install.sh               # user installer: .venv, media-control, PATH link, Tidal Shuffle.app
├── pyproject.toml           # version, dependencies, `tidal-shuffle` entry point
├── config.example.yaml      # must equal config.EXAMPLE_CONFIG (a test checks)
├── README.md                # user documentation (long; the source of truth for behaviour)
├── docs/
│   ├── HANDOFF.md           # this file
│   ├── manual/              # Alter Era manuals (PDF) + their build sources (src/)
│   └── *.pdf                # older "how it works" explainer diagrams
├── src/tidal_shuffle/       # the package (≈13,700 lines)
└── tests/                   # pytest; e2e/ runs the real CLI against a simulated Mac
```

---

## 3. Setting up to develop

Development has been done on Linux in a container; the code runs on macOS
only, so everything Mac-specific is behind injectable seams and fakes.

```bash
cd tidal-shuffle
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # ~100 s, 421 tests
```

* `tests/test_cdp_dom.py` runs the real TIDAL page scripts in **jsdom**; it is
  skipped unless `node` is installed and you ran `npm install` in
  `tests/e2e/fake_tidal/`.
* `tests/e2e/` starts the real CLI as a subprocess with `PATH` pointing at fake
  macOS binaries (`tests/e2e/fakebin/`: `media-control`, `osascript`, …) and a
  fake TIDAL web page (`fake_tidal/server.mjs`). `harness.py` patches only the OS
  name, the TIDAL login and one URL.
* `tests/conftest.py` points `TIDAL_SHUFFLE_HOME` (and the path constants) at a
  temp folder for every test, and clears Spotify/Last.fm environment variables:
  tests never touch the real `~/.config/tidal-shuffle`.

On the Mac, `./install.sh` does the same as a user install; `tidal-shuffle
doctor` checks the real environment; `tidal-shuffle update` = `git pull` +
reinstall.

---

## 4. How it works at run time

### 4.1 The big picture

```
 You ──keys/mouse/media keys──▶ ShuffleTUI ──commands──▶ ShuffleLoop ◀── NowPlaying (media-control + TIDAL page footer)
                                    ▲                        │  │
                                    │ reads state/trace      │  └─ plan ─▶ Engine ─▶ sources (Spotify app, Spotify API,
                                    │                        │                       Last.fm, Deezer, TIDAL radio)
                                    │                        │                    └▶ TidalCatalog (tidalapi): find songs
                                    │                        └─ play ─▶ TidalPlayer ─▶ TIDAL app (CDP :9222 / TidaLuna)
```

`cli.run` builds everything through `app.build_runtime(cfg)` (wiring only),
optionally makes the full-screen `ShuffleTUI` (`cli._make_screen`), starts the
key readers (`cli._start_controls`), then calls `loop.run()` on the main thread.

### 4.2 Threads

| Thread | What runs there |
|---|---|
| main | `ShuffleLoop.run()`: drain commands, `step()`, sleep until the next poll (woken early by any command) |
| Rich `Live` refresher | `ScreenRenderable` → `ShuffleTUI.compose()` at `ui.fps` (12): animation + drawing; reads loop state |
| `tidal-shuffle-keys` | `controls.KeyReader`: terminal keys (cbreak), or raw text while a settings field is edited |
| media-key tap | `controls.MediaKeyTap` (Quartz event tap), only while the terminal is frontmost |
| `tidal-shuffle-planner` | one background `engine.plan()` for the song playing |
| `tidal-shuffle-planner-ahead` | `engine.plan()` for the song *after* the pick (plan ahead) |
| `tidal-lookup` pool | up to 4 concurrent `catalog.match()` calls inside one plan |
| short-lived | Spotify API credential check, artwork/lyrics fetches |

Rules that keep this safe: the TUI never calls into TIDAL or the engine; it
posts commands (`loop.post("next")`) that the main thread executes. Shared
caches are `lru.BoundedDict` (locked). The trace (`trace.Trace`) is locked and
the screen reads copies. A plan is tagged with the loop's `generation`; when the
song changes the generation bumps and a late plan is dropped.

### 4.3 One song's life (`loop.py`)

`ShuffleLoop.step()` each poll:

1. **Observe.** `nowplaying.read()` → `_observe()`. A new track (by TIDAL id,
   or seen twice when only MediaRemote reports it) → `on_new_track()`, which
   records history, decides whether it was *our* pick (`expected`), adopts a
   plan made ahead if it was, and resets per-song state.
2. **Plan** (`plan_after_seconds`, 4 s in): `request_plan()` runs `engine.plan`
   on the planner thread; `collect_plan()` adopts it (`_apply_plan`), possibly
   queuing it in TIDAL's own queue when TidaLuna is present.
3. **Plan ahead:** `request_ahead()` starts planning the song after the pick.
4. **Prepare** (`prepare_seconds`, 10 s before the end): open the pick's page in
   TIDAL so the hand-off is instant.
5. **Hand off** when `_ending()` agrees (both macOS's report *and* our own clock
   say the song is nearly over, so one odd report cannot cut a song short):
   `_handoff_held()` in pause mode presses pause 0.8 s before the end, then
   `handoff()` → `_try_picks()` → `player.play(pick)`; on failure TIDAL is
   resumed. Two failed picks stop the attempt (the method is broken, not the
   picks) and the log suggests `inspect --watch`.
6. **Verify:** the next observation should be the pick; if TIDAL still shows the
   old song after `verify_seconds + 10`, the hand-off is retried.

Hand-off modes: `pause` (default; never cuts, never lets TIDAL's own next song
in) and `timed` (starts early by TIDAL's learned start-up delay, saved in
`timing.json`).

**Next (`n`)**: `request_skip()`. If the pick sits in TIDAL's queue *and is
verifiably still next* it presses TIDAL's next; else, with a plan ready, it
holds TIDAL and starts the pick; else it plans now and switches when ready
(`skip_requested`). Presses during a switch are dropped (`_switched_at`), and a
burst counts once (`handle_commands`).

### 4.4 Choosing the next song (`engine.py`)

`Engine.plan(seed, anchor, recent, exclude_keys, trace=None)`:

1. resolve the seed on TIDAL (id, ISRC, duration);
2. `_gather`: ask sources **in order** (`cfg.sources`) until one gives ≥3
   candidates (or all, with `shuffle.blend`);
3. `_clean`: dedupe, drop the song playing / recent seeds / refused picks /
   knock-offs (karaoke, tribute, lullaby versions; `matching.looks_like_knockoff`);
4. `_flow_fits`: audio features (`features.py`, ReccoBeats) score candidates for
   the flow (`flows.py`: radio, rising, falling, steady, soundscape, vibe);
5. `_choose`: `picker.order_candidates` (strategy: top, weighted, random,
   discovery; plus history cooldowns), then **look candidates up on TIDAL four
   at a time but accept them strictly in order** until `lookahead` (3) picks;
6. if nothing fits, ask the sources not tried yet.

Every step is recorded in a `trace.Trace` (the shuffle tree view). A plan made
ahead passes its own trace so it does not overwrite the one on screen; the
engine keeps the current plan's trace in a thread-local (`_tr()`).

### 4.5 Sources (`sources/`)

| Source | How | Notes |
|---|---|---|
| `spotify_app.py` | AppleScript drives the **Spotify desktop app**: plays the seed's radio station muted and hidden, skips through it reading ~25 upcoming tracks | the best suggestions; slow (≈1 s per skip). Needs the seed's Spotify id: `spotify_ids.py` (Spotify API search → ListenBrainz → Odesli → Spotify UI search), cached on disk. `spotify_guard.py` keeps Spotify hidden; `activity.busy()` tells the now-playing reader that Spotify owns macOS's slot during a harvest. Never interrupts the user's own Spotify listening. |
| `spotify_api.py` | Web API, client-credentials | 2026 rules: development-mode apps need a Premium owner; `/recommendations` only for old apps; degrades to related artists / genre search. Credentials: config, env vars, or the settings menu (`credentials.py`). |
| `lastfm.py` | similar tracks/artists | needs an API key |
| `deezer.py` | related artists, artist radio | keyless |
| `tidal_radio.py` | TIDAL track/artist radio via `tidalapi` | always available fallback |

All implement `available()` and `candidates(seeds, limit)`, and may implement
`cancel()` (the Spotify harvest stops when the song is skipped).

### 4.6 Controlling TIDAL (`tidal/`)

* `player.py` `TidalPlayer`: chooses the method: **TidaLuna API** (optional mod,
  HTTP 127.0.0.1:24123, gapless queue) → **CDP** → `open tidal://` deep links.
* `cdp.py` `TidalCdp`: the TIDAL app is Electron; launched with
  `--remote-debugging-port=9222` (relaunched once by `run` if needed). Page
  scripts are built by `_page_js()` (shared helpers: find the track's row, the
  hero play button, `showsTrack()` guard so a redirected page's button is never
  clicked). `play_track`: navigate (history.pushState) → click play → verify the
  footer shows the track; fallback: dispatch `playQueue/ADD_NOW` to TIDAL's Redux
  store, **only after the track is loaded** (`store_play` returns `not-loaded`
  when `state.content.mediaItems` lacks it; opening the page loads it). Also:
  footer reading (`now_playing`), `press(play|pause|next|previous)`,
  `inspect()` / `watch_actions()` for diagnosing a changed TIDAL.
* **Fragile by nature:** TIDAL's DOM and store shape are not an API. Selectors
  are in `cdp.SELECTORS`; `tidal-shuffle inspect --watch 20` dumps what the page
  looks like and which store actions fire, to adapt them.
* `catalog.py` `TidalCatalog` (unofficial `tidalapi`): search, ISRC lookup,
  fuzzy match (`matching.score_match`), radio. Login: device link, saved in
  `tidal_session.json`.

### 4.7 What is playing (`nowplaying/`)

`CompositeBackend`: macOS MediaRemote through `media-control` (Homebrew;
`nowplaying-cli` as fallback) plus the TIDAL page footer over CDP (exact track
id). MediaRemote snapshots can be half-updated during a change, hence the
"seen twice" rule and `_same_as_current()` guards in the loop.

### 4.8 The full-screen view (`tui.py` and friends)

* **Compositor (`fx.py`)**: the screen is a cell grid. `Backdrop` draws rain;
  each panel is rendered by Rich separately and laid on a `Canvas` with
  opacity (fades) and "glass" tint. `segments()` turns cells back into Rich
  segments. Colour depth: `tui.set_color_depth`; Terminal.app gets 256 colours
  with perceptual mapping (`nearest_256`).
* **Layout (`ShuffleTUI.regions` / `body_regions`)**: header; logo (or cover,
  or shuffle tree) and lyrics; bottom row split: log | Up next; key chips.
  Settings (Esc) overlay the left half with a live preview on the right.
* **Animation:** `animate()` advances springs (`fx.spring`) for fades and
  glides each frame; everything is a function of a clock, so tests drive it
  with a fake one (`stepping_tui` in `tests/test_tui.py`).
* **Settings:** `SETTINGS` (sections) → `setting_items` (rebuilt by
  `refresh_backdrops()`, which also adds the folded "Your pictures" entry and
  the Spotify API fields and hides detail levels the terminal cannot draw).
  `setting(key)` = previewed value or chosen; `chosen(key)` = config. Choices are
  saved to `ui.json` (`uistate.py`, `KEYS` lists what is saved; `VERSION`
  migrates old defaults). Sliders: `SLIDERS`. Text fields: `editing` +
  `text_input()`, fed raw by `KeyReader(text_sink=…)`.
* **Logo (`visualizer.py` `LogoScene`)**: the SVG traced to braille lines, or
  filled regions rasterised with Pillow into block characters (`detail`:
  half/quadrant/sextant/octant), with motions (float … topple, jelly, magnet,
  party) and palettes; `set_version("lines"|"flat")`.
* **Pictures (`artwork.py`, `stages.py`)**: album covers and backdrops drawn at a
  chosen detail (`detail_cells`: half, quadrant, sextant, octant, braille).
  Sextant/octant characters are only offered where the terminal draws them
  (`drawable_details`; Terminal.app shows boxes). Backdrops are made once per
  setting from the full-size picture and panned by slicing (`StageArt._strip`).
* **Lyrics (`lyrics.py`)**: TIDAL + LRCLIB, merged (`merge_lyrics`,
  `blend_timing`), word timings when available, cached; estimated timing is
  labelled and never highlighted.
* **Themes (`theme.py`)**: 20 themes mapped onto Catppuccin's role names;
  `blend()` for smooth switches.

### 4.9 Configuration

`config.py`: defaults ← `config.yaml` ← saved Spotify credentials
(`credentials.py`) ← environment ← preset ← CLI flags; then `ui.json`
overrides the `ui:` section at screen start. Every option is validated in
`_build()` with a converter; `EXAMPLE_CONFIG` documents them all.

### 4.10 The Mac app (`macapp.py`)

`tidal-shuffle app` (run by `install.sh`) writes `Tidal Shuffle.app` into
/Applications or ~/Applications: `Info.plist`, `MacOS/launch` (`open -a
Terminal …/run.command`), `Resources/run.command` (`exec <installed
tidal-shuffle> run`) and `AppIcon.icns`, generated in pure Python from the
logo regions (PNG-based ICNS entries). Not yet opened on a real Mac.

---

## 5. Files on the user's Mac (`~/.config/tidal-shuffle/`, `paths.py`)

| File | Holds |
|---|---|
| `config.yaml` | optional config (`tidal-shuffle config init`) |
| `ui.json` | settings-menu choices (versioned) |
| `spotify.json` | Spotify API credentials, mode 600 |
| `tidal_session.json` | TIDAL login |
| `history.json` | played/picked songs (repeat and artist cooldowns) |
| `timing.json` | learned TIDAL start-up delay |
| `backdrops/` | the user's pictures (`tidal-shuffle backdrops add`) |
| `cache/` | lyrics, covers, Spotify ids, Last.fm; safe to delete |

---

## 6. Working on it: conventions

* **Every behaviour change gets a test**, with fakes and a fake clock; no
  sleeping, no network. Loop tests use `World` (a fake TIDAL + MediaRemote) in
  `tests/test_loop.py`; TUI tests render to text/SVG via `render()` and
  `stepping_tui()`.
* **Style:** plain-English comments and docstrings that say *why*; small
  functions; match surrounding code. User-facing text (log lines, settings,
  README) is short, concrete and free of jargon.
* **Config changes:** add the field to the dataclass, a converter in
  `_build()`, a line in `EXAMPLE_CONFIG`, then regenerate the example:
  `.venv/bin/python -c "from tidal_shuffle.config import EXAMPLE_CONFIG; open('config.example.yaml','w').write(EXAMPLE_CONFIG)"`.
  Settings-menu keys also go in `uistate.KEYS`.
* **Versioning:** bump `src/tidal_shuffle/__init__.py`, `pyproject.toml` and the
  version check in `tests/test_cli.py` together. Minor for features, patch for
  fixes. Note the release in the manual's revision table if you rebuild it.
* **Commits:** one commit per release-sized change, message `X.Y.Z: summary`
  plus a body of bullet points; push to `claude/blissful-pasteur-dw57cr`.
* **Docs:** this handoff (`docs/HANDOFF.md`) is updated with architecture changes; README is the user-facing reference and is kept current with every
  feature. The manuals in `docs/manual/` are rebuilt with
  `cd docs/manual/src && python3 build.py && python3 render.py` (Playwright).
* **Previews:** TUI changes were checked by rendering a fake screen to SVG/PNG
  (Rich `export_svg` + Playwright screenshots); do the same before shipping
  visual changes.

---

## 7. External dependencies and how they break

| Dependency | Risk | Where to look |
|---|---|---|
| TIDAL desktop app DOM / Redux store | changes with TIDAL updates; play buttons not found | `cdp.SELECTORS`, `_page_js`, `inspect --watch` |
| `tidalapi` (unofficial) | login or endpoints change | `tidal/catalog.py` |
| Spotify desktop app AppleScript | dictionary changes; Automation permission | `sources/spotify_app.py` |
| Spotify Web API (2026 rules) | 403 without a Premium owner; limits | `sources/spotify_api.py` |
| `media-control` (Homebrew) | MediaRemote access changes in new macOS | `nowplaying/media.py` |
| ReccoBeats (audio features), LRCLIB, ListenBrainz, Odesli, Deezer, Last.fm | outages, rate limits | each degrades gracefully; see `http.py` retries |

`tidal-shuffle doctor` checks most of these and is the first thing to ask a
user to run.

---

## 8. Never do

* **Never commit credentials.** The user once pasted a Spotify client secret
  into the conversation; it is not in the repo and must never be. Credentials
  belong in `spotify.json`, the config file or the environment.
* **Never commit the fighting-game stage pictures** the user uses as
  backdrops. They are copyrighted game art; the app installs them locally from
  the user's own zip (`tidal-shuffle backdrops add`).
* Don't let the TUI call TIDAL or the engine directly (post commands instead),
  and don't block the main loop on the network: planning is on worker threads.

---

## 9. Open threads and what is unverified

Real-hardware behaviour cannot be tested here. Most recent user reports and
their state:

1. **"Next plays TIDAL's own next song first, then the pick."** Fixed in 0.11.0
   on the most likely causes (hold TIDAL before the pick; `ADD_NOW` only for
   loaded tracks; TIDAL's next only when the queued pick is verifiably next). The
   `state.content.mediaItems` shape is an educated guess: if the user still
   sees it, get `tidal-shuffle inspect --watch 20` output. A media key reaching
   TIDAL too (no Accessibility permission) produces the same symptom.
2. **Playback failures** ("no play button found", "footer never showed"): the
   user was asked for `inspect --watch` output and has not sent it yet. Adapt
   `SELECTORS` / `_page_js` from it.
3. **Plan ahead (0.12.0)** doubles Spotify app usage; watch for Spotify
   appearing or harvests slowing hand-offs on the user's Mac.
4. **Tidal Shuffle.app (0.13.0)** has not been opened on a Mac yet: check the
   icon, Gatekeeper, and that Terminal opens and runs it.
5. **Terminal.app** is the user's terminal (256 colours, macOS 15): sextant and
   octant blocks are hidden there; braille "Dots" detail reportedly showed
   boxes once, unexplained.

---

## 10. Ideas the user has raised or that would help next

* **Faster suggestions:** read Spotify's queue in one Web API call
  (`/me/player/queue`, needs user OAuth and Premium) instead of skipping 25
  tracks: harvest from ~20 s to ~2 s.
* **Real pixel graphics** for backdrops and covers in terminals that support
  them (kitty/Ghostty graphics protocol, iTerm2 inline images).
* **A standalone app** with its own window (bundled Python, signing) instead of
  the Terminal launcher.
* **A hardware display:** the user is planning a Raspberry Pi Pico (RP2040)
  with a 0.96″ SSD1306 or 0.95″ SSD1331 colour OLED in an IEC-connector-sized
  cutout, showing what is playing. A small serial protocol over USB from
  `tidal-shuffle run` (title, artist, progress, colours) would feed it.

---

## 11. Release checklist

1. Tests: `.venv/bin/python -m pytest -q` all green.
2. Regenerate `config.example.yaml` if config changed.
3. README updated for any user-visible change.
4. Version bumped in the three places.
5. Commit `X.Y.Z: summary`, push to `claude/blissful-pasteur-dw57cr`.
6. Tell the user: quit, `tidal-shuffle update`, restart.
