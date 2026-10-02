"""Tiny osascript wrapper with an injectable runner for tests."""

from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Optional, Protocol


class AppleScriptError(RuntimeError):
    pass


class ScriptRunner(Protocol):
    def run(self, script: str, timeout: float = 10.0) -> str: ...


def quote(value: str) -> str:
    """Return ``value`` as an AppleScript string literal."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


class OsascriptRunner:
    """Runs AppleScript source through ``osascript`` (macOS only)."""

    def __init__(self, binary: str = "osascript"):
        self.binary = binary
        self._procs: set = set()
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        return shutil.which("osascript") is not None

    def run(self, script: str, timeout: float = 10.0) -> str:
        try:
            proc = subprocess.Popen([self.binary, "-l", "AppleScript"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError:
            raise AppleScriptError("osascript not found; this feature needs macOS") from None
        with self._lock:
            self._procs.add(proc)
        try:
            out, err = proc.communicate(script, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise AppleScriptError(f"AppleScript timed out after {timeout}s") from None
        finally:
            with self._lock:
                self._procs.discard(proc)
        if proc.returncode != 0:
            msg = (err or out or "").strip()
            raise AppleScriptError(msg or f"osascript exited with {proc.returncode}")
        return out.rstrip("\n")

    def stop_all(self) -> int:
        """Kill every osascript this runner started that is still running."""
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                p.kill()
            except OSError:
                pass
        return len(procs)


def app_is_running(runner: ScriptRunner, app_name: str, timeout: float = 5.0) -> bool:
    out = runner.run(f'tell application "System Events" to (name of processes) contains {quote(app_name)}', timeout)
    return out.strip().lower() == "true"


def default_runner() -> Optional[OsascriptRunner]:
    return OsascriptRunner() if OsascriptRunner.available() else None
