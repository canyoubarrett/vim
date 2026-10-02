"""Keep the Spotify app out of sight while Tidal Shuffle uses it.

Recent Spotify versions bring themselves to the front when AppleScript tells
them to play a track, and macOS may show the window when the app launches.
This guard checks the window server about ten times a second; whenever
Spotify has a window on screen while it should be hidden, it hides the app
and gives the focus back to the app that had it (your terminal or TIDAL), so
the keys keep working. It only acts while ``should_hide()`` says so: during a
harvest, or when Tidal Shuffle started Spotify itself; a Spotify you opened
yourself is left alone in between.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

SPOTIFY_OWNER = "Spotify"
NS_ACTIVATE_IGNORING_OTHER_APPS = 1 << 1

Window = tuple[str, int, int]   # (owner name, owner pid, layer), front to back


def _windows() -> list[Window]:
    import Quartz

    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID) or []
    out = []
    for w in info:
        out.append((str(w.get(Quartz.kCGWindowOwnerName, "")), int(w.get(Quartz.kCGWindowOwnerPID, 0)),
                    int(w.get(Quartz.kCGWindowLayer, 0))))
    return out


def _hide_pid(pid: int) -> None:
    import AppKit

    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        app.hide()


def _activate_pid(pid: int) -> None:
    import AppKit

    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        app.activateWithOptions_(NS_ACTIVATE_IGNORING_OTHER_APPS)


class SpotifyGuard:
    def __init__(self, should_hide: Callable[[], bool], owner: str = SPOTIFY_OWNER, interval: float = 0.1,
                 log: Optional[Callable[[str], None]] = None,
                 windows: Callable[[], list[Window]] = _windows,
                 hide: Callable[[int], None] = _hide_pid,
                 activate: Callable[[int], None] = _activate_pid,
                 clock: Callable[[], float] = time.monotonic):
        self.should_hide = should_hide
        self.owner = owner
        self.interval = interval
        self.log = log or (lambda m: None)
        self._windows = windows
        self._hide = hide
        self._activate = activate
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_front: Optional[int] = None    # pid of the last app in front that was not Spotify
        self._hidden_at = -1e9
        self.hides = 0

    def available(self) -> tuple[bool, str]:
        try:
            import AppKit  # noqa: F401
            import Quartz  # noqa: F401
        except ImportError:
            return False, "PyObjC is not installed (rerun ./install.sh)"
        return True, ""

    def tick(self) -> bool:
        """One check; returns True when Spotify was hidden."""
        try:
            wins = [w for w in self._windows() if w[2] == 0]
        except Exception:
            return False
        front = wins[0] if wins else None
        if front is not None and front[0] != self.owner:
            self._last_front = front[1]
        if not self.should_hide():
            return False
        mine = [w for w in wins if w[0] == self.owner]
        if not mine:
            return False
        now = self._clock()
        if now - self._hidden_at < 0.25:
            return False                       # a hide is already on its way
        self._hidden_at = now
        try:
            self._hide(mine[0][1])
            if front is not None and front[0] == self.owner and self._last_front:
                self._activate(self._last_front)   # give the focus back (and the keys with it)
        except Exception as e:
            self.log(f"could not hide Spotify: {e}")
            return False
        self.hides += 1
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.tick()

    def start(self) -> bool:
        ok, reason = self.available()
        if not ok:
            self.log(f"cannot keep Spotify hidden: {reason}")
            return False
        self._thread = threading.Thread(target=self._run, name="tidal-shuffle-spotify-guard", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
