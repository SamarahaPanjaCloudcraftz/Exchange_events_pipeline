"""Source adapter contract (design doc §4.1).

One adapter per external data source. Adapters fetch *raw* data (list of dicts) —
normalization into canonical events is the normalizer's job (§4.2). An adapter may
serve multiple exchanges/event types if its underlying source does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..domain.enums import EventType
from ..domain.query import FetchParams


class SourceAdapter(ABC):
    @abstractmethod
    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        """Fetch raw event records for the given parameters.

        Returns source-specific raw dicts (no canonical types).

        Raises:
            SourceUnavailableError: source down or unreachable.
            SourceRateLimitError: source rate limit hit.
        """
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Unique source identifier (e.g. 'cme_calendar', 'fred_api')."""
        ...

    @abstractmethod
    def supported_event_types(self) -> list[EventType]:
        """Event types this adapter can produce."""
        ...

    @abstractmethod
    def supported_exchanges(self) -> list[str] | None:
        """Exchanges this adapter covers; None if not exchange-specific (e.g. DST)."""
        ...
