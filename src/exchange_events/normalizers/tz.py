"""IANA timezone normalizer (design doc §5.2) — DST-change events.

Raw record schema (from the IANA/zoneinfo adapter):

    {"iana_zone": "America/New_York", "date": "2026-03-08",
     "region": "US" (optional), "old_offset": "UTC-5", "new_offset": "UTC-4",
     "transition": "start"|"end" (optional),
     "timestamp_utc": "2026-03-08T07:00:00+00:00" (optional exact instant),
     "id": <str> (optional), "metadata": {...} (optional)}
"""

from __future__ import annotations

import datetime
from typing import Any

from ..domain.events import DSTChangeEvent, Event
from ..domain.serialization import dt_from_iso
from .base import BaseNormalizer
from .util import parse_date, require


class TimezoneNormalizer(BaseNormalizer):
    def target_source(self) -> str:
        return "iana_tz"

    def _normalize_one(self, record: dict[str, Any], source_name: str) -> Event | None:
        day = parse_date(require(record, "date"))
        ts: datetime.datetime | None = None
        raw_ts = record.get("timestamp_utc")
        if raw_ts:
            ts = dt_from_iso(str(raw_ts))
        metadata = dict(record.get("metadata") or {})
        if record.get("transition"):
            metadata.setdefault("transition", str(record["transition"]))
        return DSTChangeEvent(
            source=source_name,
            exchange=None,
            date=day,
            timestamp_utc=ts,
            region=str(record.get("region") or ""),
            old_utc_offset=str(require(record, "old_offset")),
            new_utc_offset=str(require(record, "new_offset")),
            iana_zone=str(require(record, "iana_zone")),
            source_raw_id=_opt_str(record.get("id")),
            metadata=metadata,
        )


def _opt_str(value: object) -> str | None:
    return None if value in (None, "") else str(value)
