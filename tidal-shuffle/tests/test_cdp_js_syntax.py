"""Every JavaScript snippet the CDP driver sends must at least parse (needs node)."""

import os
import shutil
import subprocess
import tempfile

import pytest

from tidal_shuffle.tidal.cdp import TidalCdp

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_all_snippets_parse():
    captured = []

    class Capture:
        def evaluate(self, js, timeout=10.0):
            captured.append(js)
            return None

        def close(self):
            pass

    cdp = TidalCdp(http_get=lambda u, t: '[{"type":"page","url":"https://desktop.tidal.com/","webSocketDebuggerUrl":"ws://x"}]',
                   connect=lambda ws: Capture(), sleep=lambda s: None, clock=lambda: 0.0)
    cdp.now_playing(); cdp.navigate_to_track("123"); cdp.rows_ready("123"); cdp.rows_ready(None)
    cdp.click_play_for_track("123")
    for c in ("play", "pause", "next", "previous"):
        cdp.press(c)
    cdp.inspect(); cdp.has_luna(); cdp.luna_queue_next("5"); cdp.luna_play_now("5"); cdp.luna_state(); cdp.current_path()
    assert len(captured) >= 14
    for js in captured:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write("var __r = " + js + ";\n")
        try:
            r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(f.name)
        assert r.returncode == 0, f"{r.stderr}\n{js}"
