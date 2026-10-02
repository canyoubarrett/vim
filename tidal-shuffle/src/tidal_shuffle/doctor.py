"""`tidal-shuffle doctor`: check every moving part and say how to fix it."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .config import AppConfig
from .paths import CONFIG_FILE


def _row(table: Table, name: str, ok: Optional[bool], detail: str, fix: str = "") -> None:
    mark = {True: "[green]✓[/green]", False: "[red]✗[/red]", None: "[yellow]•[/yellow]"}[ok]
    table.add_row(mark, name, detail, fix)


def run_doctor(cfg: Optional[AppConfig], console: Console) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("")
    table.add_column("check")
    table.add_column("status")
    table.add_column("how to fix")
    mac = platform.system() == "Darwin"
    _row(table, "macOS", mac, platform.platform(), "" if mac else "Tidal Shuffle only runs on macOS")

    # Config
    if cfg is None:
        _row(table, "config", False, "invalid", "fix the errors above, or `tidal-shuffle config init --force`")
    elif cfg.config_path:
        _row(table, "config", True, str(cfg.config_path))
    else:
        _row(table, "config", None, f"no file at {CONFIG_FILE}; using defaults", "`tidal-shuffle config init` to create one")

    # TIDAL app + session
    app = Path(cfg.player.tidal_app if cfg else "/Applications/TIDAL.app")
    _row(table, "TIDAL app", app.exists() if mac else None, str(app), "" if app.exists() or not mac else "install TIDAL from tidal.com/download")
    if cfg:
        sess = cfg.tidal.session_file
        if sess.exists():
            logged = None
            detail = f"session file {sess}"
            try:
                from .tidal.catalog import connect_session
                connect_session(sess, printer=lambda m: None, interactive=False)
                logged, detail = True, "logged in"
            except Exception as e:
                logged, detail = False, f"session invalid: {e}"
            _row(table, "TIDAL login", logged, detail, "" if logged else "`tidal-shuffle login`")
        else:
            _row(table, "TIDAL login", False, "no session yet", "`tidal-shuffle login`")

    # Now playing
    if mac:
        mc = shutil.which("media-control")
        npc = shutil.which("nowplaying-cli")
        _row(table, "media-control", bool(mc), mc or "not found", "" if mc else "`brew install media-control` (recommended)")
        _row(table, "nowplaying-cli", bool(npc) if not mc else None, npc or "not found",
             "" if (mc or npc) else "`brew install nowplaying-cli` (fallback)")
        if mc:
            try:
                r = subprocess.run([mc, "get", "--no-artwork"], capture_output=True, text=True, timeout=6)
                from .nowplaying.media import parse_media_control
                import json
                np = parse_media_control(json.loads(r.stdout)) if r.stdout.strip() else None
                if np:
                    _row(table, "now playing", np.is_tidal, f"{np.label()} ({np.bundle_id})",
                         "" if np.is_tidal else "play something in TIDAL to test the rest")
                else:
                    _row(table, "now playing", None, "nothing is playing", "play something in TIDAL")
            except Exception as e:
                _row(table, "now playing", False, f"media-control failed: {e}")

    # CDP / Luna
    if mac and cfg:
        from .tidal.cdp import TidalCdp
        from .tidal.luna import LunaApi

        cdp = TidalCdp(port=cfg.player.cdp_port, app_path=cfg.player.tidal_app)
        running = cdp.app_running()
        alive = cdp.alive()
        fix = ""
        if not alive:
            fix = (f"quit TIDAL, then: open -a {cfg.player.tidal_app} --args --remote-debugging-port={cfg.player.cdp_port} "
                   f"--remote-debugging-address=127.0.0.1  (or let `tidal-shuffle run` relaunch it)")
        _row(table, "TIDAL debug port", alive, f"port {cfg.player.cdp_port}: {'reachable' if alive else 'not reachable'}"
             + ("" if alive else f" (TIDAL {'is' if running else 'is not'} running)"), fix)
        if alive:
            try:
                np = cdp.now_playing()
                _row(table, "TIDAL player page", np is not None, f"footer: {np.title} — {np.artist} (id {np.track_id})" if np else "no footer found; is a song loaded?",
                     "" if np else "play any song in TIDAL, then `tidal-shuffle inspect` if this persists")
                luna = cdp.has_luna()
                _row(table, "TidaLuna (optional)", None, "present: gapless queueing available" if luna else "not installed (fine)", "")
            except Exception as e:
                _row(table, "TIDAL player page", False, f"could not talk to the page: {e}")
        api = LunaApi(port=cfg.player.luna_port)
        if api.alive():
            _row(table, "TidaLuna API plugin", True, f"port {cfg.player.luna_port}")

    # Sources
    if cfg:
        if mac:
            spot = any(Path(p).expanduser().exists() for p in ("/Applications/Spotify.app", "~/Applications/Spotify.app"))
            _row(table, "Spotify app", spot if "spotify-app" in cfg.sources else None,
                 "installed" if spot else "not installed", "" if spot else "install Spotify to use the spotify-app source (optional)")
            osa = shutil.which("osascript") is not None
            _row(table, "osascript", osa, "ok" if osa else "missing")
        creds = cfg.spotify.has_api_credentials
        _row(table, "Spotify API", True if creds else None, "credentials set" if creds else "not configured (optional)",
             "" if creds else "spotify.client_id / client_secret in config when you have a developer app")
        if creds and "spotify-api" in cfg.sources:
            try:
                from .sources.spotify_api import SpotifyApiSource
                src = SpotifyApiSource(cfg.spotify.client_id, cfg.spotify.client_secret, market=cfg.spotify.market)
                src._ensure_token()
                _row(table, "Spotify API auth", True, "token ok")
            except Exception as e:
                _row(table, "Spotify API auth", False, str(e)[:120], "check the credentials; dev-mode apps need a Premium owner")
        key = cfg.lastfm.configured
        _row(table, "Last.fm", True if key else None, "api key set" if key else "not configured (optional)",
             "" if key else "free key at https://www.last.fm/api/account/create → lastfm.api_key")
        _row(table, "Deezer", None, "keyless; " + ("enabled" if cfg.deezer.enabled else "disabled"))
        _row(table, "sources order", True, ", ".join(cfg.sources))

    console.print(table)
    if mac:
        console.print("\n[dim]Permissions: the first harvest asks for Automation access to Spotify; hiding windows "
                      "needs Accessibility access for your terminal (System Settings → Privacy & Security).[/dim]")
