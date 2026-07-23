"""Unit tests for normalizers/util.py parsing helpers, in isolation."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.errors import NormalizationError
from exchange_events.normalizers.util import (
    local_time_to_utc,
    parse_date,
    parse_float,
)

pytestmark = pytest.mark.unit

UTC = datetime.UTC


# --- parse_float ---------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3.4", 3.4),
        (3.4, 3.4),
        ("1,234.5", 1234.5),
        ("3.4%", 3.4),
        (None, None),
        ("", None),
        ("-", None),
        ("N/A", None),
        ("170K", 170_000.0),
        ("2.1M", 2_100_000.0),
        ("1.5B", 1_500_000_000.0),
        ("0K", 0.0),
    ],
)
def test_parse_float_cases(raw, expected):
    result = parse_float(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_parse_float_unparseable_raises():
    with pytest.raises(NormalizationError, match="unparseable number"):
        parse_float("not-a-number")


# --- local_time_to_utc -----------------------------------------------------------
def test_local_time_24h():
    result = local_time_to_utc(datetime.date(2026, 1, 13), "08:30", "America/New_York")
    assert result == datetime.datetime(2026, 1, 13, 13, 30, tzinfo=UTC)


@pytest.mark.parametrize("time_str", ["8:30am", "8:30 am", "8:30AM", "8:30 AM"])
def test_local_time_12h_variants(time_str):
    result = local_time_to_utc(datetime.date(2026, 1, 13), time_str, "America/New_York")
    assert result == datetime.datetime(2026, 1, 13, 13, 30, tzinfo=UTC)


def test_local_time_12h_pm():
    result = local_time_to_utc(datetime.date(2026, 1, 13), "2:00pm", "America/New_York")
    assert result == datetime.datetime(2026, 1, 13, 19, 0, tzinfo=UTC)


def test_local_time_none_returns_none():
    assert local_time_to_utc(datetime.date(2026, 1, 13), None, "America/New_York") is None
    assert local_time_to_utc(datetime.date(2026, 1, 13), "", "America/New_York") is None


def test_local_time_unparseable_raises():
    with pytest.raises(NormalizationError, match="unparseable time"):
        local_time_to_utc(datetime.date(2026, 1, 13), "not-a-time", "America/New_York")


# --- parse_date ------------------------------------------------------------------
def test_parse_date_iso():
    assert parse_date("2026-01-26") == datetime.date(2026, 1, 26)


def test_parse_date_passthrough_date_object():
    d = datetime.date(2026, 1, 26)
    assert parse_date(d) is d


def test_parse_date_custom_formats():
    assert parse_date("26-Jan-2026", ("%d-%b-%Y",)) == datetime.date(2026, 1, 26)


def test_parse_date_empty_raises():
    with pytest.raises(NormalizationError, match="empty date"):
        parse_date("")


def test_parse_date_unparseable_raises():
    with pytest.raises(NormalizationError, match="unparseable date"):
        parse_date("not-a-date", ("%d-%b-%Y",))
