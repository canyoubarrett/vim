import json

from tidal_shuffle.history import HistoryStore


def test_add_query_and_persist(tmp_path):
    path = tmp_path / "h.json"
    store = HistoryStore(path)
    store.add("Song", "Artist", tidal_id="42", source="lastfm", ts=100.0)
    assert store.has_played("song", "ARTIST")
    assert store.has_played(tidal_id="42")
    assert not store.has_played("Other", "Artist")
    again = HistoryStore(path)
    assert len(again) == 1
    assert again.recent_artists(5) == ["Artist"]


def test_windows_by_count_and_days(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    for i in range(10):
        store.add(f"S{i}", f"A{i}", tidal_id=str(i), ts=1000.0 + i * 86400)
    assert store.recent_tidal_ids(within_count=3) == {"7", "8", "9"}
    assert store.recent_keys(within_count=0, within_days=2.5, now=1000.0 + 9 * 86400) == {("s7", "a7"), ("s8", "a8"), ("s9", "a9")}


def test_max_entries_trims_oldest(tmp_path):
    store = HistoryStore(tmp_path / "h.json", max_entries=3)
    for i in range(5):
        store.add(f"S{i}", "A", tidal_id=str(i))
    assert [e.tidal_id for e in store.entries()] == ["2", "3", "4"]


def test_legacy_v1_format_is_readable(tmp_path):
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"played": ["11", "22"]}))
    store = HistoryStore(path)
    assert store.has_played(tidal_id="22")
    assert len(store) == 2


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{not json")
    store = HistoryStore(path)
    assert len(store) == 0
    store.add("S", "A")
    assert json.loads(path.read_text())["version"] == 2


def test_clear(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    store.add("S", "A")
    store.clear()
    assert len(store) == 0
