"""In-memory AlertLog for tests (design doc §5.4)."""

from __future__ import annotations

from exchange_events.contracts.alert_log import AlertLog
from exchange_events.domain.alerts import Alert


class FakeAlertLog(AlertLog):
    def __init__(self) -> None:
        self._by_id: dict[str, Alert] = {}
        self._order: list[str] = []  # insertion order of first upsert

    def get(self, alert_id: str) -> Alert | None:
        return self._by_id.get(alert_id)

    def upsert(self, alert: Alert) -> None:
        if alert.alert_id not in self._by_id:
            self._order.append(alert.alert_id)
        self._by_id[alert.alert_id] = alert

    def recent(self, limit: int = 50) -> list[Alert]:
        alerts = list(self._by_id.values())
        # Newest first by trigger time; ties broken by most-recently upserted.
        alerts.sort(
            key=lambda a: (a.triggered_at, self._order.index(a.alert_id)),
            reverse=True,
        )
        return alerts[:limit]
