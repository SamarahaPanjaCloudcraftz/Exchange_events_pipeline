"""Integration tests for the event repositories (§4.3).

Runs against the fake reference, SQLite, and Postgres (gated) via the ``repo``
fixture, so all three are held to identical contract semantics.
"""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.enums import EventType, SessionType
from exchange_events.domain.events import (
    EconomicReleaseEvent,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.domain.query import EventQuery

pytestmark = pytest.mark.integration

UTC = datetime.UTC


def _holiday(name, day, exchange="XNSE", **kw):
    return HolidayEvent(source="nse", exchange=exchange, date=day, holiday_name=name, **kw)


# --- idempotent upsert (P6) --------------------------------------------------------
def test_insert_then_unchanged_then_updated(repo):
    r, clock = repo
    ev = _holiday("Republic Day", datetime.date(2026, 1, 26))

    res1 = r.upsert([ev])
    assert (res1.inserted, res1.updated, res1.unchanged) == (1, 0, 0)

    res2 = r.upsert([ev])
    assert (res2.inserted, res2.updated, res2.unchanged) == (0, 0, 1)

    clock.advance(hours=1)
    changed = _holiday("Republic Day", datetime.date(2026, 1, 26), affected_segments=["EQ"])
    res3 = r.upsert([changed])
    assert (res3.inserted, res3.updated, res3.unchanged) == (0, 1, 0)


def test_reingest_is_idempotent_no_duplicates(repo):
    r, _ = repo
    events = [
        _holiday("A", datetime.date(2026, 1, 1)),
        _holiday("B", datetime.date(2026, 2, 1)),
    ]
    r.upsert(events)
    r.upsert(events)
    r.upsert(events)
    assert len(r.query(EventQuery())) == 2


def test_ingested_at_stable_updated_at_bumps(repo):
    r, clock = repo
    ev = _holiday("Holi", datetime.date(2026, 3, 14))
    r.upsert([ev])
    first = r.get_by_id(ev.event_id)
    assert first.ingested_at == datetime.datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert first.updated_at == first.ingested_at

    clock.advance(days=1)
    r.upsert([_holiday("Holi", datetime.date(2026, 3, 14), affected_segments=["EQ"])])
    second = r.get_by_id(ev.event_id)
    assert second.ingested_at == first.ingested_at
    assert second.updated_at == datetime.datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


# --- round-trip fidelity through storage -------------------------------------------
def test_round_trip_all_subclasses(repo):
    r, _ = repo
    holiday = HolidayEvent(
        source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
        holiday_name="Republic Day", session_type=SessionType.HALF_DAY,
        affected_segments=["EQ", "FO"], metadata={"circular": "NSE/2026/001"},
        timestamp_utc=datetime.datetime(2026, 1, 26, 3, 45, tzinfo=UTC),
    )
    expiry = ExpiryEvent(
        source="cme", exchange="XCME", date=datetime.date(2026, 3, 20),
        instrument_type="futures", underlying="ES", series="quarterly",
        expiry_date=datetime.date(2026, 3, 20), rollover_to=datetime.date(2026, 6, 19),
        is_revised=True,
    )
    release = EconomicReleaseEvent(
        source="fred", date=datetime.date(2026, 1, 13), release_name="CPI",
        release_code="CPI", agency="BLS", period="Dec 2025", forecast=3.1,
        previous=3.0, actual=3.4, unit="%",
    )
    r.upsert([holiday, expiry, release])

    got_holiday = r.get_by_id(holiday.event_id)
    assert got_holiday.holiday_name == "Republic Day"
    assert got_holiday.session_type == SessionType.HALF_DAY
    assert got_holiday.affected_segments == ["EQ", "FO"]
    assert got_holiday.timestamp_utc == datetime.datetime(2026, 1, 26, 3, 45, tzinfo=UTC)
    assert got_holiday.metadata == {"circular": "NSE/2026/001"}

    got_expiry = r.get_by_id(expiry.event_id)
    assert got_expiry.underlying == "ES"
    assert got_expiry.rollover_to == datetime.date(2026, 6, 19)
    assert got_expiry.is_revised is True

    got_release = r.get_by_id(release.event_id)
    assert got_release.release_code == "CPI"
    assert got_release.actual == 3.4
    assert got_release.surprise == pytest.approx(0.3)


def test_get_by_id_missing_returns_none(repo):
    r, _ = repo
    assert r.get_by_id("does-not-exist") is None


# --- query filters -----------------------------------------------------------------
def _seed(r):
    r.upsert([
        _holiday("New Year", datetime.date(2026, 1, 1), exchange="XCME"),
        _holiday("Republic Day", datetime.date(2026, 1, 26), exchange="XNSE"),
        ExpiryEvent(
            source="nse", exchange="XNSE", date=datetime.date(2026, 1, 29),
            instrument_type="options", underlying="NIFTY", series="weekly",
            expiry_date=datetime.date(2026, 1, 29),
        ),
        EconomicReleaseEvent(
            source="fred", date=datetime.date(2026, 1, 9), release_name="NFP",
            release_code="NFP",
        ),
        EconomicReleaseEvent(
            source="fred", date=datetime.date(2026, 1, 13), release_name="CPI",
            release_code="CPI",
        ),
    ])


def test_query_orders_by_date_ascending(repo):
    r, _ = repo
    _seed(r)
    dates = [e.date for e in r.query(EventQuery())]
    assert dates == sorted(dates)


def test_query_by_event_type(repo):
    r, _ = repo
    _seed(r)
    result = r.query(EventQuery(event_types=[EventType.EXPIRY]))
    assert len(result) == 1
    assert result[0].event_type == EventType.EXPIRY


def test_query_by_exchange(repo):
    r, _ = repo
    _seed(r)
    result = r.query(EventQuery(exchanges=["XCME"]))
    assert all(e.exchange == "XCME" for e in result)
    assert len(result) == 1


def test_query_by_date_window(repo):
    r, _ = repo
    _seed(r)
    result = r.query(EventQuery(
        date_from=datetime.date(2026, 1, 10), date_to=datetime.date(2026, 1, 28)
    ))
    assert [e.date for e in result] == [
        datetime.date(2026, 1, 13),
        datetime.date(2026, 1, 26),
    ]


def test_query_by_release_codes_excludes_non_releases(repo):
    r, _ = repo
    _seed(r)
    result = r.query(EventQuery(release_codes=["CPI"]))
    assert len(result) == 1
    assert isinstance(result[0], EconomicReleaseEvent)
    assert result[0].release_code == "CPI"


def test_query_limit_and_offset(repo):
    r, _ = repo
    r.upsert([_holiday(f"H{i}", datetime.date(2026, 1, i + 1)) for i in range(5)])
    page = r.query(EventQuery(limit=2, offset=1))
    assert [e.date.day for e in page] == [2, 3]


def test_query_offset_without_limit(repo):
    r, _ = repo
    r.upsert([_holiday(f"H{i}", datetime.date(2026, 1, i + 1)) for i in range(4)])
    page = r.query(EventQuery(offset=2))
    assert [e.date.day for e in page] == [3, 4]


def test_query_metadata_stripped_unless_requested(repo):
    r, _ = repo
    r.upsert([_holiday(
        "Republic Day", datetime.date(2026, 1, 26), metadata={"circular": "NSE/2026/001"}
    )])
    assert r.query(EventQuery())[0].metadata == {}
    with_meta = r.query(EventQuery(include_metadata=True))[0]
    assert with_meta.metadata == {"circular": "NSE/2026/001"}


# --- get_latest_ingest_time --------------------------------------------------------
def test_get_latest_ingest_time_per_source(repo):
    r, clock = repo
    r.upsert([_holiday("A", datetime.date(2026, 1, 1))])  # source=nse @ T0
    clock.advance(days=2)
    r.upsert([ExpiryEvent(
        source="cme", exchange="XCME", date=datetime.date(2026, 1, 16),
        instrument_type="futures", underlying="ES", series="monthly",
        expiry_date=datetime.date(2026, 1, 16),
    )])
    assert r.get_latest_ingest_time("nse") == datetime.datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert r.get_latest_ingest_time("cme") == datetime.datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
    assert r.get_latest_ingest_time("unknown") is None
