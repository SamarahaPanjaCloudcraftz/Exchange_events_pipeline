"""Shared fixtures for repository/alert-log integration tests.

Each repository fixture is parametrized over the fake reference, SQLite, and
(when ``EXCHANGE_EVENTS_PG_DSN`` is set) Postgres — so the identical assertion
suite proves all three behave the same.
"""

from __future__ import annotations

import datetime
import os

import pytest

from exchange_events.storage.alert_log import SqliteAlertLog
from exchange_events.storage.sqlite_repository import SqliteEventRepository
from tests.fakes.clock import FakeClock
from tests.fakes.repository import FakeEventRepository

T0 = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
_PG_DSN = os.environ.get("EXCHANGE_EVENTS_PG_DSN")


def _truncate(repo, table: str) -> None:
    cur = repo._conn.cursor()
    cur.execute(f"DELETE FROM {table}")
    repo._conn.commit()
    cur.close()


@pytest.fixture(params=["fake", "sqlite", "postgres"])
def repo(request):
    """Yield ``(repository, clock)`` for each backend."""
    clock = FakeClock(T0)
    if request.param == "fake":
        yield FakeEventRepository(clock=clock), clock
        return
    if request.param == "sqlite":
        r = SqliteEventRepository(":memory:", clock=clock)
        yield r, clock
        r.close()
        return
    if not _PG_DSN:
        pytest.skip("EXCHANGE_EVENTS_PG_DSN not set")
    from exchange_events.storage.postgres_repository import PostgresEventRepository

    r = PostgresEventRepository(_PG_DSN, clock=clock)
    _truncate(r, "events")
    yield r, clock
    r.close()


@pytest.fixture(params=["sqlite", "postgres"])
def alert_log(request):
    clock = FakeClock(T0)
    if request.param == "sqlite":
        log = SqliteAlertLog(":memory:", clock=clock)
        yield log
        log.close()
        return
    if not _PG_DSN:
        pytest.skip("EXCHANGE_EVENTS_PG_DSN not set")
    from exchange_events.storage.alert_log import PostgresAlertLog

    log = PostgresAlertLog(_PG_DSN, clock=clock)
    _truncate(log, "alerts")
    yield log
    log.close()
