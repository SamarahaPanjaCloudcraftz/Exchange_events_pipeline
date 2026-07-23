"""Small dialect helpers shared by the SQL repositories and alert log.

The repositories are written with ``?`` placeholders; ``adapt`` rewrites them to
``%s`` for Postgres (psycopg). Our SQL never contains a literal ``?`` or ``%``, so
the rewrite is safe.
"""

from __future__ import annotations

from typing import Any, Protocol


class DBAPIConnection(Protocol):
    """Minimal DB-API 2.0 surface used by the storage layer (sqlite3 / psycopg)."""

    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def adapt(sql: str, placeholder: str) -> str:
    """Rewrite ``?`` placeholders to the connection's paramstyle."""
    return sql if placeholder == "?" else sql.replace("?", placeholder)


def exec_ddl(conn: DBAPIConnection, statements: list[str]) -> None:
    """Execute a list of DDL statements and commit (placeholder-free)."""
    cur = conn.cursor()
    try:
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
    finally:
        cur.close()


def placeholders(placeholder: str, count: int) -> str:
    """Return ``?,?,?`` (or ``%s,%s,%s``) for an IN clause of ``count`` items."""
    return ",".join([placeholder] * count)
