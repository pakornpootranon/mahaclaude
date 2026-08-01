"""Shared HTTP client for adapters, honoring politeness rules
(docs/02-architecture.md §4): honor Retry-After, cap 1 req/s/host, 20s
timeout, 2 retries with jittered backoff.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from threading import Lock

import httpx

TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 2
MIN_INTERVAL_SECONDS = 1.0

_last_request_at: dict[str, float] = defaultdict(float)
_lock = Lock()


def _host_of(url: str) -> str:
    return httpx.URL(url).host or url


def _throttle(host: str) -> None:
    with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at[host])
        if wait > 0:
            time.sleep(wait)
        _last_request_at[host] = time.monotonic()


def _backoff_delay(attempt: int) -> float:
    return (2**attempt) + random.uniform(0, 1)


def polite_get(url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    host = _host_of(url)
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        _throttle(host)
        try:
            response = httpx.get(
                url, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(_backoff_delay(attempt))
            continue

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after else _backoff_delay(attempt)
            last_exc = httpx.HTTPStatusError(
                f"429 from {host}", request=response.request, response=response
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)
            continue

        if response.status_code >= 500:
            last_exc = httpx.HTTPStatusError(
                f"{response.status_code} from {host}", request=response.request, response=response
            )
            if attempt < MAX_RETRIES:
                time.sleep(_backoff_delay(attempt))
            continue

        # Non-retryable client error (404, 401, 403, ...) — fail fast rather
        # than burning retry budget on a request that won't succeed.
        response.raise_for_status()
        return response

    assert last_exc is not None
    raise last_exc
