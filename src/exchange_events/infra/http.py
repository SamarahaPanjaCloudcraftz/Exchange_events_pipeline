"""Production HTTP client (implements contracts.HttpClient).

Wraps a ``requests``-style session and adds:

* **Browser-realistic default headers** — CME / NSE / MarketWatch reject naive
  requests with 403/401 (anti-bot WAF / subscription), so a sensible UA and Accept
  set is essential for the live adapters (Phase 6).
* **Low-level retry with exponential backoff** on transient network errors and on
  429 / 5xx responses. (This is complementary to the higher-level ingestion
  ``RetryPolicy`` in Phase 7, which retries whole fetches.)

The session and sleep function are injectable so the retry/backoff logic and
response mapping are unit-testable with no real network and no real delays.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import requests

from ..contracts.http_client import HttpClient, Response
from ..domain.errors import SourceUnavailableError

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/json;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _SessionLike(Protocol):
    """Minimal duck type of ``requests.Session`` used by RealHttpClient."""

    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class RealHttpClient(HttpClient):
    def __init__(
        self,
        *,
        session: _SessionLike | None = None,
        default_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        headers = dict(DEFAULT_HEADERS)
        if default_headers:
            headers.update(default_headers)
        # Best-effort: only real requests.Session exposes a mutable .headers mapping.
        sess_headers = getattr(self._session, "headers", None)
        if sess_headers is not None:
            sess_headers.update(headers)
        self._base_headers = headers
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._sleep = sleep

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        return self._request("GET", url, params=params, headers=headers, timeout=timeout)

    def post(
        self,
        url: str,
        *,
        data: Any | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        return self._request(
            "POST", url, data=data, json=json, headers=headers, timeout=timeout
        )

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_max, self._backoff_base * (2.0**attempt))

    def _request(self, method: str, url: str, **kwargs: Any) -> Response:
        # Merge per-call headers on top of the base set (for sessions that don't
        # carry headers themselves, e.g. injected fakes).
        call_headers = dict(self._base_headers)
        if kwargs.get("headers"):
            call_headers.update(kwargs["headers"])
        kwargs["headers"] = call_headers
        kwargs.setdefault("timeout", self._timeout)
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._timeout

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                raw = self._session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    self._sleep(self._backoff(attempt))
                    continue
                raise SourceUnavailableError(f"{method} {url} failed: {exc}") from exc

            status = raw.status_code
            if status in _RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep(self._backoff(attempt))
                continue
            return self._to_response(raw)

        # Unreachable in practice (loop either returns or raises), but keeps mypy happy.
        raise SourceUnavailableError(f"{method} {url} exhausted retries: {last_exc}")

    @staticmethod
    def _to_response(raw: Any) -> Response:
        return Response(
            status_code=raw.status_code,
            url=str(getattr(raw, "url", "")),
            content=raw.content if raw.content is not None else b"",
            headers=dict(getattr(raw, "headers", {}) or {}),
            encoding=getattr(raw, "encoding", None) or "utf-8",
        )
