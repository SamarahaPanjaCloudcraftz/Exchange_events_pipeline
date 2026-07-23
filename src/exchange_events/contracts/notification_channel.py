"""Notification channel contract + delivery types (design doc §4.5).

One implementation per delivery mechanism (Email, Teams, in-dashboard). A channel
decides only *how* to deliver, never *what* to alert on.

Design note: the doc's ``send`` returns a single ``DeliveryResult``; we return one
per recipient (``list[DeliveryResult]``) so multi-recipient partial failures are
representable. Recorded in DECISIONS.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..domain.alerts import Alert


class DeliveryStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Recipient:
    """A notification target (person, team, or endpoint)."""

    id: str
    address: str  # email address, Teams webhook url, etc. — meaning per channel
    display_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of delivering one alert to one recipient via one channel."""

    channel: str
    alert_id: str
    recipient_id: str
    status: DeliveryStatus
    detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status is DeliveryStatus.SUCCESS


class NotificationChannel(ABC):
    @abstractmethod
    def send(self, alert: Alert, recipients: list[Recipient]) -> list[DeliveryResult]:
        """Deliver an alert to recipients (one result each).

        Raises:
            ChannelUnavailableError: the channel itself is down (vs. a per-recipient
            failure, which is reported as a FAILED DeliveryResult).
        """
        ...

    @abstractmethod
    def channel_name(self) -> str:
        """Channel identifier (e.g. 'email', 'teams')."""
        ...
