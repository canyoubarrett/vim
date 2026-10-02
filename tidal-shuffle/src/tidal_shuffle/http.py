"""Shared HTTP helpers: one client, retries with backoff, 429 handling."""

from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from . import __version__

USER_AGENT = f"tidal-shuffle/{__version__} ( https://github.com/canyoubarrett/vim )"


class HttpError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


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
    error_body_statuses: tuple = (),
):
    """Send a request and return parsed JSON, retrying transient failures.

    Retries connection errors, 5xx and 429 (honouring ``Retry-After`` when it
    is at most ``max_retry_after`` seconds; a longer wait raises at once, with
    the wait in ``HttpError.retry_after``). Statuses in ``error_body_statuses``
    return their JSON body (APIs such as Last.fm put the real error there).
    Any other 4xx raises :class:`HttpError`.
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
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else 2.0 ** attempt
            except ValueError:
                wait = 2.0 ** attempt
            if wait > max_retry_after or attempt >= retries:
                # Retrying before the window ends only earns another 429.
                raise HttpError(f"{url}: rate limited for {wait:.0f}s", status=429, retry_after=wait)
            sleep(max(wait, 0.5))
            continue
        if resp.status_code >= 500 and attempt < retries:
            sleep(min(2.0 ** attempt, 8.0))
            continue
        if resp.status_code in error_body_statuses:
            try:
                return resp.json()
            except ValueError:
                pass
        if resp.status_code >= 400:
            body = resp.text[:300].replace("\n", " ")
            raise HttpError(f"{url}: HTTP {resp.status_code}: {body}", status=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise HttpError(f"{url}: response was not JSON", status=resp.status_code) from None
    raise last_error or HttpError(f"{url}: gave up")


def get_json(client: httpx.Client, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             retries: int = 3, sleep: Callable[[float], None] = time.sleep, max_retry_after: float = 30.0,
             error_body_statuses: tuple = ()):
    return request_json(client, "GET", url, params=params, headers=headers, retries=retries, sleep=sleep,
                        max_retry_after=max_retry_after, error_body_statuses=error_body_statuses)


def post_json(client: httpx.Client, url: str, body, params: Optional[dict] = None, headers: Optional[dict] = None,
              retries: int = 3, sleep: Callable[[float], None] = time.sleep, max_retry_after: float = 30.0):
    return request_json(client, "POST", url, params=params, headers=headers, json_body=body, retries=retries,
                        sleep=sleep, max_retry_after=max_retry_after)
