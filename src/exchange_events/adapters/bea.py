"""BEA adapter (design doc §5.1) — tier 3 of the economic-release waterfall.

Uses the BEA API (https://apps.bea.gov/api/data, ``datasetname=NIPA``) — the
*original publisher* of PCE / Personal Income & Outlays, used as the official
backstop for that release (see DECISIONS.md "Economic-release waterfall"). Free
``UserID`` registration at https://apps.bea.gov/api/signup/, required (``api_key``).

**Table/line mapping needs confirmation before go-live** (recorded honestly, same
posture as this project's other unverified-live endpoints — e.g. BSE, ISM): BEA's
NIPA tables are large and multi-line; the default below targets Table 2.8.6
("Percent Change from Preceding Period in the Chain-Type Price Index for PCE"),
line 1 (the headline PCE price index), which is believed correct from BEA's own
table documentation but has not been exercised against a live response in this
environment (no API key available here). ``config.options["table"]`` overrides
every field if BEA's table/line numbering differs from what's assumed.

BEA's ``TimePeriod`` field is ``"YYYYMM"`` (e.g. ``"2026M06"``); represented here
as the first of that month, same simplification as the BLS adapter.

Emits the raw schema documented in ``normalizers/government_release.py``.
"""

from __future__ import annotations

import datetime
from typing import Any

from ..domain.enums import EventType
from ..domain.errors import SourceUnavailableError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_BASE_URL = "https://apps.bea.gov/api/data"

# release_code -> BEA NIPA table metadata. Overridable via config.options["table"].
DEFAULT_TABLE: dict[str, str] = {
    "release_code": "PCE",
    "release_name": "PCE Price Index",
    "table_name": "T20806",
    "line_number": "1",
    "frequency": "M",
    "agency": "BEA",
    "unit": "%",
}


class BEAAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "bea_api"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.ECONOMIC_RELEASE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    @property
    def _table(self) -> dict[str, str]:
        return self._config.option("table") or DEFAULT_TABLE

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        if not self._config.api_key:
            raise SourceUnavailableError("bea_api: BEA UserID (api_key) is required")
        table = self._table
        base = self._config.url("data", DEFAULT_BASE_URL)
        query = {
            "UserID": self._config.api_key,
            "method": "GetData",
            "datasetname": "NIPA",
            "TableName": table["table_name"],
            "Frequency": table.get("frequency", "M"),
            "Year": "X",  # all available years; filtered to the requested range below
            "ResultFormat": "JSON",
            **self._config.params,
        }
        payload = self._get_json(base, query)
        return self._parse(payload, table, params)

    @staticmethod
    def _parse(
        payload: dict[str, Any], table: dict[str, str], params: FetchParams
    ) -> list[dict[str, Any]]:
        rows = payload.get("BEAAPI", {}).get("Results", {}).get("Data", [])
        target_line = str(table["line_number"])
        # Keep only the configured line item, in chronological order.
        matching = [r for r in rows if str(r.get("LineNumber")) == target_line]
        matching.sort(key=lambda r: r.get("TimePeriod", ""))

        out: list[dict[str, Any]] = []
        previous: str | None = None
        for row in matching:
            day = _parse_time_period(row.get("TimePeriod", ""))
            if day is None:
                continue
            value = str(row.get("DataValue", "")).replace(",", "") or None
            if not params.date_range.contains(day):
                previous = value or previous
                continue
            out.append(
                {
                    "release_code": table["release_code"],
                    "release_name": table["release_name"],
                    "date": day.isoformat(),
                    "period": row.get("TimePeriod", ""),
                    "actual": value,
                    "previous": previous,
                    "unit": table.get("unit", ""),
                    "agency": table.get("agency", "BEA"),
                    "id": f"{table['table_name']}:{target_line}:{row.get('TimePeriod')}",
                }
            )
            previous = value or previous
        return out


def _parse_time_period(value: str) -> datetime.date | None:
    """Parse BEA's ``"YYYYMM06"``-style TimePeriod (e.g. ``"2026M06"``) into the
    first of that month."""
    if "M" not in value:
        return None
    year_str, _, month_str = value.partition("M")
    try:
        return datetime.date(int(year_str), int(month_str), 1)
    except ValueError:
        return None
