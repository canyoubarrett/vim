"""Build the Alter Era manuals for Tidal Shuffle: a one-page operation card and
the engineering and operation manual, as US Letter HTML pages (then PDF)."""

from __future__ import annotations

from kit import (ACCENT, CARD, INK, LINK, MONO, MUTED, PAPER, PAPER2, RULE, SANS, SOFT, E, fonts_css, keycap as K,
                 logo, watermark)
import diagrams

DOC, REV, DATE = "AE-TS-01", "0.12.0", "3 October 2026"
CARD_DOC = "AE-TS-00"

CSS = f"""
@page {{ size: 8.5in 11in; margin: 0; }}
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #d6d5d0; }}
@media print {{ html, body {{ background: {PAPER}; }} .page {{ margin: 0 !important; }} }}
body {{ font-family: {SANS}; color: {INK}; -webkit-font-smoothing: antialiased; }}
.page {{ width: 816px; height: 1056px; margin: 24px auto; position: relative; overflow: hidden; background: {PAPER};
        padding: 84px 64px 72px; break-after: page; page-break-after: always; }}
.page:last-child {{ break-after: auto; page-break-after: auto; }}
.watermark {{ position: absolute; right: -96px; bottom: -84px; opacity: 0.05; z-index: 5; pointer-events: none;
        mix-blend-mode: multiply; }}
.page > *:not(.watermark) {{ position: relative; z-index: 1; }}
.run-head, .run-foot {{ position: absolute !important; left: 64px; right: 64px; display: flex; justify-content: space-between;
        align-items: center; font: 500 7.5px/1 {MONO}; letter-spacing: 0.14em; text-transform: uppercase; color: {SOFT}; }}
.run-head {{ top: 32px; padding-bottom: 10px; border-bottom: 1px solid {RULE}; }}
.run-foot {{ bottom: 30px; padding-top: 10px; border-top: 1px solid {RULE}; }}
.brand {{ display: flex; align-items: center; gap: 8px; color: {INK}; }}
.secno {{ font: 500 9px/1 {MONO}; letter-spacing: 0.12em; color: {ACCENT}; text-transform: uppercase; }}
h1 {{ font: 300 31px/1.12 {SANS}; letter-spacing: -0.015em; margin: 8px 0 14px; }}
h2 {{ font: 500 13.5px/1.3 {SANS}; margin: 22px 0 7px; }}
h2 .n {{ font: 500 8.5px {MONO}; color: {SOFT}; margin-right: 8px; letter-spacing: 0.08em; }}
.eyebrow {{ font: 500 7.5px/1.2 {MONO}; letter-spacing: 0.14em; text-transform: uppercase; color: {MUTED}; margin: 0 0 6px; }}
p {{ font: 400 11px/1.6 {SANS}; margin: 0 0 8px; max-width: 64ch; }}
.lead {{ font: 300 15.5px/1.5 {SANS}; max-width: 54ch; margin-bottom: 14px; }}
.muted {{ color: {MUTED}; }}
ul.plain, ol.steps {{ margin: 0 0 10px; padding: 0; list-style: none; font: 400 11px/1.55 {SANS}; }}
ul.plain li {{ padding-left: 14px; position: relative; margin-bottom: 3px; }}
ul.plain li::before {{ content: '—'; position: absolute; left: 0; color: {SOFT}; }}
ol.steps {{ counter-reset: s; }}
ol.steps li {{ counter-increment: s; padding-left: 24px; position: relative; margin-bottom: 5px; }}
ol.steps li::before {{ content: counter(s); position: absolute; left: 0; top: 1px; width: 15px; height: 15px; border-radius: 50%;
        background: {INK}; color: {PAPER}; font: 500 8px/15px {MONO}; text-align: center; }}
table {{ border-collapse: collapse; width: 100%; font: 400 10.25px/1.45 {SANS}; margin: 4px 0 12px; }}
th {{ font: 500 7px/1.2 {MONO}; letter-spacing: 0.12em; text-transform: uppercase; color: {MUTED}; text-align: left;
     border-bottom: 1px solid {INK}; padding: 0 10px 5px 0; }}
td {{ border-bottom: 1px solid {RULE}; padding: 6px 10px 6px 0; vertical-align: top; }}
td:first-child {{ white-space: nowrap; }}
code, .mono {{ font-family: {MONO}; font-size: 9.25px; }}
pre {{ font: 400 9.25px/1.65 {MONO}; background: {CARD}; border: 1px solid {RULE}; border-radius: 3px; padding: 9px 12px;
      margin: 4px 0 12px; white-space: pre-wrap; color: {INK}; }}
pre .c {{ color: {SOFT}; }}
.key {{ display: inline-block; min-width: 17px; padding: 1px 5px; border: 1px solid #c8c7c1; background: {PAPER2};
       border-radius: 3px; font: 500 8.5px/13px {MONO}; text-align: center; color: {INK}; }}
figure {{ margin: 10px 0 8px; }}
figure .fig {{ overflow-x: auto; }}
figure .fig > svg {{ width: 100%; height: auto; display: block; }}
figcaption {{ font: 400 7.5px/1.4 {MONO}; letter-spacing: 0.06em; color: {SOFT}; margin-top: 6px; text-transform: uppercase; }}
.cols {{ display: grid; gap: 28px; }}
.cards {{ display: grid; gap: 12px; margin: 6px 0 14px; }}
.cardx {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 4px; padding: 12px 14px; }}
.cardx h3 {{ font: 500 10.5px/1.3 {SANS}; margin: 0 0 4px; display: flex; align-items: center; gap: 7px; }}
.cardx p {{ font-size: 10px; color: {MUTED}; margin: 0; }}
.dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; background: {INK}; }}
.dot.accent {{ background: {ACCENT}; }} .dot.link {{ background: {LINK}; }} .dot.soft {{ background: {SOFT}; }}
.note {{ border-left: 2px solid {ACCENT}; padding: 1px 0 1px 10px; font: 400 10.25px/1.55 {SANS}; color: {MUTED}; margin: 10px 0 12px; max-width: 64ch; }}
.toc {{ width: 100%; }}
.toc td {{ font-size: 10.5px; padding: 7px 10px 7px 0; }}
.toc td.n {{ font: 500 8.5px {MONO}; color: {ACCENT}; width: 36px; }}
.toc td.p {{ text-align: right; font: 400 8.5px {MONO}; color: {SOFT}; }}
"""


def head(title: str) -> str:
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{E(title)}</title>'
            f'<style>{fonts_css()}</style><style>{CSS}</style></head><body>\n')


def brand(doc: str) -> str:
    return (f'<div class="run-head"><span class="brand">{logo(16, label="")}<span>Alter Era</span></span>'
            f'<span>Tidal Shuffle · Engineering and operation manual · {doc} · Rev {REV}</span></div>')


def page(body: str, n: int, total: int, section: str, doc: str = DOC) -> str:
    return (f'<section class="page">{watermark()}{brand(doc)}{body}'
            f'<div class="run-foot"><span>{E(section)}</span><span>{n:02d} / {total:02d}</span></div></section>\n')


def figure(svg: str, caption: str) -> str:
    return f'<figure><div class="fig">{svg}</div><figcaption>{E(caption)}</figcaption></figure>'


def table(headers: list[str], rows: list[list[str]], widths: list[str] | None = None) -> str:
    cols = "".join(f'<col style="width:{w}">' for w in widths) if widths else ""
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><colgroup>{cols}</colgroup><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def c(s: str) -> str:
    return f"<code>{E(s)}</code>"


# --------------------------------------------------------------------------------------------
# the engineering and operation manual
# --------------------------------------------------------------------------------------------
def cover() -> str:
    meta = "".join(f'<div><div class="eyebrow">{k}</div><div style="font:400 10.5px/1.4 {SANS}">{v}</div></div>'
                   for k, v in (("Document", DOC), ("Revision", REV), ("Issued", DATE),
                                ("Applies to", "macOS · TIDAL desktop app")))
    return f"""<section class="page" style="padding:64px">{watermark()}
  <div style="display:flex;align-items:center;gap:14px">{logo(64)}
    <div><div style="font:500 11px/1 {MONO};letter-spacing:0.22em">ALTER ERA</div>
    <div style="font:400 8px/1.6 {MONO};letter-spacing:0.14em;color:{SOFT};margin-top:6px">ENGINEERING</div></div></div>
  <div style="position:absolute;left:64px;right:64px;top:430px">
    <div style="width:12px;height:12px;background:{ACCENT};margin-bottom:22px"></div>
    <div style="font:300 60px/1.02 {SANS};letter-spacing:-0.025em">Tidal Shuffle</div>
    <div style="font:300 22px/1.3 {SANS};color:{MUTED};margin-top:12px">Engineering and operation manual</div>
    <p style="margin-top:22px;max-width:46ch;color:{MUTED}">A smarter shuffle for the TIDAL app on the Mac. It follows
    the song you are hearing, chooses a related one, and makes TIDAL play it when the song ends.</p>
  </div>
  <div style="position:absolute;left:64px;right:64px;bottom:64px;display:grid;grid-template-columns:1fr 1fr 1.2fr 1.5fr;
       gap:20px;border-top:1px solid {INK};padding-top:12px">{meta}</div>
</section>
"""


def contents(total: int) -> str:
    rows = [("01", "Overview", 3), ("02", "Installing and updating", 4), ("03", "Operating", 5),
            ("04", "The settings menu", 7), ("05", "How the next song is chosen", 8), ("06", "The hand-off", 9),
            ("07", "Sources and services", 11), ("08", "The display", 12), ("09", "Configuration reference", 13),
            ("10", "Troubleshooting", 14), ("11", "Files, commands and revisions", 15)]
    toc = "".join(f'<tr><td class="n">{n}</td><td>{t}</td><td class="p">{p:02d}</td></tr>' for n, t, p in rows)
    body = f"""
<div class="secno">Contents</div><h1>This manual</h1>
<div class="cols" style="grid-template-columns:1.25fr 0.75fr">
  <div><table class="toc"><tbody>{toc}</tbody></table></div>
  <div>
    <div class="eyebrow">About it</div>
    <p>It describes Tidal Shuffle {REV}: how to install and run it, what each part does, and how to put it right
    when something goes wrong. A one-page operation card ({CARD_DOC}) sums up daily use.</p>
    <div class="eyebrow" style="margin-top:16px">Conventions</div>
    <ul class="plain">
      <li>{K('n')} a key to press</li>
      <li>{c('tidal-shuffle run')} something to type in Terminal</li>
      <li>{c('player.handoff_mode')} a setting in the config file</li>
      <li><b style="font-weight:500">Esc → Theme</b> a place in the settings menu</li>
      <li>In the figures, <span style="color:{ACCENT}">orange</span> marks the main path; green, a call to a web service.</li>
    </ul>
    <div class="eyebrow" style="margin-top:16px">What it does not do</div>
    <p class="muted">It never changes your TIDAL library or playlists, never plays through Spotify's speakers (Spotify is
    muted while it is used), and never interrupts Spotify while you are listening to it.</p>
  </div>
</div>
"""
    return page(body, 2, total, "Contents")


def overview(total: int) -> str:
    cards = f"""<div class="cards" style="grid-template-columns:1.1fr 1fr 0.9fr">
  <div class="cardx"><h3><span class="dot accent"></span>Never cuts a song short</h3>
    <p>TIDAL is held for the last moment of a song, then the pick starts.</p></div>
  <div class="cardx"><h3><span class="dot"></span>Never makes you wait</h3>
    <p>Songs are chosen in the background, one ahead.</p></div>
  <div class="cardx"><h3><span class="dot soft"></span>Stays out of the way</h3>
    <p>Spotify is hidden and muted while it is asked.</p></div>
</div>"""
    body = f"""
<div class="secno">01 · Overview</div><h1>What it is</h1>
<p class="lead">TIDAL's own shuffle plays your list in a random order. Tidal Shuffle instead listens to what is
playing and finds the next song that belongs with it, from Spotify's song radio and other sources, then plays it in TIDAL.</p>
{cards}
{figure(diagrams.architecture(), "Figure 1 · System overview")}
<p>The <b style="font-weight:500">shuffle loop</b> follows the song macOS reports as playing. Four seconds into each song it asks the
<b style="font-weight:500">choosing engine</b> for the next one; the engine asks the recommendation sources, cleans and orders what they
suggest, and finds the songs in the TIDAL catalog. Near the end of the song the loop makes the TIDAL app play the pick,
through the app's local debug port.</p>
"""
    return page(body, 3, total, "01 · Overview")


def install(total: int) -> str:
    req = table(["Needs", "For", "Notes"], [
        ["A Mac with the TIDAL app", "everything", "a TIDAL subscription; the app from tidal.com/download"],
        ["Homebrew", "installing", "brew.sh; the installer adds Python 3.12 and media-control with it"],
        ["Spotify app", "the best suggestions", "free or Premium; used hidden and muted"],
        ["Spotify developer app", "optional", "client ID and secret; its owner needs Premium (2026)"],
        ["Last.fm API key", "optional", "another source of similar songs"],
    ], ["30%", "22%", "48%"])
    body = f"""
<div class="secno">02 · Installing and updating</div><h1>Installing it</h1>
{req}
<h2><span class="n">2.1</span>Install</h2>
<pre><span class="c"># in Terminal</span>
git clone -b claude/blissful-pasteur-dw57cr https://github.com/canyoubarrett/vim.git ~/tidal-shuffle-src
cd ~/tidal-shuffle-src/tidal-shuffle
./install.sh
tidal-shuffle login        <span class="c"># approve the link it prints, in your browser</span>
tidal-shuffle doctor       <span class="c"># checks every part and says how to fix what is missing</span></pre>
<p>{c('install.sh')} makes a private Python environment in {c('.venv')}, installs {c('media-control')} and puts the
{c('tidal-shuffle')} command on your path. The TIDAL login is kept in {c('~/.config/tidal-shuffle')}.</p>
<h2><span class="n">2.2</span>First run</h2>
<ol class="steps">
  <li>Start TIDAL and play any song.</li>
  <li>In Terminal: {c('tidal-shuffle run')}. If TIDAL was started without its debug port, Tidal Shuffle restarts it once,
  with the port (the music resumes).</li>
  <li>The first time Spotify is used, macOS asks to let Terminal control Spotify: allow it.</li>
</ol>
<h2><span class="n">2.3</span>Update</h2>
<pre>tidal-shuffle update       <span class="c"># fetches the latest version and reinstalls it</span>
tidal-shuffle --version    <span class="c"># shows the version and where it is installed</span></pre>
<p class="muted">Quit Tidal Shuffle first ({K('q')}). Settings, history and pictures live in {c('~/.config/tidal-shuffle')}
and are kept. If {c('update')} reports changed files, run {c('git -C ~/tidal-shuffle-src stash')} and update again.
To remove it, delete {c('~/tidal-shuffle-src')} and {c('~/.config/tidal-shuffle')}.</p>
"""
    return page(body, 4, total, "02 · Installing and updating")


def operating(total: int) -> str:
    parts = table(["", "Part", "What it shows"], [
        ["1", "Header", "the song, its progress and where the pick came from"],
        ["2", "Logo", f"the Alter Era mark, moving with the music; or the cover ({K('a')}), or the shuffle tree ({K('t')})"],
        ["3", "Lyrics", f"synced lyrics from TIDAL and LRCLIB; {K('l')} hides them"],
        ["4", "Log", "what Tidal Shuffle is doing, newest last"],
        ["5", "Up next", "the pick and its backups, then what played"],
        ["6", "Keys", "every key, clickable"],
    ], ["4%", "16%", "80%"])
    body = f"""
<div class="secno">03 · Operating</div><h1>Running it</h1>
<p>Start it with {c('tidal-shuffle run')} and leave the window open; it keeps the music going until you press {K('q')}.
Choose a starting style with {c('--preset NAME')} (see 3.3), or {c('--plain')} for a scrolling log instead of the screen below.</p>
{figure(diagrams.screen_map(), "Figure 2 · The full-screen view")}
{parts}
<div class="note">The screen adapts to the window. In a narrow window the lyrics take the whole width; Up next always
stays beside the log.</div>
"""
    return page(body, 5, total, "03 · Operating")


def keys(total: int) -> str:
    rows = [
        [K("space"), "play or pause TIDAL"],
        [K("n"), "next: start the pick now (the song after it is already being chosen)"],
        [K("b"), "back: the previous song in TIDAL"],
        [K("f"), "the next flow (how each song follows the last; see 3.3)"],
        [K("p"), "presets: choose a ready-made style"],
        [K("l"), "lyrics on or off"],
        [K("a"), "the album cover in place of the logo"],
        [K("t"), "the shuffle tree: watch the next song being chosen"],
        [K("esc"), "the settings menu (chapter 04)"],
        [K("q"), "quit; TIDAL keeps playing"],
        [K("?"), "help"],
    ]
    flows = table(["Flow", "Each next song is…"], [
        [c("radio"), "the song radio's own order"], [c("rising"), "a little more energetic"],
        [c("falling"), "a little calmer"], [c("steady"), "at one energy level"],
        [c("soundscape"), "close to the first song's overall sound"], [c("vibe"), "of the current song's mood and energy"],
    ], ["30%", "70%"])
    presets = ("anchor, balanced, chill, discovery, familiar, lastfm-only, late-night-drive, radio, soundscape, "
               "spotify-only, steady, tidal-only, vibe, wander, warm-up, wind-down, workout")
    body = f"""
<div class="secno">03 · Operating</div><h1>Keys and styles</h1>
<div class="cols" style="grid-template-columns:1.15fr 0.85fr">
  <div><h2><span class="n">3.1</span>Keys</h2>{table(["Key", "Does"], rows, ["18%", "82%"])}</div>
  <div>
    <h2><span class="n">3.2</span>Media keys and mouse</h2>
    <p>While the Terminal window is in front, the keyboard's {K("⏯")} {K("⏭")} {K("⏮")} keys work like
    {K("space")} {K("n")} {K("b")}. macOS asks once to let Terminal see them (Accessibility). Every key in the bottom
    row, every preset and every setting can be clicked.</p>
    <h2><span class="n">3.3</span>Flows</h2>{flows}
    <h2><span class="n">3.4</span>Presets</h2>
    <p class="muted">{presets}. List them with {c('tidal-shuffle presets')}; add your own in the config file.</p>
  </div>
</div>
"""
    return page(body, 6, total, "03 · Operating")


def settings(total: int) -> str:
    rows = [
        ["Theme", "twenty colour themes for the whole screen (Nord, Dracula, Gruvbox, Catppuccin and more)", c("ui.theme")],
        ["Party mode", "the logo glides through every colour and motion", c("ui.party")],
        ["Logo colours", "theme, muted, the logo's own (filled or lines), pastel, neon, sunset, ocean, Catppuccin, mono", c("ui.logo_style")],
        ["Logo version", "lines, or flat (solid shapes, no outlines)", c("ui.logo_version")],
        ["Logo detail", "how finely filled colours are drawn: Low to Highest", c("ui.logo_detail")],
        ["Logo motion", "float, gentle, lively, shapes, tide, topple, jelly, magnet, still", c("ui.logo_motion")],
        ["Logo size", "slider: the logo on its own", c("ui.logo_size")],
        ["Shuffle tree", "off, in place of the logo, or beside it", c("ui.shuffle_view")],
        ["Rain", "the rain behind the panels: off, faint, soft or clear", c("ui.rain")],
        ["Lyrics not sung yet", "shown (default), dimmed or hidden", c("ui.lyrics_ahead")],
        ["Lyrics timing", "move the highlight earlier or later", c("ui.lyrics_lead")],
        ["Backdrop look", "sliders: zoom, dim, logo size and floor on a picture", c("ui.backdrop_*")],
        ["Picture detail", "Low, Medium, High, Highest, Dots (chapter 08)", c("ui.picture_detail")],
        ["Logo backdrop", "off, album cover, a picture each song, or one of Your pictures", c("ui.logo_backdrop")],
        ["Spotify API", "client ID and secret, typed or pasted; Check asks Spotify", c("spotify.json")],
    ]
    body = f"""
<div class="secno">04 · The settings menu</div><h1>Settings</h1>
<p class="lead">{K('esc')} opens the menu on the left half of the screen, with a live preview on the right. Whatever the
cursor is on is shown at once; nothing is kept until you choose it.</p>
<ol class="steps">
  <li>{K('↑')} {K('↓')} move; {K('←')} {K('→')} jump a section (on a slider, they move the slider).</li>
  <li>{K('enter')} or a click chooses. The choice is kept between runs, in {c('~/.config/tidal-shuffle/ui.json')}.</li>
  <li>{K('esc')} closes the menu and puts back anything only previewed.</li>
</ol>
{table(["Section", "What it sets", "Kept as"], rows, ["20%", "60%", "20%"])}
<div class="note">Your pictures are folded behind one entry, <b style="font-weight:500">Your pictures</b>: {K('enter')}
unfolds them. A picture is loaded only when the cursor rests on it, so moving through the list stays quick.</div>
"""
    return page(body, 7, total, "04 · The settings menu")


def choosing(total: int) -> str:
    strat = table(["Strategy", "Picks"], [
        [c("top"), "the best-ranked song that fits"],
        [c("weighted"), "at random, favouring the best-ranked (default)"],
        [c("random"), "any song that fits"],
        [c("discovery"), "deeper cuts and less popular songs"],
    ], ["30%", "70%"])
    body = f"""
<div class="secno">05 · How the next song is chosen</div><h1>Choosing</h1>
<p class="lead">Every choice goes the same way: ask, clean, order, find. The shuffle tree ({K('t')}) shows each step as
it happens, with what was left out and why.</p>
{figure(diagrams.funnel(), "Figure 3 · From suggestions to a pick (an example run)")}
<div class="cols" style="grid-template-columns:1fr 1fr">
  <div>
    <h2><span class="n">5.1</span>Ask</h2>
    <p>The sources are asked in order ({c('sources')} in the config) until one gives enough songs. First the Spotify app:
    it plays the song's radio, hidden and muted, and reads the 25 songs it lines up. Then the Spotify API, Last.fm,
    Deezer and TIDAL's own radio.</p>
    <h2><span class="n">5.2</span>Clean</h2>
    <p>Out go repeats, the song playing and the last few heard, songs picked in the last 200 picks or 7 days, and
    karaoke, tribute and lullaby versions.</p>
  </div>
  <div>
    <h2><span class="n">5.3</span>Order and find</h2>
    <p>The strategy orders the pool; the flow, if any, moves songs that fit it forward. Songs are then looked up on
    TIDAL four at a time, but taken strictly in order, until a pick and two backups are found.</p>
    {strat}
  </div>
</div>
"""
    return page(body, 8, total, "05 · How the next song is chosen")


def handoff(total: int) -> str:
    modes = table(["Mode", "At the end of a song", "Use when"], [
        [c("pause") + " (default)", "holds TIDAL 0.8 s before the end, then starts the pick", "always; nothing is cut and TIDAL's own next song never plays"],
        [c("timed"), "starts the pick early, by the time TIDAL takes to start a song (learned)", "you want no gap and accept a clipped end now and then"],
        ["TidaLuna queue", "the pick waits in TIDAL's own queue; TIDAL moves on by itself", "the TidaLuna mod is installed: gapless"],
    ], ["22%", "44%", "34%"])
    body = f"""
<div class="secno">06 · The hand-off</div><h1>Handing over to the pick</h1>
<p class="lead">The hand-off is the moment the pick takes over from the song playing. It is timed from the song's own
clock and what macOS reports; both must agree before anything happens.</p>
{figure(diagrams.timeline(), "Figure 4 · One song, from its start to the hand-off")}
<h2><span class="n">6.1</span>Modes</h2>
{modes}
<h2><span class="n">6.2</span>Choosing ahead</h2>
<p>As soon as the pick is known, the song after it is chosen too, in the background. When the pick starts, its own next
song is ready, so pressing {K('n')} again and again never waits. If another song starts instead (you chose one in TIDAL),
the early choice is dropped. Turn it off with {c('shuffle.plan_ahead: false')}.</p>
<h2><span class="n">6.3</span>Starting a song in TIDAL</h2>
<p>Tidal Shuffle opens the pick's page in the TIDAL app and presses its play button, then waits up to 8 seconds for
TIDAL to show it playing. If the button cannot be found, it asks TIDAL's play queue directly, but only for a track TIDAL
has loaded; opening the page loads it. After two failed picks it stops trying and says so in the log.</p>
"""
    return page(body, 9, total, "06 · The hand-off")


def pressing_next(total: int) -> str:
    body = f"""
<div class="secno">06 · The hand-off</div><h1>Pressing next</h1>
{figure(diagrams.sequence(), "Figure 5 · What happens when you press n")}
<ol class="steps">
  <li>{K('n')} reaches Tidal Shuffle (or {K('⏭')} while its window is in front).</li>
  <li>TIDAL is held (pause mode, the default), so you never hear TIDAL's own next song while the pick loads.</li>
  <li>The pick's page is opened, which also loads the track in TIDAL.</li>
  <li>The pick is played, and macOS reports the new song.</li>
  <li>Tidal Shuffle confirms it is the pick; the song after it is already chosen.</li>
</ol>
<div class="note">Presses made while a switch is under way are counted once: a burst of {K('n')} moves one song on, not
five. If nothing is chosen yet, the log says "choosing a song…" and the switch follows as soon as one is.</div>
<h2><span class="n">6.4</span>If TIDAL moves on by itself first</h2>
<p>Then the media key reached TIDAL too: allow Terminal under System Settings → Privacy &amp; Security → Accessibility,
and press {K('n')} in the Tidal Shuffle window rather than {K('⏭')} elsewhere.</p>
"""
    return page(body, 10, total, "06 · The hand-off")


def sources(total: int) -> str:
    rows = [
        ["Spotify app", "the song radio: the closest matches", "the Spotify app; Automation access", "hidden and muted; never interrupts your own Spotify listening"],
        ["Spotify API", "related artists, same-genre songs; finds Spotify ids", "client ID and secret", "development-mode apps need a Premium owner"],
        ["Last.fm", "similar tracks and artists", "an API key", "free"],
        ["Deezer", "related artists and artist radio", "nothing", "public API"],
        ["TIDAL radio", "TIDAL's track and artist radio", "your TIDAL login", "the fallback that is always there"],
        ["ListenBrainz, Odesli", "Spotify ids for TIDAL songs", "nothing", "used to start the Spotify radio"],
    ]
    body = f"""
<div class="secno">07 · Sources and services</div><h1>Where suggestions come from</h1>
{table(["Source", "Gives", "Needs", "Notes"], rows, ["17%", "33%", "22%", "28%"])}
<h2><span class="n">7.1</span>Adding the Spotify API</h2>
<ol class="steps">
  <li>At developer.spotify.com/dashboard, create an app (any name; redirect URI not needed) and open its Settings.</li>
  <li>In Tidal Shuffle: {K('esc')} → <b style="font-weight:500">Spotify API</b> → <b style="font-weight:500">Client ID</b>;
  paste it ({K('⌘')}{K('V')}) and press {K('enter')}. Then the same for the <b style="font-weight:500">Client secret</b>.</li>
  <li>Spotify is asked at once; the answer shows beside <b style="font-weight:500">Check</b>.</li>
</ol>
<p class="muted">The values are kept in {c('~/.config/tidal-shuffle/spotify.json')}, readable only by you; the secret is
never shown. While a field is being typed into, every key is text: {K('enter')} saves, {K('esc')} cancels,
{K('ctrl')}{K('U')} clears. The environment variables {c('SPOTIFY_CLIENT_ID')} and {c('SPOTIFY_CLIENT_SECRET')}, when set,
take precedence.</p>
<h2><span class="n">7.2</span>Controlling TIDAL</h2>
<p>The TIDAL app is controlled through its local debug port ({c('127.0.0.1:9222')}), opened only on this Mac. Tidal Shuffle
starts TIDAL with it when needed ({c('player.auto_relaunch')}). With the optional TidaLuna mod, picks go into TIDAL's own
queue for gapless changes.</p>
"""
    return page(body, 11, total, "07 · Sources and services")


def display(total: int) -> str:
    detail = table(["Step", "Pixels a character", "Drawn with", "Where"], [
        ["Low", "1 × 2", "half blocks", "every terminal"],
        ["Medium", "2 × 2", "quarter blocks", "every terminal (default)"],
        ["High", "2 × 3", "sixth blocks", "Ghostty, kitty, WezTerm, iTerm2"],
        ["Highest", "2 × 4", "eighth blocks", "Ghostty, kitty"],
        ["Dots", "2 × 4", "braille dots", "every terminal; grainier"],
    ], ["16%", "22%", "22%", "40%"])
    body = f"""
<div class="secno">08 · The display</div><h1>The display</h1>
<div class="cols" style="grid-template-columns:1fr 1fr">
  <div>
    <h2><span class="n">8.1</span>Colour</h2>
    <p>Terminal.app shows 256 colours: every theme colour is matched to its nearest one by eye. iTerm2, Ghostty, WezTerm and
    kitty show the exact colours. {c('tidal-shuffle colors')} shows what a terminal can do; {c('ui.color')} overrides it.</p>
    <h2><span class="n">8.2</span>The logo</h2>
    <p>The Alter Era mark, as a line drawing or flat shapes, in the theme's colours or its own. It floats, tilts and comes
    apart according to its motion, faster when the music is livelier.</p>
    <h2><span class="n">8.3</span>Backdrops</h2>
    <p>A picture behind the logo, dimmed so the logo stands out; wide ones pan slowly. On a picture the logo stands on the
    floor, fighter-sized. Add pictures with {c('tidal-shuffle backdrops add PATH')} (files, folders or zips).</p>
  </div>
  <div>
    <h2><span class="n">8.4</span>Picture detail</h2>
    <p>Backdrops and the large cover are drawn from the full-size picture, in steps:</p>
    {detail}
    <p class="muted">High and Highest use newer block characters most fonts lack; they are only offered where the terminal
    draws them itself ({c('ui.block_glyphs: all')} offers them anyway). For more detail in any terminal, make its font smaller
    ({K('⌘')}{K('−')}).</p>
  </div>
</div>
"""
    return page(body, 12, total, "08 · The display")


def config_ref(total: int) -> str:
    rows = [
        ["sources", "spotify-app, spotify-api, lastfm, deezer, tidal-radio", "the order sources are asked in"],
        ["shuffle.strategy", "weighted", "top · weighted · random · discovery"],
        ["shuffle.flow", "radio", "radio · rising · falling · steady · soundscape · vibe"],
        ["shuffle.seed", "current", "current · anchor (the first song) · window (the last few)"],
        ["shuffle.artist_cooldown", "5", "picks before an artist may return"],
        ["shuffle.avoid_repeats_for", "200", "picks before a song may return (and _days: 7)"],
        ["shuffle.lookahead", "3", "the pick and its backups"],
        ["shuffle.plan_ahead", "true", "choose the song after the pick in advance"],
        ["shuffle.lookup_workers", "4", "TIDAL lookups at once"],
        ["player.handoff_mode", "pause", "pause · timed (6.1)"],
        ["player.pause_before_end", "0.8", "seconds before the end to hold TIDAL"],
        ["player.prepare_seconds", "10", "seconds before the end to open the pick's page"],
        ["player.plan_after_seconds", "4", "seconds into a song before choosing"],
        ["player.verify_seconds", "8", "how long TIDAL has to confirm the pick"],
        ["player.media_keys", "focus", "focus (window in front) · always · off"],
        ["spotify.app.harvest", "25", "radio songs read per seed"],
        ["ui.theme", "mocha", "any of the twenty themes"],
        ["ui.color", "auto", "auto · truecolor · 256 · 16"],
        ["ui.picture_detail", "quadrant", "half · quadrant · sextant · octant · braille"],
        ["ui.block_glyphs", "auto", "auto · all · basic"],
        ["ui.fps", "12", "frames a second; lower it on a slow Mac"],
    ]
    rows = [[c(a), c(b), e] for a, b, e in rows]
    body = f"""
<div class="secno">09 · Configuration reference</div><h1>The config file</h1>
<p>Optional. {c('tidal-shuffle config init')} writes {c('~/.config/tidal-shuffle/config.yaml')} with every setting and a
note on each; {c('tidal-shuffle config show')} prints what is in effect. Choices made in the settings menu override the
file's {c('ui:')} section. The most used settings:</p>
{table(["Setting", "Default", "Values"], rows, ["34%", "22%", "44%"])}
"""
    return page(body, 13, total, "09 · Configuration reference")


def troubleshoot(total: int) -> str:
    rows = [
        ["TIDAL plays its own next song", "the media key reached TIDAL too", f"allow Terminal in Accessibility; press {K('n')} in the window"],
        ["“could not start” in the log", "TIDAL's page has changed", f"{c('tidal-shuffle inspect --watch 20')}; send the output"],
        ["Nothing is chosen", "no source answered", f"{c('tidal-shuffle sources')} shows each source's answer"],
        ["No colours", "the terminal, or NO_COLOR set", f"{c('tidal-shuffle colors')}; {c('ui.color: 256')}"],
        ["Boxes with question marks", "the font lacks the characters", "Esc → Picture detail → Medium"],
        ["Spotify keeps appearing", "its search needed the window", f"{c('spotify.app.keep_hidden: true')}"],
    ]
    body = f"""
<div class="secno">10 · Troubleshooting</div><h1>Putting it right</h1>
<p>Start with {c('tidal-shuffle doctor')}: it checks every part (macOS, TIDAL, the login, the debug port, media-control,
Spotify, the sources) and says how to fix each one it marks.</p>
{figure(diagrams.troubleshooting(), "Figure 6 · When the music does not switch")}
{table(["Symptom", "Cause", "Remedy"], rows, ["30%", "30%", "40%"])}
"""
    return page(body, 14, total, "10 · Troubleshooting")


def files(total: int) -> str:
    frows = [[c(a), b] for a, b in (
        ("config.yaml", "the config file (optional)"), ("ui.json", "choices made in the settings menu"),
        ("spotify.json", "Spotify API credentials (readable only by you)"), ("tidal_session.json", "the TIDAL login"),
        ("history.json", "songs played and picked"), ("backdrops/", "your pictures"), ("cache/", "lyrics, covers, ids; safe to delete"),
        ("timing.json", "how long TIDAL takes to start a song"))]
    crow = [[c(a), b] for a, b in (
        ("run", "follow TIDAL and keep the music going"), ("next", "skip to a fresh pick now"),
        ("doctor", "check every part"), ("update", "get the latest version"), ("login", "log in to TIDAL"),
        ("test", "show what would play next, without playing"), ("sources", "ask every source once"),
        ("presets", "list the presets"), ("history", "show or clear the history"), ("backdrops", "add or list pictures"),
        ("colors", "show what the terminal can display"), ("inspect", "dump TIDAL's page, for fixing"),
        ("config", "create or show the config file"))]
    revs = [[c("0.12.0"), "3 Oct 2026", "the song after the pick chosen ahead; lookups four at a time; Spotify API in settings; pictures folded away"],
            [c("0.11.1"), "3 Oct 2026", "Up next beside the log; upcoming lyrics shown; no boxes in Terminal.app"],
            [c("0.11.0"), "3 Oct 2026", "next starts the pick without TIDAL's own next; finer detail; the flat logo"]]
    body = f"""
<div class="secno">11 · Files, commands and revisions</div><h1>Reference</h1>
<div class="cols" style="grid-template-columns:0.95fr 1.05fr">
  <div><h2><span class="n">11.1</span>Files, in {c('~/.config/tidal-shuffle')}</h2>{table(["File", "Holds"], frows, ["40%", "60%"])}</div>
  <div><h2><span class="n">11.2</span>Commands: {c('tidal-shuffle …')}</h2>{table(["Command", "Does"], crow, ["24%", "76%"])}</div>
</div>
<h2><span class="n">11.3</span>Revisions</h2>
{table(["Rev", "Date", "Changes"], revs, ["10%", "14%", "76%"])}
<p class="muted" style="margin-top:18px">Alter Era · Engineering. Tidal Shuffle is not made by or affiliated with TIDAL or Spotify.</p>
"""
    return page(body, 15, total, "11 · Reference")


def manual() -> str:
    total = 15
    parts = [cover(), contents(total), overview(total), install(total), operating(total), keys(total), settings(total),
             choosing(total), handoff(total), pressing_next(total), sources(total), display(total), config_ref(total),
             troubleshoot(total), files(total)]
    return head("Tidal Shuffle · Engineering and operation manual") + "".join(parts) + "</body></html>"


# --------------------------------------------------------------------------------------------
# the one-page operation card
# --------------------------------------------------------------------------------------------
def card() -> str:
    keys = "".join(f'<tr><td>{K(k)}</td><td>{d}</td></tr>' for k, d in (
        ("space", "play / pause"), ("n", "next pick"), ("b", "back"), ("f", "next flow"), ("p", "presets"),
        ("l", "lyrics"), ("a", "album cover"), ("t", "shuffle tree"), ("esc", "settings"), ("q", "quit")))
    body = f"""
<div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:-6px">
  <div><div class="secno">Operation card</div><h1 style="margin-bottom:6px">Tidal Shuffle</h1>
  <p class="muted" style="margin:0">Follows the song TIDAL plays, chooses a related one, and plays it when the song ends.</p></div>
  <div style="text-align:right;font:400 8px/1.6 {MONO};color:{SOFT};letter-spacing:0.08em">{CARD_DOC} · REV {REV}<br>{DATE.upper()}</div>
</div>
<div class="cols" style="grid-template-columns:1.12fr 0.88fr;margin-top:14px;gap:26px">
  <div>
    <h2><span class="n">1</span>Install, once</h2>
<pre>git clone -b claude/blissful-pasteur-dw57cr \\
  https://github.com/canyoubarrett/vim.git ~/tidal-shuffle-src
cd ~/tidal-shuffle-src/tidal-shuffle && ./install.sh
tidal-shuffle login     <span class="c"># approve the link</span>
tidal-shuffle doctor    <span class="c"># fix what it marks</span></pre>
    <h2><span class="n">2</span>Run</h2>
    <p>Play a song in TIDAL, then {c('tidal-shuffle run')}. Leave the window open. Options: {c('--preset chill')},
    {c('--flow rising')}, {c('--plain')}.</p>
    <h2><span class="n">3</span>Update</h2>
    <p>Quit with {K('q')}, then {c('tidal-shuffle update')}. Settings and pictures are kept.</p>
    <h2><span class="n">4</span>When something is wrong</h2>
    <ul class="plain">
      <li>{c('tidal-shuffle doctor')}: checks every part, says how to fix it.</li>
      <li>TIDAL plays its own song first: allow Terminal in Accessibility.</li>
      <li>"could not start": {c('tidal-shuffle inspect --watch 20')}, send it.</li>
      <li>Boxes with question marks: Esc → Picture detail → Medium.</li>
    </ul>
  </div>
  <div>
    <h2><span class="n">5</span>Keys</h2>
    <table style="margin-top:2px"><colgroup><col style="width:22%"><col style="width:78%"></colgroup><tbody>{keys}</tbody></table>
    <p class="muted">{K('⏯')} {K('⏭')} {K('⏮')} work too while the window is in front. Everything can be clicked.</p>
    <h2><span class="n">6</span>Settings {K('esc')}</h2>
    <p class="muted">{K('↑')}{K('↓')} move, {K('←')}{K('→')} section or slider, {K('enter')} choose, {K('esc')} close.
    Themes, logo, backdrops, picture detail, lyrics and the Spotify API: the preview shows each before you choose.</p>
  </div>
</div>
{figure(diagrams.timeline(slug="card-timeline"), "Every song · the next is chosen early, the pick starts as the song ends")}
"""
    page_html = (f'<section class="page">{watermark()}'
                 f'<div class="run-head"><span class="brand">{logo(16, label="")}<span>Alter Era</span></span>'
                 f'<span>Tidal Shuffle · Operation card · {CARD_DOC}</span></div>{body}'
                 f'<div class="run-foot"><span>Full manual: {DOC}</span><span>01 / 01</span></div></section>')
    return head("Tidal Shuffle · Operation card") + page_html + "</body></html>"


if __name__ == "__main__":
    from pathlib import Path

    here = Path(__file__).parent
    (here / "tidal-shuffle-manual.html").write_text(manual())
    (here / "tidal-shuffle-operation-card.html").write_text(card())
    print("built")
