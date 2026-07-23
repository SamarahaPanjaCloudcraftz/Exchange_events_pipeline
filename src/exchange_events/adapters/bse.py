"""BSE adapter (design doc §5.1) — XBOM holidays + expiries.

Targets BSE's public JSON APIs (``api.bseindia.com/BseIndiaAPI/api/...``), the
same origin the BSE website's JS calls. Unlike NSE, BSE's public API host does
not require a session handshake in front of it.

**Known issue (recorded in DECISIONS.md, found during the Phase-6 contract-test
spike):** the default endpoint paths above are a best-effort guess at BSE's
current API surface, not confirmed against a live capture. The holiday endpoint
returns **HTTP 200 with a classic-ASP 404 HTML body** (a soft-404), which
``HttpSourceAdapter._get_json`` now correctly surfaces as a typed
``SourceUnavailableError`` (previously an unhandled ``JSONDecodeError`` — fixed
alongside this finding) rather than a 403/401 anti-bot block. **Before go-live,
capture BSE's real network calls (browser devtools, Network tab, on
bseindia.com's holiday/expiry pages) and update ``DEFAULT_HOLIDAY_URL`` /
``DEFAULT_EXPIRY_URL`` (or pass overrides via ``AdapterConfig.urls``)** — this
is a URL-discovery task, not an anti-bot problem like CME/MarketWatch.

Emits the raw schema documented in ``normalizers/exchange.py``.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import EventType
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_HOLIDAY_URL = "https://api.bseindia.com/BseIndiaAPI/api/TradingHoliday/w"
DEFAULT_EXPIRY_URL = "https://api.bseindia.com/BseIndiaAPI/api/DerivativesExpiry/w"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
}


class BSEAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "bse_circular"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.HOLIDAY, EventType.EXPIRY]

    def supported_exchanges(self) -> list[str] | None:
        return ["XBOM"]

    def _headers(self) -> dict[str, str]:
        merged = dict(DEFAULT_HEADERS)
        merged.update(self._config.headers)
        return merged

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        want = params.event_types
        records: list[dict[str, Any]] = []
        if want is None or EventType.HOLIDAY in want:
            records.extend(self._fetch_holidays(params))
        if want is None or EventType.EXPIRY in want:
            records.extend(self._fetch_expiries(params))
        return records

    def _fetch_holidays(self, params: FetchParams) -> list[dict[str, Any]]:
        url = self._config.url("holiday", DEFAULT_HOLIDAY_URL)
        query = {"year": params.date_range.start.year, **self._config.params}
        payload = self._get_json(url, params=query, headers=self._headers())
        entries = payload if isinstance(payload, list) else payload.get("Table", [])
        return [
            {
                "record_type": "holiday",
                "date": item.get("holiday_date") or item.get("date"),
                "name": item.get("holiday_desc") or item.get("description"),
                "session": item.get("session"),
                "id": item.get("id"),
            }
            for item in entries
        ]

    def _fetch_expiries(self, params: FetchParams) -> list[dict[str, Any]]:
        url = self._config.url("expiry", DEFAULT_EXPIRY_URL)
        underlyings = self._config.option("underlyings") or ["SENSEX"]
        out: list[dict[str, Any]] = []
        for underlying in underlyings:
            query = {"symbol": underlying, "year": params.date_range.start.year}
            payload = self._get_json(url, params=query, headers=self._headers())
            entries = payload if isinstance(payload, list) else payload.get("Table", [])
            for item in entries:
                out.append(
                    {
                        "record_type": "expiry",
                        "underlying": underlying,
                        "instrument_type": item.get("instrument_type", "options"),
                        "series": item.get("series", "weekly"),
                        "expiry_date": item.get("expiry_date"),
                        "is_revised": bool(item.get("is_revised", False)),
                        "id": item.get("id"),
                    }
                )
        return out
