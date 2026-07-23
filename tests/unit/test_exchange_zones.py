"""Unit tests for the exchange<->IANA-zone mapping (domain/exchange_zones.py)."""

from __future__ import annotations

import pytest

from exchange_events.domain.exchange_zones import (
    EXCHANGE_TIMEZONES,
    dst_transition_label,
    exchanges_for_zone,
)

pytestmark = pytest.mark.unit


def test_exchanges_for_zone_returns_single_match():
    assert exchanges_for_zone("America/Chicago") == ["XCME"]


def test_exchanges_for_zone_returns_multiple_matches_sorted():
    # XNSE and XBOM both run on Asia/Kolkata.
    assert exchanges_for_zone("Asia/Kolkata") == ["XBOM", "XNSE"]


def test_exchanges_for_zone_returns_empty_for_untracked_zone():
    assert exchanges_for_zone("Europe/London") == []


def test_every_configured_exchange_has_a_timezone():
    assert set(EXCHANGE_TIMEZONES) == {"XNSE", "XBOM", "XKRX", "XCME"}


def test_dst_transition_label_entering_daylight_saving():
    assert dst_transition_label("America/Chicago", "start") == "CST -> CDT"


def test_dst_transition_label_leaving_daylight_saving():
    assert dst_transition_label("America/Chicago", "end") == "CDT -> CST"


def test_dst_transition_label_none_for_zone_with_no_dst():
    assert dst_transition_label("Asia/Kolkata", "start") is None


def test_dst_transition_label_none_for_unknown_direction():
    assert dst_transition_label("America/Chicago", None) is None
