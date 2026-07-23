"""SQLite event repository (design doc §5, v1 default).

Zero-infrastructure, stdlib-only. Use ``:memory:`` for tests, a file path for a
persistent dev/prod store. Holds a single connection for the life of the object
(required for in-memory databases).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..contracts.clock import Clock
from ..contracts.logger import Logger
from ..infra.clock import SystemClock
from ..infra.logging import NullLogger
from .sql_repository import BaseSqlEventRepository


class SqliteEventRepository(BaseSqlEventRepository):
    _ph = "?"

    def __init__(
        self,
        path: str = ":memory:",
        *,
        clock: Clock | None = None,
        logger: Logger | None = None,
    ) -> None:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        super().__init__(conn, clock or SystemClock(), logger or NullLogger())

    def _limit_offset(self, limit: int | None, offset: int) -> tuple[str, list[Any]]:
        # SQLite needs a LIMIT before OFFSET; use -1 (unbounded) when only offsetting.
        if offset and limit is None:
            return " LIMIT -1 OFFSET ?", [offset]
        return super()._limit_offset(limit, offset)
