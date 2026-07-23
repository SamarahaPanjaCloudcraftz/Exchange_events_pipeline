"""Unit tests for the ingestion engine (§5.3, §7) — error isolation, retry,
idempotency, incremental windows, and report accuracy. All fakes, no I/O."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.contracts.normalizer import NormalizationResult
from exchange_events.domain.enums import EventType
from exchange_events.domain.errors import (
    NormalizationError,
    SourceRateLimitError,
    SourceUnavailableError,
)
from exchange_events.domain.events import HolidayEvent
from exchange_events.domain.query import DateRange, EventQuery
from exchange_events.infra.logging import NullLogger
from exchange_events.ingestion.engine import IngestionEngine
from exchange_events.ingestion.normalizer_registry import NormalizerRegistry
from exchange_events.ingestion.retry import RetryPolicy
from tests.fakes.clock import FakeClock
from tests.fakes.normalizer import FakeNormalizer
from tests.fakes.repository import FakeEventRepository
from tests.fakes.source_adapter import FakeSourceAdapter

pytestmark = pytest.mark.unit

T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
RANGE = DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))


def _holiday_record(name: str, day: datetime.date, source: str) -> dict:
    return {"__event__": HolidayEvent(source=source, exchange="XNSE", date=day, holiday_name=name)}


def make_engine(adapters, normalizers, *, repo=None, retry_policy=None, sleep=None, clock=None):
    clock = clock or FakeClock(T0)
    repo = repo if repo is not None else FakeEventRepository(clock=clock)

    engine = IngestionEngine(
        adapters=adapters,
        normalizer_registry=NormalizerRegistry.from_list(normalizers),
        repository=repo,
        clock=clock,
        logger=NullLogger(),
        retry_policy=retry_policy or RetryPolicy(max_retries=2, backoff_base_seconds=0.0),
        sleep=sleep or (lambda _seconds: None),
    )
    return engine, repo, clock


# --- happy path + report accuracy ---------------------------------------------------
def test_run_full_ingest_happy_path_report_accuracy():
    records = [_holiday_record("Republic Day", datetime.date(2026, 1, 26), "src_a")]
    adapter = FakeSourceAdapter("src_a", script=[records])
    normalizer = FakeNormalizer("src_a")
    engine, repo, _ = make_engine([adapter], [normalizer])

    report = engine.run_full_ingest(RANGE)

    assert len(report.results) == 1
    result = report.results[0]
    assert result.source_name == "src_a"
    assert result.fetched == 1
    assert result.normalized == 1
    assert result.normalization_errors == 0
    assert result.upserted_inserted == 1
    assert result.succeeded
    assert report.any_source_failed is False
    assert report.total_upserted == 1
    assert len(repo.query(EventQuery())) == 1  # actually stored


# --- error isolation (§7) ------------------------------------------------------------
def test_one_failing_adapter_does_not_block_others():
    good_records = [_holiday_record("New Year", datetime.date(2026, 1, 1), "good")]
    good = FakeSourceAdapter("good", script=[good_records])
    bad = FakeSourceAdapter("bad", script=[SourceUnavailableError("down")] * 10)
    engine, repo, _ = make_engine(
        [bad, good], [FakeNormalizer("good"), FakeNormalizer("bad")]
    )

    report = engine.run_full_ingest(RANGE)

    bad_result = report.for_source("bad")
    good_result = report.for_source("good")
    assert bad_result is not None and not bad_result.succeeded
    assert "down" in bad_result.error
    assert good_result is not None and good_result.succeeded
    assert good_result.upserted_inserted == 1


def test_missing_normalizer_is_isolated_failure():
    adapter = FakeSourceAdapter("orphan", script=[[{"x": 1}]])
    engine, _, _ = make_engine([adapter], [])  # no normalizer registered
    report = engine.run_full_ingest(RANGE)
    result = report.results[0]
    assert not result.succeeded
    assert "no normalizer registered" in result.error


def test_repository_failure_is_isolated():
    class ExplodingRepo(FakeEventRepository):
        def upsert(self, events):
            raise RuntimeError("db is down")

    adapter = FakeSourceAdapter(
        "src_a", script=[[_holiday_record("H", datetime.date(2026, 1, 1), "src_a")]]
    )
    engine, _, _ = make_engine(
        [adapter], [FakeNormalizer("src_a")], repo=ExplodingRepo(clock=FakeClock(T0))
    )
    report = engine.run_full_ingest(RANGE)
    assert not report.results[0].succeeded
    assert "db is down" in report.results[0].error


# --- retry policy --------------------------------------------------------------------
def test_retryable_exception_retried_then_succeeds():
    records = [_holiday_record("H", datetime.date(2026, 1, 1), "src_a")]
    adapter = FakeSourceAdapter(
        "src_a",
        script=[SourceUnavailableError("blip"), SourceUnavailableError("blip"), records],
    )
    sleeps: list[float] = []
    engine, _, _ = make_engine(
        [adapter], [FakeNormalizer("src_a")],
        retry_policy=RetryPolicy(max_retries=3, backoff_base_seconds=1.0),
        sleep=sleeps.append,
    )
    report = engine.run_full_ingest(RANGE)
    assert report.results[0].succeeded
    assert report.results[0].fetched == 1
    assert len(adapter.calls) == 3
    assert len(sleeps) == 2


def test_retries_exhausted_records_isolated_failure():
    adapter = FakeSourceAdapter("src_a", script=[SourceRateLimitError("limited")] * 10)
    engine, _, _ = make_engine(
        [adapter], [FakeNormalizer("src_a")],
        retry_policy=RetryPolicy(max_retries=2, backoff_base_seconds=0.0),
    )
    report = engine.run_full_ingest(RANGE)
    assert not report.results[0].succeeded
    assert "limited" in report.results[0].error
    assert len(adapter.calls) == 3  # initial + 2 retries


def test_non_retryable_exception_fails_immediately_without_retry():
    adapter = FakeSourceAdapter("src_a", script=[ValueError("boom")] * 5)
    engine, _, _ = make_engine(
        [adapter], [FakeNormalizer("src_a")],
        retry_policy=RetryPolicy(max_retries=3, backoff_base_seconds=0.0),
    )
    report = engine.run_full_ingest(RANGE)
    assert not report.results[0].succeeded
    assert "boom" in report.results[0].error
    assert len(adapter.calls) == 1  # no retry for a non-retryable exception type


# --- idempotency (P6) ----------------------------------------------------------------
def test_reingest_is_idempotent():
    records = [_holiday_record("Republic Day", datetime.date(2026, 1, 26), "src_a")]
    adapter = FakeSourceAdapter("src_a", script=[records])
    engine, repo, _ = make_engine([adapter], [FakeNormalizer("src_a")])

    r1 = engine.run_full_ingest(RANGE)
    r2 = engine.run_full_ingest(RANGE)

    assert r1.results[0].upserted_inserted == 1
    assert r2.results[0].upserted_unchanged == 1
    assert r2.results[0].upserted_inserted == 0


# --- partial normalization pass-through (§5.2 contract) -------------------------------
def test_partial_normalization_errors_still_upsert_good_events():
    good_event = HolidayEvent(source="src_a", exchange="XNSE",
                               date=datetime.date(2026, 1, 1), holiday_name="H")

    def transform(records):
        return NormalizationResult(
            events=[good_event],
            errors=[NormalizationError("bad record", raw_record={"bad": True})],
        )

    adapter = FakeSourceAdapter("src_a", script=[[{"any": 1}]])
    engine, repo, _ = make_engine([adapter], [FakeNormalizer("src_a", transform)])

    report = engine.run_full_ingest(RANGE)
    result = report.results[0]
    assert result.normalized == 1
    assert result.normalization_errors == 1
    assert result.upserted_inserted == 1
    assert result.succeeded  # partial normalization failure is not an adapter failure
    assert report.total_normalization_errors == 1


# --- run_single_source -----------------------------------------------------------------
def test_run_single_source_returns_one_result():
    records = [_holiday_record("H", datetime.date(2026, 1, 1), "src_a")]
    adapter_a = FakeSourceAdapter("src_a", script=[records])
    adapter_b = FakeSourceAdapter("src_b", script=[[]])
    engine, _, _ = make_engine(
        [adapter_a, adapter_b], [FakeNormalizer("src_a"), FakeNormalizer("src_b")]
    )
    report = engine.run_single_source("src_a", RANGE)
    assert len(report.results) == 1
    assert report.results[0].source_name == "src_a"
    assert len(adapter_b.calls) == 0  # other adapter untouched


def test_run_single_source_unknown_raises():
    engine, _, _ = make_engine([], [])
    with pytest.raises(ValueError, match="no adapter registered"):
        engine.run_single_source("nope", RANGE)


# --- incremental fetch window narrowing -----------------------------------------------
def test_incremental_narrows_start_to_last_ingest_date():
    clock = FakeClock(T0)
    repo = FakeEventRepository(clock=clock)
    # Seed a prior ingest so get_latest_ingest_time("src_a") is non-None.
    repo.upsert([HolidayEvent(source="src_a", exchange="XNSE",
                               date=datetime.date(2026, 1, 1), holiday_name="Seed")])
    clock.advance(days=5)  # ingested_at for the seed stays at T0

    adapter = FakeSourceAdapter("src_a", script=[[]])
    engine, _, _ = make_engine([adapter], [FakeNormalizer("src_a")], repo=repo, clock=clock)

    engine.run_full_ingest(RANGE, incremental=True)
    assert adapter.calls[0].date_range.start == datetime.date(2026, 1, 1)  # T0's date


def test_incremental_uses_full_range_when_no_prior_ingest():
    adapter = FakeSourceAdapter("src_a", script=[[]])
    engine, _, _ = make_engine([adapter], [FakeNormalizer("src_a")])
    engine.run_full_ingest(RANGE, incremental=True)
    assert adapter.calls[0].date_range.start == RANGE.start


def test_non_incremental_always_uses_full_range():
    clock = FakeClock(T0)
    repo = FakeEventRepository(clock=clock)
    repo.upsert([HolidayEvent(source="src_a", exchange="XNSE",
                               date=datetime.date(2026, 6, 1), holiday_name="Seed")])
    adapter = FakeSourceAdapter("src_a", script=[[]])
    engine, _, _ = make_engine([adapter], [FakeNormalizer("src_a")], repo=repo, clock=clock)
    engine.run_full_ingest(RANGE, incremental=False)
    assert adapter.calls[0].date_range.start == RANGE.start


# --- adapter receives its own declared event_types/exchanges --------------------------
def test_fetch_params_carry_adapter_declared_scope():
    adapter = FakeSourceAdapter(
        "src_a", script=[[]], event_types=[EventType.EXPIRY], exchanges=["XCME"]
    )
    engine, _, _ = make_engine([adapter], [FakeNormalizer("src_a")])
    engine.run_full_ingest(RANGE)
    assert adapter.calls[0].event_types == [EventType.EXPIRY]
    assert adapter.calls[0].exchanges == ["XCME"]
