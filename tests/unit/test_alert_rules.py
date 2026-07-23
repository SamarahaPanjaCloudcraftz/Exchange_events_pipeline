"""Unit tests for alert rules (§5.4, post-delivery proximity redesign) — fire/
no-fire boundaries, severity classification thresholds, and per-rule isolation
of edge cases. All FakeClock-driven (via AlertContext), no I/O."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.alerting.rules import (
    ALERT_EXPIRY_UNDERLYINGS,
    CORE_RELEASE_CODES,
    DstShiftProximityRule,
    EconomicReleaseProximityRule,
    ExpiryProximityRule,
    HolidayProximityRule,
    IVThresholdRule,
)
from exchange_events.domain.alerts import AlertContext, AlertSeverity
from exchange_events.domain.events import (
    DSTChangeEvent,
    EconomicReleaseEvent,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.domain.iv import IVSnapshot

pytestmark = pytest.mark.unit

UTC = datetime.UTC


def ctx(today: datetime.date) -> AlertContext:
    now = datetime.datetime(today.year, today.month, today.day, 12, tzinfo=UTC)
    return AlertContext(now_utc=now)


def release(date: datetime.date, code: str = "NFP", **kw) -> EconomicReleaseEvent:
    kwargs = dict(source="fred", date=date, release_name=code, release_code=code)
    kwargs.update(kw)
    return EconomicReleaseEvent(**kwargs)


def expiry(expiry_date: datetime.date, **kw) -> ExpiryEvent:
    kwargs = dict(
        source="cme", exchange="XCME", date=expiry_date, instrument_type="futures",
        underlying="ES", series="quarterly", expiry_date=expiry_date,
    )
    kwargs.update(kw)
    return ExpiryEvent(**kwargs)


def holiday(date: datetime.date, **kw) -> HolidayEvent:
    kwargs = dict(source="cme", exchange="XCME", date=date, holiday_name="Labor Day")
    kwargs.update(kw)
    return HolidayEvent(**kwargs)


def dst(date: datetime.date, **kw) -> DSTChangeEvent:
    kwargs = dict(
        source="iana_tz", date=date, region="CME", old_utc_offset="-05:00",
        new_utc_offset="-06:00", iana_zone="America/Chicago",
    )
    kwargs.update(kw)
    return DSTChangeEvent(**kwargs)


# --- HolidayProximityRule (always INFO, never escalates) ---------------------------
def test_holiday_is_always_info_regardless_of_proximity():
    today = datetime.date(2026, 8, 6)
    rule = HolidayProximityRule()
    tomorrow_alert = rule.evaluate([holiday(datetime.date(2026, 8, 7))], ctx(today))[0]
    far_alert = rule.evaluate([holiday(datetime.date(2027, 1, 1))], ctx(today))[0]
    assert tomorrow_alert.severity == AlertSeverity.INFO
    assert far_alert.severity == AlertSeverity.INFO


def test_holiday_ignores_past_dates():
    today = datetime.date(2026, 8, 6)
    rule = HolidayProximityRule()
    assert rule.evaluate([holiday(datetime.date(2026, 8, 5))], ctx(today)) == []


def test_holiday_ignores_non_holiday_events():
    today = datetime.date(2026, 8, 6)
    rule = HolidayProximityRule()
    assert rule.evaluate([expiry(datetime.date(2026, 8, 7))], ctx(today)) == []


# --- DstShiftProximityRule -----------------------------------------------------------
def test_dst_shift_info_when_far_out():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([dst(datetime.date(2026, 8, 20))], ctx(today))
    assert alerts[0].severity == AlertSeverity.INFO


def test_dst_shift_warning_at_boundary():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([dst(datetime.date(2026, 8, 8))], ctx(today))  # 2 days away
    assert alerts[0].severity == AlertSeverity.WARNING


def test_dst_shift_critical_within_one_day():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([dst(datetime.date(2026, 8, 7))], ctx(today))  # tomorrow
    assert alerts[0].severity == AlertSeverity.CRITICAL


def test_dst_shift_critical_same_day():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([dst(datetime.date(2026, 8, 6))], ctx(today))
    assert alerts[0].severity == AlertSeverity.CRITICAL


def test_dst_shift_ignores_past_dates():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule()
    assert rule.evaluate([dst(datetime.date(2026, 8, 5))], ctx(today)) == []


def test_dst_shift_ignores_non_dst_events():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule()
    assert rule.evaluate([expiry(datetime.date(2026, 8, 7))], ctx(today)) == []


def test_dst_shift_title_names_the_exchange_not_the_iana_region():
    """DSTChangeEvent has no `exchange` field, only `iana_zone` -- the title
    must resolve America/Chicago to "XCME", not the raw region prefix
    ("America") that used to appear."""
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule()
    alerts = rule.evaluate([dst(datetime.date(2026, 8, 7))], ctx(today))
    assert alerts[0].title.startswith("XCME")


def test_dst_shift_title_falls_back_to_zone_for_untracked_zone():
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule()
    untracked = dst(datetime.date(2026, 8, 7), iana_zone="Europe/London", region="Europe")
    alerts = rule.evaluate([untracked], ctx(today))
    assert alerts[0].title.startswith("Europe/London")


def test_dst_shift_title_shows_named_abbreviation_falling_back():
    """Named abbreviations (e.g. "CDT -> CST") read far more clearly than raw
    UTC offsets and must match the dashboard's own "Next Timezone Shift"
    block. Falls back to raw offsets when the transition direction isn't
    known (no metadata)."""
    today = datetime.date(2026, 8, 6)
    rule = DstShiftProximityRule()

    ending_dst = dst(datetime.date(2026, 8, 7), metadata={"transition": "end"})
    alerts = rule.evaluate([ending_dst], ctx(today))
    assert "CDT -> CST" in alerts[0].title

    starting_dst = dst(datetime.date(2026, 8, 7), metadata={"transition": "start"})
    alerts = rule.evaluate([starting_dst], ctx(today))
    assert "CST -> CDT" in alerts[0].title

    unknown_direction = dst(datetime.date(2026, 8, 7))  # no metadata at all
    alerts = rule.evaluate([unknown_direction], ctx(today))
    assert "-05:00 -> -06:00" in alerts[0].title


# --- ExpiryProximityRule (no CRITICAL tier) -------------------------------------------
def test_expiry_info_when_far_out():
    today = datetime.date(2026, 3, 1)
    rule = ExpiryProximityRule(warning_days=2)
    alerts = rule.evaluate([expiry(datetime.date(2026, 3, 20))], ctx(today))
    assert alerts[0].severity == AlertSeverity.INFO


def test_expiry_warning_at_boundary():
    today = datetime.date(2026, 3, 18)
    rule = ExpiryProximityRule(warning_days=2)
    alerts = rule.evaluate([expiry(datetime.date(2026, 3, 20))], ctx(today))  # 2 days away
    assert alerts[0].severity == AlertSeverity.WARNING
    assert "ES" in alerts[0].title


def test_expiry_warning_one_day_away():
    today = datetime.date(2026, 3, 19)
    rule = ExpiryProximityRule(warning_days=2)
    alerts = rule.evaluate([expiry(datetime.date(2026, 3, 20))], ctx(today))
    assert alerts[0].severity == AlertSeverity.WARNING


def test_expiry_never_critical():
    today = datetime.date(2026, 3, 20)
    rule = ExpiryProximityRule(warning_days=2)
    alerts = rule.evaluate([expiry(datetime.date(2026, 3, 20))], ctx(today))  # expires today
    assert alerts[0].severity == AlertSeverity.WARNING


def test_expiry_ignores_past_dates():
    today = datetime.date(2026, 3, 21)
    rule = ExpiryProximityRule()
    assert rule.evaluate([expiry(datetime.date(2026, 3, 20))], ctx(today)) == []


def test_expiry_ignores_non_expiry_events():
    today = datetime.date(2026, 8, 6)
    rule = ExpiryProximityRule()
    assert rule.evaluate([release(datetime.date(2026, 8, 7))], ctx(today)) == []


def test_expiry_ignores_non_allowed_underlyings():
    today = datetime.date(2026, 8, 6)
    rule = ExpiryProximityRule()
    other = expiry(datetime.date(2026, 8, 7), underlying="CL")
    assert rule.evaluate([other], ctx(today)) == []


def test_expiry_custom_underlyings_override_default():
    today = datetime.date(2026, 8, 6)
    cl = expiry(datetime.date(2026, 8, 7), underlying="CL")
    rule = ExpiryProximityRule(underlyings=frozenset({"CL"}))
    assert len(rule.evaluate([cl], ctx(today))) == 1


def test_default_alert_expiry_underlyings_are_es_and_nq():
    expected = {"ES", "NQ"}
    assert expected == ALERT_EXPIRY_UNDERLYINGS


# --- EconomicReleaseProximityRule -----------------------------------------------------
def test_release_info_when_far_out():
    today = datetime.date(2026, 8, 1)
    rule = EconomicReleaseProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([release(datetime.date(2026, 8, 20), code="NFP")], ctx(today))
    assert alerts[0].severity == AlertSeverity.INFO


def test_release_title_includes_country():
    """Economic releases are country-specific, not exchange-specific --
    EconomicReleaseEvent has no `exchange`, only `country` -- the title must
    say which country this release is for."""
    today = datetime.date(2026, 8, 6)
    rule = EconomicReleaseProximityRule()
    nfp = release(datetime.date(2026, 8, 7), code="NFP", country="US")
    alerts = rule.evaluate([nfp], ctx(today))
    assert "US" in alerts[0].title


def test_release_warning_at_boundary():
    today = datetime.date(2026, 8, 6)
    rule = EconomicReleaseProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([release(datetime.date(2026, 8, 8), code="NFP")], ctx(today))
    assert alerts[0].severity == AlertSeverity.WARNING


def test_release_critical_within_one_day():
    today = datetime.date(2026, 8, 6)
    rule = EconomicReleaseProximityRule(warning_days=2, critical_days=1)
    alerts = rule.evaluate([release(datetime.date(2026, 8, 7), code="NFP")], ctx(today))
    assert alerts[0].severity == AlertSeverity.CRITICAL


def test_release_ignores_non_core_codes():
    today = datetime.date(2026, 8, 6)
    rule = EconomicReleaseProximityRule()
    other = release(datetime.date(2026, 8, 7), code="FEDFUNDS")
    assert rule.evaluate([other], ctx(today)) == []


def test_release_custom_codes_override_default():
    today = datetime.date(2026, 8, 6)
    retail = release(datetime.date(2026, 8, 7), code="RETAIL_SALES")
    rule = EconomicReleaseProximityRule(release_codes=frozenset({"RETAIL_SALES"}))
    assert len(rule.evaluate([retail], ctx(today))) == 1


def test_release_ignores_non_release_events():
    today = datetime.date(2026, 8, 6)
    rule = EconomicReleaseProximityRule()
    assert rule.evaluate([expiry(datetime.date(2026, 8, 7))], ctx(today)) == []


def test_default_core_release_codes_match_requirements_doc():
    expected = {"CPI", "NFP", "PPI", "PCE", "ISM_PMI", "JOLTS", "FOMC"}
    assert expected == CORE_RELEASE_CODES


# --- IVThresholdRule (gated on optional IV data) ------------------------------------
def test_iv_threshold_fires_when_iv_at_or_above_threshold():
    today = datetime.date(2026, 3, 20)
    ev = expiry(today)
    snapshot = IVSnapshot(exchange="XCME", underlying="ES", date=today, iv=0.35)
    context = AlertContext(
        now_utc=datetime.datetime(2026, 3, 20, 12, tzinfo=UTC),
        iv_snapshots={("XCME", "ES"): snapshot},
    )
    rule = IVThresholdRule(default_threshold=0.30)
    alerts = rule.evaluate([ev], context)
    assert len(alerts) == 1
    assert alerts[0].severity == AlertSeverity.WARNING


def test_iv_threshold_does_not_fire_below_threshold():
    today = datetime.date(2026, 3, 20)
    ev = expiry(today)
    snapshot = IVSnapshot(exchange="XCME", underlying="ES", date=today, iv=0.20)
    context = AlertContext(
        now_utc=datetime.datetime(2026, 3, 20, 12, tzinfo=UTC),
        iv_snapshots={("XCME", "ES"): snapshot},
    )
    rule = IVThresholdRule(default_threshold=0.30)
    assert rule.evaluate([ev], context) == []


def test_iv_threshold_skips_gracefully_when_no_snapshot_present():
    """No IV provider wired (or no data for this underlying) -> empty iv_snapshots."""
    today = datetime.date(2026, 3, 20)
    ev = expiry(today)
    context = AlertContext(now_utc=datetime.datetime(2026, 3, 20, 12, tzinfo=UTC))
    rule = IVThresholdRule()
    assert rule.evaluate([ev], context) == []  # no crash, no false alert


def test_iv_threshold_per_underlying_override():
    today = datetime.date(2026, 3, 20)
    ev = expiry(today, underlying="NQ")
    snapshot = IVSnapshot(exchange="XCME", underlying="NQ", date=today, iv=0.45)
    context = AlertContext(
        now_utc=datetime.datetime(2026, 3, 20, 12, tzinfo=UTC),
        iv_snapshots={("XCME", "NQ"): snapshot},
    )
    rule = IVThresholdRule(thresholds={"NQ": 0.50})  # override above 45% -> no fire
    assert rule.evaluate([ev], context) == []
