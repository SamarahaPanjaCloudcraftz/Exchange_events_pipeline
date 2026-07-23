"""Configurable in-memory SourceAdapter for engine/ingestion tests.

``script`` is a list of "what to do on the Nth call to fetch()": either a raw
record list (returned as-is) or an ``Exception`` instance (raised). Once the
script is exhausted, the last entry repeats. Every call's params are recorded.
"""

from __future__ import annotations

from typing import Any

from exchange_events.contracts.source_adapter import SourceAdapter
from exchange_events.domain.enums import EventType
from exchange_events.domain.query import FetchParams


class FakeSourceAdapter(SourceAdapter):
    def __init__(
        self,
        name: str,
        script: list[list[dict[str, Any]] | Exception] | None = None,
        *,
        event_types: list[EventType] | None = None,
        exchanges: list[str] | None = None,
    ) -> None:
        self._name = name
        self._script = list(script) if script is not None else [[]]
        self._event_types = event_types or [EventType.HOLIDAY]
        self._exchanges = exchanges
        self.calls: list[FetchParams] = []

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        self.calls.append(params)
        index = min(len(self.calls) - 1, len(self._script) - 1)
        outcome = self._script[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def source_name(self) -> str:
        return self._name

    def supported_event_types(self) -> list[EventType]:
        return self._event_types

    def supported_exchanges(self) -> list[str] | None:
        return self._exchanges
