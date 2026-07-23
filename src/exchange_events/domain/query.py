"""Query and fetch value objects (design doc §4.3.1, §4.1, §5.1)."""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from dataclasses import dataclass

from .enums import EventType


@dataclass(frozen=True)
class DateRange:
    """An inclusive [start, end] calendar-date range."""

    start: datetime.date
    end: datetime.date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"DateRange start {self.start} is after end {self.end}")

    def contains(self, day: datetime.date) -> bool:
        return self.start <= day <= self.end

    def days(self) -> Iterator[datetime.date]:
        """Yield each date in the range, inclusive."""
        day = self.start
        while day <= self.end:
            yield day
            day += datetime.timedelta(days=1)


@dataclass(frozen=True)
class FetchParams:
    """Parameters passed to ``SourceAdapter.fetch`` (§4.1)."""

    date_range: DateRange
    exchanges: list[str] | None = None
    event_types: list[EventType] | None = None


@dataclass
class EventQuery:
    """Composite filter passed to ``EventRepository.query`` (§4.3.1).

    All fields optional; ``None`` means "no filter on this dimension". Kept mutable
    so callers (e.g. the API layer) can build it up incrementally.
    """

    event_types: list[EventType] | None = None
    exchanges: list[str] | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    release_codes: list[str] | None = None
    include_metadata: bool = False
    limit: int | None = None
    offset: int = 0
