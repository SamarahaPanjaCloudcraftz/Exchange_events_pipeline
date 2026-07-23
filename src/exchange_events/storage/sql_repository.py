"""Dialect-agnostic SQL event repository (design doc §4.3).

Concrete SQLite / Postgres subclasses supply a DB-API connection and their
placeholder style; all logic lives here. Upsert is done per-event inside one
transaction so inserted/updated/unchanged counts are exact and idempotent (P6):

    * no existing row               -> INSERT           (inserted)
    * existing row, same content    -> no write         (unchanged)
    * existing row, changed content -> UPDATE (keep ingested_at, bump updated_at)

**Thread safety:** a single DB-API connection is held for the repository's
lifetime and is not safe for concurrent use from multiple threads — `sqlite3`
in particular raises ``InterfaceError: bad parameter or other API misuse`` if
two threads execute on the same connection at once (``check_same_thread=False``
only disables sqlite3's same-thread *ownership* check; it does not make the
connection safe for concurrent statement execution). Flask's dev server runs
threaded by default (`Flask.run()` sets ``threaded=True``), so every method
here acquires ``self._lock`` around all connection access. Found via a real
concurrency bug when the dashboard's per-exchange tabs started firing several
simultaneous API requests that all hit the same repository.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import threading
from typing import Any

from ..contracts.clock import Clock
from ..contracts.logger import Logger
from ..contracts.repository import EventRepository, UpsertResult
from ..domain.errors import RepositoryError
from ..domain.events import EconomicReleaseEvent, Event
from ..domain.query import EventQuery
from ..domain.serialization import deserialize_event, dt_from_iso, dt_to_iso, serialize_event
from ._sql import DBAPIConnection, adapt, exec_ddl, placeholders
from .schema import EVENTS_STATEMENTS


def content_hash(event: Event) -> str:
    """Stable hash of an event's content, excluding repository-managed timestamps."""
    payload = serialize_event(event)
    payload.pop("ingested_at", None)
    payload.pop("updated_at", None)
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class BaseSqlEventRepository(EventRepository):
    _ph: str = "?"

    def __init__(self, conn: DBAPIConnection, clock: Clock, logger: Logger) -> None:
        self._conn = conn
        self._clock = clock
        self._logger = logger
        self._lock = threading.Lock()
        exec_ddl(conn, EVENTS_STATEMENTS)

    # --- helpers -------------------------------------------------------------------
    def _adapt(self, sql: str) -> str:
        return adapt(sql, self._ph)

    def _limit_offset(self, limit: int | None, offset: int) -> tuple[str, list[Any]]:
        frag = ""
        params: list[Any] = []
        if limit is not None:
            frag += " LIMIT ?"
            params.append(limit)
        if offset:
            frag += " OFFSET ?"
            params.append(offset)
        return frag, params

    def close(self) -> None:
        self._conn.close()

    # --- writes --------------------------------------------------------------------
    def upsert(self, events: list[Event]) -> UpsertResult:
        inserted = updated = unchanged = 0
        now = self._clock.now_utc()
        with self._lock:
            cur = self._conn.cursor()
            try:
                for event in events:
                    digest = content_hash(event)
                    cur.execute(
                        self._adapt(
                            "SELECT content_hash, ingested_at FROM events WHERE event_id = ?"
                        ),
                        (event.event_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        self._write(cur, event, ingested_at=now, updated_at=now, digest=digest,
                                    is_update=False)
                        inserted += 1
                    elif row["content_hash"] == digest:
                        unchanged += 1
                    else:
                        prior_ingested = dt_from_iso(row["ingested_at"])
                        self._write(cur, event, ingested_at=prior_ingested, updated_at=now,
                                    digest=digest, is_update=True)
                        updated += 1
                self._conn.commit()
            except Exception as exc:  # noqa: BLE001 - re-raised as RepositoryError
                self._conn.rollback()
                raise RepositoryError(f"upsert failed: {exc}") from exc
            finally:
                cur.close()
        return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)

    def _write(
        self,
        cur: Any,
        event: Event,
        *,
        ingested_at: datetime.datetime | None,
        updated_at: datetime.datetime | None,
        digest: str,
        is_update: bool,
    ) -> None:
        stored = dataclasses.replace(event, ingested_at=ingested_at, updated_at=updated_at)
        data = json.dumps(serialize_event(stored))
        release_code = stored.release_code if isinstance(stored, EconomicReleaseEvent) else None
        common = (
            str(event.event_type),
            event.source,
            event.exchange,
            event.date.isoformat(),
            release_code,
            dt_to_iso(ingested_at),
            dt_to_iso(updated_at),
            digest,
            data,
        )
        if is_update:
            cur.execute(
                self._adapt(
                    "UPDATE events SET event_type=?, source=?, exchange=?, event_date=?, "
                    "release_code=?, ingested_at=?, updated_at=?, content_hash=?, data=? "
                    "WHERE event_id=?"
                ),
                (*common, event.event_id),
            )
        else:
            cur.execute(
                self._adapt(
                    "INSERT INTO events (event_type, source, exchange, event_date, "
                    "release_code, ingested_at, updated_at, content_hash, data, event_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (*common, event.event_id),
            )

    # --- reads ---------------------------------------------------------------------
    def query(self, filters: EventQuery) -> list[Event]:
        where: list[str] = []
        params: list[Any] = []
        if filters.event_types:
            where.append(f"event_type IN ({placeholders('?', len(filters.event_types))})")
            params.extend(str(t) for t in filters.event_types)
        if filters.exchanges:
            where.append(f"exchange IN ({placeholders('?', len(filters.exchanges))})")
            params.extend(filters.exchanges)
        if filters.date_from is not None:
            where.append("event_date >= ?")
            params.append(filters.date_from.isoformat())
        if filters.date_to is not None:
            where.append("event_date <= ?")
            params.append(filters.date_to.isoformat())
        if filters.release_codes:
            where.append(f"release_code IN ({placeholders('?', len(filters.release_codes))})")
            params.extend(filters.release_codes)

        sql = "SELECT data FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY event_date ASC, event_id ASC"
        frag, page_params = self._limit_offset(filters.limit, filters.offset)
        sql += frag
        params.extend(page_params)

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(self._adapt(sql), tuple(params))
                rows = cur.fetchall()
            finally:
                cur.close()

        events = [deserialize_event(json.loads(r["data"])) for r in rows]
        if not filters.include_metadata:
            events = [dataclasses.replace(e, metadata={}) for e in events]
        return events

    def get_by_id(self, event_id: str) -> Event | None:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    self._adapt("SELECT data FROM events WHERE event_id = ?"), (event_id,)
                )
                row = cur.fetchone()
            finally:
                cur.close()
        if row is None:
            return None
        return deserialize_event(json.loads(row["data"]))

    def get_latest_ingest_time(self, source: str) -> datetime.datetime | None:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    self._adapt(
                        "SELECT MAX(ingested_at) AS latest FROM events WHERE source = ?"
                    ),
                    (source,),
                )
                row = cur.fetchone()
            finally:
                cur.close()
        latest = row["latest"] if row is not None else None
        return dt_from_iso(latest) if latest else None
