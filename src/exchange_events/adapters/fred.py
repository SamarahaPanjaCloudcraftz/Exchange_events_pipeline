"""FRED adapter (design doc §5.1) — tier 1 of the economic-release waterfall.

Uses the FRED ``series/observations`` API (https://api.stlouisfed.org). Each
configured release maps to a FRED series id; observations in the date range become
raw records (with ``previous`` = the prior observation). Requires ``api_key``.

**Waterfall role (see DECISIONS.md "Economic-release waterfall"):** FRED is tier 1
— the primary source for 6 of the 7 required releases (NFP, CPI, PPI, PCE, JOLTS,
FOMC). BLS (tier 2) and BEA (tier 3) are official backstops for the releases they
originally publish; ISM (best-effort) is the only one FRED can't cover at all —
FRED discontinued its ISM series in 2016 over licensing.

``FOMC``'s "actual" is the Federal Funds Target Range - Upper Limit (FRED series
``DFEDTARU``) — the literal outcome of the FOMC's rate decision, not the
market-determined effective rate (``FEDFUNDS``, kept separately below for anyone
who wants the effective-rate series too). The lower bound (``DFEDTARL``) is not
separately modeled here (``EconomicReleaseEvent.actual`` is a single float); a
future enhancement could carry it in ``metadata`` if the range itself matters.

**Forward schedule (§ DECISIONS.md "Release-schedule adapter"):** ``fetch`` also
calls FRED's ``fred/series/release`` (resolve which release a series belongs to)
and ``fred/release/dates`` with ``include_release_dates_with_no_data=true`` — per
FRED's own docs, this returns scheduled dates *even before the data is published*,
i.e. a genuine forward calendar. This is what lets ``EconomicReleaseProximityRule``
fire for real releases instead of only ones that have already happened. Verified
reachable from this sandbox (unlike BLS's own schedule page, which 403s here, and
ISM's, which redirects to a paid member login) — using FRED for this avoids
depending on either. Schedule lookup is best-effort per source (§7): a failure for
one release code is logged and skipped, never blocks the others or the actuals
fetch. Dates already covered by a real observation are never duplicated — the
schedule only fills in dates that don't have one yet.

Emits the raw schema documented in ``normalizers/government_release.py``.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import EventType
from ..domain.errors import SourceUnavailableError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
DEFAULT_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
DEFAULT_SERIES_RELEASE_URL = "https://api.stlouisfed.org/fred/series/release"

# release_code -> FRED series metadata. Overridable via config.options["series"].
# ``skip_schedule`` (default False) opts a code out of the forward-schedule fetch —
# used for FOMC, whose FRED series belongs to a *daily*-updating release (H.15
# Selected Interest Rates), unrelated to specific FOMC meeting dates; scheduling
# FOMC meetings is handled by FOMCScheduleAdapter instead (adapters/fomc.py).
DEFAULT_SERIES: dict[str, dict[str, Any]] = {
    "CPI": {"series_id": "CPIAUCSL", "release_name": "Consumer Price Index",
            "agency": "BLS", "unit": "index"},
    "NFP": {"series_id": "PAYEMS", "release_name": "Total Nonfarm Payrolls",
            "agency": "BLS", "unit": "thousands"},
    "PPI": {"series_id": "PPIACO", "release_name": "Producer Price Index",
            "agency": "BLS", "unit": "index"},
    "PCE": {"series_id": "PCEPI", "release_name": "PCE Price Index",
            "agency": "BEA", "unit": "index"},
    "JOLTS": {"series_id": "JTSJOL", "release_name": "Job Openings: Total Nonfarm",
              "agency": "BLS", "unit": "thousands"},
    "FOMC": {"series_id": "DFEDTARU", "release_name": "Federal Funds Target Range (Upper Limit)",
             "agency": "Federal Reserve", "unit": "%", "skip_schedule": True},
    "UNRATE": {"series_id": "UNRATE", "release_name": "Unemployment Rate",
               "agency": "BLS", "unit": "%"},
    "GDP": {"series_id": "GDP", "release_name": "Gross Domestic Product",
            "agency": "BEA", "unit": "billions"},
    "FEDFUNDS": {"series_id": "FEDFUNDS", "release_name": "Federal Funds Effective Rate",
                 "agency": "Federal Reserve", "unit": "%"},
}


class FREDAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "fred_api"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.ECONOMIC_RELEASE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    @property
    def _series(self) -> dict[str, dict[str, Any]]:
        return self._config.option("series") or DEFAULT_SERIES

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        if not self._config.api_key:
            raise SourceUnavailableError("fred_api: FRED_API_KEY is required")
        base = self._config.url("observations", DEFAULT_BASE_URL)
        fetch_schedule = bool(self._config.option("fetch_schedule", True))
        records: list[dict[str, Any]] = []
        for code, meta in self._series.items():
            query = {
                "series_id": meta["series_id"],
                "api_key": self._config.api_key,
                "file_type": "json",
                "observation_start": params.date_range.start.isoformat(),
                "observation_end": params.date_range.end.isoformat(),
                **self._config.params,
            }
            payload = self._get_json(base, params=query)
            observed = self._parse(payload, code, meta)
            records.extend(observed)
            if fetch_schedule and not meta.get("skip_schedule", False):
                observed_dates = {r["date"] for r in observed}
                for sched in self._fetch_schedule(code, meta, params):
                    if sched["date"] not in observed_dates:
                        records.append(sched)
        return records

    @staticmethod
    def _parse(
        payload: dict[str, Any], code: str, meta: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        previous: str | None = None
        for obs in payload.get("observations", []):
            value = obs.get("value")
            actual = None if value in (None, ".", "") else value
            out.append(
                {
                    "release_code": code,
                    "release_name": meta["release_name"],
                    "date": obs["date"],
                    "actual": actual,
                    "previous": previous,
                    "unit": meta.get("unit", ""),
                    "agency": meta.get("agency", ""),
                    "id": f"{meta['series_id']}:{obs['date']}",
                }
            )
            if actual is not None:
                previous = actual
        return out

    def _fetch_schedule(
        self, code: str, meta: dict[str, Any], params: FetchParams
    ) -> list[dict[str, Any]]:
        """Forward release calendar for one series, including not-yet-published
        dates (see module docstring). Best-effort: any failure is logged and
        skipped rather than raised, so one release code's schedule hiccup never
        blocks the others or the actuals fetch (§7)."""
        try:
            release_id = self._resolve_release_id(meta["series_id"])
            url = self._config.url("release_dates", DEFAULT_RELEASE_DATES_URL)
            query = {
                "release_id": release_id,
                "api_key": self._config.api_key,
                "file_type": "json",
                "realtime_start": params.date_range.start.isoformat(),
                "realtime_end": params.date_range.end.isoformat(),
                "include_release_dates_with_no_data": "true",
            }
            payload = self._get_json(url, params=query)
        except Exception as exc:  # noqa: BLE001 - best-effort per-code schedule lookup
            self._logger.warning(
                "fred_api: schedule lookup failed, continuing with actuals only",
                release_code=code, error=str(exc),
            )
            return []
        return [
            {
                "release_code": code,
                "release_name": meta["release_name"],
                "date": item["date"],
                "actual": None,    # scheduled only — no data published yet
                "previous": None,
                "unit": meta.get("unit", ""),
                "agency": meta.get("agency", ""),
                "id": f"{meta['series_id']}:schedule:{item['date']}",
            }
            for item in payload.get("release_dates", [])
        ]

    def _resolve_release_id(self, series_id: str) -> str:
        url = self._config.url("series_release", DEFAULT_SERIES_RELEASE_URL)
        query = {"series_id": series_id, "api_key": self._config.api_key, "file_type": "json"}
        payload = self._get_json(url, params=query)
        releases = payload.get("releases", [])
        if not releases:
            raise SourceUnavailableError(f"fred_api: no release found for series {series_id}")
        return str(releases[0]["id"])
