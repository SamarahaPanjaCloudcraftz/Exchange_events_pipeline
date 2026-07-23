"""Unit tests for query/fetch value objects (§4.3.1, §4.1)."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.enums import EventType
from exchange_events.domain.query import DateRange, EventQuery, FetchParams

pytestmark = pytest.mark.unit


# --- DateRange ---------------------------------------------------------------------
def test_daterange_contains():
    dr = DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    assert dr.contains(datetime.date(2026, 1, 1))
    assert dr.contains(datetime.date(2026, 1, 15))
    assert dr.contains(datetime.date(2026, 1, 31))
    assert not dr.contains(datetime.date(2025, 12, 31))
    assert not dr.contains(datetime.date(2026, 2, 1))


def test_daterange_single_day_is_valid():
    d = datetime.date(2026, 1, 1)
    dr = DateRange(d, d)
    assert list(dr.days()) == [d]


def test_daterange_days_iterates_inclusive():
    dr = DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 1, 3))
    assert list(dr.days()) == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 1, 2),
        datetime.date(2026, 1, 3),
    ]


def test_daterange_rejects_start_after_end():
    with pytest.raises(ValueError, match="after end"):
        DateRange(datetime.date(2026, 2, 1), datetime.date(2026, 1, 1))


# --- FetchParams -------------------------------------------------------------------
def test_fetchparams_defaults():
    fp = FetchParams(date_range=DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)))
    assert fp.exchanges is None
    assert fp.event_types is None


def test_fetchparams_carries_filters():
    fp = FetchParams(
        date_range=DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)),
        exchanges=["XCME"],
        event_types=[EventType.HOLIDAY, EventType.EXPIRY],
    )
    assert fp.exchanges == ["XCME"]
    assert EventType.HOLIDAY in fp.event_types


# --- EventQuery --------------------------------------------------------------------
def test_eventquery_all_defaults():
    q = EventQuery()
    assert q.event_types is None
    assert q.exchanges is None
    assert q.date_from is None
    assert q.date_to is None
    assert q.release_codes is None
    assert q.include_metadata is False
    assert q.limit is None
    assert q.offset == 0


def test_eventquery_is_mutable_for_incremental_building():
    q = EventQuery()
    q.exchanges = ["XCME"]
    q.limit = 50
    assert q.exchanges == ["XCME"]
    assert q.limit == 50
