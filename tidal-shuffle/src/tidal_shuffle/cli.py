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


def say(msg: str) -> None:
    console.print(f"[dim]{_stamp()}[/dim] {escape(msg)}", highlight=False)


class Verbose:
    enabled = False

    @classmethod
    def log(cls, msg: str) -> None:
        if cls.enabled:
            console.print(f"[dim]{_stamp()}   {escape(msg)}[/dim]", highlight=False)


def common_options(fn):
    @click.option("--config", "config_path", type=click.Path(path_type=Path), help="Config file (default ~/.config/tidal-shuffle/config.yaml)")
    @click.option("--preset", "-p", help="Named preset (see `tidal-shuffle presets`)")
    @click.option("--source", "-s", "sources", help="Comma separated sources, in priority order")
    @click.option("--strategy", type=click.Choice(["top", "weighted", "random", "discovery"]), help="Pick strategy")
    @click.option("--blend/--no-blend", default=None, help="Merge candidates from every source")
    @click.option("--artist-cooldown", type=int, help="Do not repeat an artist within N picks")
    @click.option("--allow-seed-artist/--no-seed-artist", default=None, help="May the next song be by the current artist?")
    @click.option("--seed-mode", type=click.Choice(["current", "anchor", "window"]), help="What the recommendations are seeded from")
    @click.option("--handoff", type=float, help="Seconds before the end to start the next song")
    @click.option("--energy", type=float, help="Spotify API tuning 0-1")
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
    for key, name in (("strategy", "strategy"), ("blend", "blend"), ("artist_cooldown", "artist_cooldown"),
                      ("allow_seed_artist", "allow_seed_artist"), ("seed_mode", "seed")):
        if kwargs.get(key) is not None:
            shuffle[name] = kwargs[key]
    if kwargs.get("handoff") is not None:
        player["handoff_seconds"] = kwargs["handoff"]
    if kwargs.get("energy") is not None:
        vibe["energy"] = kwargs["energy"]
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
@click.group()
@click.version_option(__version__, prog_name="tidal-shuffle")
def cli():
    """A smarter shuffle for the TIDAL macOS app.

    Watches what TIDAL plays, picks a related next song from Spotify, Last.fm,
    Deezer or TIDAL radio, and makes TIDAL play it when the current one ends.
    """


@cli.command()
@common_options
@click.option("--dry-run", is_flag=True, help="Plan picks but never touch TIDAL")
@click.option("--once", is_flag=True, help="Stop after the first plan")
def run(dry_run, once, **kwargs):
    """Follow TIDAL and keep the music going."""
    cfg = _config_from(kwargs)
    _banner("Tidal Shuffle", "a smarter shuffle for the TIDAL app")
    _require_macos("tidal-shuffle run")
    rt = _runtime(cfg)
    from .loop import ShuffleLoop

    try:
        method = rt.player.ensure_ready() if not dry_run else rt.player.method()
    except RuntimeError as e:
        raise click.ClickException(str(e))
    _print_startup(rt, method)
    loop = ShuffleLoop(cfg, rt.engine, rt.player, rt.nowplaying, rt.history, log=say, background=True,
                       timing_path=TIMING_FILE)
    controls = _start_controls(cfg, loop)
    import signal

    def _stop(signum, frame):  # closing the terminal or `kill` should clean up like Ctrl+C
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            signal.signal(sig, _stop)
    try:
        loop.run(dry_run=dry_run, once=once)
    except KeyboardInterrupt:
        rt.abort()
    finally:
        for c in controls:
            c.stop()
        rt.close()
    console.print(f"\n[bold]Stopped after {loop.state.picks_played} picks. Happy listening.[/bold]")


def _start_controls(cfg: AppConfig, loop) -> list:
    """Terminal keys and media keys; returns what was started (to stop later)."""
    from .controls import KEY_HELP, KeyReader, MediaKeyTap

    started = []
    keys = KeyReader(loop.post) if cfg.player.terminal_keys else None
    if keys is not None and keys.start():
        started.append(keys)
        console.print(f"[dim]keys: {KEY_HELP} · Ctrl+C stops[/dim]")
    else:
        console.print("[dim]Press Ctrl+C to stop[/dim]")
    if cfg.player.media_keys != "off":
        tap = MediaKeyTap(loop.post, mode=cfg.player.media_keys, log=say)
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
def inspect(track, config_path):
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
    cands = src.candidates([seed], limit)
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
