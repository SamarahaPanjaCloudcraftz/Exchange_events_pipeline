"""Canonical enumerations shared across the whole system (design doc §3.3).

`str`-based enums so values serialize transparently to JSON / SQL and compare
equal to their string form (``EventType.HOLIDAY == "holiday"``).
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """The four canonical event categories (design doc §3.3)."""

    HOLIDAY = "holiday"
    DST_CHANGE = "dst_change"
    EXPIRY = "expiry"
    ECONOMIC_RELEASE = "economic_release"


class SessionType(StrEnum):
    """How a trading session is affected by a holiday (design doc §3.2)."""

    FULL_CLOSE = "full_close"
    HALF_DAY = "half_day"
    SPECIAL_SESSION = "special_session"  # e.g. NSE Muhurat trading
