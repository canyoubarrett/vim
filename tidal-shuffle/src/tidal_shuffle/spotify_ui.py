"""Find songs through the Spotify desktop app's own interface.

AppleScript can play a Spotify URI but cannot search. To start the song radio
for whatever TIDAL is playing without any API key, Tidal Shuffle:

1. opens ``spotify:search:<title artist>`` in the Spotify app,
2. reads the app's Accessibility tree (the same tree VoiceOver uses) and finds
   the track buttons labelled ``Play <title> by <artist>``,
3. presses the one that best matches the TIDAL song.

AppleScript then reads ``id of current track`` to get the Spotify URI. All
of this needs Accessibility permission for the terminal running Tidal
Shuffle (System Settings → Privacy & Security → Accessibility).

The Accessibility calls go through PyObjC and are isolated behind
:class:`AXBackend` so the matching logic is tested without a Mac.
"""

from __future__ import annotations

import re
import subprocess
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Protocol

from .matching import core_title, primary_artist, score_match

DEFAULT_LABEL_PATTERN = r"^Play (?P<rest>.+)$"   # "Play <title> by <artist>"
DEFAULT_BY_WORD = " by "


class SpotifyUIError(RuntimeError):
    pass


@dataclass
class UIButton:
    label: str
    title: str
    artist: str
    element: Any = None
    score: float = 0.0


class AXBackend(Protocol):
    def trusted(self) -> bool: ...

    def app_element(self, pid: int) -> Any: ...

    def attribute(self, element: Any, name: str) -> Any: ...

    def press(self, element: Any) -> bool: ...


class PyObjCAX:
    """Real Accessibility API via ``pyobjc-framework-ApplicationServices``."""

    def __init__(self, messaging_timeout: float = 0.1):
        try:
            import ApplicationServices as AS  # type: ignore
        except ImportError as e:  # not macOS, or pyobjc missing
            raise SpotifyUIError("pyobjc-framework-ApplicationServices is not installed") from e
        self.AS = AS
        self.messaging_timeout = messaging_timeout

    def trusted(self) -> bool:
        try:
            return bool(self.AS.AXIsProcessTrusted())
        except Exception:
            return False

    def app_element(self, pid: int) -> Any:
        el = self.AS.AXUIElementCreateApplication(pid)
        try:
            self.AS.AXUIElementSetMessagingTimeout(el, self.messaging_timeout)
        except Exception:
            pass
        # Ask Chromium-based apps to publish their full web accessibility tree.
        # Unsupported attributes are simply refused, which is fine.
        for attr in ("AXManualAccessibility", "AXEnhancedUserInterface"):
            try:
                self.AS.AXUIElementSetAttributeValue(el, attr, True)
            except Exception:
                pass
        return el

    def attribute(self, element: Any, name: str) -> Any:
        try:
            err, value = self.AS.AXUIElementCopyAttributeValue(element, name, None)
        except Exception:
            return None
        return value if err == 0 else None

    def press(self, element: Any) -> bool:
        try:
            return self.AS.AXUIElementPerformAction(element, "AXPress") == 0
        except Exception:
            return False


def split_play_label(label: str, pattern: str = DEFAULT_LABEL_PATTERN, by_word: str = DEFAULT_BY_WORD) -> list[tuple[str, str]]:
    """All (title, artist) readings of a label such as ``Play Stand by Me by Ben E. King``.

    Titles can themselves contain the word "by", so every split point is returned
    and the caller scores each reading.
    """
    m = re.match(pattern, label.strip())
    if not m:
        return []
    rest = m.group("rest")
    out = []
    start = 0
    while True:
        i = rest.find(by_word, start)
        if i < 0:
            break
        title, artist = rest[:i].strip(), rest[i + len(by_word):].strip()
        if title and artist:
            out.append((title, artist))
        start = i + 1
    return out


class SpotifyUI:
    """Search and press buttons in the Spotify app through Accessibility."""

    def __init__(
        self,
        ax: Optional[AXBackend] = None,
        run: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        label_pattern: str = DEFAULT_LABEL_PATTERN,
        by_word: str = DEFAULT_BY_WORD,
        max_nodes: int = 6000,
        walk_seconds: float = 4.0,
        log: Optional[Callable[[str], None]] = None,
    ):
        self._ax = ax
        self._run = run
        self._sleep = sleep
        self._clock = clock
        self.label_pattern = label_pattern
        self.by_word = by_word
        self.max_nodes = max_nodes
        self.walk_seconds = walk_seconds
        self.log = log or (lambda m: None)

    # -- plumbing ---------------------------------------------------------------
    @property
    def ax(self) -> AXBackend:
        if self._ax is None:
            self._ax = PyObjCAX()
        return self._ax

    def available(self) -> tuple[bool, str]:
        try:
            ax = self.ax
        except SpotifyUIError as e:
            return False, str(e)
        if not ax.trusted():
            return False, ("Accessibility permission missing: allow your terminal in System Settings → "
                           "Privacy & Security → Accessibility")
        return True, ""

    def spotify_pid(self) -> Optional[int]:
        try:
            r = self._run(["pgrep", "-x", "Spotify"], capture_output=True, text=True, timeout=5)
        except Exception:
            return None
        if getattr(r, "returncode", 1) != 0:
            return None
        try:
            return int(str(r.stdout).split()[0])
        except (IndexError, ValueError):
            return None

    def open_search(self, query: str) -> bool:
        uri = "spotify:search:" + urllib.parse.quote(query, safe="")
        try:
            r = self._run(["open", "-g", uri], capture_output=True, text=True, timeout=10)
        except Exception as e:
            self.log(f"could not open Spotify search: {e}")
            return False
        return getattr(r, "returncode", 1) == 0

    def _text(self, el: Any) -> str:
        for attr in ("AXDescription", "AXTitle", "AXHelp"):
            v = self.ax.attribute(el, attr)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def walk(self, root: Any) -> Iterable[tuple[Any, str, str]]:
        """Breadth-first (element, role, label) over at most ``max_nodes`` elements."""
        deadline = self._clock() + self.walk_seconds
        queue = deque([root])
        seen = 0
        while queue and seen < self.max_nodes and self._clock() < deadline:
            el = queue.popleft()
            seen += 1
            role = self.ax.attribute(el, "AXRole") or ""
            yield el, str(role), self._text(el)
            kids = self.ax.attribute(el, "AXChildren") or []
            try:
                queue.extend(list(kids))
            except TypeError:
                pass

    def play_buttons(self, root: Any) -> list[UIButton]:
        out = []
        for el, role, label in self.walk(root):
            if role not in ("AXButton", "AXLink", "AXCell", "AXRow") or not label:
                continue
            for title, artist in split_play_label(label, self.label_pattern, self.by_word):
                out.append(UIButton(label=label, title=title, artist=artist, element=el))
        return out

    def best_button(self, buttons: list[UIButton], title: str, artist: str,
                    duration: Optional[float] = None, threshold: float = 0.75) -> Optional[UIButton]:
        best: Optional[UIButton] = None
        for b in buttons:
            b.score = score_match(title, artist, b.title, [b.artist])
            if best is None or b.score > best.score:
                best = b
        if best is None or best.score < threshold:
            return None
        return best

    # -- the operation ------------------------------------------------------------
    def find_and_play(self, title: str, artist: str, wait: float = 10.0) -> Optional[UIButton]:
        """Search Spotify for the song and press its play button. Returns the button pressed."""
        ok, reason = self.available()
        if not ok:
            raise SpotifyUIError(reason)
        pid = self.spotify_pid()
        if pid is None:
            raise SpotifyUIError("Spotify is not running")
        query = f"{core_title(title)} {primary_artist(artist)}"
        if not self.open_search(query):
            raise SpotifyUIError("could not open the Spotify search page")
        root = self.ax.app_element(pid)
        deadline = self._clock() + wait
        last_count = 0
        while True:
            buttons = self.play_buttons(root)
            last_count = len(buttons)
            choice = self.best_button(buttons, title, artist)
            if choice is not None:
                if self.ax.press(choice.element):
                    self.log(f"pressed '{choice.label}' in Spotify (match {choice.score:.2f})")
                    return choice
                self.log(f"Spotify refused to press '{choice.label}'")
                return None
            if self._clock() >= deadline:
                break
            self._sleep(0.5)
        self.log(f"no matching song on Spotify's search page ({last_count} play buttons seen)")
        return None

    def dump(self, limit: int = 200) -> list[tuple[str, str]]:
        """(role, label) of labelled elements in Spotify's window, for diagnostics."""
        pid = self.spotify_pid()
        if pid is None:
            raise SpotifyUIError("Spotify is not running")
        out = []
        for _, role, label in self.walk(self.ax.app_element(pid)):
            if label:
                out.append((role, label))
                if len(out) >= limit:
                    break
        return out
