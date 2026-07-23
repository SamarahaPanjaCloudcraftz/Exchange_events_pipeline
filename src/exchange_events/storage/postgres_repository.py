"""Postgres event repository (design doc §5).

Shares all logic with the SQLite repository via :class:`BaseSqlEventRepository`;
only the connection and placeholder style differ. Integration tests run only when
``EXCHANGE_EVENTS_PG_DSN`` is set (no local Postgres in this environment).

``psycopg`` is imported lazily so the rest of the system works without it installed.
"""

from __future__ import annotations

from ..contracts.clock import Clock
from ..contracts.logger import Logger
from ..infra.clock import SystemClock
from ..infra.logging import NullLogger
from .sql_repository import BaseSqlEventRepository


class PostgresEventRepository(BaseSqlEventRepository):
    _ph = "%s"

    def __init__(
        self,
        dsn: str,
        *,
        clock: Clock | None = None,
        logger: Logger | None = None,
    ) -> None:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        super().__init__(conn, clock or SystemClock(), logger or NullLogger())
