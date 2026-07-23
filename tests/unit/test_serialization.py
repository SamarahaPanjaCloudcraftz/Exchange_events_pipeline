"""Round-trip fidelity for domain.serialization (all four event subclasses)."""

from __future__ import annotations

import datetime
import json

import pytest

from exchange_events.domain.enums import SessionType
from exchange_events.domain.events import (
    DSTChangeEvent,
    EconomicReleaseEvent,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.domain.serialization import deserialize_event, serialize_event

pytestmark = pytest.mark.unit

UTC = datetime.UTC
DATE = datetime.date(2026, 1, 26)
TS = datetime.datetime(2026, 1, 26, 9, 30, 15, 123456, tzinfo=UTC)
INGESTED = datetime.datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)

CASES = [
    HolidayEvent(
        source="nse", exchange="XNSE", date=DATE, timestamp_utc=TS,
        source_raw_id="NSE/2026/001", ingested_at=INGESTED, updated_at=INGESTED,
        metadata={"circular": "x"}, holiday_name="Republic Day",
        session_type=SessionType.HALF_DAY, affected_segments=["EQ", "FO"],
    ),
    DSTChangeEvent(
        source="iana", date=DATE, ingested_at=INGESTED, updated_at=INGESTED,
        region="US", old_utc_offset="UTC-5", new_utc_offset="UTC-4",
        iana_zone="America/New_York",
    ),
    ExpiryEvent(
        source="cme", exchange="XCME", date=DATE, ingested_at=INGESTED, updated_at=INGESTED,
        instrument_type="futures", underlying="ES", series="quarterly",
        expiry_date=datetime.date(2026, 3, 20), rollover_to=datetime.date(2026, 6, 19),
        is_revised=True,
    ),
    EconomicReleaseEvent(
        source="fred", date=DATE, ingested_at=INGESTED, updated_at=INGESTED,
        release_name="Consumer Price Index", release_code="CPI", agency="BLS",
        period="Dec 2025", forecast=3.1, previous=3.0, actual=3.4, revision=None, unit="%",
        country="US",
    ),
]


@pytest.mark.parametrize("event", CASES, ids=lambda e: type(e).__name__)
def test_round_trip_through_json(event):
    restored = deserialize_event(json.loads(json.dumps(serialize_event(event))))
    assert restored == event


@pytest.mark.parametrize("event", CASES, ids=lambda e: type(e).__name__)
def test_round_trip_preserves_type(event):
    restored = deserialize_event(serialize_event(event))
    assert type(restored) is type(event)


def test_serialize_is_json_safe():
    # No datetime/date objects survive into the serialized dict — all strings.
    data = serialize_event(CASES[0])
    json.dumps(data)  # would raise if any value were non-JSON-safe
    assert isinstance(data["date"], str)
    assert isinstance(data["timestamp_utc"], str)


def test_none_optionals_round_trip():
    ev = ExpiryEvent(
        source="cme", exchange="XCME", date=DATE, instrument_type="options",
        underlying="ES", series="weekly", expiry_date=DATE, rollover_to=None,
    )
    restored = deserialize_event(serialize_event(ev))
    assert restored.rollover_to is None
    assert restored.timestamp_utc is None


def test_economic_release_country_defaults_to_none_and_round_trips():
    ev = EconomicReleaseEvent(
        source="fred", date=DATE, release_name="CPI", release_code="CPI",
    )
    assert ev.country is None
    restored = deserialize_event(serialize_event(ev))
    assert restored.country is None
