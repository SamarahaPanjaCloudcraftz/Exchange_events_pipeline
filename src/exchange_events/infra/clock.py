"""Production clock (implements contracts.Clock)."""

from __future__ import annotations

import datetime

from ..contracts.clock import Clock


class SystemClock(Clock):
    """Real wall-clock time, always timezone-aware UTC."""

    def now_utc(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC)

    def today_utc(self) -> datetime.date:
        return self.now_utc().date()
