"""BLS adapter (design doc §5.1) — tier 2 of the economic-release waterfall.

Uses the BLS Public Data API v2 (https://api.bls.gov/publicAPI/v2/timeseries/data/)
— the *original publisher* of NFP, CPI, PPI, and JOLTS, used as an official
backstop when FRED is stale or unreachable (see DECISIONS.md "Economic-release
waterfall"). Free registration key = 500 requests/day and 10 years of history
(https://www.bls.gov/developers/); without a key, BLS still answers up to 25
series with less history — this adapter works either way, ``api_key`` is optional.

Series ids verified against BLS's own documentation (not guessed):
CPI = ``CUUR0000SA0`` (CPI-U, U.S. city average, not seasonally adjusted),
NFP = ``CES0000000001`` (Total Nonfarm, seasonally adjusted),
PPI = ``WPSFD4`` (Final Demand, seasonally adjusted),
JOLTS = ``JTS000000000000000JOL`` (Job Openings, Total Nonfarm, seasonally adjusted)
— the same underlying series FRED carries as ``JTSJOL``, published by its
original source instead of St. Louis Fed's mirror.

BLS returns each observation as ``{year, period, periodName, value}`` where
``period`` is ``"M01"``..``"M12"`` for monthly series; represented here as the
first of that month (a simplification — BLS doesn't publish an exact release-date
field in this API, only the period the data covers).

Emits the raw schema documented in ``normalizers/government_release.py``.

Requests use POST with a JSON ``seriesid`` array, not GET with comma-joined ids
in the URL path — confirmed live that BLS's v2 API answers a single series fine
either way, but rejects a multi-series GET (``REQUEST_FAILED``, ``Results: null``)
while POST works for both one and many series, so one code path covers both.
"""

from __future__ import annotations

import datetime
from typing import Any

from ..domain.enums import EventType
from ..domain.errors import SourceUnavailableError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# release_code -> BLS series metadata. Overridable via config.options["series"].
DEFAULT_SERIES: dict[str, dict[str, str]] = {
    "CPI": {"series_id": "CUUR0000SA0", "release_name": "Consumer Price Index",
            "agency": "BLS", "unit": "index"},
    "NFP": {"series_id": "CES0000000001", "release_name": "Total Nonfarm Payrolls",
            "agency": "BLS", "unit": "thousands"},
    "PPI": {"series_id": "WPSFD4", "release_name": "Producer Price Index (Final Demand)",
            "agency": "BLS", "unit": "index"},
    "JOLTS": {"series_id": "JTS000000000000000JOL", "release_name": "Job Openings: Total Nonfarm",
              "agency": "BLS", "unit": "thousands"},
}

_PERIOD_MONTH = {f"M{m:02d}": m for m in range(1, 13)}


class BLSAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "bls_api"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.ECONOMIC_RELEASE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    @property
    def _series(self) -> dict[str, dict[str, str]]:
        return self._config.option("series") or DEFAULT_SERIES

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        series = self._series
        series_ids = [meta["series_id"] for meta in series.values()]
        # BLS's v2 API rejects comma-joined multi-series GET requests on the path
        # (confirmed live: REQUEST_FAILED/Results=null for 2+ ids) — the documented
        # way to query more than one series is a POST with a JSON "seriesid" array.
        url = self._config.url("timeseries", DEFAULT_BASE_URL)
        body: dict[str, Any] = {
            "seriesid": series_ids,
            "startyear": str(params.date_range.start.year),
            "endyear": str(params.date_range.end.year),
            **self._config.params,
        }
        if self._config.api_key:
            body["registrationkey"] = self._config.api_key
        payload = self._post_json(url, body)
        if payload.get("status") != "REQUEST_SUCCEEDED":
            message = "; ".join(payload.get("message") or []) or "unknown error"
            raise SourceUnavailableError(f"bls_api: {message}")
        return self._parse(payload, series, params)

    @staticmethod
    def _parse(
        payload: dict[str, Any],
        series: dict[str, dict[str, str]],
        params: FetchParams,
    ) -> list[dict[str, Any]]:
        by_series_id = {meta["series_id"]: (code, meta) for code, meta in series.items()}
        out: list[dict[str, Any]] = []
        for result in payload.get("Results", {}).get("series", []):
            match = by_series_id.get(result.get("seriesID"))
            if match is None:
                continue
            code, meta = match
            # BLS returns newest-first; reverse so "previous" walks forward in time.
            observations = list(reversed(result.get("data", [])))
            previous: str | None = None
            for obs in observations:
                month = _PERIOD_MONTH.get(obs.get("period", ""))
                if month is None:
                    continue  # skip annual/quarterly rows for series reported monthly
                day = datetime.date(int(obs["year"]), month, 1)
                if not params.date_range.contains(day):
                    previous = obs.get("value") or previous
                    continue
                out.append(
                    {
                        "release_code": code,
                        "release_name": meta["release_name"],
                        "date": day.isoformat(),
                        "period": obs.get("periodName", ""),
                        "actual": obs.get("value"),
                        "previous": previous,
                        "unit": meta.get("unit", ""),
                        "agency": meta.get("agency", ""),
                        "id": f"{result.get('seriesID')}:{obs.get('year')}{obs.get('period')}",
                    }
                )
                previous = obs.get("value") or previous
        return out
