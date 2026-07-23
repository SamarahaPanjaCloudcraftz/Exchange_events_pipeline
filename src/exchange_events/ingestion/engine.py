"""Ingestion engine (design doc §5.3) — the orchestrator.

Owns the fetch lifecycle: which adapters to call, with what parameters, retrying
per policy, normalizing, and storing. Contains no source-specific or
normalization logic itself (P2). Adapter failures are isolated (§7) — one
failing adapter never blocks another, and the same is true of a bad normalizer
lookup or a repository failure.

Not a scheduler (§5.3): it's a plain callable. A cron job / APScheduler /
whatever the deployment uses calls ``run_full_ingest()`` on a cadence — that
wrapper is intentionally outside this class so the engine stays testable
without any scheduling infrastructure.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..contracts.clock import Clock
from ..contracts.logger import Logger
from ..contracts.repository import EventRepository
from ..contracts.source_adapter import SourceAdapter
from ..domain.query import DateRange, FetchParams
from .normalizer_registry import NormalizerRegistry
from .report import IngestionReport, SourceIngestResult
from .retry import RetryPolicy


@dataclass
class IngestionEngine:
    adapters: list[SourceAdapter]
    normalizer_registry: NormalizerRegistry
    repository: EventRepository
    clock: Clock
    logger: Logger
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Callable[[float], None] = time.sleep

    def run_full_ingest(
        self, date_range: DateRange, *, incremental: bool = False
    ) -> IngestionReport:
        """Run every registered adapter for the given date range.

        If ``incremental``, each adapter's fetch window start is narrowed to the
        later of ``date_range.start`` and the adapter's last successful ingest
        date (via ``repository.get_latest_ingest_time``) — re-running is still
        safe either way since upsert is idempotent (P6).
        """
        started_at = self.clock.now_utc()
        results = [
            self._run_one(adapter, date_range, incremental=incremental)
            for adapter in self.adapters
        ]
        return IngestionReport(
            results=results, started_at=started_at, finished_at=self.clock.now_utc()
        )

    def run_single_source(
        self, source_name: str, date_range: DateRange, *, incremental: bool = False
    ) -> IngestionReport:
        """Run one named adapter. Useful for retries and debugging (§5.3)."""
        adapter = next((a for a in self.adapters if a.source_name() == source_name), None)
        if adapter is None:
            raise ValueError(f"no adapter registered for source {source_name!r}")
        started_at = self.clock.now_utc()
        result = self._run_one(adapter, date_range, incremental=incremental)
        return IngestionReport(
            results=[result], started_at=started_at, finished_at=self.clock.now_utc()
        )

    # --- internals -------------------------------------------------------------
    def _run_one(
        self, adapter: SourceAdapter, date_range: DateRange, *, incremental: bool
    ) -> SourceIngestResult:
        source_name = adapter.source_name()
        start = self.clock.now_utc()
        result = SourceIngestResult(source_name=source_name)
        try:
            window = self._fetch_window(adapter, date_range, incremental=incremental)
            params = FetchParams(
                date_range=window,
                event_types=adapter.supported_event_types(),
                exchanges=adapter.supported_exchanges(),
            )
            raw_records = self._fetch_with_retry(adapter, params)
            result.fetched = len(raw_records)

            normalizer = self.normalizer_registry.get(source_name)
            if normalizer is None:
                raise LookupError(f"no normalizer registered for source {source_name!r}")

            norm_result = normalizer.normalize(raw_records, source_name)
            result.normalized = norm_result.ok_count
            result.normalization_errors = norm_result.error_count
            for err in norm_result.errors:
                self.logger.warning(
                    "normalization error", source=source_name, reason=err.reason
                )

            upsert_result = self.repository.upsert(norm_result.events)
            result.upserted_inserted = upsert_result.inserted
            result.upserted_updated = upsert_result.updated
            result.upserted_unchanged = upsert_result.unchanged

            self.logger.info(
                "ingest complete",
                source=source_name,
                fetched=result.fetched,
                normalized=result.normalized,
                errors=result.normalization_errors,
                upserted=upsert_result.total,
            )
        except Exception as exc:  # noqa: BLE001 - isolate this adapter's failure (§7)
            result.error = str(exc)
            self.logger.error("ingest failed", source=source_name, error=str(exc))
        finally:
            result.duration_seconds = (self.clock.now_utc() - start).total_seconds()
        return result

    def _fetch_window(
        self, adapter: SourceAdapter, date_range: DateRange, *, incremental: bool
    ) -> DateRange:
        if not incremental:
            return date_range
        latest = self.repository.get_latest_ingest_time(adapter.source_name())
        if latest is None:
            return date_range
        narrowed_start = max(date_range.start, latest.date())
        if narrowed_start > date_range.end:
            narrowed_start = date_range.end
        return DateRange(narrowed_start, date_range.end)

    def _fetch_with_retry(
        self, adapter: SourceAdapter, params: FetchParams
    ) -> list[dict[str, Any]]:
        policy = self.retry_policy
        last_exc: Exception | None = None
        for attempt in range(policy.max_retries + 1):
            try:
                return adapter.fetch(params)
            except policy.retryable_exceptions as exc:
                last_exc = exc
                if attempt < policy.max_retries:
                    self.logger.warning(
                        "retrying source fetch",
                        source=adapter.source_name(),
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    self.sleep(policy.backoff_for(attempt))
                    continue
                raise
        assert last_exc is not None  # pragma: no cover - loop always returns or raises
        raise last_exc
