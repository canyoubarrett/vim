"""CLI tests that run anywhere (no macOS, no network)."""

from click.testing import CliRunner

from tidal_shuffle.cli import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


def test_help_lists_commands():
    r = invoke("--help")
    assert r.exit_code == 0
    for cmd in ("run", "test", "next", "doctor", "login", "presets", "sources", "history", "config", "playtest", "inspect", "harvest", "now"):
        assert cmd in r.output


def test_presets_and_config_roundtrip(isolated_home):
    r = invoke("presets")
    assert r.exit_code == 0 and "discovery" in r.output and "balanced" in r.output
    r = invoke("config", "init")
    assert r.exit_code == 0 and (isolated_home / "config.yaml").exists()
    r = invoke("config", "init")
    assert r.exit_code != 0 and "already exists" in r.output
    r = invoke("config", "show", "--preset", "discovery", "--artist-cooldown", "3")
    assert r.exit_code == 0 and "strategy: discovery" in r.output and "artist_cooldown: 3" in r.output
    r = invoke("config", "path")
    assert r.exit_code == 0 and r.output.strip().endswith("config.yaml")


def test_bad_option_values_are_clean_errors(isolated_home):
    r = invoke("config", "show", "--source", "napster")
    assert r.exit_code != 0 and "unknown source" in r.output
    r = invoke("config", "show", "--preset", "nope")
    assert r.exit_code != 0 and "Unknown preset" in r.output


def test_history_empty_and_clear(isolated_home):
    r = invoke("history")
    assert r.exit_code == 0 and "0 entries" in r.output
    r = invoke("history", "--clear")
    assert r.exit_code == 0


def test_run_requires_macos(isolated_home, monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    r = invoke("run")
    assert r.exit_code != 0 and "needs macOS" in r.output


def test_doctor_runs_without_config(isolated_home, monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    r = invoke("doctor")
    assert r.exit_code == 0 and "TIDAL login" in r.output and "no session yet" in r.output


def test_log_lines_render_markup_and_keep_brackets(capsys):
    from tidal_shuffle import cli as cli_mod
    from rich.console import Console
    import io
    buf = io.StringIO()
    old = cli_mod.console
    cli_mod.console = Console(file=buf, width=200, color_system=None)
    try:
        cli_mod.say("♫ now playing: Dreams [live] [/intro] — Band")
    finally:
        cli_mod.console = old
    out = buf.getvalue()
    assert "[dim]" not in out and "Dreams [live] [/intro] — Band" in out


def test_presets_with_bad_yaml_is_a_clean_error(isolated_home):
    (isolated_home / "config.yaml").write_text("shuffle: [unclosed")
    r = invoke("presets", "--config", str(isolated_home / "config.yaml"))
    assert r.exit_code != 0 and "invalid YAML" in r.output and "Traceback" not in r.output


def test_missing_config_flag_is_reported(isolated_home):
    r = invoke("config", "show", "--config", str(isolated_home / "nope.yaml"))
    assert r.exit_code != 0 and "not found" in r.output


def test_version_names_the_copy():
    from click.testing import CliRunner

    from tidal_shuffle.cli import cli
    out = CliRunner().invoke(cli, ["--version"]).output
    assert out.startswith("tidal-shuffle 0.8.0") and " from " in out


def test_update_refuses_outside_a_git_clone(monkeypatch):
    from click.testing import CliRunner

    import tidal_shuffle.buildinfo as bi
    from tidal_shuffle.cli import cli
    monkeypatch.setattr(bi, "git_root", lambda: None)
    res = CliRunner().invoke(cli, ["update"])
    assert res.exit_code != 0 and "not installed from a git clone" in res.output



def test_auto_colour_for_terminal_app_and_others():
    from tidal_shuffle.cli import auto_color

    app = {"TERM_PROGRAM": "Apple_Terminal", "TERM": "xterm-256color"}
    for version in ("26.0.1", "15.5"):                 # 256 colours always show in Terminal.app
        mode, hint = auto_color(app, version, "256")
        assert mode == "256" and "tidal-shuffle colors" in hint
    assert auto_color(app, "15.5", None)[0] == "256"
    assert auto_color({"TERM_PROGRAM": "iTerm.app", "COLORTERM": "truecolor"}, "15.5", "truecolor") == (None, "")
    assert auto_color({"TERM": "xterm-256color"}, "", "256") == (None, "")
    mode, hint = auto_color({"TERM": "xterm"}, "", None)
    assert mode == "256" and "did not report" in hint
    mode, hint = auto_color(dict(app, NO_COLOR="1"), "26.0", None)
    assert mode is None and "NO_COLOR" in hint


def test_colors_command_shows_swatches(tmp_path):
    from click.testing import CliRunner

    from tidal_shuffle.cli import cli

    res = CliRunner().invoke(cli, ["colors"], env={"TERM_PROGRAM": "Apple_Terminal", "TERM": "xterm-256color"})
    assert res.exit_code == 0, res.output
    assert "\x1b[48;5;183m" in res.output and "\x1b[48;2;203;166;247m" in res.output
    assert "tidal-shuffle run uses  256" in res.output and "ui: {color: truecolor}" in res.output
