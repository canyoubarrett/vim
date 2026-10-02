"""Run the real tidal-shuffle CLI against the simulated Mac.

The test starts this script as a subprocess with PATH pointing at the fake
macOS binaries. It patches only what cannot be faked from outside the
process: the operating system name, the TIDAL catalog login and the
ListenBrainz URL.
"""

import json
import os
import platform
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

platform.system = lambda: "Darwin"  # the code under test checks for macOS

from fake_session import FakeSession  # noqa: E402

import tidal_shuffle.app as app  # noqa: E402
from tidal_shuffle.sources import spotify_ids  # noqa: E402

catalog = json.loads(Path(os.environ["FAKE_DIR"], "catalog.json").read_text())
session = FakeSession(catalog)
app.connect_session = lambda *a, **k: session
spotify_ids.ListenBrainzSpotifyIds.URL = f"http://127.0.0.1:{os.environ['FAKE_TIDAL_PORT']}/lb/spotify-id-from-metadata/json"

from tidal_shuffle.cli import cli  # noqa: E402

cli.main(sys.argv[1:], prog_name="tidal-shuffle")
