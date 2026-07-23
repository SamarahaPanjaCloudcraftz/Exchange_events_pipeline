"""Unit tests for Alert / AlertContext (§4.4)."""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from exchange_events.domain.alerts import Alert, AlertContext, AlertSeverity
from exchange_events.domain.events import HolidayEvent
from exchange_events.domain.ids import make_alert_id

pytestmark = pytest.mark.unit

UTC = datetime.UTC
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
DATE = datetime.date(2026, 1, 26)


def make_event() -> HolidayEvent:
    return HolidayEvent(source="nse", exchange="XNSE", date=DATE, holiday_name="Republic Day")


def make_alert(**overrides) -> Alert:
    kwargs = dict(
        rule_id="expiry_day",
        event=make_event(),
        severity=AlertSeverity.WARNING,
        title="t",
        body="b",
        triggered_at=datetime.datetime(2026, 1, 25, 12, 0, tzinfo=UTC),
    )
    kwargs.update(overrides)
    return Alert(**kwargs)


def test_alert_id_auto_derived():
    a = make_alert()
    expected = make_alert_id(rule_id="expiry_day", event_id=make_event().event_id)
    assert a.alert_id == expected


def test_alert_id_stable_regardless_of_triggered_at():
    """No time component in alert_id at all (post-delivery redesign, see
    DECISIONS.md "Proximity-based alert severity") -- the same (rule, event)
    pair always maps to the same id, on any day, at any time, so AlertLog can
    upsert a single row in place as severity escalates."""
    a1 = make_alert(triggered_at=datetime.datetime(2026, 1, 25, 6, 0, tzinfo=UTC))
    a2 = make_alert(triggered_at=datetime.datetime(2026, 6, 30, 22, 0, tzinfo=UTC))
    assert a1.alert_id == a2.alert_id


def test_alert_is_frozen():
    a = make_alert()
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.title = "x"  # type: ignore[misc]


def test_naive_triggered_at_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_alert(triggered_at=datetime.datetime(2026, 1, 25, 12, 0))


def test_triggered_at_normalized_to_utc():
    # 01:00 IST on the 26th is 19:30 UTC on the 25th.
    a = make_alert(triggered_at=datetime.datetime(2026, 1, 26, 1, 0, tzinfo=IST))
    assert a.triggered_at.tzinfo == UTC
    assert a.triggered_at == datetime.datetime(2026, 1, 25, 19, 30, tzinfo=UTC)


# --- AlertContext ------------------------------------------------------------------
def test_context_today_defaults_to_now_date():
    ctx = AlertContext(now_utc=datetime.datetime(2026, 8, 6, 12, 0, tzinfo=UTC))
    assert ctx.today_utc == datetime.date(2026, 8, 6)


def test_context_naive_now_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        AlertContext(now_utc=datetime.datetime(2026, 8, 6, 12, 0))


def test_context_now_normalized_to_utc_shifts_today():
    # 02:00 IST on the 7th is 20:30 UTC on the 6th.
    ctx = AlertContext(now_utc=datetime.datetime(2026, 8, 7, 2, 0, tzinfo=IST))
    assert ctx.today_utc == datetime.date(2026, 8, 6)


def test_context_defaults_empty_fired_ids_and_iv():
    ctx = AlertContext(now_utc=datetime.datetime(2026, 8, 6, 12, 0, tzinfo=UTC))
    assert ctx.already_fired_ids == frozenset()
    assert ctx.iv_snapshots == {}
