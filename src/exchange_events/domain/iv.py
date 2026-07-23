"""Implied-volatility snapshot (design doc §4.6).

A pure domain data type. It lives in ``domain/`` (not with the optional
``IVThresholdProvider`` contract) so that both the contract layer and
:class:`~exchange_events.domain.alerts.AlertContext` can reference it without the
domain ever importing upward into ``contracts/``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class IVSnapshot:
    """Implied volatility for one underlying on one date."""

    exchange: str
    underlying: str
    date: datetime.date
    iv: float                       # implied volatility (e.g. 0.18 for 18%)
    iv_rank: float | None = None    # 0..1 rank within a trailing window, if known
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
