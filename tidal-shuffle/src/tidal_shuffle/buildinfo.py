"""Which copy of Tidal Shuffle is running: version, git revision, location."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[1]          # src/tidal_shuffle -> the project (where install.sh is)


def _git(*args: str, cwd: Path = PROJECT_DIR) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_root() -> Optional[Path]:
    """The git checkout this copy runs from, if it is one (install.sh from a clone)."""
    if not (PROJECT_DIR / "pyproject.toml").exists():
        return None
    top = _git("rev-parse", "--show-toplevel")
    return Path(top) if top else None


def revision() -> Optional[str]:
    """'abc1234 2026-10-02' for a git checkout."""
    return _git("log", "-1", "--format=%h %cs") if git_root() else None


def describe() -> str:
    rev = revision()
    where = PROJECT_DIR if (PROJECT_DIR / "pyproject.toml").exists() else PACKAGE_DIR
    return f"tidal-shuffle {__version__}" + (f" ({rev})" if rev else "") + f" from {where}"
