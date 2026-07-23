"""Alert log contract (design doc §5.4, §5.6).

Persistence for the alert engine's "one row per event, escalates over time"
model (post-delivery redesign — see DECISIONS.md "Proximity-based alert
severity"): ``get`` reads the currently stored classification for an
(rule, event) pair so the engine can detect an escalation; ``upsert`` writes
the current classification in place, keyed by the time-stable ``alert_id``.
Also used by the API's ``GET /api/v1/alerts`` feed (``recent``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.alerts import Alert


class AlertLog(ABC):
    @abstractmethod
    def get(self, alert_id: str) -> Alert | None:
        """The currently stored alert for this id, or ``None`` if never seen."""
        ...

    @abstractmethod
    def upsert(self, alert: Alert) -> None:
        """Insert or update the alert record for its ``alert_id`` (idempotent)."""
        ...

    @abstractmethod
    def recent(self, limit: int = 50) -> list[Alert]:
        """Most recently updated alerts, newest first (for the API feed)."""
        ...
