"""Integration tests for the SQL AlertLog (§5.4, post-delivery proximity
redesign). SQLite always; Postgres gated."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.alerts import Alert, AlertSeverity
from exchange_events.domain.events import HolidayEvent

pytestmark = pytest.mark.integration

UTC = datetime.UTC

_EVENT = HolidayEvent(
    source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
    holiday_name="Republic Day", metadata={"note": "x"},
)


def _alert(
    rule: str, when: datetime.datetime, severity: AlertSeverity = AlertSeverity.WARNING
) -> Alert:
    return Alert(
        rule_id=rule, event=_EVENT, severity=severity,
        title="Upcoming", body="details", triggered_at=when,
    )


def test_get_returns_none_before_upsert(alert_log):
    a = _alert("r1", datetime.datetime(2026, 1, 25, 12, 0, tzinfo=UTC))
    assert alert_log.get(a.alert_id) is None


def test_get_returns_upserted_alert(alert_log):
    a = _alert("r1", datetime.datetime(2026, 1, 25, 12, 0, tzinfo=UTC))
    alert_log.upsert(a)
    got = alert_log.get(a.alert_id)
    assert got is not None
    assert got.alert_id == a.alert_id


def test_upsert_same_rule_and_event_updates_in_place_not_duplicated(alert_log):
    """Same (rule, event) pair -> same alert_id -> one row, severity/title
    refreshed -- the core of the "escalates in place" model."""
    a = _alert("r1", datetime.datetime(2026, 1, 25, 12, 0, tzinfo=UTC), AlertSeverity.INFO)
    alert_log.upsert(a)
    escalated = _alert(
        "r1", datetime.datetime(2026, 1, 26, 12, 0, tzinfo=UTC), AlertSeverity.CRITICAL
    )
    assert escalated.alert_id == a.alert_id  # same rule + same event -> same id
    alert_log.upsert(escalated)
    assert len(alert_log.recent()) == 1
    got = alert_log.get(a.alert_id)
    assert got is not None
    assert got.severity == AlertSeverity.CRITICAL


def test_recent_newest_first_and_limited(alert_log):
    a1 = _alert("r1", datetime.datetime(2026, 1, 1, tzinfo=UTC))
    a2 = _alert("r2", datetime.datetime(2026, 1, 3, tzinfo=UTC))
    a3 = _alert("r3", datetime.datetime(2026, 1, 2, tzinfo=UTC))
    for a in (a1, a2, a3):
        alert_log.upsert(a)
    recent = alert_log.recent(limit=2)
    assert [a.rule_id for a in recent] == ["r2", "r3"]


def test_recent_reconstructs_full_event(alert_log):
    a = _alert("r1", datetime.datetime(2026, 1, 25, 12, 0, tzinfo=UTC))
    alert_log.upsert(a)
    got = alert_log.recent()[0]
    assert got.alert_id == a.alert_id
    assert got.severity == AlertSeverity.WARNING
    assert isinstance(got.event, HolidayEvent)
    assert got.event.holiday_name == "Republic Day"
    assert got.event.metadata == {"note": "x"}
    assert got.triggered_at == a.triggered_at
