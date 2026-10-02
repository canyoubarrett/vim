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


def test_key_reader_maps_keys_and_arrows():
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
    assert got == ["playpause", "next", "up", "previous", "help", "quit"]


def test_key_reader_needs_a_terminal(tmp_path):
    f = open(tmp_path / "not-a-tty", "w+")
    try:
        assert KeyReader(lambda c: None, fd=f.fileno()).start() is False
    finally:
        f.close()


def test_parse_input_arrows_enter_escape_and_mouse():
    from tidal_shuffle.controls import parse_input

    cmds, rest = parse_input("\x1b[A\x1b[B\x1bOAp\r\x1b[<0;12;5M\x1b[<0;12;5m\x1b[<64;3;3M\x1b[<65;3;3M\x1b[<2;1;1M")
    assert cmds == ["up", "down", "up", "presets", "enter", "click:12:5", "wheel-up", "wheel-down"]
    assert rest == ""


def test_parse_input_keeps_an_unfinished_sequence():
    from tidal_shuffle.controls import parse_input

    assert parse_input("n\x1b") == (["next"], "\x1b")
    assert parse_input("\x1b[<0;1") == ([], "\x1b[<0;1")
    assert parse_input("\x1b[<0;1" + ";2M") == (["click:1:2"], "")
    assert parse_input("\x1bq") == (["escape", "quit"], "")


def test_key_reader_lone_escape_is_the_escape_key():
    import os
    import threading

    from tidal_shuffle.controls import KeyReader

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
        os.write(master, b"\x1b")
        import time
        time.sleep(0.3)
        os.write(master, b"\x1b[<0;4;2Mq")
        assert done.wait(3)
    finally:
        reader.stop()
        os.close(master)
        os.close(slave)
    assert got == ["escape", "click:4:2", "quit"]
