import pytest
import yaml

from tidal_shuffle.config import (
    ConfigError, EXAMPLE_CONFIG, DEFAULT_PRESETS, load_config, write_example_config, deep_merge,
)


def test_defaults_without_file():
    cfg = load_config(env={})
    assert cfg.sources == ["spotify-app", "spotify-api", "lastfm", "deezer", "tidal-radio"]
    assert cfg.shuffle.strategy == "weighted"
    assert cfg.player.handoff_seconds == 3.0
    assert cfg.config_path is None
    assert not cfg.spotify.has_api_credentials
    assert not cfg.lastfm.configured


def test_example_config_parses_and_validates(isolated_home):
    path = write_example_config(isolated_home / "config.yaml")
    cfg = load_config(path, env={})
    assert cfg.config_path == path
    assert "my-evening" in cfg.presets
    assert cfg.spotify.app.harvest == 25
    with pytest.raises(FileExistsError):
        write_example_config(path)


def test_file_env_preset_cli_precedence(isolated_home):
    path = isolated_home / "config.yaml"
    path.write_text(yaml.safe_dump({
        "shuffle": {"strategy": "top", "artist_cooldown": 1},
        "lastfm": {"api_key": "file-key"},
        "presets": {"mine": {"description": "x", "shuffle": {"strategy": "random"}, "sources": ["lastfm"]}},
    }))
    cfg = load_config(path, preset="mine", overrides={"shuffle": {"artist_cooldown": 9}},
                      env={"LASTFM_API_KEY": "env-key", "SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "sec"})
    assert cfg.lastfm.api_key == "env-key"
    assert cfg.spotify.has_api_credentials
    assert cfg.shuffle.strategy == "random"      # preset beats file
    assert cfg.shuffle.artist_cooldown == 9      # CLI beats preset
    assert cfg.sources == ["lastfm"]
    assert cfg.preset == "mine"


def test_builtin_presets_all_load():
    for name in DEFAULT_PRESETS:
        cfg = load_config(preset=name, env={})
        assert cfg.preset == name


def test_unknown_preset_and_bad_values():
    with pytest.raises(ConfigError, match="Unknown preset"):
        load_config(preset="nope", env={})
    with pytest.raises(ConfigError, match="strategy"):
        load_config(overrides={"shuffle": {"strategy": "bogus"}}, env={})
    with pytest.raises(ConfigError, match="unknown source"):
        load_config(overrides={"sources": ["napster"]}, env={})
    with pytest.raises(ConfigError, match="unknown option"):
        load_config(overrides={"player": {"typo": 1}}, env={})
    with pytest.raises(ConfigError, match="min_duration"):
        load_config(overrides={"shuffle": {"min_duration": 500, "max_duration": 100}}, env={})


def test_source_aliases_and_csv():
    cfg = load_config(overrides={"sources": "spotify, last.fm, tidal"}, env={})
    assert cfg.sources == ["spotify-app", "lastfm", "tidal-radio"]


def test_legacy_v1_config_upgrades(isolated_home):
    path = isolated_home / "config.yaml"
    path.write_text(yaml.safe_dump({
        "lastfm": {"api_key": "k"},
        "spotify": {"client_id": "a", "client_secret": "b"},
        "defaults": {"batch_size": 12, "min_popularity": 20, "seconds_before_end": 15, "poll_interval": 5},
        "presets": {"late-night-drive": {"vibe": {"energy": 0.6, "genres": ["synthwave"]}, "description": "d"}},
    }))
    cfg = load_config(path, preset="late-night-drive", env={})
    assert cfg.shuffle.candidates == 12
    assert cfg.player.handoff_seconds == 15
    assert cfg.player.poll_interval == 5
    assert cfg.spotify.vibe.min_popularity == 20
    assert cfg.spotify.vibe.energy == 0.6
    assert cfg.spotify.vibe.genres == ["synthwave"]


def test_describe_masks_secrets():
    cfg = load_config(env={"LASTFM_API_KEY": "secret", "SPOTIFY_CLIENT_ID": "i", "SPOTIFY_CLIENT_SECRET": "s"})
    d = cfg.describe()
    assert d["lastfm"]["api_key"] == "***"
    assert d["spotify"]["client_secret"] == "***"


def test_deep_merge_does_not_mutate():
    base = {"a": {"b": 1}}
    out = deep_merge(base, {"a": {"c": 2}})
    assert out == {"a": {"b": 1, "c": 2}} and base == {"a": {"b": 1}}


def test_invalid_yaml_reports_path(isolated_home):
    path = isolated_home / "config.yaml"
    path.write_text("shuffle: [unclosed")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path, env={})


def test_repo_example_matches_config_init():
    from pathlib import Path
    repo_example = Path(__file__).resolve().parents[1] / "config.example.yaml"
    assert repo_example.read_text() == EXAMPLE_CONFIG


def test_missing_explicit_config_is_an_error(isolated_home, monkeypatch):
    with pytest.raises(ConfigError, match="not found"):
        load_config(isolated_home / "typo.yaml", env={})
    monkeypatch.setenv("TIDAL_SHUFFLE_CONFIG", str(isolated_home / "also-missing.yaml"))
    with pytest.raises(ConfigError, match="not found"):
        load_config(env={})


def test_env_config_path_is_used_by_init_and_loader(isolated_home, monkeypatch):
    target = isolated_home / "custom" / "conf.yaml"
    monkeypatch.setenv("TIDAL_SHUFFLE_CONFIG", str(target))
    assert write_example_config() == target
    assert load_config(env={}).config_path == target


def test_scalar_sections_are_config_errors(isolated_home):
    path = isolated_home / "config.yaml"
    path.write_text("spotify: abc\n")
    with pytest.raises(ConfigError, match="spotify: expected a mapping"):
        load_config(path, env={})


def test_odesli_key_is_masked():
    cfg = load_config(overrides={"spotify": {"app": {"odesli_api_key": "SEKRIT"}}}, env={})
    assert cfg.describe()["spotify"]["app"]["odesli_api_key"] == "***"


def test_quit_after_accepts_auto_and_booleans():
    assert load_config(env={}).spotify.app.quit_after == "auto"
    assert load_config(overrides={"spotify": {"app": {"quit_after": "yes"}}}, env={}).spotify.app.quit_after is True
