"""Unit tests for the canonical event types (§3.1–3.4)."""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from exchange_events.domain.enums import EventType, SessionType
from exchange_events.domain.events import (
    DSTChangeEvent,
    EconomicReleaseEvent,
    Event,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.domain.ids import make_event_id

pytestmark = pytest.mark.unit

UTC = datetime.UTC
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
DATE = datetime.date(2026, 1, 26)


def make_holiday(**overrides) -> HolidayEvent:
    kwargs = dict(
        source="nse_circular",
        exchange="XNSE",
        date=DATE,
        holiday_name="Republic Day",
        session_type=SessionType.FULL_CLOSE,
        affected_segments=["EQ", "FO"],
    )
    kwargs.update(overrides)
    return HolidayEvent(**kwargs)


# --- event_type defaults -----------------------------------------------------------
def test_subclass_event_type_defaults():
    assert make_holiday().event_type is EventType.HOLIDAY
    assert ExpiryEvent(
        source="nse", exchange="XNSE", date=DATE,
        instrument_type="options", underlying="NIFTY", series="weekly",
        expiry_date=DATE,
    ).event_type is EventType.EXPIRY
    assert EconomicReleaseEvent(
        source="fred", date=DATE, release_name="CPI", release_code="CPI",
    ).event_type is EventType.ECONOMIC_RELEASE
    assert DSTChangeEvent(
        source="iana", date=DATE, region="US", old_utc_offset="UTC-5",
        new_utc_offset="UTC-4", iana_zone="America/New_York",
    ).event_type is EventType.DST_CHANGE


# --- event_id derivation -----------------------------------------------------------
def test_event_id_auto_derived_from_natural_key():
    h = make_holiday()
    expected = make_event_id(
        source="nse_circular", event_type=EventType.HOLIDAY, exchange="XNSE",
        date=DATE, discriminator="Republic Day",
    )
    assert h.event_id == expected


def test_same_natural_key_yields_same_id():
    assert make_holiday().event_id == make_holiday().event_id


def test_different_holiday_name_yields_different_id():
    assert make_holiday().event_id != make_holiday(holiday_name="Holi").event_id


def test_metadata_does_not_affect_event_id():
    assert make_holiday(metadata={"note": "x"}).event_id == make_holiday().event_id


def test_explicit_event_id_is_preserved():
    h = make_holiday(event_id="hand-supplied")
    assert h.event_id == "hand-supplied"


def test_expiry_discriminator_uses_underlying_and_series():
    e = ExpiryEvent(
        source="nse", exchange="XNSE", date=DATE, instrument_type="options",
        underlying="NIFTY", series="weekly", expiry_date=DATE,
    )
    assert e.discriminator() == "NIFTY:weekly"
    e2 = dataclasses.replace(e, series="monthly", event_id="")
    assert e2.event_id != e.event_id


def test_dst_discriminator_is_iana_zone_and_exchange_is_none():
    d = DSTChangeEvent(
        source="iana", date=DATE, region="US", old_utc_offset="UTC-5",
        new_utc_offset="UTC-4", iana_zone="America/New_York",
    )
    assert d.exchange is None
    assert d.discriminator() == "America/New_York"


def test_release_discriminator_is_release_code():
    r = EconomicReleaseEvent(source="fred", date=DATE, release_name="CPI", release_code="CPI")
    assert r.discriminator() == "CPI"


def test_base_event_discriminator_raises():
    with pytest.raises(NotImplementedError):
        Event(source="x", date=DATE, event_type=EventType.HOLIDAY)


# --- immutability ------------------------------------------------------------------
def test_events_are_frozen():
    h = make_holiday()
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.holiday_name = "changed"  # type: ignore[misc]


def test_metadata_default_is_not_shared_between_instances():
    a = make_holiday()
    b = make_holiday()
    a.metadata["k"] = "v"
    assert b.metadata == {}


# --- UTC enforcement (P5) ----------------------------------------------------------
def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_holiday(timestamp_utc=datetime.datetime(2026, 1, 26, 9, 15))


def test_aware_timestamp_normalized_to_utc():
    ist_time = datetime.datetime(2026, 1, 26, 15, 0, tzinfo=IST)  # 09:30 UTC
    h = make_holiday(timestamp_utc=ist_time)
    assert h.timestamp_utc.tzinfo == UTC
    assert h.timestamp_utc == datetime.datetime(2026, 1, 26, 9, 30, tzinfo=UTC)


def test_naive_ingested_at_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_holiday(ingested_at=datetime.datetime(2026, 1, 26, 0, 0))


# --- EconomicReleaseEvent.surprise (§3.2) ------------------------------------------
def _release(**overrides) -> EconomicReleaseEvent:
    kwargs = dict(source="fred", date=DATE, release_name="CPI", release_code="CPI")
    kwargs.update(overrides)
    return EconomicReleaseEvent(**kwargs)


def test_surprise_computed_when_both_present():
    assert _release(actual=3.4, forecast=3.1).surprise == pytest.approx(0.3)


def test_surprise_negative():
    assert _release(actual=2.8, forecast=3.1).surprise == pytest.approx(-0.3)


@pytest.mark.parametrize(
    "actual,forecast",
    [(None, 3.1), (3.4, None), (None, None)],
)
def test_surprise_is_none_when_missing_inputs(actual, forecast):
    assert _release(actual=actual, forecast=forecast).surprise is None


def test_surprise_is_not_a_dataclass_field():
    # It's a computed property, never stored (§3.2).
    field_names = {f.name for f in dataclasses.fields(_release())}
    assert "surprise" not in field_names
