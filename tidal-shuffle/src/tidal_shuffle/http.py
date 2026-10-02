"""Shared HTTP helpers: one client, retries with backoff, 429 handling."""

from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from . import __version__

USER_AGENT = f"tidal-shuffle/{__version__} ( https://github.com/canyoubarrett/vim )"


class HttpError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def make_client(timeout: float = 20.0, **kwargs) -> httpx.Client:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    headers.update(kwargs.pop("headers", {}) or {})
    return httpx.Client(timeout=timeout, headers=headers, follow_redirects=True, **kwargs)


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    json_body=None,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    max_retry_after: float = 30.0,
):
    """Send a request and return parsed JSON, retrying transient failures.

    Retries connection errors, 5xx and 429 (honouring ``Retry-After`` up to
    ``max_retry_after`` seconds). Any other 4xx raises :class:`HttpError` with
    the status and the start of the body.
    """
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = client.request(method, url, params=params, headers=headers, json=json_body)
        except httpx.HTTPError as e:
            last_error = HttpError(f"{url}: {e}")
            if attempt < retries:
                sleep(min(2.0 ** attempt, 8.0))
                continue
            raise last_error from None
        if resp.status_code == 429 and attempt < retries:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else 2.0 ** attempt
            except ValueError:
                wait = 2.0 ** attempt
            if wait > max_retry_after * 10:
                raise HttpError(f"{url}: rate limited for {wait:.0f}s", status=429)
            sleep(min(max(wait, 0.5), max_retry_after))
            continue
        if resp.status_code >= 500 and attempt < retries:
            sleep(min(2.0 ** attempt, 8.0))
            continue
        if resp.status_code >= 400:
            body = resp.text[:300].replace("\n", " ")
            raise HttpError(f"{url}: HTTP {resp.status_code}: {body}", status=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise HttpError(f"{url}: response was not JSON", status=resp.status_code) from None
    raise last_error or HttpError(f"{url}: gave up")


def get_json(client: httpx.Client, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             retries: int = 3, sleep: Callable[[float], None] = time.sleep, max_retry_after: float = 30.0):
    return request_json(client, "GET", url, params=params, headers=headers, retries=retries, sleep=sleep,
                        max_retry_after=max_retry_after)


def post_json(client: httpx.Client, url: str, body, params: Optional[dict] = None, headers: Optional[dict] = None,
              retries: int = 3, sleep: Callable[[float], None] = time.sleep, max_retry_after: float = 30.0):
    return request_json(client, "POST", url, params=params, headers=headers, json_body=body, retries=retries,
                        sleep=sleep, max_retry_after=max_retry_after)
