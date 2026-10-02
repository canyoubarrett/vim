"""Terminal keys and media keys."""

import os
import threading
import time

from tidal_shuffle.controls import (KeyReader, MediaKeyTap, NX_KEYTYPE_NEXT, NX_KEYTYPE_PLAY, NX_KEYTYPE_PREVIOUS,
                                    decode_media_key, terminal_bundle_id)


def media_data1(code, down=True, repeat=False):
    flags = (0xA if down else 0xB) << 8 | (1 if repeat else 0)
    return (code << 16) | flags


def test_decode_media_key():
    assert decode_media_key(media_data1(NX_KEYTYPE_PLAY)) == ("playpause", True, False)
    assert decode_media_key(media_data1(NX_KEYTYPE_NEXT, down=False)) == ("next", False, False)
    assert decode_media_key(media_data1(NX_KEYTYPE_PREVIOUS, repeat=True)) == ("previous", True, True)
    assert decode_media_key((0 << 16) | 0xA00) is None  # volume up etc. are left alone


def test_media_keys_are_taken_only_while_the_terminal_is_in_front():
    got = []
    front = {"app": "com.apple.Terminal"}
    tap = MediaKeyTap(got.append, mode="focus", bundle_id="com.apple.Terminal", frontmost=lambda: front["app"])
    assert tap.handle(media_data1(NX_KEYTYPE_NEXT)) is True
    assert tap.handle(media_data1(NX_KEYTYPE_NEXT, down=False)) is True     # key-up swallowed too
    assert tap.handle(media_data1(NX_KEYTYPE_NEXT, repeat=True)) is True    # held key: once only
    assert got == ["next"]
    front["app"] = "com.tidal.desktop"
    assert tap.handle(media_data1(NX_KEYTYPE_PLAY)) is False                # TIDAL gets it as usual
    assert got == ["next"]


def test_media_keys_always_and_unknown_terminal():
    got = []
    always = MediaKeyTap(got.append, mode="always", bundle_id=None, frontmost=lambda: "x")
    assert always.handle(media_data1(NX_KEYTYPE_PLAY)) and got == ["playpause"]
    unknown = MediaKeyTap(got.append, mode="focus", bundle_id="", frontmost=lambda: "")
    assert unknown.handle(media_data1(NX_KEYTYPE_PLAY)) is False


def test_terminal_bundle_id():
    assert terminal_bundle_id({"__CFBundleIdentifier": "com.googlecode.iterm2"}) == "com.googlecode.iterm2"
    assert terminal_bundle_id({"TERM_PROGRAM": "Apple_Terminal"}) == "com.apple.Terminal"
    assert terminal_bundle_id({}) is None


def test_key_reader_maps_keys_and_ignores_escape_sequences():
    master, slave = os.openpty()
    got = []
    done = threading.Event()

    def on(cmd):
        got.append(cmd)
        if cmd == "quit":
            done.set()

    reader = KeyReader(on, fd=slave)
    assert reader.start()
    try:
        os.write(master, b" n\x1b[Ab?xq")   # space, n, arrow-up (ignored), b, ?, x (unbound), q
        assert done.wait(3)
    finally:
        reader.stop()
        os.close(master)
        os.close(slave)
    assert got == ["playpause", "next", "previous", "help", "quit"]


def test_key_reader_needs_a_terminal(tmp_path):
    f = open(tmp_path / "not-a-tty", "w+")
    try:
        assert KeyReader(lambda c: None, fd=f.fileno()).start() is False
    finally:
        f.close()
