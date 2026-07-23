"""Database schema (design doc §5, §4.3).

One schema works for both SQLite and Postgres: all columns are ``TEXT`` and every
statement uses ``IF NOT EXISTS``, so the same DDL initializes either backend.

Storage model: common/queryable fields are real columns (indexed); the full
round-trippable event is stored as JSON in ``data`` (via
``domain.serialization``). ``content_hash`` drives unchanged-detection for
idempotent upsert (P6). Datetimes/dates are ISO strings (UTC), which sort
correctly lexicographically, so date-range filters and MAX() work on TEXT.
"""

from __future__ import annotations

EVENTS_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id     TEXT PRIMARY KEY,
        event_type   TEXT NOT NULL,
        source       TEXT NOT NULL,
        exchange     TEXT,
        event_date   TEXT NOT NULL,
        release_code TEXT,
        ingested_at  TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        data         TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_type_exch_date "
    "ON events (event_type, exchange, event_date)",
    "CREATE INDEX IF NOT EXISTS idx_events_source ON events (source)",
    "CREATE INDEX IF NOT EXISTS idx_events_date ON events (event_date)",
    "CREATE INDEX IF NOT EXISTS idx_events_release_code ON events (release_code)",
]

ALERTS_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id     TEXT PRIMARY KEY,
        rule_id      TEXT NOT NULL,
        event_id     TEXT NOT NULL,
        severity     TEXT NOT NULL,
        title        TEXT NOT NULL,
        body         TEXT NOT NULL,
        triggered_at TEXT NOT NULL,
        event_data   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_alerts_triggered_at ON alerts (triggered_at)",
]
