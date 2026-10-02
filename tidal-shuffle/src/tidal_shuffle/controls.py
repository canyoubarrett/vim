"""Keyboard control while `tidal-shuffle run` is in front.

Two inputs, both turned into the same commands ("playpause", "next",
"previous", "quit", "help") and handed to a callback:

* ``KeyReader``: single keys typed into the terminal (space, n, b, q, ?), plus
  arrows, Enter, Esc and mouse clicks and wheel for the full-screen view
  ("up", "click:x:y", ...). Needs nothing but a terminal.
* ``MediaKeyTap``: the keyboard's media keys (play/pause, next, previous).
  macOS sends those to the app that owns "Now Playing" (TIDAL), never to the
  focused window, so they are caught with a Quartz event tap before that
  routing, and only taken over while the terminal running Tidal Shuffle is
  the frontmost app. Needs the Accessibility permission (the same one the
  Spotify search uses). Headphone and Touch Bar buttons do not go through an
  event tap and keep controlling TIDAL directly.
"""

from __future__ import annotations

import os
import select
import sys
import threading
from typing import Callable, Optional

Command = Callable[[str], None]

TERMINAL_KEYS = {
    " ": "playpause",
    "k": "playpause",
    "n": "next",
    "b": "previous",
    "j": "previous",
    "l": "view",
    "v": "view",
    "f": "flow",
    "p": "presets",
    "q": "quit",
    "?": "help",
    "h": "help",
}

KEY_HELP = "space play/pause · n next pick · b back · f flow · p presets · l lyrics · q quit · ? help"

# Mouse reporting (SGR mode): clicks and the wheel arrive as \x1b[<b;x;yM.
MOUSE_ON = "\x1b[?1000h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1006l\x1b[?1000l"


def _csi(params: str, final: str) -> Optional[str]:
    """The command for one escape sequence (arrow key, mouse event), if any."""
    if final in "Mm" and params.startswith("<"):
        try:
            b, x, y = (int(v) for v in params[1:].split(";"))
        except ValueError:
            return None
        if final == "m" or b & 32:          # button release, drag
            return None
        if b & 64:
            return "wheel-up" if b & 1 == 0 else "wheel-down"
        if b & 3 == 0:
            return f"click:{x}:{y}"         # left button, 1-based column and row
        return None
    return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(final) if not params or params == "1" else None


def parse_input(data: str) -> tuple[list[str], str]:
    """Commands for typed text, and what is left of an unfinished escape
    sequence (to be completed by the next read, or taken as Esc)."""
    out: list[str] = []
    i = 0
    while i < len(data):
        ch = data[i]
        if ch == "\x1b":
            if i + 1 >= len(data):
                return out, data[i:]         # Esc alone, or the start of a sequence
            if data[i + 1] in "[O":
                j = i + 2
                while j < len(data) and not ("\x40" <= data[j] <= "\x7e"):
                    j += 1
                if j >= len(data):
                    return out, data[i:]
                cmd = _csi(data[i + 2:j], data[j])
                if cmd:
                    out.append(cmd)
                i = j + 1
                continue
            out.append("escape")
            i += 1
            continue
        if ch in "\r\n":
            out.append("enter")
        else:
            cmd = TERMINAL_KEYS.get(ch.lower())
            if cmd:
                out.append(cmd)
        i += 1
    return out, ""

# NX_KEYTYPE_* codes carried in an NSSystemDefined (subtype 8) event's data1.
NX_KEYTYPE_PLAY = 16
NX_KEYTYPE_NEXT = 17
NX_KEYTYPE_PREVIOUS = 18
NX_KEYTYPE_FAST = 19
NX_KEYTYPE_REWIND = 20
MEDIA_KEYS = {
    NX_KEYTYPE_PLAY: "playpause",
    NX_KEYTYPE_NEXT: "next",
    NX_KEYTYPE_FAST: "next",
    NX_KEYTYPE_PREVIOUS: "previous",
    NX_KEYTYPE_REWIND: "previous",
}
NS_SYSTEM_DEFINED = 14
MEDIA_KEY_SUBTYPE = 8

# TERM_PROGRAM -> bundle id, for terminals that do not export __CFBundleIdentifier.
TERMINAL_BUNDLES = {
    "Apple_Terminal": "com.apple.Terminal",
    "iTerm.app": "com.googlecode.iterm2",
    "WezTerm": "com.github.wez.wezterm",
    "vscode": "com.microsoft.VSCode",
    "ghostty": "com.mitchellh.ghostty",
    "WarpTerminal": "dev.warp.Warp-Stable",
    "Hyper": "co.zeit.hyper",
    "kitty": "net.kovidgoyal.kitty",
    "alacritty": "org.alacritty",
    "Tabby": "org.tabby",
}


def decode_media_key(data1: int) -> Optional[tuple[str, bool, bool]]:
    """``(command, key_down, is_repeat)`` for a media-key event's data1, else None."""
    code = (data1 & 0xFFFF0000) >> 16
    command = MEDIA_KEYS.get(code)
    if command is None:
        return None
    flags = data1 & 0xFFFF
    state = (flags & 0xFF00) >> 8
    return command, state == 0xA, bool(flags & 0x1)


def terminal_bundle_id(env: Optional[dict] = None) -> Optional[str]:
    """The bundle id of the terminal app this process runs in, when knowable."""
    env = os.environ if env is None else env
    bid = env.get("__CFBundleIdentifier")
    if bid:
        return bid
    return TERMINAL_BUNDLES.get(env.get("TERM_PROGRAM", ""))


class KeyReader:
    """Read single keys from the terminal without Enter (cbreak mode)."""

    def __init__(self, on_command: Command, fd: Optional[int] = None):
        self.on_command = on_command
        self.fd = sys.stdin.fileno() if fd is None else fd
        self._old = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        try:
            import termios
            import tty
        except ImportError:  # pragma: no cover - not a POSIX terminal
            return False
        if not os.isatty(self.fd):
            return False
        try:
            self._old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)  # keys arrive one by one; Ctrl+C still interrupts
        except termios.error:
            return False
        self._thread = threading.Thread(target=self._run, name="tidal-shuffle-keys", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        pending = ""
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.05 if pending else 0.2)
            except (OSError, ValueError):
                return
            if not ready:
                if pending:                    # nothing followed the Esc: it was the Esc key
                    pending = ""
                    self.on_command("escape")
                continue
            try:
                data = os.read(self.fd, 256)
            except OSError:
                return
            if not data:
                return
            commands, pending = parse_input(pending + data.decode("utf-8", "ignore"))
            if len(pending) > 32:
                pending = ""                   # not a sequence we know
            for command in commands:
                self.on_command(command)

    def stop(self) -> None:
        self._stop.set()
        if self._old is not None:
            try:
                import termios

                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass
            self._old = None


class MediaKeyTap:
    """Take over the media keys while the terminal running Tidal Shuffle is in front."""

    def __init__(self, on_command: Command, mode: str = "focus", bundle_id: Optional[str] = None,
                 log: Optional[Callable[[str], None]] = None,
                 frontmost: Optional[Callable[[], Optional[str]]] = None):
        self.on_command = on_command
        self.mode = mode                  # focus | always
        self.bundle_id = bundle_id if bundle_id is not None else terminal_bundle_id()
        self.log = log or (lambda m: None)
        self._frontmost = frontmost
        self._tap = None
        self._loop = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self.active = False

    # -- decisions (pure, testable) ---------------------------------------------
    def wants(self) -> bool:
        """Should a media key be taken over right now?"""
        if self.mode == "always":
            return True
        if not self.bundle_id:
            return False
        try:
            front = self._frontmost() if self._frontmost else _frontmost_bundle_id()
        except Exception:
            return False
        return front == self.bundle_id

    def handle(self, data1: int) -> bool:
        """Process one media-key event; returns True when it was taken over
        (the caller then swallows it so TIDAL does not act on it as well)."""
        decoded = decode_media_key(data1)
        if decoded is None or not self.wants():
            return False
        command, down, repeat = decoded
        if down and not repeat:
            self.on_command(command)
        return True  # swallow key-down and key-up alike

    # -- Quartz plumbing -------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        try:
            import AppKit  # noqa: F401
            import Quartz  # noqa: F401
        except ImportError:
            return False, "PyObjC Quartz is not installed (rerun ./install.sh)"
        if self.mode == "focus" and not self.bundle_id:
            return False, "cannot tell which terminal app this is (set player.media_keys: always to take them over everywhere)"
        try:
            from ApplicationServices import AXIsProcessTrusted

            if not AXIsProcessTrusted():
                return False, "allow your terminal under System Settings › Privacy & Security › Accessibility"
        except ImportError:
            pass
        return True, ""

    def start(self, timeout: float = 3.0) -> bool:
        ok, reason = self.available()
        if not ok:
            self.log(f"media keys off: {reason}")
            return False
        self._thread = threading.Thread(target=self._run, name="tidal-shuffle-media-keys", daemon=True)
        self._thread.start()
        self._started.wait(timeout)
        return self.active

    def _run(self) -> None:
        import AppKit
        import Quartz

        def callback(proxy, etype, event, refcon):
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, True)
                return event
            if etype != NS_SYSTEM_DEFINED:
                return event
            try:
                ns = AppKit.NSEvent.eventWithCGEvent_(event)
                if ns is None or ns.subtype() != MEDIA_KEY_SUBTYPE:
                    return event
                if self.handle(int(ns.data1())):
                    return None
            except Exception as e:  # never break the user's media keys
                self.log(f"media key error: {e}")
            return event

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap, Quartz.kCGEventTapOptionDefault,
            Quartz.CGEventMaskBit(NS_SYSTEM_DEFINED), callback, None)
        if self._tap is None:
            self.log("media keys off: macOS refused the key tap (check the Accessibility permission)")
            self._started.set()
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        self.active = True
        self._started.set()
        Quartz.CFRunLoopRun()

    def stop(self) -> None:
        if not self.active:
            return
        try:
            import Quartz

            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, False)
            if self._loop is not None:
                Quartz.CFRunLoopStop(self._loop)
        except Exception:
            pass
        self.active = False


def _frontmost_bundle_id() -> Optional[str]:
    """The app owning the frontmost normal window. Read from the window server,
    because NSWorkspace's answer goes stale in a process without an app run loop."""
    import AppKit
    import Quartz

    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID) or []
    for w in windows:  # front to back
        if int(w.get(Quartz.kCGWindowLayer, 1)) != 0:
            continue   # menu bar, Dock, overlays
        pid = w.get(Quartz.kCGWindowOwnerPID)
        if pid is None:
            continue
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        if app is not None and app.bundleIdentifier():
            return str(app.bundleIdentifier())
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.bundleIdentifier()) if app is not None and app.bundleIdentifier() else None
