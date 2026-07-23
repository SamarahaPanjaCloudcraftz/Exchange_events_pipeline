"""NSE adapter (design doc §5.1) — XNSE holidays + expiries.

Targets NSE's public JSON APIs (``nseindia.com/api/...``), the same ones the NSE
website's own JS calls. NSE fronts these with a WAF that requires a warmed-up
session: a plain GET to the API 403s, but a prior GET to the site homepage sets
cookies that the API then accepts. ``_warm_session`` performs that handshake
once per adapter instance (lazily, on first fetch) via the injected
``HttpClient`` — no adapter-owned network client, so it stays fake-testable.

**Validated live** during the Phase-6 contract-test spike (2026-07-21): this
adapter's session-warm-up + browser-header design successfully reached the real
NSE holiday endpoint from the sandbox, unlike CME/MarketWatch which are
IP/JS-challenge blocked there — see DECISIONS.md.

Emits the raw schema documented in ``normalizers/exchange.py``.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import EventType
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_HOME_URL = "https://www.nseindia.com"
DEFAULT_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
DEFAULT_EXPIRY_URL = "https://www.nseindia.com/api/equity-stock?index=expiry"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}

# NSE's holiday API groups by segment (CM = equity cash, FO = futures & options, ...).
DEFAULT_SEGMENTS: list[str] = ["CM", "FO", "CD"]


class NSEAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "nse_circular"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.HOLIDAY, EventType.EXPIRY]

    def supported_exchanges(self) -> list[str] | None:
        return ["XNSE"]

    def _headers(self) -> dict[str, str]:
        merged = dict(DEFAULT_HEADERS)
        merged.update(self._config.headers)
        return merged

    def _warm_session(self) -> None:
        """Visit the homepage once so the WAF issues session cookies for the API."""
        home = self._config.url("home", DEFAULT_HOME_URL)
        self._http.get(home, headers=self._headers(), timeout=self._config.timeout)

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        self._warm_session()
        want = params.event_types
        records: list[dict[str, Any]] = []
        if want is None or EventType.HOLIDAY in want:
            records.extend(self._fetch_holidays())
        if want is None or EventType.EXPIRY in want:
            records.extend(self._fetch_expiries(params))
        return records

    def _fetch_holidays(self) -> list[dict[str, Any]]:
        url = self._config.url("holiday", DEFAULT_HOLIDAY_URL)
        payload = self._get_json(url, headers=self._headers())
        out: list[dict[str, Any]] = []
        segments = self._config.option("segments") or DEFAULT_SEGMENTS
        for segment in segments:
            for item in payload.get(segment, []):
                out.append(
                    {
                        "record_type": "holiday",
                        "date": item.get("tradingDate") or item.get("date"),
                        "name": item.get("description") or item.get("holidayName"),
                        "session": item.get("session"),
                        "segments": [segment],
                        "id": item.get("sr_no") or item.get("id"),
                    }
                )
        return out

    def _fetch_expiries(self, params: FetchParams) -> list[dict[str, Any]]:
        url = self._config.url("expiry", DEFAULT_EXPIRY_URL)
        underlyings = self._config.option("underlyings") or ["NIFTY", "BANKNIFTY"]
        out: list[dict[str, Any]] = []
        for underlying in underlyings:
            query = {"symbol": underlying, "year": params.date_range.start.year}
            payload = self._get_json(url, params=query, headers=self._headers())
            entries = payload if isinstance(payload, list) else payload.get("data", [])
            for item in entries:
                out.append(
                    {
                        "record_type": "expiry",
                        "underlying": underlying,
                        "instrument_type": item.get("instrumentType", "options"),
                        "series": item.get("series", "weekly"),
                        "expiry_date": item.get("expiryDate"),
                        "is_revised": bool(item.get("isRevised", False)),
                        "id": item.get("id"),
                    }
                )
        return out
