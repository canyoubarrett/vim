"""Wiring: build the sources, catalog, player and loop from a configuration."""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from typing import Callable, Optional

from .config import AppConfig
from .engine import Engine
from .history import HistoryStore
from .nowplaying.base import CompositeBackend, NowPlayingBackend
from .sources.base import Source
from .tidal.catalog import TidalCatalog, TidalLoginRequired, connect_session
from .tidal.cdp import TidalCdp
from .tidal.luna import LunaApi
from .tidal.player import TidalPlayer

Logger = Callable[[str], None]
log = logging.getLogger(__name__)


def is_macos() -> bool:
    return platform.system() == "Darwin"


@dataclass
class Runtime:
    config: AppConfig
    history: HistoryStore
    catalog: Optional[TidalCatalog]
    sources: list
    engine: Engine
    cdp: Optional[TidalCdp]
    luna: Optional[LunaApi]
    player: TidalPlayer
    nowplaying: NowPlayingBackend
    notes: list[str] = field(default_factory=list)

    def close(self) -> None:
        for s in self.sources:
            close = getattr(s, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass
        if self.cdp is not None:
            self.cdp.close()


def build_catalog(cfg: AppConfig, printer: Logger = print, interactive: bool = True,
                  logger: Optional[Logger] = None) -> Optional[TidalCatalog]:
    """Log in to TIDAL (or load the saved session) and wrap it in a catalog."""
    session = connect_session(cfg.tidal.session_file, printer=printer, interactive=interactive)
    return TidalCatalog(session, search_limit=cfg.tidal.search_limit, threshold=cfg.tidal.match_threshold, log_fn=logger)


def build_sources(cfg: AppConfig, catalog: Optional[TidalCatalog], logger: Optional[Logger] = None) -> list[Source]:
    """Instantiate the configured sources, in priority order. Unknown names were
    rejected by the config loader already."""
    out: list[Source] = []
    for name in cfg.sources:
        if name == "spotify-app":
            from .applescript import default_runner
            from .sources.spotify_app import SpotifyAppSource

            out.append(SpotifyAppSource(cfg.spotify.app, runner=default_runner(), log=logger, catalog=catalog))
        elif name == "spotify-api":
            from .sources.spotify_api import SpotifyApiSource

            out.append(SpotifyApiSource(cfg.spotify.client_id, cfg.spotify.client_secret, market=cfg.spotify.market,
                                        vibe=cfg.spotify.vibe, log=logger))
        elif name == "lastfm":
            from .sources.lastfm import LastfmSource

            out.append(LastfmSource(cfg.lastfm.api_key, expand_similar_artists=cfg.lastfm.expand_similar_artists))
        elif name == "deezer":
            from .sources.deezer import DeezerSource

            out.append(DeezerSource(enabled=cfg.deezer.enabled, log=logger))
        elif name == "tidal-radio":
            from .sources.tidal_radio import TidalRadioSource

            out.append(TidalRadioSource(catalog, limit=cfg.tidal.radio_limit))
    return out


def build_nowplaying(cfg: AppConfig, cdp: Optional[TidalCdp], logger: Optional[Logger] = None) -> NowPlayingBackend:
    from .nowplaying.media import detect_backend

    media = detect_backend(cfg.player.nowplaying_backend, log=logger)
    return CompositeBackend(media, cdp, log=logger)


def build_runtime(cfg: AppConfig, logger: Optional[Logger] = None, printer: Logger = print,
                  interactive: bool = True, need_tidal: bool = True) -> Runtime:
    logger = logger or (lambda m: None)
    notes: list[str] = []
    catalog: Optional[TidalCatalog] = None
    if need_tidal:
        try:
            catalog = build_catalog(cfg, printer=printer, interactive=interactive, logger=logger)
        except TidalLoginRequired as e:
            notes.append(str(e))
            if interactive:
                raise
    history = HistoryStore()
    sources = build_sources(cfg, catalog, logger)
    if catalog is None:
        raise TidalLoginRequired("TIDAL login required; run `tidal-shuffle login`")
    engine = Engine(cfg, sources, catalog, history, log=logger)
    cdp = TidalCdp(port=cfg.player.cdp_port, app_path=cfg.player.tidal_app, log=logger) if is_macos() else None
    luna = LunaApi(port=cfg.player.luna_port) if is_macos() else None
    player = TidalPlayer(cfg.player, cdp=cdp, luna=luna, log=logger)
    nowplaying = build_nowplaying(cfg, cdp, logger)
    return Runtime(config=cfg, history=history, catalog=catalog, sources=sources, engine=engine,
                   cdp=cdp, luna=luna, player=player, nowplaying=nowplaying, notes=notes)
