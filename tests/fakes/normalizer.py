"""Configurable in-memory EventNormalizer for engine/ingestion tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from exchange_events.contracts.normalizer import EventNormalizer, NormalizationResult


class FakeNormalizer(EventNormalizer):
    def __init__(
        self,
        source: str,
        transform: Callable[[list[dict[str, Any]]], NormalizationResult] | None = None,
    ) -> None:
        self._source = source
        # Default: treat every raw record's "__event__" key as a pre-built Event.
        self._transform = transform or (
            lambda records: NormalizationResult(events=[r["__event__"] for r in records])
        )

    def normalize(
        self, raw_records: list[dict[str, Any]], source_name: str
    ) -> NormalizationResult:
        return self._transform(raw_records)

    def target_source(self) -> str:
        return self._source
