"""Unit tests for deterministic id generation (§3.4) — the basis of P6 idempotency."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.enums import EventType
from exchange_events.domain.ids import make_alert_id, make_event_id

pytestmark = pytest.mark.unit

D = datetime.date(2026, 1, 26)


def _eid(**overrides):
    base = dict(
        source="nse_circular",
        event_type=EventType.HOLIDAY,
        exchange="XNSE",
        date=D,
        discriminator="Republic Day",
    )
    base.update(overrides)
    return make_event_id(**base)


def test_event_id_is_deterministic():
    assert _eid() == _eid()


def test_event_id_is_sha256_hex():
    eid = _eid()
    assert len(eid) == 64
    assert all(c in "0123456789abcdef" for c in eid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "bse_circular"),
        ("event_type", EventType.EXPIRY),
        ("exchange", "XBOM"),
        ("date", datetime.date(2026, 1, 27)),
        ("discriminator", "Independence Day"),
    ],
)
def test_changing_any_key_component_changes_id(field, value):
    assert _eid(**{field: value}) != _eid()


def test_enum_and_string_event_type_produce_same_id():
    assert _eid(event_type=EventType.HOLIDAY) == _eid(event_type="holiday")


def test_none_exchange_renders_as_empty_string():
    # DST-style events have no exchange; None and "" must collapse to the same key.
    assert _eid(exchange=None) == _eid(exchange="")


def test_none_exchange_differs_from_named_exchange():
    assert _eid(exchange=None) != _eid(exchange="XNSE")


def test_alert_id_is_deterministic():
    args = dict(rule_id="upcoming_release", event_id="abc123")
    assert make_alert_id(**args) == make_alert_id(**args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rule_id", "expiry_day"),
        ("event_id", "def456"),
    ],
)
def test_changing_any_alert_component_changes_id(field, value):
    base = dict(rule_id="upcoming_release", event_id="abc123")
    changed = dict(base)
    changed[field] = value
    assert make_alert_id(**changed) != make_alert_id(**base)
