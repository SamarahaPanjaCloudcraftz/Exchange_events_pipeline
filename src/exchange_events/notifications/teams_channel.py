"""Microsoft Teams notification channel (design doc §4.5, user-chosen v1 channel).

Delivers via a Teams **Incoming Webhook** (one URL per channel/team, no
per-recipient addressing) using the injected ``HttpClient`` — no direct network
dependency, so this is unit-testable with ``FakeHttpClient``. Payload is a
MessageCard, the format Teams incoming webhooks expect.

A webhook has no concept of "recipients" — everyone in the Teams channel it
posts to receives it. ``recipients`` is still accepted (to satisfy the
``NotificationChannel`` contract uniformly) and one ``DeliveryResult`` is
returned per named recipient, all sharing the outcome of the single POST.
"""

from __future__ import annotations

from typing import Any

from ..contracts.http_client import HttpClient
from ..contracts.logger import Logger
from ..contracts.notification_channel import (
    DeliveryResult,
    DeliveryStatus,
    NotificationChannel,
    Recipient,
)
from ..domain.alerts import Alert
from ..domain.errors import ChannelUnavailableError
from ..infra.logging import NullLogger
from .labels import event_type_label

_SEVERITY_COLOR = {"info": "0078D4", "warning": "FFB900", "critical": "D13438"}


class TeamsChannel(NotificationChannel):
    def __init__(
        self,
        http_client: HttpClient,
        webhook_url: str,
        logger: Logger | None = None,
    ) -> None:
        self._http = http_client
        self._webhook_url = webhook_url
        self._logger = logger or NullLogger()

    def channel_name(self) -> str:
        return "teams"

    def send(self, alert: Alert, recipients: list[Recipient]) -> list[DeliveryResult]:
        payload = self._build_card(alert)
        try:
            resp = self._http.post(self._webhook_url, json=payload)
        except Exception as exc:  # noqa: BLE001 - the webhook endpoint itself is down
            raise ChannelUnavailableError(f"teams webhook unreachable: {exc}") from exc

        if not resp.ok:
            raise ChannelUnavailableError(
                f"teams webhook returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        status = DeliveryStatus.SUCCESS
        return [
            DeliveryResult(
                channel=self.channel_name(), alert_id=alert.alert_id,
                recipient_id=r.id, status=status,
            )
            for r in recipients
        ]

    def _build_card(self, alert: Alert) -> dict[str, Any]:
        color = _SEVERITY_COLOR.get(str(alert.severity), "0078D4")
        card: dict[str, Any] = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": alert.title,
            "title": alert.title,
        }
        # `rule_id` is internal plumbing (e.g. "economic_release_proximity:2:1") -- not
        # shown, it means nothing to the reader. `body` is optional per-rule supplementary
        # detail (see alerting/rules/*_proximity.py) -- title alone already carries the
        # full "what + when"; omit the section entirely rather than show an empty fact.
        if alert.body:
            card["text"] = alert.body
        card["sections"] = [
            {
                "facts": [
                    {"name": "Type", "value": event_type_label(alert.event.event_type)},
                    {"name": "Severity", "value": str(alert.severity).upper()},
                    {"name": "Updated", "value": alert.triggered_at.strftime("%Y-%m-%d %H:%M UTC")},
                ]
            }
        ]
        return card
