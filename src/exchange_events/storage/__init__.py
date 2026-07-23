"""Persistence layer (design doc §4.3, §5).

The only package that touches a database. SQLite is always available; Postgres
classes import ``psycopg`` lazily, so importing this package never requires it.
"""

from __future__ import annotations

from .alert_log import SqliteAlertLog
from .sql_repository import content_hash
from .sqlite_repository import SqliteEventRepository

__all__ = ["SqliteEventRepository", "SqliteAlertLog", "content_hash"]


def __getattr__(name: str) -> object:
    # Lazy access to the Postgres classes so psycopg stays an optional dependency.
    if name == "PostgresEventRepository":
        from .postgres_repository import PostgresEventRepository

        return PostgresEventRepository
    if name == "PostgresAlertLog":
        from .alert_log import PostgresAlertLog

        return PostgresAlertLog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
