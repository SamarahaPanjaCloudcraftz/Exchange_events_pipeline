"""Shared base for official-statistics "actuals" normalizers (design doc §5.2).

FRED, BLS, and BEA are all government/Fed-published sources of *realized*
economic data — no forecasts, ever (that's not what these APIs publish; see
DECISIONS.md's "Economic-release waterfall" entry). They therefore share one
raw-record schema and one normalization routine; each source is a thin subclass
declaring only its own ``target_source()`` (same pattern as
``ExchangeCalendarNormalizer`` -> CME/NSE/BSE/KRX).

Raw record schema (produced by FredAdapter / BlsAdapter / BeaAdapter / IsmAdapter):

    {"release_code": "CPI", "release_name": "Consumer Price Index",
     "date": "2026-01-13",              # release/observation date
     "period": "2025-12" (optional),    # period the datum covers
     "actual": 3.4, "previous": 3.0 (optional), "revision": <float> (optional),
     "unit": "%" (optional), "agency": "BLS" (optional), "country": "US" (optional),
     "id": <str> (optional), "metadata": {...} (optional)}

``forecast`` is always ``None`` for these sources — consensus estimates are not
government statistics. (The MarketWatch adapter is the one place forecasts could
come from, and it has its own normalizer with its own, slightly richer schema.)

``country`` defaults to ``"US"`` when the raw record doesn't set it — every
current source (FRED/BLS/BEA/ISM) is exclusively US data; this lets the
dashboard associate a release with the exchanges in that country (e.g. showing
US releases under the CME tab) without needing a new backend query filter.

``timestamp_utc`` is derived from ``STANDARD_RELEASE_TIMES_ET`` (§ util.py) when
the raw record doesn't supply its own ``"time"`` — none of FRED/BLS/BEA's APIs
return an intraday release time, only a date, but every one of the 7 required
releases has a fixed, publicly-published release time.
"""

from __future__ import annotations

from typing import Any

from ..domain.events import EconomicReleaseEvent, Event
from .base import BaseNormalizer
from .util import STANDARD_RELEASE_TIMES_ET, local_time_to_utc, parse_date, parse_float, require

_EASTERN = "America/New_York"


class GovernmentReleaseNormalizer(BaseNormalizer):
    def _normalize_one(self, record: dict[str, Any], source_name: str) -> Event | None:
        day = parse_date(require(record, "date"))
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
            forecast=None,
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
