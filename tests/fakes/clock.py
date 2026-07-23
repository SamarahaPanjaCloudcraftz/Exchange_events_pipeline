"""In-memory Clock for tests (design doc §4.7, §9.2)."""

from __future__ import annotations

import datetime

from exchange_events.contracts.clock import Clock

_UTC = datetime.UTC


class FakeClock(Clock):
    """A clock fixed at a chosen instant; advanceable within a test."""

    def __init__(self, fixed_time: datetime.datetime) -> None:
        if fixed_time.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = fixed_time.astimezone(_UTC)

    def now_utc(self) -> datetime.datetime:
        return self._now

    def today_utc(self) -> datetime.date:
        return self._now.date()

    def set(self, when: datetime.datetime) -> None:
        if when.tzinfo is None:
            raise ValueError("FakeClock.set requires a timezone-aware datetime")
        self._now = when.astimezone(_UTC)

    def advance(self, **timedelta_kwargs: float) -> None:
        self._now = self._now + datetime.timedelta(**timedelta_kwargs)
