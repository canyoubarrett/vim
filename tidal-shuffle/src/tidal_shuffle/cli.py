"""Command line interface."""

from __future__ import annotations

import datetime as _dt
import functools
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import (EXAMPLE_CONFIG, AppConfig, ConfigError, all_presets, default_config_path, load_config,
                     read_config_file, write_example_config)
from .models import Seed
from .paths import TIMING_FILE

console = Console()
err_console = Console(stderr=True)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%H:%M:%S")


# The full-screen view, while `run` shows it: log lines go to its log panel.
_SCREEN = None


def say(msg: str) -> None:
    if _SCREEN is not None:
        _SCREEN.log(msg)
        return
    console.print(f"[dim]{_stamp()}[/dim] {escape(msg)}", highlight=False)


class Verbose:
    enabled = False

    @classmethod
    def log(cls, msg: str) -> None:
        if cls.enabled:
            if _SCREEN is not None:
                _SCREEN.log("  " + msg, dim=True)
                return
            console.print(f"[dim]{_stamp()}   {escape(msg)}[/dim]", highlight=False)


def common_options(fn):
    @click.option("--config", "config_path", type=click.Path(path_type=Path), help="Config file (default ~/.config/tidal-shuffle/config.yaml)")
    @click.option("--preset", "-p", help="Named preset (see `tidal-shuffle presets`)")
    @click.option("--source", "-s", "sources", help="Comma separated sources, in priority order")
    @click.option("--strategy", type=click.Choice(["top", "weighted", "random", "discovery"]), help="Pick strategy")
    @click.option("--flow", type=click.Choice(["radio", "rising", "falling", "steady", "soundscape", "vibe"]),
                  help="How each song follows the last: radio, rising / falling energy, steady energy, soundscape, vibe")
    @click.option("--blend/--no-blend", default=None, help="Merge candidates from every source")
    @click.option("--artist-cooldown", type=int, help="Do not repeat an artist within N picks")
    @click.option("--allow-seed-artist/--no-seed-artist", default=None, help="May the next song be by the current artist?")
    @click.option("--seed-mode", type=click.Choice(["current", "anchor", "window"]), help="What the recommendations are seeded from")
    @click.option("--handoff", type=float, help="Seconds before the end to start the next song")
    @click.option("--energy", type=float, help="Energy 0-1: the steady flow's level (and Spotify API tuning)")
    @click.option("--mood", type=float, help="Spotify API tuning 0-1 (valence)")
    @click.option("--genres", help="Spotify API genre seeds, comma separated")
    @click.option("--verbose", "-v", is_flag=True, help="Show what every source and lookup is doing")
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


def _config_from(kwargs: dict) -> AppConfig:
    Verbose.enabled = bool(kwargs.pop("verbose", False))
    overrides: dict = {}
    shuffle: dict = {}
    player: dict = {}
    vibe: dict = {}
    if kwargs.get("sources"):
        overrides["sources"] = kwargs["sources"]
    for key, name in (("strategy", "strategy"), ("flow", "flow"), ("blend", "blend"), ("artist_cooldown", "artist_cooldown"),
                      ("allow_seed_artist", "allow_seed_artist"), ("seed_mode", "seed")):
        if kwargs.get(key) is not None:
            shuffle[name] = kwargs[key]
    if kwargs.get("handoff") is not None:
        player["handoff_seconds"] = kwargs["handoff"]
    if kwargs.get("energy") is not None:
        vibe["energy"] = kwargs["energy"]
        shuffle["energy"] = kwargs["energy"]      # the steady flow's level too
    if kwargs.get("mood") is not None:
        vibe["valence"] = kwargs["mood"]
    if kwargs.get("genres"):
        vibe["genres"] = kwargs["genres"]
    if shuffle:
        overrides["shuffle"] = shuffle
    if player:
        overrides["player"] = player
    if vibe:
        overrides["spotify"] = {"vibe": vibe}
    try:
        return load_config(kwargs.get("config_path"), preset=kwargs.get("preset"), overrides=overrides)
    except ConfigError as e:
        raise click.ClickException(str(e))


def _banner(title: str, subtitle: str = "") -> None:
    body = f"[bold blue]{title}[/bold blue]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/dim]"
    console.print(Panel.fit(body, border_style="blue"))


def _require_macos(what: str) -> None:
    if platform.system() != "Darwin":
        raise click.ClickException(f"{what} needs macOS (this is {platform.system()})")


def _runtime(cfg: AppConfig, need_tidal: bool = True):
    from .app import build_runtime
    from .tidal.catalog import TidalLoginRequired

    try:
        return build_runtime(cfg, logger=Verbose.log, printer=lambda m: console.print(m, markup=False),
                             interactive=True, need_tidal=need_tidal)
    except TidalLoginRequired as e:
        raise click.ClickException(str(e))


def _describe_sources(rt) -> Table:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("source")
    table.add_column("status")
    for s in rt.sources:
        ok, reason = s.available()
        table.add_row(s.name, "[green]ready[/green]" if ok else f"[yellow]off[/yellow] [dim]{escape(reason)}[/dim]")
    return table


def _print_startup(rt, method: str) -> None:
    cfg = rt.config
    sh = cfg.shuffle
    console.print(_describe_sources(rt))
    console.print(f"[dim]strategy[/dim] {sh.strategy}   [dim]seed[/dim] {sh.seed}   [dim]artist cooldown[/dim] {sh.artist_cooldown}"
                  f"   [dim]preset[/dim] {cfg.preset or '-'}")
    ok, reason = rt.nowplaying.available()
    np_desc = "[green]ok[/green]" if ok else f"[red]{reason}[/red]"
    console.print(f"[dim]player[/dim] {method}   [dim]now playing[/dim] {np_desc}   [dim]history[/dim] {len(rt.history)} songs")
    if method.startswith("open-url"):
        console.print("[yellow]TIDAL is not reachable over its debug port, so songs can only be opened, not started. "
                      "Run `tidal-shuffle doctor` for the fix.[/yellow]")


# ---------------------------------------------------------------------------
def _print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    from .buildinfo import describe

    click.echo(describe())
    ctx.exit()


@click.group()
@click.option("--version", is_flag=True, expose_value=False, is_eager=True, callback=_print_version,
              help="Show the version, the code revision and where this copy is installed.")
def cli():
    """A smarter shuffle for the TIDAL macOS app.

    Watches what TIDAL plays, picks a related next song from Spotify, Last.fm,
    Deezer or TIDAL radio, and makes TIDAL play it when the current one ends.
    """


@cli.command()
@common_options
@click.option("--dry-run", is_flag=True, help="Plan picks but never touch TIDAL")
@click.option("--once", is_flag=True, help="Stop after the first plan")
@click.option("--plain", is_flag=True, help="Scrolling log instead of the full-screen view with lyrics")
@click.option("--color", "color_opt", type=click.Choice(["auto", "truecolor", "256", "16"]), default=None,
              help="Colours to use (overrides ui.color); see `tidal-shuffle colors`")
def run(dry_run, once, plain, color_opt, **kwargs):
    """Follow TIDAL and keep the music going."""
    cfg = _config_from(kwargs)
    from .buildinfo import revision

    rev = revision()
    _banner("Tidal Shuffle", f"a smarter shuffle for the TIDAL app · {__version__}" + (f" · {rev}" if rev else ""))
    _require_macos("tidal-shuffle run")
    rt = _runtime(cfg)
    from .loop import ShuffleLoop

    try:
        method = rt.player.ensure_ready() if not dry_run else rt.player.method()
    except RuntimeError as e:
        raise click.ClickException(str(e))
    _print_startup(rt, method)
    loop = ShuffleLoop(cfg, rt.engine, rt.player, rt.nowplaying, rt.history, log=say, background=True,
                       timing_path=TIMING_FILE, apply_preset=rt.apply_preset)
    screen = None
    color = color_opt or cfg.ui.color
    hint = ""
    if color != "auto":
        _use_color(color)
    else:
        mode, hint = auto_color(os.environ, platform.mac_ver()[0], console.color_system)
        if mode:
            _use_color(mode, explicit=False)
        if hint:
            console.print(hint, style="yellow", markup=False)
    if cfg.ui.screen == "full" and not plain and not once:
        if console.is_terminal:
            screen = _make_screen(cfg, rt, loop)
            loop.max_poll = cfg.ui.track_poll     # see a new song (and drop the old lyrics) quickly
            if hint:
                screen.log(f"⚠ {hint}")             # the note above is hidden by the full screen
        else:
            console.print("[yellow]full-screen view off: the output is not a terminal (piped or redirected)[/yellow]")
    controls = _start_controls(cfg, loop, screen)
    guard = _keep_spotify_hidden(cfg, [s for s in rt.sources if s.name == "spotify-app"])
    if guard is not None:
        controls.append(guard)
    import signal

    def _stop(signum, frame):  # closing the terminal or `kill` should clean up like Ctrl+C
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            signal.signal(sig, _stop)
    global _SCREEN
    live = None
    try:
        if screen is not None:
            from rich.live import Live

            from .tui import ScreenRenderable

            live = Live(ScreenRenderable(screen), console=console, screen=True, auto_refresh=True,
                        refresh_per_second=cfg.ui.fps, redirect_stdout=False, redirect_stderr=False)
            live.start()
            if cfg.ui.mouse:
                _mouse(True)
            _SCREEN = screen
        loop.run(dry_run=dry_run, once=once)
    except KeyboardInterrupt:
        rt.abort()
    finally:
        _SCREEN = None
        if live is not None:
            if cfg.ui.mouse:
                _mouse(False)
            live.stop()
        for c in controls:
            c.stop()
        rt.close()
    if screen is not None:
        for stamp, msg, dim in list(screen.logs)[-12:]:   # what happened last, on the normal screen
            console.print(f"[dim]{stamp}[/dim] {escape(msg)}", highlight=False)
    console.print(f"\n[bold]Stopped after {loop.state.picks_played} picks. Happy listening.[/bold]")


def _mouse(on: bool) -> None:
    """Have the terminal report clicks and the wheel (to the key reader), or stop."""
    from .controls import MOUSE_OFF, MOUSE_ON

    try:
        console.file.write(MOUSE_ON if on else MOUSE_OFF)
        console.file.flush()
    except Exception:
        pass


def _keep_spotify_hidden(cfg: AppConfig, spotify_sources: list):
    """Hide the Spotify app whenever it shows up while Tidal Shuffle is using it."""
    if not spotify_sources or not cfg.spotify.app.keep_hidden or platform.system() != "Darwin":
        return None
    from .activity import is_busy
    from .spotify_guard import SpotifyGuard

    src = spotify_sources[0]
    guard = SpotifyGuard(lambda: is_busy() or bool(getattr(src, "_launched_by_us", False)), log=say)
    return guard if guard.start() else None


def auto_color(env, mac_version: str, system: Optional[str]) -> tuple[Optional[str], str]:
    """(colour system to use, or None to keep what was detected; a note for
    the user) for ``ui.color: auto``.

    Terminal.app shows 256 colours for certain; whether it shows 24-bit
    colour depends on the macOS version, and it never says (no COLORTERM).
    Sending it 24-bit colour it cannot show leaves the screen colourless, so
    it gets 256 colours, which are always right, with the theme matched to
    its palette; `tidal-shuffle colors` shows whether true colour works."""
    if env.get("NO_COLOR"):
        return None, ("colours are off because NO_COLOR is set in your shell; "
                      "unset it, or set ui.color: 256 to use colours anyway")
    if system == "truecolor":
        return None, ""
    if env.get("TERM_PROGRAM") == "Apple_Terminal":
        return "256", ("Terminal.app: 256 colours, with the theme matched to them; run `tidal-shuffle colors` "
                       "to see whether your Terminal shows true colour (then set ui.color: truecolor)")
    if system is None:
        return "256", (f"your terminal did not report colour support (TERM={env.get('TERM', '')!r}); using 256 "
                       "colours; run `tidal-shuffle colors` to check")
    if system == "standard":
        return None, ("your terminal reports 16 colours only, so the theme is approximated; "
                      "run `tidal-shuffle colors` to check what it can show")
    return None, ""


def _use_color(mode: str, explicit: bool = True) -> None:
    """Force a colour system when the terminal under-reports it (ui.color)."""
    global console
    systems = {"truecolor": "truecolor", "256": "256", "16": "standard"}
    console = Console(color_system=systems.get(mode, "auto"), force_terminal=True if console.is_terminal else None,
                      no_color=False if explicit else None)


def _make_screen(cfg: AppConfig, rt, loop):
    """The full-screen view: lyrics service, floating logo, log panel."""
    from . import paths
    from .lyrics import LrclibLyrics, LyricsService, TidalLyrics
    from .tui import ShuffleTUI
    from .visualizer import LogoScene

    lyrics = None
    if cfg.ui.lyrics:
        sources = []
        for name in cfg.ui.lyrics_sources:
            if name == "tidal" and rt.catalog is not None:
                sources.append(TidalLyrics(rt.catalog))
            elif name == "lrclib":
                sources.append(LrclibLyrics())
        lyrics = LyricsService(sources, cache_path=paths.CONFIG_DIR / "cache" / "lyrics.json", log=Verbose.log)
    from . import uistate

    settings_path = paths.CONFIG_DIR / "ui.json"
    uistate.apply(cfg.ui, uistate.load(settings_path))      # what was chosen in the settings menu last time
    scene = None
    if cfg.ui.visualizer:
        art = Path(cfg.ui.logo_file).expanduser() if cfg.ui.logo_file else None
        scene = LogoScene(art_path=art, cell_aspect=cfg.ui.cell_aspect, style=cfg.ui.logo_style,
                          motion=cfg.ui.logo_motion)
    artwork = None
    if cfg.ui.artwork and rt.catalog is not None:
        from .artwork import ArtworkService

        artwork = ArtworkService(rt.catalog, paths.CONFIG_DIR / "cache" / "art", log=Verbose.log)
    return ShuffleTUI(loop, cfg, lyrics=lyrics, scene=scene, artwork=artwork, history=rt.history, post=loop.post,
                      settings_path=settings_path)


def _start_controls(cfg: AppConfig, loop, screen=None) -> list:
    """Terminal keys and media keys; returns what was started (to stop later)."""
    from .controls import KEY_HELP, KeyReader, MediaKeyTap

    def command(cmd: str) -> None:
        if screen is not None:
            if not screen.handle_input(cmd):      # menus and clicks first, then the loop
                loop.post(cmd)
        elif cmd == "view":
            say("the logo and lyrics are part of the full-screen view (leave out --plain)")
        elif cmd == "presets":
            say("pick a preset with --preset NAME, or in the full-screen view (leave out --plain)")
        elif cmd == "art":
            say("the album cover is part of the full-screen view (leave out --plain)")
        elif cmd == "art":
            say("the album cover is part of the full-screen view (leave out --plain)")
        else:
            loop.post(cmd)

    started = []
    sink = getattr(screen, "text_sink", None) if screen is not None else None
    keys = KeyReader(command, text_sink=sink) if cfg.player.terminal_keys else None
    if keys is not None and keys.start():
        started.append(keys)
        console.print(f"[dim]keys: {KEY_HELP} · Ctrl+C stops[/dim]")
    else:
        console.print("[dim]Press Ctrl+C to stop[/dim]")
    if cfg.player.media_keys != "off":
        tap = MediaKeyTap(command, mode=cfg.player.media_keys, log=say)
        if tap.start():
            started.append(tap)
            where = "while this window is in front" if cfg.player.media_keys == "focus" else "everywhere"
            console.print(f"[dim]media keys ⏯ ⏭ ⏮ control Tidal Shuffle {where}[/dim]")
    console.print()
    return started


@cli.command()
@common_options
def test(**kwargs):
    """Dry run: show what would be played next for the current song."""
    cfg = _config_from(kwargs)
    _banner("Tidal Shuffle — test", "one planning pass, nothing is played")
    _require_macos("tidal-shuffle test")
    rt = _runtime(cfg)
    from .loop import ShuffleLoop

    _print_startup(rt, rt.player.method())
    loop = ShuffleLoop(cfg, rt.engine, rt.player, rt.nowplaying, rt.history, log=say, timing_path=TIMING_FILE)
    np = rt.nowplaying.read()
    if np is None or not np.is_tidal:
        raise click.ClickException("TIDAL is not playing anything right now")
    loop.step(dry_run=True)
    plan = loop.state.plan or loop.plan_now(dry_run=True)
    rt.close()
    if plan is None or not plan.picks:
        raise click.ClickException("no pick could be made")
    table = Table(title=f"after {escape(plan.seed.label())}", show_header=True, header_style="bold")
    table.add_column("#"); table.add_column("song"); table.add_column("source"); table.add_column("why")
    for i, p in enumerate(plan.picks, 1):
        table.add_row(str(i), escape(p.track.label()), p.source, escape(p.reason))
    console.print(table)


@cli.command(name="next")
@common_options
def next_cmd(**kwargs):
    """Skip to a fresh pick right now."""
    cfg = _config_from(kwargs)
    _require_macos("tidal-shuffle next")
    rt = _runtime(cfg)
    from .loop import ShuffleLoop

    np = rt.nowplaying.read()
    if np is None or not np.is_tidal:
        raise click.ClickException("TIDAL is not playing anything right now")
    try:
        rt.player.ensure_ready(allow_relaunch=False)  # never stop the music we are about to skip
    except RuntimeError as e:
        raise click.ClickException(str(e))
    loop = ShuffleLoop(cfg, rt.engine, rt.player, rt.nowplaying, rt.history, log=say, timing_path=TIMING_FILE)
    ok = loop.skip_now()
    rt.close()
    if not ok:
        raise click.ClickException("could not pick or start a next song (is TIDAL playing?)")


@cli.command()
@click.option("--force", is_flag=True, help="Log in again even if a session exists")
@click.option("--config", "config_path", type=click.Path(path_type=Path))
def login(force, config_path):
    """Log in to TIDAL (device link; opens a URL to approve)."""
    cfg = _config_from({"config_path": config_path})
    from .tidal.catalog import TidalLoginRequired, connect_session

    if force and cfg.tidal.session_file.exists():
        cfg.tidal.session_file.unlink()
    try:
        session = connect_session(cfg.tidal.session_file, printer=lambda m: console.print(m, markup=False))
    except TidalLoginRequired as e:
        raise click.ClickException(str(e))
    user = getattr(session, "user", None)
    console.print(f"[green]✓[/green] logged in to TIDAL (user id {getattr(user, 'id', '?')}); session saved to {cfg.tidal.session_file}")


@cli.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path))
def presets(config_path):
    """List the built-in and user-defined presets."""
    try:
        raw, _ = read_config_file(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e))
    file_presets = raw.get("presets") if isinstance(raw.get("presets"), dict) else {}
    table = Table(show_header=True, header_style="bold")
    table.add_column("preset"); table.add_column("description"); table.add_column("settings")
    for name, p in sorted(all_presets(file_presets).items()):
        p = dict(p) if isinstance(p, dict) else {}
        desc = str(p.pop("description", ""))
        bits = []
        for section, values in p.items():
            if isinstance(values, dict):
                inner = ", ".join(f"{k}={v}" for k, v in values.items() if not isinstance(v, dict))
                for k, v in values.items():
                    if isinstance(v, dict):
                        inner += (", " if inner else "") + f"{k}: " + ", ".join(f"{kk}={vv}" for kk, vv in v.items())
                bits.append(f"{section}: {inner}")
            else:
                bits.append(f"{section}={values}")
        table.add_row(escape(str(name)), escape(desc), escape("; ".join(bits)))
    console.print(table)


@cli.command()
@common_options
@click.option("--seed", help='Seed song as "Title - Artist" (default: what TIDAL is playing)')
@click.option("--limit", default=8, show_default=True, help="Candidates to show per source")
def sources(seed, limit, **kwargs):
    """Check every source and show what each would suggest."""
    cfg = _config_from(kwargs)
    rt = _runtime(cfg)
    seed_obj = _seed_from(seed, rt)
    console.print(f"[bold]seed:[/bold] {escape(seed_obj.label())}\n")
    for s in rt.sources:
        ok, reason = s.available()
        if not ok:
            console.print(f"[yellow]{s.name}[/yellow]: off ({escape(reason)})")
            continue
        try:
            cands = s.candidates([seed_obj], limit)
        except Exception as e:
            console.print(f"[red]{s.name}[/red]: error: {escape(str(e))}")
            continue
        console.print(f"[green]{s.name}[/green]: {len(cands)} candidates")
        for c in cands[:limit]:
            console.print(f"   {c.score:.2f}  {escape(c.label())}" + (f"  [dim]({escape(c.album)})[/dim]" if c.album else ""), highlight=False)
    rt.close()


def _seed_from(seed: Optional[str], rt, hint: str = '--seed "Title - Artist"') -> Seed:
    if seed:
        if " - " not in seed:
            raise click.ClickException(f"use {hint}")
        title, artist = [p.strip() for p in seed.split(" - ", 1)]
        return Seed(title=title, artist=artist)
    np = rt.nowplaying.read()
    if np is None or not np.is_tidal:
        raise click.ClickException('TIDAL is not playing anything; pass --seed "Title - Artist"')
    return Seed.from_now_playing(np)


@cli.command()
@click.option("--clear", is_flag=True, help="Forget everything")
@click.option("-n", "count", default=20, show_default=True)
def history(clear, count):
    """Show (or clear) the songs this tool has played."""
    from .history import HistoryStore

    store = HistoryStore()
    if clear:
        n = len(store)
        store.clear()
        console.print(f"cleared {n} entries")
        return
    for e in store.recent(count):
        when = _dt.datetime.fromtimestamp(e.ts).strftime("%Y-%m-%d %H:%M") if e.ts else "?"
        console.print(f"{when}  {escape(e.title)} — {escape(e.artist)}  [dim]{escape(e.source or '')}[/dim]", highlight=False)
    console.print(f"[dim]{len(store)} entries total[/dim]")


@cli.group()
def config():
    """Create or show the configuration file."""


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite an existing file")
@click.option("--path", type=click.Path(path_type=Path), default=None)
def config_init(force, path):
    """Write an annotated example config."""
    try:
        p = write_example_config(path, overwrite=force)
    except FileExistsError as e:
        raise click.ClickException(f"{e} already exists (use --force to overwrite)")
    console.print(f"wrote {p}")


@config.command("show")
@common_options
def config_show(**kwargs):
    """Print the effective configuration (secrets masked)."""
    import yaml

    cfg = _config_from(kwargs)
    console.print(yaml.safe_dump(cfg.describe(), sort_keys=False), markup=False)


@config.command("path")
def config_path_cmd():
    console.print(str(default_config_path()), markup=False)


@cli.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path))
def now(config_path):
    """Show what each now-playing backend reports."""
    cfg = _config_from({"config_path": config_path})
    _require_macos("tidal-shuffle now")
    from .nowplaying.media import MediaControlBackend, NowPlayingCliBackend
    from .tidal.cdp import TidalCdp

    for backend in (MediaControlBackend(), NowPlayingCliBackend()):
        ok, reason = backend.available()
        if not ok:
            console.print(f"[yellow]{backend.name}[/yellow]: {reason}")
            continue
        np = backend.read()
        console.print(f"[green]{backend.name}[/green]: {np}")
    cdp = TidalCdp(port=cfg.player.cdp_port, app_path=cfg.player.tidal_app)
    if cdp.alive():
        try:
            console.print(f"[green]tidal (cdp)[/green]: {cdp.now_playing()}")
        except Exception as e:
            console.print(f"[red]tidal (cdp)[/red]: {e}")
    else:
        console.print("[yellow]tidal (cdp)[/yellow]: TIDAL not reachable on the debug port")


def _resolve_track(track, rt):
    """A TIDAL track from an id, "Title - Artist", or (no argument) a radio pick for what is playing."""
    from .models import TidalTrack

    if track and track.isdigit():
        t = rt.catalog.get_track(track)
        if t is None:
            raise click.ClickException(f"TIDAL track {track} not found")
    elif track:
        seed = _seed_from(track, rt, hint='a TIDAL track id or "Title - Artist"')
        t, score = rt.catalog.find(seed.title, seed.artist)
        if t is None:
            raise click.ClickException(f"could not find {track!r} on TIDAL (best score {score:.2f})")
    else:
        np = rt.nowplaying.read()
        if np is None or not np.is_tidal:
            raise click.ClickException("give a track id or \"Title - Artist\"")
        seed = Seed.from_now_playing(np)
        radio = [s for s in rt.sources if s.name == "tidal-radio"]
        cands = radio[0].candidates([seed], 5) if radio else []
        if not cands:
            raise click.ClickException("no candidate to test with; give a track id")
        t = rt.catalog.match(cands[0]) or TidalTrack(id=cands[0].tidal_id, title=cands[0].title, artist=cands[0].artist)
    return t


@cli.command()
@click.argument("track", required=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path))
@click.option("--method", type=click.Choice(["auto", "luna", "cdp", "open-url", "open-url-play"]), default="auto", show_default=True)
def playtest(track, config_path, method):
    """Try to make TIDAL play a track (id or "Title - Artist") and report what worked."""
    cfg = _config_from({"config_path": config_path})
    _require_macos("tidal-shuffle playtest")
    cfg.player.play_strategy = method
    rt = _runtime(cfg)
    t = _resolve_track(track, rt)
    console.print(f"target: {escape(t.label())}  (id {t.id})")
    try:
        ready = rt.player.ensure_ready()
    except RuntimeError as e:
        raise click.ClickException(str(e))
    console.print(f"method: {ready}")
    outcome = rt.player.play(t)
    console.print(f"result: {'[green]ok[/green]' if outcome.ok else '[red]failed[/red]'}  via {outcome.method}  {escape(outcome.detail)}")
    if not outcome.ok:
        import time

        time.sleep(3)
        np = rt.nowplaying.read()
        console.print(f"now playing afterwards: {escape(np.label()) if np else 'nothing'}")
    rt.close()


@cli.command()
@click.argument("track", required=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path))
@click.option("--watch", type=int, default=0, metavar="SECONDS",
              help="Then record what TIDAL does while you start a song by hand (try 20)")
def inspect(track, config_path, watch):
    """Dump what the TIDAL player page looks like (for fixing selectors).

    With TRACK (an id or "Title - Artist") it first opens that track's page
    and reports how the play logic sees it. Paste the output into a bug report.
    """
    cfg = _config_from({"config_path": config_path})
    _require_macos("tidal-shuffle inspect")
    import json
    import time

    from .tidal.cdp import TidalCdp

    cdp = TidalCdp(port=cfg.player.cdp_port, app_path=cfg.player.tidal_app)
    if not cdp.alive():
        raise click.ClickException("TIDAL is not reachable on the debug port; run `tidal-shuffle doctor`")
    tid = None
    if track:
        rt = _runtime(cfg)
        t = _resolve_track(track, rt)
        rt.close()
        tid = t.id
        console.print(f"opening {escape(t.label())} (id {t.id})", highlight=False)
        cdp.navigate_to_track(tid)
        time.sleep(4)
    console.print(json.dumps(cdp.inspect(tid), indent=2), markup=False)
    if watch:
        res = cdp.watch_actions()
        if res != "ok":
            console.print(f"could not watch TIDAL's player ({res})", markup=False)
            return
        console.print(f"\nNow start any song in TIDAL by hand (click a track's play button). "
                      f"Recording for {watch} seconds…", markup=False)
        time.sleep(watch)
        acts = [a for a in cdp.recorded_actions() if not str(a.get("type", "")).startswith(("@@", "persist/"))]
        console.print(json.dumps({"actions": acts[-120:]}, indent=2), markup=False)


@cli.command()
@click.argument("title")
@click.argument("artist")
@click.option("--config", "config_path", type=click.Path(path_type=Path))
@click.option("--limit", default=15, show_default=True)
def harvest(title, artist, config_path, limit):
    """Drive the Spotify app once and print the songs it suggests after TITLE by ARTIST."""
    cfg = _config_from({"config_path": config_path, "verbose": True})
    _require_macos("tidal-shuffle harvest")
    from .app import build_spotify_app

    rt = _runtime(cfg)
    srcs = [s for s in rt.sources if s.name == "spotify-app"]
    src = srcs[0] if srcs else build_spotify_app(cfg, rt.catalog, None, say)
    src.log = say
    ok, reason = src.available()
    if not ok:
        raise click.ClickException(reason)
    seed = Seed(title=title, artist=artist)
    guard = _keep_spotify_hidden(cfg, [src])
    try:
        cands = src.candidates([seed], limit)
    finally:
        if guard is not None:
            guard.stop()
    rt.close()
    if seed.spotify_id:
        console.print(f"[dim]found on Spotify as spotify:track:{seed.spotify_id} via {src.last_lookup}[/dim]")
    for c in cands:
        console.print(f"  {c.score:.2f}  {escape(c.label())}  [dim]{escape(c.album or '')}[/dim]", highlight=False)
    console.print(f"[dim]{len(cands)} songs[/dim]")


@cli.command(name="spotify-ui")
@click.option("--find", "find", help='Search Spotify for "Title - Artist" and press its play button (muted)')
@click.option("--limit", default=150, show_default=True, help="Labels to list")
@click.option("--config", "config_path", type=click.Path(path_type=Path))
def spotify_ui_cmd(find, limit, config_path):
    """Check that Tidal Shuffle can see and use the Spotify app's interface."""
    cfg = _config_from({"config_path": config_path})
    _require_macos("tidal-shuffle spotify-ui")
    import re

    from .spotify_ui import SpotifyUI, SpotifyUIError

    app_cfg = cfg.spotify.app
    ui = SpotifyUI(label_pattern="^" + re.escape(app_cfg.ui_label_prefix) + r"(?P<rest>.+)$",
                   by_word=app_cfg.ui_label_by, log=say)
    ok, reason = ui.available()
    if not ok:
        raise click.ClickException(reason)
    try:
        if find:
            if " - " not in find:
                raise click.ClickException('use --find "Title - Artist"')
            title, artist = [p.strip() for p in find.split(" - ", 1)]
            from .app import build_spotify_app
            from .sources.spotify_app import MUTE_SCRIPT

            src = build_spotify_app(cfg, None, None, say)
            ok, reason = src.available()
            if not ok:
                raise click.ClickException(reason)
            volume = src.ensure_running().get("volume")
            try:
                src.runner.run(MUTE_SCRIPT, timeout=8)
                button = ui.find_and_play(title, artist)
                if button is None:
                    raise click.ClickException("no matching song found on Spotify's search page")
                console.print(f"pressed: {escape(button.label)}  (match {button.score:.2f})")
                import time as _time
                _time.sleep(2.0)
                cur = src.current()
                console.print(f"Spotify is now on: {escape(cur.get('name', ''))} — {escape(cur.get('artist', ''))}  ({cur.get('id', '?')})")
            finally:
                src._restore(volume)  # pause Spotify and put its volume back
            return
        rows = ui.dump(limit=limit)
    except SpotifyUIError as e:
        raise click.ClickException(str(e))
    plays = 0
    for role, label in rows:
        mark = ""
        if label.startswith(app_cfg.ui_label_prefix) and app_cfg.ui_label_by in label:
            mark = "  [green]← track button[/green]"
            plays += 1
        console.print(f"[dim]{role:12}[/dim] {escape(label)}{mark}", highlight=False)
    console.print(f"[dim]{len(rows)} labelled elements, {plays} track play buttons[/dim]")


@cli.command()
def update():
    """Get the latest version (git pull) and reinstall it."""
    import subprocess

    from .buildinfo import PROJECT_DIR, describe, git_root, revision

    root = git_root()
    if root is None:
        raise click.ClickException(
            f"this copy ({PROJECT_DIR}) was not installed from a git clone, so it cannot update itself. "
            "Download the latest zip, unzip it, and run `bash install.sh` in it.")
    before = revision()
    console.print(f"[dim]updating {root}[/dim]")
    pull = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"], capture_output=True, text=True)
    console.print(escape((pull.stdout + pull.stderr).strip()), highlight=False)
    if pull.returncode != 0:
        raise click.ClickException("git pull failed (see above). If you changed files in that folder, "
                                   f"`git -C {root} stash` and run `tidal-shuffle update` again.")
    inst = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-e", str(PROJECT_DIR)],
                          capture_output=True, text=True)
    if inst.returncode != 0:
        console.print(escape(inst.stderr[-2000:]), highlight=False)
        raise click.ClickException("reinstalling failed (see above); run `bash install.sh` in " + str(PROJECT_DIR))
    after = revision()
    if before == after:
        console.print(f"[green]already up to date[/green]: {escape(describe())}")
    else:
        console.print(f"[green]updated[/green] {before} → {after}")
        console.print(escape(describe()))


@cli.command()
def colors():
    """Show which colours this terminal can display, to pick ui.color."""
    import sys as _sys

    env = os.environ
    out = _sys.stdout
    rows = [("TERM", env.get("TERM", "")), ("COLORTERM", env.get("COLORTERM", "")),
            ("TERM_PROGRAM", f"{env.get('TERM_PROGRAM', '')} {env.get('TERM_PROGRAM_VERSION', '')}".strip()),
            ("NO_COLOR", env.get("NO_COLOR", "")), ("macOS", platform.mac_ver()[0] or "-"),
            ("output is a terminal", str(out.isatty())), ("detected", str(console.color_system))]
    mode, hint = auto_color(env, platform.mac_ver()[0], console.color_system)
    rows.append(("tidal-shuffle run uses", mode or str(console.color_system)))
    for k, v in rows:
        out.write(f"  {k:<24}{v}\n")
    out.write("\n")
    from .theme import theme as _theme
    from .tui import nearest_256

    names = ["mauve", "pink", "peach", "yellow", "green", "teal", "blue", "lavender", "surface1", "base", "crust"]
    p = _theme("mocha").p
    reset = "\x1b[0m"
    line_a = "".join(f"\x1b[4{i}m  " for i in range(1, 7)) + reset
    line_b = "".join(f"\x1b[48;5;{nearest_256(p[n])}m   " for n in names) + reset
    line_c = "".join(f"\x1b[48;2;{p[n][0]};{p[n][1]};{p[n][2]}m   " for n in names) + reset
    grad = "".join(f"\x1b[48;2;{int(30 + 200 * i / 40)};{int(30 + 60 * i / 40)};{int(160 + 80 * i / 40)}m " for i in range(40)) + reset
    out.write(f"  A  16 colours      {line_a}\n")
    out.write(f"  B  256 colours     {line_b}\n")
    out.write(f"  C  true colour     {line_c}\n")
    out.write(f"  D  true colour     {grad}\n\n")
    out.write("  Rows B and C use the theme's colours: purple, pink, orange, yellow, green, teal, blue,\n"
              "  lavender, then three dark greys.\n"
              "  * C and D show those colours, D a smooth blue-to-pink blend: true colour works.\n"
              "    Put this in the config (`tidal-shuffle config path`):  ui: {color: truecolor}\n"
              "  * only A and B show colours (C and D grey, wrong or blank): keep ui.color: auto (256).\n"
              "  * nothing shows colours: check Terminal's profile and that NO_COLOR is not set.\n")
    if hint:
        out.write(f"\n  note: {hint}\n")
    out.flush()


@cli.group()
def backdrops():
    """Pictures to show behind the logo (Esc → Logo backdrop)."""


@backdrops.command("add")
@click.argument("sources", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
def backdrops_add(sources):
    """Copy pictures, folders of pictures or zips of pictures into the backdrops folder."""
    from .stages import add_backdrops, backdrop_dir

    n = add_backdrops(list(sources), log=lambda m: console.print(m, markup=False))
    console.print(f"added {n} picture{'s' if n != 1 else ''} to {backdrop_dir()}", markup=False)
    if n:
        console.print("pick one in `tidal-shuffle run`: Esc → Logo backdrop (←→ jumps to it)", markup=False)


@backdrops.command("list")
def backdrops_list():
    """The pictures in the backdrops folder."""
    from .stages import backdrop_dir, label, list_backdrops

    names = list_backdrops()
    for n in names:
        console.print(f"{label(n):<12} {n}", markup=False, highlight=False)
    console.print(f"{len(names)} in {backdrop_dir()}", markup=False)


@backdrops.command("path")
def backdrops_path():
    """Where the pictures are kept."""
    from .stages import backdrop_dir

    console.print(str(backdrop_dir()), markup=False)


@cli.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path))
def doctor(config_path):
    """Check everything this tool depends on and say how to fix what is missing."""
    from .doctor import run_doctor

    cfg = None
    try:
        cfg = _config_from({"config_path": config_path})
    except click.ClickException as e:
        console.print(f"[red]config error:[/red] {e.message}")
    run_doctor(cfg, console)


if __name__ == "__main__":
    cli()
