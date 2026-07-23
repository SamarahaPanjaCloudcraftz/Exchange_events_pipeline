"""Event repository contract + upsert result (design doc §4.3).

The only component that touches the database. Supports idempotent upsert (P6) and
querying (for the API/dashboard). Matching is by ``event_id``.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..domain.events import Event
from ..domain.query import EventQuery


@dataclass(frozen=True)
class UpsertResult:
    """Per-batch upsert counts (§4.3)."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


class EventRepository(ABC):
    @abstractmethod
    def upsert(self, events: list[Event]) -> UpsertResult:
        """Insert or update events, matched by ``event_id``. Idempotent (P6)."""
        ...

    @abstractmethod
    def query(self, filters: EventQuery) -> list[Event]:
        """Return events matching all filters, ordered by date ascending (§4.3.1)."""
        ...

    @abstractmethod
    def get_by_id(self, event_id: str) -> Event | None:
        """Return a single event by its canonical id, or None."""
        ...

    @abstractmethod
    def get_latest_ingest_time(self, source: str) -> datetime.datetime | None:
        """Most recent ``ingested_at`` for a source (drives incremental windows)."""
        ...
