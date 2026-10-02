"""Optional: TidaLuna's API plugin (HTTP on 127.0.0.1:24123).

TidaLuna is a community mod of the TIDAL desktop app. With its API plugin
installed we can ask TIDAL to queue a track as the *next* item, which gives
perfectly gapless transitions. Everything here is optional: if the port does
not answer, the rest of Tidal Shuffle works without it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

DEFAULT_PORT = 24123


class LunaApi:
    name = "luna-api"

    def __init__(self, port: int = DEFAULT_PORT, host: str = "127.0.0.1", token: Optional[str] = None,
                 opener: Optional[Callable[[urllib.request.Request, float], bytes]] = None):
        self.base = f"http://{host}:{port}"
        self.token = token
        self._open = opener or self._default_open

    @staticmethod
    def _default_open(req: urllib.request.Request, timeout: float) -> bytes:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (loopback only)
            return resp.read()

    def _request(self, method: str, path: str, body: Optional[dict] = None, timeout: float = 5.0) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method, headers=headers)
        raw = self._open(req, timeout)
        try:
            return json.loads(raw.decode("utf-8", "replace")) if raw else {}
        except ValueError:
            return {"raw": raw[:200]}

    def alive(self) -> bool:
        try:
            state = self._request("GET", "/", timeout=1.5)
        except Exception:
            return False
        return isinstance(state, dict) and ("playing" in state or "track" in state)

    def state(self) -> dict:
        s = self._request("GET", "/")
        return s if isinstance(s, dict) else {}

    def _post(self, action: str, body: Optional[dict] = None) -> bool:
        try:
            res = self._request("POST", f"/{action}", body or {})
        except (urllib.error.URLError, OSError, ValueError):
            return False
        return isinstance(res, dict) and res.get("type") != "error"

    def play_next(self, track_id: str) -> bool:
        return self._post("playNext", {"itemId": str(track_id)})

    def add_to_queue(self, track_id: str) -> bool:
        return self._post("addToQueue", {"itemId": str(track_id)})

    def next(self) -> bool:
        return self._post("next")

    def resume(self) -> bool:
        return self._post("resume")

    def pause(self) -> bool:
        return self._post("pause")

    def play_now(self, track_id: str) -> bool:
        return self.play_next(track_id) and self.next() and (self.resume() or True)

    def current_track_id(self) -> Optional[str]:
        try:
            track = self.state().get("track") or {}
        except Exception:
            return None
        tid = track.get("id") if isinstance(track, dict) else None
        return str(tid) if tid is not None else None
