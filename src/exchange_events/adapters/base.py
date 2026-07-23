"""Base HTTP source adapter (design doc §5.1).

Provides HTTP plumbing + typed error mapping so concrete adapters focus on
endpoint URLs and response parsing. Network failures / blocks become
``SourceUnavailableError``; 429 becomes ``SourceRateLimitError`` — the ingestion
engine (Phase 7) isolates and retries these per policy.
"""

from __future__ import annotations

import base64
from typing import Any

from ..contracts.http_client import HttpClient, Response
from ..contracts.logger import Logger
from ..contracts.source_adapter import SourceAdapter
from ..domain.errors import SourceRateLimitError, SourceUnavailableError
from ..infra.logging import NullLogger
from .config import AdapterConfig


class HttpSourceAdapter(SourceAdapter):
    def __init__(
        self,
        http_client: HttpClient,
        config: AdapterConfig | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._http = http_client
        self._config = config or AdapterConfig()
        self._logger = logger or NullLogger()

    # --- HTTP helpers --------------------------------------------------------------
    def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        merged_headers = dict(self._config.headers)
        if headers:
            merged_headers.update(headers)
        resp = self._http.get(
            url,
            params=params or None,
            headers=merged_headers or None,
            timeout=self._config.timeout,
        )
        self._raise_for_status(resp, url)
        return resp

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        resp = self._get(url, params, headers)
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - any malformed body is a source problem
            raise SourceUnavailableError(
                f"{self.source_name()}: non-JSON or malformed response from {url} "
                f"(HTTP {resp.status_code}): {exc}"
            ) from exc

    def _get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        return self._get(url, params, headers).text

    def _post_json(
        self,
        url: str,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any:
        merged_headers = dict(self._config.headers)
        if headers:
            merged_headers.update(headers)
        resp = self._http.post(
            url,
            json=json_body,
            headers=merged_headers or None,
            timeout=self._config.timeout,
        )
        self._raise_for_status(resp, url)
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - any malformed body is a source problem
            raise SourceUnavailableError(
                f"{self.source_name()}: non-JSON or malformed response from {url} "
                f"(HTTP {resp.status_code}): {exc}"
            ) from exc

    def _post_form(
        self,
        url: str,
        form_data: dict[str, Any],
        headers: dict[str, str] | None = None,
        basic_auth: tuple[str, str] | None = None,
    ) -> Any:
        """POST form-urlencoded data (as OAuth2 token endpoints expect), optionally
        with HTTP Basic auth — ``HttpClient`` has no ``auth=`` param, so the header
        is built here rather than relying on a client-library convenience."""
        merged_headers = dict(self._config.headers)
        if headers:
            merged_headers.update(headers)
        if basic_auth is not None:
            user, password = basic_auth
            token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
            merged_headers["Authorization"] = f"Basic {token}"
        resp = self._http.post(
            url,
            data=form_data,
            headers=merged_headers or None,
            timeout=self._config.timeout,
        )
        self._raise_for_status(resp, url)
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - any malformed body is a source problem
            raise SourceUnavailableError(
                f"{self.source_name()}: non-JSON or malformed response from {url} "
                f"(HTTP {resp.status_code}): {exc}"
            ) from exc

    def _raise_for_status(self, resp: Response, url: str) -> None:
        if resp.ok:
            return
        if resp.status_code == 429:
            raise SourceRateLimitError(f"{self.source_name()}: rate limited by {url}")
        if resp.status_code in (401, 403):
            raise SourceUnavailableError(
                f"{self.source_name()}: access denied (HTTP {resp.status_code}) at {url} "
                "— source may require session/subscription or the IP is blocked"
            )
        raise SourceUnavailableError(
            f"{self.source_name()}: HTTP {resp.status_code} from {url}"
        )
