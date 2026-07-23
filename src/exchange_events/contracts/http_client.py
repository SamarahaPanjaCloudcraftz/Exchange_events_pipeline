"""HTTP client contract + Response value type (infrastructure interface).

Source adapters (§5.1) receive an ``HttpClient`` rather than importing ``requests``
directly, so they are unit-testable against a ``FakeHttpClient`` with canned
fixtures — no network. The concrete ``RealHttpClient`` lives in ``infra/``.
"""

from __future__ import annotations

import json as _json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import ExchangeEventsError


class HttpError(ExchangeEventsError):
    """Non-2xx HTTP response surfaced by ``Response.raise_for_status``.

    Adapters translate this into ``SourceUnavailableError`` /
    ``SourceRateLimitError`` as appropriate for their source.
    """

    def __init__(self, status_code: int, url: str, *, body: str = "") -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status_code} for {url}")


@dataclass(frozen=True)
class Response:
    """An immutable HTTP response, decoupled from any specific HTTP library."""

    status_code: int
    url: str
    content: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    encoding: str = "utf-8"

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self) -> Any:
        return _json.loads(self.content)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise HttpError(self.status_code, self.url, body=self.text[:500])


class HttpClient(ABC):
    @abstractmethod
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        """Issue a GET request."""
        ...

    @abstractmethod
    def post(
        self,
        url: str,
        *,
        data: Any | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        """Issue a POST request (``json`` is serialized; ``data`` sent as-is)."""
        ...
