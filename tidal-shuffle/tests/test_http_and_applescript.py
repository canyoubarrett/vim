import httpx
import pytest

from tidal_shuffle.applescript import AppleScriptError, OsascriptRunner, quote
from tidal_shuffle.http import HttpError, get_json


def test_get_json_retries_5xx_then_raises_4xx():
    seen = []
    def handler(request):
        seen.append(1)
        return httpx.Response(503) if len(seen) < 3 else httpx.Response(200, json={"ok": 1})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert get_json(client, "https://x/y", sleep=lambda s: None) == {"ok": 1}

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404, text="nope")))
    with pytest.raises(HttpError) as e:
        get_json(client, "https://x/y", sleep=lambda s: None)
    assert e.value.status == 404


def test_get_json_waits_out_short_rate_limits():
    waits = []
    n = {"c": 0}
    def handler(request):
        n["c"] += 1
        return httpx.Response(429, headers={"Retry-After": "3"}) if n["c"] == 1 else httpx.Response(200, json={})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    get_json(client, "https://x", sleep=waits.append, max_retry_after=5)
    assert waits == [3.0]


def test_get_json_does_not_retry_before_a_long_window_ends():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "40"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(HttpError) as e:
        get_json(client, "https://x", sleep=lambda s: None, max_retry_after=5)
    assert e.value.status == 429 and e.value.retry_after == 40.0 and len(calls) == 1


def test_error_bodies_can_be_returned():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": 6, "message": "Track not found"})))
    assert get_json(client, "https://x", error_body_statuses=(400,)) == {"error": 6, "message": "Track not found"}


def test_get_json_gives_up_on_hours_long_rate_limits():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "7200"})))
    with pytest.raises(HttpError) as e:
        get_json(client, "https://x", sleep=lambda s: None, max_retry_after=30)
    assert e.value.status == 429


def test_get_json_non_json_body():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(HttpError, match="not JSON"):
        get_json(client, "https://x")


def test_quote_escapes():
    assert quote('He said "hi" \\ there') == '"He said \\"hi\\" \\\\ there"'


def test_runner_missing_binary_is_clean_error():
    runner = OsascriptRunner(binary="/definitely/not/here/osascript")
    with pytest.raises(AppleScriptError, match="osascript not found"):
        runner.run('return "x"')
