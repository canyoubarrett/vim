"""End to end: the real `tidal-shuffle run` against a simulated Mac.

What is real: the whole tidal_shuffle package, the CLI, subprocess calls to
`osascript` / `media-control` / `open` / `pgrep`, the websocket-client
DevTools connection, and every JavaScript snippet, which runs inside a jsdom
copy of a TIDAL-like web player.

What is simulated: the TIDAL app (tests/e2e/fake_tidal/server.mjs), Spotify
and macOS's now-playing service (tests/e2e/fakebin), the TIDAL catalog
(fake_session.py) and ListenBrainz.

Needs node and `npm install` in tests/e2e/fake_tidal; skipped otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(
    NODE is None or not (HERE / "fake_tidal" / "node_modules" / "jsdom").exists(),
    reason="needs node and `npm install` in tests/e2e/fake_tidal",
)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SONG = 14  # seconds per song; short so the test runs quickly


def track(id, title, artist, artist_id, spotify=True, spotify_title=None, duration=SONG, album="Album", lyrics=None):
    t = {"id": str(id), "title": title, "artist": artist, "artist_id": artist_id, "album": album, "album_id": id,
         "duration": duration, "auto_next": "190", "album_tracks": []}
    if lyrics:
        t["lyrics"] = lyrics
    if spotify:
        t["spotify"] = f"sp{id}"
    if spotify_title:
        t["spotify_title"] = spotify_title
    return t


CATALOG = {
    "tracks": [
        track(101, "Neon Harbor", "Glass Coast", 1,
              lyrics="[00:00.50]Lights across the neon harbor\n[00:03.00]Ships that never sail\n[00:06.00]Glass along the coast"),
        track(102, "Paper Lanterns", "Velvet Static", 2),
        track(103, "Midnight Ferry", "Ninth Avenue", 3, spotify_title="Midnight Ferry - 2019 Remaster"),
        track(104, "Copper Skies", "Low Orbit", 4),
        track(105, "Slow Signal", "Marlow Twins", 5),
        track(106, "Glass Houses", "Ninth Avenue", 3),
        track(107, "Static Bloom", "Velvet Static", 2),
        track(108, "Undertow", "Low Orbit", 4),
        track(110, "City of Echoes", "The Lanterns", 6),
        track(111, "Afterglow Avenue", "Sunday Motel", 7),
        track(112, "Quiet Machines", "Paper Moons", 8),
        track(120, "Midnight Ferry (Live)", "Ninth Avenue", 3, spotify=False),
        track(190, "Album Filler", "Glass Coast", 1, spotify=False, duration=300),
    ],
    "spotify_only": [{"spotify": "sp900", "title": "Not On Tidal", "artist": "Ghost Band", "duration": 200}],
    "filler_id": "190",
    "stations": {
        # Spotify song radio, as the fake Spotify app plays it after the seed.
        "sp101": ["sp900", "sp103", "sp102", "sp104"],
        "sp103": ["sp101", "sp106", "sp105", "sp107"],
        "sp105": ["sp108", "sp104"],
        "sp110": ["sp111", "sp112"],
    },
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(port, path, timeout=2.0):
    with OPENER.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait_until(cond, timeout, step=0.25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = cond()
        except OSError:
            value = None
        if value:
            return value
        time.sleep(step)
    return None


@pytest.fixture()
def mac(tmp_path):
    """A simulated Mac: fake binaries on PATH, catalog, config, Spotify.app."""
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "catalog.json").write_text(json.dumps(CATALOG))
    (tmp_path / "Spotify.app").mkdir()
    port = free_port()
    home = tmp_path / "home"
    home.mkdir()
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "sources": ["spotify-app", "tidal-radio"],
        "shuffle": {"strategy": "top", "min_duration": 1, "artist_cooldown": 2, "lookahead": 2},
        "player": {"handoff_seconds": 2.5, "prepare_seconds": 6, "poll_interval": 0.5, "near_end_poll_interval": 0.3,
                   "plan_after_seconds": 1, "verify_seconds": 5, "idle_poll_interval": 0.5, "cdp_port": port,
                   "nowplaying_backend": "media-control"},
        "spotify": {"app": {"app_path": str(tmp_path / "Spotify.app"), "harvest": 6,
                            "id_lookups": ["listenbrainz", "spotify-ui"]}},
        "tidal": {"session_file": str(tmp_path / "session.json")},
    }))
    env = dict(os.environ)
    env.update({
        "PATH": f"{HERE / 'fakebin'}{os.pathsep}{env.get('PATH', '')}",
        "FAKE_DIR": str(fake), "FAKE_TIDAL_PORT": str(port), "FAKE_NODE": NODE,
        "FAKE_SERVER": str(HERE / "fake_tidal" / "server.mjs"),
        "TIDAL_SHUFFLE_HOME": str(home), "PYTHONUNBUFFERED": "1", "COLUMNS": "200",
    })
    state = {"port": port, "env": env, "fake": fake, "config": cfg_path, "home": home, "procs": []}
    yield state
    for p in state["procs"]:
        if p.poll() is None:
            p.kill()
    pid_file = fake / "tidal.pid"
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def cli(mac, *args, timeout=60):
    return subprocess.run([sys.executable, str(HERE / "harness.py"), *args, "--config", str(mac["config"])],
                          env=mac["env"], capture_output=True, text=True, timeout=timeout)


def test_run_follows_tidal_and_plays_spotify_picks(mac):
    port = mac["port"]
    log_path = mac["fake"] / "run.log"
    proc = subprocess.Popen([sys.executable, str(HERE / "harness.py"), "run", "--config", str(mac["config"]), "-v"],
                            env=mac["env"], stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
    mac["procs"].append(proc)
    try:
        # `run` must launch TIDAL itself with the debug port (fake `open -a ... --args`).
        assert wait_until(lambda: get(port, "/json/version"), 30), "tidal-shuffle did not start TIDAL"
        get(port, "/__play?id=101&how=user")  # you press play in TIDAL

        def clicks():
            return [p for p in get(port, "/__played") if p["how"] == "row-click"]
        assert wait_until(lambda: len(clicks()) >= 2, 4 * SONG), "no hand-offs happened"
        time.sleep(3)
        get(port, "/__play?id=110&how=user")  # you skip to something else
        assert wait_until(lambda: len(clicks()) >= 3, 3 * SONG), "no hand-off after the manual skip"
        time.sleep(1)
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    output = log_path.read_text()
    played = get(port, "/__played")
    sequence = [(p["id"], p["how"]) for p in played]
    assert sequence[:5] == [("101", "user"), ("103", "row-click"), ("105", "row-click"),
                            ("110", "user"), ("111", "row-click")], f"{sequence}\n{output}"
    assert all(how != "auto" for _, how in sequence), "TIDAL reached the end of a song on its own"
    # Each hand-off happened shortly before the end of the song, not at its start.
    for prev, cur in zip(played, played[1:]):
        if cur["how"] == "row-click":
            gap = (cur["at"] - prev["at"]) / 1000
            assert SONG - 6 <= gap <= SONG, f"hand-off after {gap:.1f}s\n{output}"
    # Spotify was used, muted while harvesting, and put back.
    calls = (mac["fake"] / "calls.log").read_text()
    assert "harvest seed=spotify:track:sp101" in calls and "harvest seed=spotify:track:sp110" in calls
    spotify = json.loads((mac["fake"] / "spotify_state.json").read_text())
    assert spotify["volume"] == 64 and spotify["playing"] is False
    # Picks are recorded; the remastered Spotify title matched TIDAL's studio track, not the live one.
    history = json.loads((mac["home"] / "history.json").read_text())["entries"]
    assert [(e["tidal_id"], e["source"]) for e in history][:5] == [
        ("101", "tidal"), ("103", "spotify-app"), ("105", "spotify-app"), ("110", "tidal"), ("111", "spotify-app")]
    assert "Stopped after" in output and "Traceback" not in output, output


def test_diagnostics_and_dry_run_commands(mac):
    port = mac["port"]
    # Start TIDAL ourselves this time, the way the README tells you to.
    subprocess.run(["open", "-a", "/Applications/TIDAL.app", "--args", f"--remote-debugging-port={port}"],
                   env=mac["env"], check=True)
    assert wait_until(lambda: get(port, "/json/version"), 20)
    get(port, "/__play?id=101&how=user")
    time.sleep(1)

    doctor = cli(mac, "doctor")
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    for text in ("TIDAL debug port", "reachable", "footer: Neon Harbor", "media-control"):
        assert text in doctor.stdout, doctor.stdout

    now = cli(mac, "now")
    assert now.returncode == 0 and "Neon Harbor" in now.stdout and "tidal (cdp)" in now.stdout, now.stdout

    inspect = cli(mac, "inspect")
    assert inspect.returncode == 0 and '"footer": 1' in inspect.stdout.replace(" ", "").replace('"footer":1', '"footer": 1'), inspect.stdout

    test = cli(mac, "test", "-v")
    assert test.returncode == 0, test.stdout + test.stderr
    assert "Midnight Ferry" in test.stdout and "spotify-app" in test.stdout, test.stdout
    assert [p["how"] for p in get(port, "/__played")] == ["user"], "the dry run must not play anything"

    sources = cli(mac, "sources", "--seed", "City of Echoes - The Lanterns")
    assert sources.returncode == 0 and "Afterglow Avenue" in sources.stdout, sources.stdout

    harvest = cli(mac, "harvest", "Slow Signal", "Marlow Twins")
    assert harvest.returncode == 0 and "Undertow" in harvest.stdout and "listenbrainz" in harvest.stdout, harvest.stdout

    playtest = cli(mac, "playtest", "104")
    assert playtest.returncode == 0 and "result: ok" in playtest.stdout, playtest.stdout
    assert get(port, "/__played")[-1]["id"] == "104"


def test_full_screen_view_in_a_real_terminal(mac):
    """`run` in a pseudo-terminal: the full-screen view draws, shows TIDAL's
    synced lyrics, switches to the visualizer with `l`, and quits on `q`."""
    import fcntl
    import pty
    import struct
    import termios
    import threading

    port = mac["port"]
    cfg = yaml.safe_load(mac["config"].read_text())
    cfg["ui"] = {"lyrics_sources": ["tidal"], "fps": 10}
    mac["config"].write_text(yaml.safe_dump(cfg))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = dict(mac["env"], TERM="xterm-256color", COLORTERM="truecolor")
    env.pop("COLUMNS", None)
    proc = subprocess.Popen([sys.executable, str(HERE / "harness.py"), "run", "--config", str(mac["config"])],
                            env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    mac["procs"].append(proc)
    os.close(slave)
    chunks = []

    def pump():
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:
                return
            if not data:
                return
            chunks.append(data)
    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    import re

    ansi = re.compile(rb"\x1b\[[0-9;?<]*[A-Za-z]")
    # the screen is drawn cell by cell over an animated sky, so text is
    # interleaved with colour codes: look at what is visible
    seen = lambda text: text.encode() in ansi.sub(b"", b"".join(chunks))
    try:
        assert wait_until(lambda: get(port, "/json/version"), 30), "tidal-shuffle did not start TIDAL"
        get(port, "/__play?id=101&how=user")
        assert wait_until(lambda: seen("Neon Harbor") and seen("Lyrics · TIDAL"), 15), "no lyrics view"
        assert wait_until(lambda: seen("Ships that never sail"), 10)
        assert wait_until(lambda: seen("Alter Era") and seen("\u28c0".encode().decode()), 5), "no logo beside the lyrics"
        os.write(master, b"l")
        assert wait_until(lambda: seen("l for lyrics"), 5), "l did not switch to the logo alone"
        os.write(master, b"n")                    # next: never blocks the other keys
        os.write(master, b" ")
        assert wait_until(lambda: seen("paused") or seen("could not pause"), 10), "play/pause did not respond"
        os.write(master, b"q")
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    reader.join(timeout=2)
    out = b"".join(chunks).decode("utf-8", "replace")
    assert "\x1b[?1049h" in out and "\x1b[?1049l" in out   # entered and left the alternate screen
    assert "Stopped after" in out and "Traceback" not in out, out[-3000:]
