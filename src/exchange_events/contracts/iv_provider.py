"""Implied-volatility provider contract (design doc §4.6).

Optional dependency — the system works without it. When present it feeds both the
dashboard (observational overlay) and IV-based alert rules. Rules that need IV skip
gracefully when no provider is wired.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod

from ..domain.iv import IVSnapshot


class IVThresholdProvider(ABC):
    @abstractmethod
    def get_iv_snapshot(
        self, exchange: str, underlying: str, date: datetime.date
    ) -> IVSnapshot | None:
        """IV for an underlying on a date, or None if unavailable."""
        ...

    @abstractmethod
    def get_iv_series(
        self,
        exchange: str,
        underlying: str,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> list[IVSnapshot]:
        """IV time series for overlay display."""
        ...
