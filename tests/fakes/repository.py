"""In-memory EventRepository for tests (design doc §9.2).

This is the *reference semantics* for the repository contract: the real SQLite and
Postgres repositories (Phase 4) are tested to behave identically. Encodes:

* idempotent upsert with inserted/updated/unchanged accounting (P6),
* every ``EventQuery`` filter (§4.3.1),
* ``ingested_at`` set once, ``updated_at`` on every change,
* metadata populated only when ``include_metadata`` is requested,
* results ordered by date ascending (then event_id for stability).
"""

from __future__ import annotations

import dataclasses
import datetime

from exchange_events.contracts.clock import Clock
from exchange_events.contracts.repository import EventRepository, UpsertResult
from exchange_events.domain.events import EconomicReleaseEvent, Event
from exchange_events.domain.query import EventQuery
from exchange_events.infra.clock import SystemClock

_IGNORED_ON_COMPARE = {"ingested_at", "updated_at"}


def _content(event: Event) -> dict:
    return {
        f.name: getattr(event, f.name)
        for f in dataclasses.fields(event)
        if f.name not in _IGNORED_ON_COMPARE
    }


class FakeEventRepository(EventRepository):
    def __init__(self, clock: Clock | None = None) -> None:
        self._events: dict[str, Event] = {}
        self._clock = clock or SystemClock()

    def upsert(self, events: list[Event]) -> UpsertResult:
        inserted = updated = unchanged = 0
        now = self._clock.now_utc()
        for event in events:
            existing = self._events.get(event.event_id)
            if existing is None:
                self._events[event.event_id] = dataclasses.replace(
                    event, ingested_at=now, updated_at=now
                )
                inserted += 1
            elif _content(existing) == _content(event):
                unchanged += 1
            else:
                self._events[event.event_id] = dataclasses.replace(
                    event, ingested_at=existing.ingested_at, updated_at=now
                )
                updated += 1
        return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)

    def query(self, filters: EventQuery) -> list[Event]:
        results = [e for e in self._events.values() if self._matches(e, filters)]
        results.sort(key=lambda e: (e.date, e.event_id))
        if filters.offset:
            results = results[filters.offset :]
        if filters.limit is not None:
            results = results[: filters.limit]
        if not filters.include_metadata:
            results = [dataclasses.replace(e, metadata={}) for e in results]
        return results

    def get_by_id(self, event_id: str) -> Event | None:
        return self._events.get(event_id)

    def get_latest_ingest_time(self, source: str) -> datetime.datetime | None:
        times = [
            e.ingested_at
            for e in self._events.values()
            if e.source == source and e.ingested_at is not None
        ]
        return max(times) if times else None

    @staticmethod
    def _matches(event: Event, f: EventQuery) -> bool:
        if f.event_types is not None and event.event_type not in f.event_types:
            return False
        if f.exchanges is not None and event.exchange not in f.exchanges:
            return False
        if f.date_from is not None and event.date < f.date_from:
            return False
        if f.date_to is not None and event.date > f.date_to:
            return False
        if f.release_codes is not None:
            if not isinstance(event, EconomicReleaseEvent):
                return False
            if event.release_code not in f.release_codes:
                return False
        return True
