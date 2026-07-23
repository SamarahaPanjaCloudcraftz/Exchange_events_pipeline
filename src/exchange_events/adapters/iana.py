"""IANA timezone adapter (design doc §5.1) — DST transitions via stdlib zoneinfo.

Fully offline and deterministic: for each configured zone it scans the requested
date range and emits a raw record whenever the UTC offset changes between
consecutive days (a DST transition). No network involved.

Emits the raw schema documented in ``normalizers/tz.py``.
"""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..contracts.logger import Logger
from ..contracts.source_adapter import SourceAdapter
from ..domain.enums import EventType
from ..domain.query import FetchParams
from ..infra.logging import NullLogger
from .config import AdapterConfig

_UTC = datetime.UTC

DEFAULT_ZONES: list[str] = [
    "America/New_York",   # ET — US equity/futures reference
    "America/Chicago",    # CT — CME
    "Europe/London",      # UK
    "Europe/Berlin",      # EU (there is no "Europe/Frankfurt" IANA key)
    "Asia/Kolkata",       # IST (no DST, but included for completeness)
    "Asia/Seoul",         # KST (no DST)
]


def _format_offset(delta: datetime.timedelta | None) -> str:
    total = int((delta or datetime.timedelta()).total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, minutes = divmod(total // 60, 60)
    return f"UTC{sign}{hours}" if minutes == 0 else f"UTC{sign}{hours}:{minutes:02d}"


class IANATimezoneAdapter(SourceAdapter):
    def __init__(
        self,
        config: AdapterConfig | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._config = config or AdapterConfig()
        self._logger = logger or NullLogger()
        zones = self._config.option("zones") or DEFAULT_ZONES
        self._zones: list[str] = list(zones)

    def source_name(self) -> str:
        return "iana_tz"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.DST_CHANGE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for zone_name in self._zones:
            records.extend(self._transitions_for_zone(zone_name, params))
        return records

    def _transitions_for_zone(
        self, zone_name: str, params: FetchParams
    ) -> list[dict[str, Any]]:
        tz = ZoneInfo(zone_name)
        region = zone_name.split("/", 1)[0]
        out: list[dict[str, Any]] = []
        start = params.date_range.start
        prev_offset = self._offset(start - datetime.timedelta(days=1), tz)
        for day in params.date_range.days():
            offset = self._offset(day, tz)
            if offset != prev_offset:
                transition = "start" if (offset or _ZERO) > (prev_offset or _ZERO) else "end"
                out.append(
                    {
                        "iana_zone": zone_name,
                        "date": day.isoformat(),
                        "region": region,
                        "old_offset": _format_offset(prev_offset),
                        "new_offset": _format_offset(offset),
                        "transition": transition,
                    }
                )
            prev_offset = offset
        return out

    @staticmethod
    def _offset(day: datetime.date, tz: ZoneInfo) -> datetime.timedelta | None:
        # Noon avoids the ambiguous/imaginary hour right at the transition.
        return datetime.datetime(day.year, day.month, day.day, 12, tzinfo=tz).utcoffset()


_ZERO = datetime.timedelta()
