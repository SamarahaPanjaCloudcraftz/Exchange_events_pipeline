"""Alert rule contract (design doc §4.4).

Each rule encodes exactly one alerting condition and is a stateless evaluator — it
decides *whether* to alert, never *how* to deliver. Rules receive candidate events
plus an :class:`AlertContext` (resolved time, IV snapshots, already-fired ids).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.alerts import Alert, AlertContext
from ..domain.events import Event


class AlertRule(ABC):
    @abstractmethod
    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        """Return alerts for events that meet this rule's condition (empty if none)."""
        ...

    @abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier (for dedup and audit)."""
        ...
