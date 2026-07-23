"""Recording NotificationChannel for tests (design doc §9.2)."""

from __future__ import annotations

from exchange_events.contracts.notification_channel import (
    DeliveryResult,
    DeliveryStatus,
    NotificationChannel,
    Recipient,
)
from exchange_events.domain.alerts import Alert
from exchange_events.domain.errors import ChannelUnavailableError


class FakeChannel(NotificationChannel):
    """Records every send; behavior configurable to exercise error isolation.

    * ``unavailable=True`` -> ``send`` raises ``ChannelUnavailableError`` (whole
      channel down).
    * ``fail=True`` -> per-recipient results are ``FAILED`` (delivery failures).
    """

    def __init__(
        self, name: str = "fake", *, fail: bool = False, unavailable: bool = False
    ) -> None:
        self._name = name
        self._fail = fail
        self._unavailable = unavailable
        self.sent: list[tuple[Alert, list[Recipient]]] = []

    def send(self, alert: Alert, recipients: list[Recipient]) -> list[DeliveryResult]:
        if self._unavailable:
            raise ChannelUnavailableError(f"channel {self._name} is down")
        self.sent.append((alert, list(recipients)))
        status = DeliveryStatus.FAILED if self._fail else DeliveryStatus.SUCCESS
        return [
            DeliveryResult(
                channel=self._name,
                alert_id=alert.alert_id,
                recipient_id=r.id,
                status=status,
            )
            for r in recipients
        ]

    def channel_name(self) -> str:
        return self._name
