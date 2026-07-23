"""SQL-backed AlertLog (design doc §5.4).

Kept in ``storage/`` alongside the event repositories (all SQL persistence in one
package) rather than ``alerting/`` — this avoids a concrete-to-concrete import from
``alerting/`` into ``storage/``. (Recorded in DECISIONS.md.) The ``alerting/``
package holds pure logic (engine, dispatcher, rules).

**Thread safety:** see the matching note in ``sql_repository.py`` — the shared
connection is not safe for concurrent multi-threaded access, so every method
here acquires ``self._lock``.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from ..contracts.alert_log import AlertLog
from ..contracts.clock import Clock
from ..contracts.logger import Logger
from ..domain.alerts import Alert, AlertSeverity
from ..domain.errors import RepositoryError
from ..domain.serialization import deserialize_event, dt_from_iso, dt_to_iso, serialize_event
from ..infra.clock import SystemClock
from ..infra.logging import NullLogger
from ._sql import DBAPIConnection, adapt, exec_ddl
from .schema import ALERTS_STATEMENTS


class BaseSqlAlertLog(AlertLog):
    _ph: str = "?"

    def __init__(self, conn: DBAPIConnection, clock: Clock, logger: Logger) -> None:
        self._conn = conn
        self._clock = clock
        self._logger = logger
        self._lock = threading.Lock()
        exec_ddl(conn, ALERTS_STATEMENTS)

    def _adapt(self, sql: str) -> str:
        return adapt(sql, self._ph)

    def close(self) -> None:
        self._conn.close()

    def get(self, alert_id: str) -> Alert | None:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    self._adapt(
                        "SELECT rule_id, severity, title, body, triggered_at, event_data, "
                        "alert_id FROM alerts WHERE alert_id = ?"
                    ),
                    (alert_id,),
                )
                row = cur.fetchone()
            finally:
                cur.close()
        return self._row_to_alert(row) if row is not None else None

    def upsert(self, alert: Alert) -> None:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    self._adapt(
                        "INSERT INTO alerts (alert_id, rule_id, event_id, severity, title, "
                        "body, triggered_at, event_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (alert_id) DO UPDATE SET "
                        "severity = excluded.severity, title = excluded.title, "
                        "body = excluded.body, triggered_at = excluded.triggered_at, "
                        "event_data = excluded.event_data"
                    ),
                    (
                        alert.alert_id,
                        alert.rule_id,
                        alert.event.event_id,
                        str(alert.severity),
                        alert.title,
                        alert.body,
                        dt_to_iso(alert.triggered_at),
                        json.dumps(serialize_event(alert.event)),
                    ),
                )
                self._conn.commit()
            except Exception as exc:  # noqa: BLE001
                self._conn.rollback()
                raise RepositoryError(f"alert upsert failed: {exc}") from exc
            finally:
                cur.close()

    def recent(self, limit: int = 50) -> list[Alert]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    self._adapt(
                        "SELECT rule_id, severity, title, body, triggered_at, event_data, "
                        "alert_id FROM alerts ORDER BY triggered_at DESC LIMIT ?"
                    ),
                    (limit,),
                )
                rows = cur.fetchall()
            finally:
                cur.close()
        return [self._row_to_alert(r) for r in rows]

    @staticmethod
    def _row_to_alert(row: Any) -> Alert:
        triggered = dt_from_iso(row["triggered_at"])
        assert triggered is not None
        return Alert(
            alert_id=row["alert_id"],
            rule_id=row["rule_id"],
            event=deserialize_event(json.loads(row["event_data"])),
            severity=AlertSeverity(row["severity"]),
            title=row["title"],
            body=row["body"],
            triggered_at=triggered,
        )


class SqliteAlertLog(BaseSqlAlertLog):
    _ph = "?"

    def __init__(
        self, path: str = ":memory:", *, clock: Clock | None = None, logger: Logger | None = None
    ) -> None:
        import sqlite3

        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        super().__init__(conn, clock or SystemClock(), logger or NullLogger())


class PostgresAlertLog(BaseSqlAlertLog):
    _ph = "%s"

    def __init__(
        self, dsn: str, *, clock: Clock | None = None, logger: Logger | None = None
    ) -> None:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        super().__init__(conn, clock or SystemClock(), logger or NullLogger())
