"""Component contracts (design doc §4) — ABCs only, no implementations.

Everything the wiring layer assembles is expressed here as an abstract interface,
plus the value types those interfaces exchange. Imports only from ``domain/``.
"""

from __future__ import annotations

from .alert_log import AlertLog
from .alert_rule import AlertRule
from .clock import Clock
from .http_client import HttpClient, HttpError, Response
from .iv_provider import IVThresholdProvider
from .logger import Logger
from .normalizer import EventNormalizer, NormalizationResult
from .notification_channel import (
    DeliveryResult,
    DeliveryStatus,
    NotificationChannel,
    Recipient,
)
from .repository import EventRepository, UpsertResult
from .source_adapter import SourceAdapter

__all__ = [
    # infrastructure
    "Clock",
    "Logger",
    "HttpClient",
    "Response",
    "HttpError",
    # pipeline
    "SourceAdapter",
    "EventNormalizer",
    "NormalizationResult",
    "EventRepository",
    "UpsertResult",
    # alerting / notification
    "AlertRule",
    "AlertLog",
    "NotificationChannel",
    "Recipient",
    "DeliveryResult",
    "DeliveryStatus",
    "IVThresholdProvider",
]
