"""Regression test for a real concurrency bug found while driving the dashboard
(2026-07-21): Flask's dev server runs threaded by default (`Flask.run()` sets
``threaded=True``), and the SQL repository/alert-log held one shared DB-API
connection with no locking — concurrent requests hitting the same connection
from different threads raised ``sqlite3.InterfaceError: bad parameter or other
API misuse``. Fixed with a ``threading.Lock`` around every connection access in
``BaseSqlEventRepository``/``BaseSqlAlertLog``. This test hammers both with a
thread pool to prove the fix holds, not just that single-threaded usage works.
"""

from __future__ import annotations

import datetime
from concurrent.futures import ThreadPoolExecutor

import pytest

from exchange_events.domain.alerts import Alert, AlertSeverity
from exchange_events.domain.events import HolidayEvent
from exchange_events.domain.query import EventQuery
from exchange_events.storage.alert_log import SqliteAlertLog
from exchange_events.storage.sqlite_repository import SqliteEventRepository

pytestmark = pytest.mark.integration

N_THREADS = 16
N_ROUNDS = 25


def test_repository_survives_concurrent_reads_and_writes():
    repo = SqliteEventRepository(":memory:")
    seed = [
        HolidayEvent(source="nse", exchange="XNSE", date=datetime.date(2026, 1, i + 1),
                     holiday_name=f"H{i}")
        for i in range(5)
    ]
    repo.upsert(seed)

    errors: list[Exception] = []

    def hammer(_i: int) -> None:
        try:
            for _ in range(N_ROUNDS):
                repo.query(EventQuery())
                repo.upsert(seed)  # re-upsert -> exercises the read-then-write path too
                repo.get_by_id(seed[0].event_id)
                repo.get_latest_ingest_time("nse")
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        list(pool.map(hammer, range(N_THREADS)))

    assert errors == [], f"concurrent access raised: {errors}"
    assert len(repo.query(EventQuery())) == 5  # data intact, no corruption
    repo.close()


def test_alert_log_survives_concurrent_reads_and_writes():
    log = SqliteAlertLog(":memory:")
    event = HolidayEvent(source="nse", exchange="XNSE", date=datetime.date(2026, 1, 1),
                          holiday_name="H")
    errors: list[Exception] = []

    def hammer(i: int) -> None:
        try:
            for r in range(N_ROUNDS):
                alert = Alert(
                    rule_id=f"rule-{i}-{r}", event=event, severity=AlertSeverity.INFO,
                    title="t", body="b",
                    triggered_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                )
                log.upsert(alert)
                log.get(alert.alert_id)
                log.recent(limit=10)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        list(pool.map(hammer, range(N_THREADS)))

    assert errors == [], f"concurrent access raised: {errors}"
    log.close()
