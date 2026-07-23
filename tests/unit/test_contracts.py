"""Unit tests for the contract layer (§4): ABC enforcement + value-type invariants."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.contracts import (
    AlertLog,
    AlertRule,
    Clock,
    DeliveryResult,
    DeliveryStatus,
    EventNormalizer,
    EventRepository,
    HttpClient,
    IVThresholdProvider,
    Logger,
    NormalizationResult,
    NotificationChannel,
    Recipient,
    SourceAdapter,
    UpsertResult,
)
from exchange_events.contracts.http_client import HttpError, Response
from exchange_events.domain.errors import NormalizationError
from exchange_events.domain.events import HolidayEvent

pytestmark = pytest.mark.unit

ALL_ABCS = [
    AlertLog,
    AlertRule,
    Clock,
    EventNormalizer,
    EventRepository,
    HttpClient,
    IVThresholdProvider,
    Logger,
    NotificationChannel,
    SourceAdapter,
]


@pytest.mark.parametrize("abc_cls", ALL_ABCS, ids=[c.__name__ for c in ALL_ABCS])
def test_abc_cannot_be_instantiated(abc_cls):
    with pytest.raises(TypeError):
        abc_cls()  # type: ignore[abstract]


def test_partial_implementation_cannot_be_instantiated():
    class HalfRepo(EventRepository):
        def upsert(self, events):  # missing query/get_by_id/get_latest_ingest_time
            return UpsertResult()

    with pytest.raises(TypeError):
        HalfRepo()  # type: ignore[abstract]


def test_complete_implementation_can_be_instantiated():
    class Tiny(Clock):
        def now_utc(self):
            return datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

        def today_utc(self):
            return datetime.date(2026, 1, 1)

    assert Tiny().today_utc() == datetime.date(2026, 1, 1)


# --- UpsertResult ------------------------------------------------------------------
def test_upsert_result_total_and_defaults():
    assert UpsertResult().total == 0
    r = UpsertResult(inserted=3, updated=2, unchanged=5)
    assert r.total == 10


# --- NormalizationResult -----------------------------------------------------------
def test_normalization_result_counts():
    ev = HolidayEvent(source="s", exchange="XNSE", date=datetime.date(2026, 1, 1), holiday_name="H")
    res = NormalizationResult(events=[ev], errors=[NormalizationError("bad", raw_record={"x": 1})])
    assert res.ok_count == 1
    assert res.error_count == 1


def test_normalization_result_defaults_empty():
    res = NormalizationResult()
    assert res.events == []
    assert res.errors == []


# --- Response / HttpError ----------------------------------------------------------
def test_response_ok_boundaries():
    assert Response(status_code=200, url="u").ok
    assert Response(status_code=299, url="u").ok
    assert not Response(status_code=300, url="u").ok
    assert not Response(status_code=404, url="u").ok


def test_response_text_and_json():
    resp = Response(status_code=200, url="u", content=b'{"a": 1}')
    assert resp.text == '{"a": 1}'
    assert resp.json() == {"a": 1}


def test_response_raise_for_status_ok_is_noop():
    Response(status_code=200, url="u").raise_for_status()  # no raise


def test_response_raise_for_status_raises_httperror():
    with pytest.raises(HttpError) as exc:
        Response(status_code=403, url="https://cme", content=b"denied").raise_for_status()
    assert exc.value.status_code == 403
    assert exc.value.url == "https://cme"


# --- Recipient / DeliveryResult ----------------------------------------------------
def test_recipient_defaults():
    r = Recipient(id="team", address="team@x.com")
    assert r.display_name == ""
    assert r.metadata == {}


def test_delivery_result_succeeded():
    ok = DeliveryResult(
        channel="email", alert_id="a", recipient_id="r", status=DeliveryStatus.SUCCESS
    )
    bad = DeliveryResult(
        channel="email", alert_id="a", recipient_id="r", status=DeliveryStatus.FAILED
    )
    assert ok.succeeded
    assert not bad.succeeded


def test_delivery_status_values():
    assert DeliveryStatus.SUCCESS == "success"
    assert DeliveryStatus.FAILED == "failed"
    assert DeliveryStatus.SKIPPED == "skipped"
