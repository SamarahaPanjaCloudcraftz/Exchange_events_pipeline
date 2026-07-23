"""Flask blueprints (design doc §5.6) — one module per endpoint group."""

from __future__ import annotations

from . import alerts, calendar, events, ingest, iv

__all__ = ["events", "alerts", "iv", "calendar", "ingest"]
