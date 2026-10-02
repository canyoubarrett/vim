from tidal_shuffle.app import build_sources
from tidal_shuffle.config import load_config
from tidal_shuffle.models import Seed


def test_sources_built_in_configured_order():
    cfg = load_config(overrides={"sources": ["tidal-radio", "deezer", "lastfm"]}, env={})
    assert [s.name for s in build_sources(cfg, None)] == ["tidal-radio", "deezer", "lastfm"]


def test_spotify_app_gets_every_lookup_and_shares_the_api_client():
    cfg = load_config(env={"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "secret"})
    sources = {s.name: s for s in build_sources(cfg, None)}
    app, api = sources["spotify-app"], sources["spotify-api"]
    names = [l.name for l in app.id_lookups]
    assert names == ["spotify-api", "listenbrainz", "odesli"]
    assert app.ui is None and app.id_cache is not None   # Spotify kept hidden: no visible search page
    assert app.id_lookups[0].api is api  # one client, one token, one cache
    shown = load_config(overrides={"spotify": {"app": {"keep_hidden": False}}}, env={})
    assert {s.name: s for s in build_sources(shown, None)}["spotify-app"].ui is not None
    api.find_track = lambda seed: {"id": "sp1"}
    assert app.id_lookups[0].lookup(Seed("T", "A")) == "sp1"


def test_spotify_app_without_api_credentials():
    cfg = load_config(env={})
    app = {s.name: s for s in build_sources(cfg, None)}["spotify-app"]
    assert [l.name for l in app.id_lookups] == ["listenbrainz", "odesli"]
    assert app.cfg.id_lookups == ["spotify-api", "listenbrainz", "spotify-ui", "odesli"]


def test_id_lookup_config_validation():
    import pytest
    from tidal_shuffle.config import ConfigError
    cfg = load_config(overrides={"spotify": {"app": {"id_lookups": "spotify-ui, listenbrainz"}}}, env={})
    assert cfg.spotify.app.id_lookups == ["spotify-ui", "listenbrainz"]
    with pytest.raises(ConfigError, match="unknown lookup"):
        load_config(overrides={"spotify": {"app": {"id_lookups": ["odesli", "shazam"]}}}, env={})


def test_switching_presets_while_running_updates_in_place(tmp_path):
    import types

    from tidal_shuffle.app import Runtime

    path = tmp_path / "config.yaml"
    path.write_text("sources: [tidal-radio, deezer]\n"
                    "presets:\n  mine:\n    description: Just Last.fm\n    sources: [lastfm, tidal-radio]\n"
                    "    shuffle: {strategy: random}\n", encoding="utf-8")
    cfg = load_config(path, env={})
    sources = build_sources(cfg, None)
    radio = sources[0]
    shuffle, vibe = cfg.shuffle, cfg.spotify.vibe
    engine = types.SimpleNamespace(sources=list(sources))
    rt = Runtime(config=cfg, history=None, catalog=None, sources=sources, engine=engine, cdp=None, luna=None,
                 player=None, nowplaying=None)
    msg = rt.apply_preset("warm-up")
    assert msg == "preset: warm-up — Energy rises a little with every song."
    assert cfg.preset == "warm-up" and cfg.shuffle is shuffle and shuffle.flow == "rising"
    assert [s.name for s in rt.sources] == ["tidal-radio", "deezer"]      # sources untouched
    assert rt.apply_preset("mine") == "preset: mine — Just Last.fm"
    assert shuffle.strategy == "random" and shuffle.flow == "radio"       # the previous preset is gone
    assert [s.name for s in rt.sources] == ["lastfm", "tidal-radio"]
    assert rt.sources[1] is radio and [s.name for s in engine.sources] == ["lastfm", "tidal-radio"]
    rt.apply_preset("workout")
    assert cfg.spotify.vibe is vibe and vibe.energy == 0.9                # the Spotify tuning too
    import pytest

    from tidal_shuffle.config import ConfigError
    with pytest.raises(ConfigError):
        rt.apply_preset("nope")
