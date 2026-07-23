"""Notification dispatcher (design doc §5.5).

Sits between the alert engine and notification channels. Routes each alert to
its matching channels/recipients (per ``RoutingConfig``) and calls
``channel.send()``. Channel failures are isolated (§7) — a down channel is
recorded as failed deliveries and does not block dispatch to other channels.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.logger import Logger
from ..contracts.notification_channel import (
    DeliveryResult,
    DeliveryStatus,
    NotificationChannel,
    Recipient,
)
from ..domain.alerts import Alert
from ..domain.errors import ChannelUnavailableError
from .routing import RoutingConfig


@dataclass
class NotificationDispatcher:
    channels: list[NotificationChannel]
    routing_config: RoutingConfig
    logger: Logger

    def __post_init__(self) -> None:
        self._by_name = {c.channel_name(): c for c in self.channels}

    def dispatch(self, alerts: list[Alert]) -> list[DeliveryResult]:
        results: list[DeliveryResult] = []
        for alert in alerts:
            route = self.routing_config.match(alert)
            if route is None:
                self.logger.warning(
                    "no route matched for alert",
                    alert_id=alert.alert_id, severity=str(alert.severity),
                )
                continue
            recipients = self.routing_config.resolve_recipients(route)
            for channel_name in route.channels:
                results.extend(self._send_via(channel_name, alert, recipients))
        return results

    def _send_via(
        self, channel_name: str, alert: Alert, recipients: list[Recipient]
    ) -> list[DeliveryResult]:
        channel = self._by_name.get(channel_name)
        if channel is None:
            self.logger.error("unknown channel in routing config", channel=channel_name)
            return []
        try:
            return channel.send(alert, recipients)
        except ChannelUnavailableError as exc:
            self.logger.error("channel unavailable", channel=channel_name, error=str(exc))
            return [
                DeliveryResult(
                    channel=channel_name, alert_id=alert.alert_id, recipient_id=r.id,
                    status=DeliveryStatus.FAILED, detail=str(exc),
                )
                for r in recipients
            ]
