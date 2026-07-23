"""Dashboard notification channel (design doc §4.5, §5.5 — dev/local convenience).

INFO-severity alerts route here by default (§5.5's routing example). Alerts are
already durably recorded by ``AlertLog`` regardless of channel (the API's
``GET /api/v1/alerts`` reads from there — §5.6), so this channel's only job is
to be a lightweight, always-available "delivery" target: it logs the alert and
keeps an in-memory record of what passed through it, for local dev/debugging and
tests. It never fails (no external dependency), so it's a safe default recipient
for every severity.
"""

from __future__ import annotations

from ..contracts.logger import Logger
from ..contracts.notification_channel import (
    DeliveryResult,
    DeliveryStatus,
    NotificationChannel,
    Recipient,
)
from ..domain.alerts import Alert
from ..infra.logging import NullLogger


class DashboardChannel(NotificationChannel):
    def __init__(self, logger: Logger | None = None) -> None:
        self._logger = logger or NullLogger()
        self.delivered: list[tuple[Alert, list[Recipient]]] = []

    def channel_name(self) -> str:
        return "dashboard"

    def send(self, alert: Alert, recipients: list[Recipient]) -> list[DeliveryResult]:
        self.delivered.append((alert, list(recipients)))
        self._logger.info(
            "dashboard alert", alert_id=alert.alert_id, title=alert.title,
            severity=str(alert.severity),
        )
        return [
            DeliveryResult(
                channel=self.channel_name(), alert_id=alert.alert_id,
                recipient_id=r.id, status=DeliveryStatus.SUCCESS,
            )
            for r in recipients
        ]
