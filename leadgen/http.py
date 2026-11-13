"""Shared HTTP behaviour: User-Agent, per-key throttling, bounded exponential backoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from leadgen.config import Settings
from leadgen.models import RateLimited, SourceUnavailable

RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        backoff_base: float = 2.0,
    ):
        self.settings = settings
        self._client = httpx.Client(
            transport=transport,
            timeout=settings.request_timeout,
            headers={"User-Agent": settings.user_agent},
        )
        self._sleep = sleep
        self._clock = clock
        self._backoff_base = backoff_base
        self._last_request: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def _throttle(self, key: str | None, min_interval: float) -> None:
        if not key or min_interval <= 0:
            return
        last = self._last_request.get(key)
        if last is not None:
            wait = min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[key] = self._clock()

    def request(
        self,
        method: str,
        url: str,
        *,
        source: str,
        throttle_key: str | None = None,
        min_interval: float = 0.0,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a request, retrying 429/5xx/timeouts with exponential backoff (bounded)."""
        attempts = self.settings.max_attempts
        last_status: int | None = None
        last_error = ""
        for attempt in range(attempts):
            if attempt:
                self._sleep(self._backoff_base * (2 ** (attempt - 1)))
            self._throttle(throttle_key, min_interval)
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                last_status, last_error = None, "timed out"
                continue
            except httpx.HTTPError as exc:
                last_status, last_error = None, f"network error: {exc.__class__.__name__}"
                continue
            if resp.status_code in RETRY_STATUS:
                last_status, last_error = resp.status_code, f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                raise SourceUnavailable(f"HTTP {resp.status_code} from {source}", source)
            return resp
        message = f"{source} failed after {attempts} attempts ({last_error})"
        if last_status == 429:
            raise RateLimited(message, source)
        raise SourceUnavailable(message, source)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
