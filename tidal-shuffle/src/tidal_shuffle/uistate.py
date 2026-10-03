"""Settings chosen in the full-screen view's settings menu (Esc), kept
between runs in ~/.config/tidal-shuffle/ui.json. They override the ``ui:``
section of the config file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

KEYS = ("theme", "logo_style", "logo_motion", "rain", "lyrics_lead", "lyrics_ahead", "shuffle_view", "party", "logo_backdrop", "backdrop_zoom", "backdrop_dim", "picture_detail", "logo_size",
        "logo_size_stage", "logo_floor", "logo_version", "logo_detail")

VERSION = 2   # 2: lyrics not sung yet are shown by default


def load(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("v", 1) < 2 and data.get("lyrics_ahead") == "hide":
        data.pop("lyrics_ahead")         # the old default: lyrics not sung yet are now shown
    return {k: v for k, v in data.items() if k in KEYS}


def save(path: Optional[Path], values: dict) -> None:
    if path is None:
        return
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict({k: values[k] for k in KEYS if k in values}, v=VERSION), indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def apply(ui, values: dict) -> None:
    """Copy saved values onto the config's ui section (ignoring ones it lacks)."""
    for k, v in values.items():
        if hasattr(ui, k):
            setattr(ui, k, v)
