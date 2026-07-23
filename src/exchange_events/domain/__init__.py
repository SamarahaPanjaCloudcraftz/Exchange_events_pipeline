"""Canonical domain model (design doc §3).

Pure data types with no dependencies on any other package. Everything else in the
system imports from here.
"""

from __future__ import annotations

from .alerts import Alert, AlertContext, AlertSeverity
from .enums import EventType, SessionType
from .errors import (
    ChannelUnavailableError,
    ConfigError,
    ExchangeEventsError,
    NormalizationError,
    RepositoryError,
    SourceError,
    SourceRateLimitError,
    SourceUnavailableError,
)
from .events import (
    DSTChangeEvent,
    EconomicReleaseEvent,
    Event,
    ExpiryEvent,
    HolidayEvent,
)
from .ids import make_alert_id, make_event_id
from .iv import IVSnapshot
from .query import DateRange, EventQuery, FetchParams
from .reconciliation import DEFAULT_SOURCE_PRIORITY, reconcile_economic_releases

__all__ = [
    # enums
    "EventType",
    "SessionType",
    "AlertSeverity",
    # events
    "Event",
    "HolidayEvent",
    "DSTChangeEvent",
    "ExpiryEvent",
    "EconomicReleaseEvent",
    # alerts
    "Alert",
    "AlertContext",
    # iv
    "IVSnapshot",
    # query
    "DateRange",
    "EventQuery",
    "FetchParams",
    # reconciliation
    "reconcile_economic_releases",
    "DEFAULT_SOURCE_PRIORITY",
    # ids
    "make_event_id",
    "make_alert_id",
    # errors
    "ExchangeEventsError",
    "SourceError",
    "SourceUnavailableError",
    "SourceRateLimitError",
    "NormalizationError",
    "RepositoryError",
    "ChannelUnavailableError",
    "ConfigError",
]
