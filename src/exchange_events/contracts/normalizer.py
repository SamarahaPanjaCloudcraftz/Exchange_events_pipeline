"""Normalizer contract + result type (design doc §4.2, §5.2).

Stateless transformation of raw source dicts into canonical events. One normalizer
per source adapter. Per §5.2 a normalizer never raises on a single bad record — it
transforms what it can and returns the failures alongside, so a partially broken
fetch still yields usable events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import NormalizationError
from ..domain.events import Event


@dataclass(frozen=True)
class NormalizationResult:
    """Outcome of a normalization pass (§5.2)."""

    events: list[Event] = field(default_factory=list)
    errors: list[NormalizationError] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return len(self.events)

    @property
    def error_count(self) -> int:
        return len(self.errors)


class EventNormalizer(ABC):
    @abstractmethod
    def normalize(
        self, raw_records: list[dict[str, Any]], source_name: str
    ) -> NormalizationResult:
        """Transform raw records into canonical events (partial success allowed)."""
        ...

    @abstractmethod
    def target_source(self) -> str:
        """The ``source_name`` whose output this normalizer handles."""
        ...
