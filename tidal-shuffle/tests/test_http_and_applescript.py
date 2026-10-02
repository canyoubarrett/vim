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


def test_get_json_honours_retry_after_cap():
    waits = []
    n = {"c": 0}
    def handler(request):
        n["c"] += 1
        return httpx.Response(429, headers={"Retry-After": "40"}) if n["c"] == 1 else httpx.Response(200, json={})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    get_json(client, "https://x", sleep=waits.append, max_retry_after=5)
    assert waits == [5]


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
