"""Ingestion report types (design doc §7 — the system's primary health signal).

Per adapter: records fetched, normalized, upserted, errors encountered, duration.
If an adapter starts returning zero records or high error rates, it shows up here
before it becomes a silent data gap.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass
class SourceIngestResult:
    """Outcome of running one adapter through one ingestion pass."""

    source_name: str
    fetched: int = 0
    normalized: int = 0
    upserted_inserted: int = 0
    upserted_updated: int = 0
    upserted_unchanged: int = 0
    normalization_errors: int = 0
    error: str | None = None  # set only on a whole-adapter failure (fetch/repo)
    duration_seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.error is None

    @property
    def upserted_total(self) -> int:
        return self.upserted_inserted + self.upserted_updated + self.upserted_unchanged


@dataclass
class IngestionReport:
    """Aggregate result of a `run_full_ingest` / `run_single_source` call."""

    results: list[SourceIngestResult] = field(default_factory=list)
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None

    @property
    def total_duration_seconds(self) -> float:
        return sum(r.duration_seconds for r in self.results)

    @property
    def any_source_failed(self) -> bool:
        return any(not r.succeeded for r in self.results)

    @property
    def total_normalization_errors(self) -> int:
        return sum(r.normalization_errors for r in self.results)

    @property
    def total_upserted(self) -> int:
        return sum(r.upserted_total for r in self.results)

    def for_source(self, source_name: str) -> SourceIngestResult | None:
        return next((r for r in self.results if r.source_name == source_name), None)
