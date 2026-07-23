"""Economic-calendar normalizer (design doc §5.2) — MarketWatch upcoming releases.

Raw record schema (from the MarketWatch adapter):

    {"release_code": "NFP", "release_name": "Nonfarm Payrolls",
     "date": "2026-02-06", "time": "08:30" (optional, US/Eastern),
     "period": "Jan" (optional),
     "forecast": 170.0, "previous": 150.0, "actual": null,
     "unit": "thousands" (optional), "agency": "BLS" (optional),
     "id": <str> (optional), "metadata": {...} (optional)}

MarketWatch times are US/Eastern; ``time`` (if present) is converted to a UTC
``timestamp_utc`` (P5), falling back to ``STANDARD_RELEASE_TIMES_ET`` (§ util.py)
if the page omits it for a row. This adapter supplies the forward calendar with
forecast/previous; realized actuals are backfilled from FRED.

``country`` defaults to ``"US"`` — the currently-configured release codes
(§ adapters/econ.py) are all US releases; see the same note in
``normalizers/government_release.py``.
"""

from __future__ import annotations

from typing import Any

from ..domain.events import EconomicReleaseEvent, Event
from .base import BaseNormalizer
from .util import STANDARD_RELEASE_TIMES_ET, local_time_to_utc, parse_date, parse_float, require

_EASTERN = "America/New_York"


class EconCalendarNormalizer(BaseNormalizer):
    # MarketWatch's calendar page has used both "2/6/26" and "2/6/2026" styles.
    date_formats = ("%m/%d/%y", "%m/%d/%Y")

    def target_source(self) -> str:
        return "econ_calendar"

    def _normalize_one(self, record: dict[str, Any], source_name: str) -> Event | None:
        day = parse_date(require(record, "date"), self.date_formats)
        release_code = str(require(record, "release_code"))
        time_str = record.get("time") or STANDARD_RELEASE_TIMES_ET.get(release_code)
        timestamp = local_time_to_utc(day, time_str, _EASTERN)
        return EconomicReleaseEvent(
            source=source_name,
            exchange=None,
            date=day,
            timestamp_utc=timestamp,
            release_name=str(require(record, "release_name")),
            release_code=release_code,
            agency=str(record.get("agency") or ""),
            period=str(record.get("period") or ""),
            forecast=parse_float(record.get("forecast")),
            previous=parse_float(record.get("previous")),
            actual=parse_float(record.get("actual")),
            revision=parse_float(record.get("revision")),
            unit=str(record.get("unit") or ""),
            country=str(record.get("country") or "US"),
            source_raw_id=_opt_str(record.get("id")),
            metadata=dict(record.get("metadata") or {}),
        )


def _opt_str(value: object) -> str | None:
    return None if value in (None, "") else str(value)
