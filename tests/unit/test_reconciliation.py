"""Unit tests for domain.reconciliation — cross-source economic-release merging.

Built to close two real gaps found while wiring the economic-release waterfall
(DECISIONS.md "Economic-release waterfall"): (1) different sources produce
different event_ids for the same real-world release, so the dashboard would show
duplicate rows; (2) EconomicSurpriseRule could never fire because no single
source's event ever had both forecast and actual populated at once.
"""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.events import EconomicReleaseEvent, HolidayEvent
from exchange_events.domain.reconciliation import (
    DEFAULT_SOURCE_PRIORITY,
    reconcile_economic_releases,
)

pytestmark = pytest.mark.unit

DATE = datetime.date(2026, 1, 13)


def _release(source: str, **overrides) -> EconomicReleaseEvent:
    kwargs = dict(
        source=source, date=DATE, release_name="Consumer Price Index", release_code="CPI",
    )
    kwargs.update(overrides)
    return EconomicReleaseEvent(**kwargs)


def test_single_event_passes_through_unchanged():
    ev = _release("fred_api", actual=3.4)
    result = reconcile_economic_releases([ev])
    assert result == [ev]


def test_non_economic_events_pass_through_untouched():
    holiday = HolidayEvent(source="nse", exchange="XNSE", date=DATE, holiday_name="X")
    result = reconcile_economic_releases([holiday])
    assert result == [holiday]


def test_mixed_list_preserves_order_and_merges_only_releases():
    holiday = HolidayEvent(source="nse", exchange="XNSE", date=DATE, holiday_name="X")
    fred = _release("fred_api", actual=3.4)
    bls = _release("bls_api", actual=3.4)  # same real release, different source
    result = reconcile_economic_releases([holiday, fred, bls])
    assert len(result) == 2
    assert result[0] is holiday
    assert isinstance(result[1], EconomicReleaseEvent)


def test_merges_forecast_from_one_source_and_actual_from_another():
    # This is the exact scenario that silently broke EconomicSurpriseRule: no
    # single source had both fields, so surprise was always None pre-merge.
    forecast_only = _release("econ_calendar", forecast=3.1, actual=None)
    actual_only = _release("fred_api", forecast=None, actual=3.4)
    [merged] = reconcile_economic_releases([forecast_only, actual_only])
    assert merged.forecast == pytest.approx(3.1)
    assert merged.actual == pytest.approx(3.4)
    assert merged.surprise == pytest.approx(0.3)


def test_higher_priority_source_wins_when_both_have_a_value():
    fred = _release("fred_api", actual=3.4)
    bls = _release("bls_api", actual=999.0)  # should be ignored — FRED outranks BLS
    [merged] = reconcile_economic_releases([fred, bls])
    assert merged.actual == pytest.approx(3.4)


def test_lower_priority_fills_gap_when_higher_priority_field_is_none():
    fred = _release("fred_api", actual=None, previous=3.0)  # FRED has no actual yet
    bls = _release("bls_api", actual=3.4, previous=None)     # BLS has it
    [merged] = reconcile_economic_releases([fred, bls])
    assert merged.actual == pytest.approx(3.4)  # backfilled from BLS
    assert merged.previous == pytest.approx(3.0)  # kept from FRED (higher priority)


def test_different_release_codes_on_same_date_are_not_merged():
    cpi = _release("fred_api", release_code="CPI", actual=3.4)
    nfp = _release("fred_api", release_code="NFP", actual=180.0)
    result = reconcile_economic_releases([cpi, nfp])
    assert len(result) == 2


def test_different_dates_are_not_merged():
    d1 = _release("fred_api", date=datetime.date(2026, 1, 13), actual=3.4)
    d2 = _release("fred_api", date=datetime.date(2026, 2, 13), actual=3.5)
    result = reconcile_economic_releases([d1, d2])
    assert len(result) == 2


def test_econ_calendar_is_lowest_priority_by_default():
    fred = _release("fred_api", actual=3.4)
    econ = _release("econ_calendar", actual=999.0, forecast=3.1)
    [merged] = reconcile_economic_releases([fred, econ])
    assert merged.actual == pytest.approx(3.4)  # FRED wins over MarketWatch
    assert merged.forecast == pytest.approx(3.1)  # but MarketWatch still fills the gap


def test_unranked_source_sorts_last_not_dropped():
    fred = _release("fred_api", actual=None)
    mystery = _release("some_new_source", actual=42.0)
    [merged] = reconcile_economic_releases([fred, mystery])
    assert merged.actual == pytest.approx(42.0)  # only source with a value, kept


def test_merged_event_records_contributing_sources_in_metadata():
    fred = _release("fred_api", actual=3.4)
    bls = _release("bls_api", actual=3.4)
    [merged] = reconcile_economic_releases([fred, bls])
    assert merged.metadata["reconciled_from"] == ["bls_api", "fred_api"]


def test_custom_priority_order_is_respected():
    fred = _release("fred_api", actual=1.0)
    bls = _release("bls_api", actual=2.0)
    [merged] = reconcile_economic_releases(
        [fred, bls], source_priority=("bls_api", "fred_api")
    )
    assert merged.actual == pytest.approx(2.0)  # BLS now outranks FRED


def test_three_way_merge():
    fred = _release("fred_api", actual=None, previous=None, agency="")
    bls = _release("bls_api", actual=3.4, previous=None, agency="BLS")
    bea = _release("bea_api", actual=None, previous=3.0, agency="")
    [merged] = reconcile_economic_releases([fred, bls, bea])
    assert merged.actual == pytest.approx(3.4)
    assert merged.previous == pytest.approx(3.0)
    assert merged.agency == "BLS"


def test_default_source_priority_matches_documented_waterfall():
    assert DEFAULT_SOURCE_PRIORITY == (
        "fred_api", "fomc_schedule", "bls_api", "bea_api", "ism_pmi", "econ_calendar",
    )


def test_country_is_preserved_through_merge():
    fred = _release("fred_api", actual=3.4, country="US")
    bls = _release("bls_api", actual=3.4, country="US")
    [merged] = reconcile_economic_releases([fred, bls])
    assert merged.country == "US"


def test_country_backfilled_from_lower_priority_when_higher_priority_lacks_it():
    fred = _release("fred_api", actual=3.4, country=None)
    bls = _release("bls_api", actual=3.4, country="US")
    [merged] = reconcile_economic_releases([fred, bls])
    assert merged.country == "US"
