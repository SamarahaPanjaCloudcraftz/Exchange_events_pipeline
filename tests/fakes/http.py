"""In-memory HttpClient for tests (design doc §9.2).

Returns canned :class:`Response` objects registered by URL and records every call
so tests can assert what an adapter requested. Fixtures (raw JSON/HTML) are loaded
into responses via the ``json``/``text``/``bytes`` helpers.
"""

from __future__ import annotations

import json as _json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from exchange_events.contracts.http_client import HttpClient, Response


@dataclass
class RecordedCall:
    method: str
    url: str
    params: Mapping[str, Any] | None = None
    headers: Mapping[str, str] | None = None
    data: Any | None = None
    json: Any | None = None


class FakeHttpClient(HttpClient):
    def __init__(self, responses: Mapping[str, Response] | None = None) -> None:
        self._responses: dict[str, Response] = dict(responses or {})
        self._sequences: dict[str, list[Response]] = {}
        self.calls: list[RecordedCall] = []

    # --- registration helpers ------------------------------------------------------
    def register(self, url: str, response: Response) -> None:
        self._responses[url] = response

    def register_json(self, url: str, obj: Any, status_code: int = 200) -> None:
        self._responses[url] = Response(
            status_code=status_code,
            url=url,
            content=_json.dumps(obj).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    def register_json_sequence(self, url: str, objs: list[Any]) -> None:
        """Queue a distinct JSON response per call to ``url`` (e.g. successive
        pagination pages) — ``params`` alone can't route different responses
        since this fake matches on URL only, mirroring how ``_get`` is called."""
        self._sequences[url] = [
            Response(
                status_code=200,
                url=url,
                content=_json.dumps(obj).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            for obj in objs
        ]

    def register_text(self, url: str, text: str, status_code: int = 200) -> None:
        self._responses[url] = Response(
            status_code=status_code, url=url, content=text.encode("utf-8")
        )

    def register_bytes(self, url: str, content: bytes, status_code: int = 200) -> None:
        self._responses[url] = Response(status_code=status_code, url=url, content=content)

    # --- HttpClient interface ------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        self.calls.append(RecordedCall("GET", url, params=params, headers=headers))
        return self._lookup(url)

    def post(
        self,
        url: str,
        *,
        data: Any | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        self.calls.append(
            RecordedCall("POST", url, headers=headers, data=data, json=json)
        )
        return self._lookup(url)

    # --- internals -----------------------------------------------------------------
    def _lookup(self, url: str) -> Response:
        if url in self._sequences and self._sequences[url]:
            return self._sequences[url].pop(0)
        if url in self._responses:
            return self._responses[url]
        base = url.split("?", 1)[0]
        if base in self._sequences and self._sequences[base]:
            return self._sequences[base].pop(0)
        if base in self._responses:
            return self._responses[base]
        return Response(status_code=404, url=url, content=b"not registered")
