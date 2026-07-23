"""Email notification channel (design doc §4.5, user-chosen v1 channel).

Delivers one email per recipient (so a bad address doesn't affect the others).
SMTP transport is injected (``SmtpTransport``) — this channel never imports
``smtplib`` directly, keeping it fully unit-testable (P3).
"""

from __future__ import annotations

from email.message import EmailMessage

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
from .smtp_transport import SmtpTransport

_SEVERITY_PREFIX = {"info": "[INFO]", "warning": "[WARNING]", "critical": "[CRITICAL]"}


class EmailChannel(NotificationChannel):
    def __init__(
        self,
        transport: SmtpTransport,
        from_address: str,
        logger: Logger | None = None,
    ) -> None:
        self._transport = transport
        self._from_address = from_address
        self._logger = logger or NullLogger()

    def channel_name(self) -> str:
        return "email"

    def send(self, alert: Alert, recipients: list[Recipient]) -> list[DeliveryResult]:
        results = []
        for recipient in recipients:
            message = self._build_message(alert, recipient)
            try:
                self._transport.send(message)
            except ChannelUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001 - per-recipient failure, not fatal
                self._logger.error(
                    "email delivery failed", recipient=recipient.address, error=str(exc)
                )
                results.append(
                    DeliveryResult(
                        channel=self.channel_name(), alert_id=alert.alert_id,
                        recipient_id=recipient.id, status=DeliveryStatus.FAILED,
                        detail=str(exc),
                    )
                )
                continue
            results.append(
                DeliveryResult(
                    channel=self.channel_name(), alert_id=alert.alert_id,
                    recipient_id=recipient.id, status=DeliveryStatus.SUCCESS,
                )
            )
        return results

    def _build_message(self, alert: Alert, recipient: Recipient) -> EmailMessage:
        prefix = _SEVERITY_PREFIX.get(str(alert.severity), "")
        type_tag = f"[{event_type_label(alert.event.event_type)}]"
        message = EmailMessage()
        message["Subject"] = f"{prefix} {type_tag} {alert.title}".strip()
        message["From"] = self._from_address
        message["To"] = recipient.address
        message.set_content(alert.body)
        return message
