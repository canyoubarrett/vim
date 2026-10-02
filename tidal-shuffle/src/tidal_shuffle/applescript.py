"""Tiny osascript wrapper with an injectable runner for tests."""

from __future__ import annotations

import shutil
import subprocess
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

    @staticmethod
    def available() -> bool:
        return shutil.which("osascript") is not None

    def run(self, script: str, timeout: float = 10.0) -> str:
        try:
            proc = subprocess.run(
                [self.binary, "-l", "AppleScript"],
                input=script,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise AppleScriptError("osascript not found; this feature needs macOS") from None
        except subprocess.TimeoutExpired:
            raise AppleScriptError(f"AppleScript timed out after {timeout}s") from None
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise AppleScriptError(msg or f"osascript exited with {proc.returncode}")
        return proc.stdout.rstrip("\n")


def app_is_running(runner: ScriptRunner, app_name: str, timeout: float = 5.0) -> bool:
    out = runner.run(f'tell application "System Events" to (name of processes) contains {quote(app_name)}', timeout)
    return out.strip().lower() == "true"


def default_runner() -> Optional[OsascriptRunner]:
    return OsascriptRunner() if OsascriptRunner.available() else None
