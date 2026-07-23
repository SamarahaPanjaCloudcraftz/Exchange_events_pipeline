"""Alert payloads and evaluation context (design doc §4.4).

Design note on ``AlertContext``: the doc's illustrative test passes a ``Clock``
into the context, but ``domain/`` must not import ``contracts/`` (dependencies
point inward). So the context instead carries the *resolved* time values that the
alert engine reads from its injected clock. Rules use ``context.today_utc`` /
``context.now_utc`` — no clock object in the domain. (Recorded in DECISIONS.md.)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import StrEnum

from .events import Event
from .ids import make_alert_id
from .iv import IVSnapshot

_UTC = datetime.UTC


class AlertSeverity(StrEnum):
    """Severity of an alert (§4.4)."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, kw_only=True)
class Alert:
    """A single alert produced by a rule (§4.4).

    ``alert_id`` is auto-derived from ``rule_id`` + ``event_id`` only (no time
    component) unless supplied — stable across repeated evaluations so the same
    (rule, event) pair always maps to the same stored row. ``AlertEngine``
    upserts it in place as the event's classified severity escalates over time,
    rather than creating a new row per pipeline run.
    """

    rule_id: str
    event: Event
    severity: AlertSeverity
    title: str
    body: str
    triggered_at: datetime.datetime  # must be tz-aware; normalized to UTC
    alert_id: str = ""

    def __post_init__(self) -> None:
        if self.triggered_at.tzinfo is None:
            raise ValueError("triggered_at must be timezone-aware (UTC)")
        object.__setattr__(self, "triggered_at", self.triggered_at.astimezone(_UTC))
        if not self.alert_id:
            object.__setattr__(
                self,
                "alert_id",
                make_alert_id(rule_id=self.rule_id, event_id=self.event.event_id),
            )


@dataclass(frozen=True, kw_only=True)
class AlertContext:
    """Contextual data an :class:`AlertRule` may need during evaluation (§4.4).

    ``today_utc`` is always derived from ``now_utc`` (not independently
    settable — there is exactly one source of truth for "now"). ``iv_snapshots``
    is keyed by ``(exchange, underlying)`` and is empty when no IV provider is
    wired.
    """

    now_utc: datetime.datetime
    already_fired_ids: frozenset[str] = frozenset()
    iv_snapshots: dict[tuple[str, str], IVSnapshot] = field(default_factory=dict)
    today_utc: datetime.date = field(init=False, default=datetime.date.min)

    def __post_init__(self) -> None:
        if self.now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware (UTC)")
        object.__setattr__(self, "now_utc", self.now_utc.astimezone(_UTC))
        object.__setattr__(self, "today_utc", self.now_utc.date())
