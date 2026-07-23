"""Unit tests for all normalizers (§5.2) + partial-failure semantics."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.enums import EventType, SessionType
from exchange_events.domain.events import (
    DSTChangeEvent,
    EconomicReleaseEvent,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.normalizers import (
    BEANormalizer,
    BLSNormalizer,
    BSENormalizer,
    CMENormalizer,
    EconCalendarNormalizer,
    FREDNormalizer,
    ISMNormalizer,
    KRXNormalizer,
    NSENormalizer,
    TimezoneNormalizer,
)
from exchange_events.normalizers.base import BaseNormalizer

pytestmark = pytest.mark.unit

UTC = datetime.UTC


def only(result):
    assert result.errors == [], result.errors
    assert len(result.events) == 1
    return result.events[0]


# --- CME (production priority) -----------------------------------------------------
def test_cme_holiday_full_close_with_products():
    raw = [{"record_type": "holiday", "date": "2026-01-01", "name": "New Year's Day",
            "session": "closed", "products": ["ES", "NQ"], "id": "h1"}]
    ev = only(CMENormalizer().normalize(raw, "cme_calendar"))
    assert isinstance(ev, HolidayEvent)
    assert ev.exchange == "XCME"
    assert ev.date == datetime.date(2026, 1, 1)
    assert ev.holiday_name == "New Year's Day"
    assert ev.session_type == SessionType.FULL_CLOSE
    assert ev.affected_segments == ["ES", "NQ"]
    assert ev.source_raw_id == "h1"


def test_cme_holiday_early_close_is_half_day():
    raw = [{"record_type": "holiday", "date": "2026-11-27", "name": "Thanksgiving (early)",
            "session": "early_close"}]
    ev = only(CMENormalizer().normalize(raw, "cme_calendar"))
    assert ev.session_type == SessionType.HALF_DAY


def test_cme_holiday_alt_date_format():
    raw = [{"record_type": "holiday", "date": "04 Jul 2026", "name": "Independence Day"}]
    ev = only(CMENormalizer().normalize(raw, "cme_calendar"))
    assert ev.date == datetime.date(2026, 7, 4)


def test_cme_expiry():
    raw = [{"record_type": "expiry", "product": "ES", "instrument_type": "futures",
            "series": "quarterly", "expiry_date": "2026-03-20",
            "metadata": {"product_name": "E-mini S&P 500"}}]
    ev = only(CMENormalizer().normalize(raw, "cme_calendar"))
    assert isinstance(ev, ExpiryEvent)
    assert ev.exchange == "XCME"
    assert ev.underlying == "ES"
    assert ev.instrument_type == "futures"
    assert ev.series == "quarterly"
    assert ev.expiry_date == datetime.date(2026, 3, 20)
    assert ev.date == datetime.date(2026, 3, 20)
    assert ev.metadata == {"product_name": "E-mini S&P 500"}


def test_cme_event_id_is_deterministic():
    raw = [{"record_type": "holiday", "date": "2026-01-01", "name": "New Year's Day"}]
    a = only(CMENormalizer().normalize(raw, "cme_calendar"))
    b = only(CMENormalizer().normalize(raw, "cme_calendar"))
    assert a.event_id == b.event_id


# --- NSE / BSE / KRX date formats --------------------------------------------------
def test_nse_holiday_and_expiry_date_formats():
    raw = [
        {"record_type": "holiday", "date": "26-Jan-2026", "description": "Republic Day",
         "segments": ["EQ", "FO", "CD"]},
        {"record_type": "expiry", "underlying": "NIFTY", "instrument": "options",
         "series": "weekly", "expiry_date": "29-Jan-2026", "is_revised": True},
    ]
    result = NSENormalizer().normalize(raw, "nse_circular")
    assert result.errors == []
    holiday = next(e for e in result.events if isinstance(e, HolidayEvent))
    expiry = next(e for e in result.events if isinstance(e, ExpiryEvent))
    assert holiday.exchange == "XNSE"
    assert holiday.date == datetime.date(2026, 1, 26)
    assert holiday.affected_segments == ["EQ", "FO", "CD"]
    assert expiry.underlying == "NIFTY"
    assert expiry.instrument_type == "options"
    assert expiry.is_revised is True
    assert expiry.expiry_date == datetime.date(2026, 1, 29)


def test_bse_slash_date_format():
    raw = [{"record_type": "holiday", "date": "26/01/2026", "name": "Republic Day"}]
    ev = only(BSENormalizer().normalize(raw, "bse_circular"))
    assert ev.exchange == "XBOM"
    assert ev.date == datetime.date(2026, 1, 26)


def test_krx_compact_date_format():
    raw = [{"record_type": "holiday", "date": "20260101", "name": "New Year's Day"}]
    ev = only(KRXNormalizer().normalize(raw, "krx_calendar"))
    assert ev.exchange == "XKRX"
    assert ev.date == datetime.date(2026, 1, 1)


# --- FRED (actuals) ----------------------------------------------------------------
def test_fred_release_actuals():
    raw = [{"release_code": "CPI", "release_name": "Consumer Price Index",
            "date": "2026-01-13", "period": "2025-12", "actual": "3.4",
            "previous": "3.0", "unit": "%", "agency": "BLS"}]
    ev = only(FREDNormalizer().normalize(raw, "fred_api"))
    assert isinstance(ev, EconomicReleaseEvent)
    assert ev.exchange is None
    assert ev.event_type == EventType.ECONOMIC_RELEASE
    assert ev.release_code == "CPI"
    assert ev.actual == pytest.approx(3.4)
    assert ev.previous == pytest.approx(3.0)
    assert ev.forecast is None
    assert ev.surprise is None  # no forecast


# --- IANA / DST --------------------------------------------------------------------
def test_tz_dst_change():
    raw = [{"iana_zone": "America/New_York", "date": "2026-03-08", "region": "US",
            "old_offset": "UTC-5", "new_offset": "UTC-4", "transition": "start",
            "timestamp_utc": "2026-03-08T07:00:00.000000+00:00"}]
    ev = only(TimezoneNormalizer().normalize(raw, "iana_tz"))
    assert isinstance(ev, DSTChangeEvent)
    assert ev.exchange is None
    assert ev.iana_zone == "America/New_York"
    assert ev.old_utc_offset == "UTC-5"
    assert ev.new_utc_offset == "UTC-4"
    assert ev.timestamp_utc == datetime.datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    assert ev.metadata["transition"] == "start"


# --- Econ / MarketWatch (forecast + ET->UTC time) ----------------------------------
def test_econ_release_with_eastern_time_winter():
    raw = [{"release_code": "NFP", "release_name": "Nonfarm Payrolls", "date": "2026-02-06",
            "time": "08:30", "period": "Jan", "forecast": "170", "previous": "150",
            "unit": "thousands", "agency": "BLS"}]
    ev = only(EconCalendarNormalizer().normalize(raw, "econ_calendar"))
    assert ev.forecast == pytest.approx(170.0)
    assert ev.previous == pytest.approx(150.0)
    # 08:30 EST (UTC-5) -> 13:30 UTC
    assert ev.timestamp_utc == datetime.datetime(2026, 2, 6, 13, 30, tzinfo=UTC)


def test_econ_release_eastern_time_summer_dst():
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-07-14",
            "time": "08:30", "forecast": "3.2"}]
    ev = only(EconCalendarNormalizer().normalize(raw, "econ_calendar"))
    # 08:30 EDT (UTC-4) -> 12:30 UTC
    assert ev.timestamp_utc == datetime.datetime(2026, 7, 14, 12, 30, tzinfo=UTC)


def test_econ_release_surprise_when_actual_present():
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-01-13",
            "forecast": "3.1", "actual": "3.4"}]
    ev = only(EconCalendarNormalizer().normalize(raw, "econ_calendar"))
    assert ev.surprise == pytest.approx(0.3)


# --- partial-failure contract (§5.2) -----------------------------------------------
def test_partial_failure_keeps_good_records():
    raw = [
        {"record_type": "holiday", "date": "2026-01-01", "name": "New Year's Day"},
        {"record_type": "holiday", "date": "NOT-A-DATE", "name": "Bad"},
        {"record_type": "holiday", "date": "2026-01-26", "name": "Republic Day"},
    ]
    result = CMENormalizer().normalize(raw, "cme_calendar")
    assert len(result.events) == 2
    assert len(result.errors) == 1
    assert result.errors[0].raw_record["name"] == "Bad"
    assert result.errors[0].source == "cme_calendar"


def test_unknown_record_type_is_captured_error():
    result = CMENormalizer().normalize([{"record_type": "mystery"}], "cme_calendar")
    assert result.events == []
    assert len(result.errors) == 1


def test_missing_required_field_is_captured_error():
    result = CMENormalizer().normalize([{"record_type": "holiday", "date": "2026-01-01"}],
                                       "cme_calendar")
    assert result.events == []
    assert "holiday name" in result.errors[0].reason


def test_empty_batch_yields_empty_result():
    result = FREDNormalizer().normalize([], "fred_api")
    assert result.events == []
    assert result.errors == []


# --- BaseNormalizer contract, exercised directly (no production normalizer
# currently needs the None-skip / list-expansion / generic-exception paths,
# but they are documented, load-bearing parts of the base contract) ----------------
class _ContractProbeNormalizer(BaseNormalizer):
    """Returns events/None/lists/raises based on a marker field, to exercise
    every branch of BaseNormalizer.normalize in isolation."""

    def target_source(self):
        return "probe"

    def _normalize_one(self, record, source_name):
        marker = record.get("marker")
        if marker == "none":
            return None
        if marker == "list":
            return [
                HolidayEvent(source=source_name, exchange="XNSE",
                             date=datetime.date(2026, 1, 1), holiday_name="A"),
                HolidayEvent(source=source_name, exchange="XNSE",
                             date=datetime.date(2026, 1, 2), holiday_name="B"),
            ]
        if marker == "boom":
            raise KeyError("unexpected bug, not a NormalizationError")
        return HolidayEvent(source=source_name, exchange="XNSE",
                             date=datetime.date(2026, 1, 3), holiday_name="C")


def test_base_normalizer_none_return_is_skipped_not_an_event():
    result = _ContractProbeNormalizer().normalize([{"marker": "none"}], "probe")
    assert result.events == []
    assert result.errors == []


def test_base_normalizer_list_return_is_expanded():
    result = _ContractProbeNormalizer().normalize([{"marker": "list"}], "probe")
    assert len(result.events) == 2
    assert {e.holiday_name for e in result.events} == {"A", "B"}


def test_base_normalizer_generic_exception_is_captured_not_raised():
    result = _ContractProbeNormalizer().normalize([{"marker": "boom"}], "probe")
    assert result.events == []
    assert len(result.errors) == 1
    assert "unexpected bug" in result.errors[0].reason
    assert result.errors[0].source == "probe"


def test_base_normalizer_mixed_batch_all_branches_together():
    records = [
        {"marker": "ok"}, {"marker": "none"}, {"marker": "list"}, {"marker": "boom"},
    ]
    result = _ContractProbeNormalizer().normalize(records, "probe")
    assert len(result.events) == 3  # 1 "ok" + 2 from the list; "none" contributes 0
    assert len(result.errors) == 1


def test_target_source_names():
    assert CMENormalizer().target_source() == "cme_calendar"
    assert NSENormalizer().target_source() == "nse_circular"
    assert BSENormalizer().target_source() == "bse_circular"
    assert KRXNormalizer().target_source() == "krx_calendar"
    assert FREDNormalizer().target_source() == "fred_api"
    assert BLSNormalizer().target_source() == "bls_api"
    assert BEANormalizer().target_source() == "bea_api"
    assert ISMNormalizer().target_source() == "ism_pmi"
    assert TimezoneNormalizer().target_source() == "iana_tz"
    assert EconCalendarNormalizer().target_source() == "econ_calendar"


# --- BLS / BEA / ISM (economic-release waterfall, tiers 2/3/best-effort) -----------
@pytest.mark.parametrize(
    "normalizer_cls,source_name",
    [(BLSNormalizer, "bls_api"), (BEANormalizer, "bea_api"), (ISMNormalizer, "ism_pmi")],
)
def test_government_release_normalizer_forecast_always_none(normalizer_cls, source_name):
    # These are all "actuals" sources — forecast is never a field they publish.
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-01-13",
            "actual": "3.4"}]
    ev = only(normalizer_cls().normalize(raw, source_name))
    assert ev.forecast is None
    assert ev.actual == pytest.approx(3.4)


def test_bls_normalizer_full_fields():
    raw = [{"release_code": "NFP", "release_name": "Total Nonfarm Payrolls",
            "date": "2026-02-06", "period": "January", "actual": "180.0",
            "previous": "150.0", "unit": "thousands", "agency": "BLS"}]
    ev = only(BLSNormalizer().normalize(raw, "bls_api"))
    assert ev.release_code == "NFP"
    assert ev.actual == pytest.approx(180.0)
    assert ev.previous == pytest.approx(150.0)
    assert ev.agency == "BLS"


def test_bea_normalizer_full_fields():
    raw = [{"release_code": "PCE", "release_name": "PCE Price Index",
            "date": "2026-06-01", "actual": "126.1", "previous": "125.4",
            "unit": "%", "agency": "BEA"}]
    ev = only(BEANormalizer().normalize(raw, "bea_api"))
    assert ev.release_code == "PCE"
    assert ev.actual == pytest.approx(126.1)


def test_ism_normalizer_full_fields():
    raw = [{"release_code": "ISM_PMI", "release_name": "ISM Manufacturing PMI",
            "date": "2026-01-02", "actual": "48.5", "unit": "index", "agency": "ISM"}]
    ev = only(ISMNormalizer().normalize(raw, "ism_pmi"))
    assert ev.release_code == "ISM_PMI"
    assert ev.actual == pytest.approx(48.5)


# --- country tagging (lets the dashboard show a release under the right
# country's exchange tab, e.g. US releases under CME) -------------------------------
@pytest.mark.parametrize(
    "normalizer_cls,source_name",
    [
        (FREDNormalizer, "fred_api"), (BLSNormalizer, "bls_api"),
        (BEANormalizer, "bea_api"), (ISMNormalizer, "ism_pmi"),
        (EconCalendarNormalizer, "econ_calendar"),
    ],
)
def test_all_economic_normalizers_default_country_to_us(normalizer_cls, source_name):
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-01-13",
            "actual": "3.4", "forecast": "3.1"}]
    ev = only(normalizer_cls().normalize(raw, source_name))
    assert ev.country == "US"


def test_government_release_normalizer_country_overridable_via_raw_record():
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-01-13",
            "actual": "3.4", "country": "IN"}]
    ev = only(FREDNormalizer().normalize(raw, "fred_api"))
    assert ev.country == "IN"


# --- standard release-time fallback (FRED/BLS/BEA/ISM don't return an intraday
# time, only a date — every required release has a fixed, published time) ----------
@pytest.mark.parametrize(
    "release_code,expected_et_hhmm",
    [("NFP", "08:30"), ("CPI", "08:30"), ("PPI", "08:30"), ("PCE", "08:30"),
     ("JOLTS", "10:00"), ("ISM_PMI", "10:00"), ("FOMC", "14:00")],
)
def test_government_release_normalizer_applies_standard_release_time(
    release_code, expected_et_hhmm
):
    # 2026-01-13 is EST (UTC-5) — no DST in effect.
    raw = [{"release_code": release_code, "release_name": "X", "date": "2026-01-13",
            "actual": "1.0"}]
    ev = only(FREDNormalizer().normalize(raw, "fred_api"))
    hour, minute = (int(x) for x in expected_et_hhmm.split(":"))
    assert ev.timestamp_utc == datetime.datetime(2026, 1, 13, hour + 5, minute, tzinfo=UTC)


def test_government_release_normalizer_standard_time_respects_summer_dst():
    # 2026-07-14 is EDT (UTC-4).
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-07-14", "actual": "1.0"}]
    ev = only(FREDNormalizer().normalize(raw, "fred_api"))
    assert ev.timestamp_utc == datetime.datetime(2026, 7, 14, 12, 30, tzinfo=UTC)


def test_government_release_normalizer_explicit_time_overrides_standard_mapping():
    raw = [{"release_code": "CPI", "release_name": "CPI", "date": "2026-01-13",
            "actual": "1.0", "time": "09:15"}]
    ev = only(FREDNormalizer().normalize(raw, "fred_api"))
    assert ev.timestamp_utc == datetime.datetime(2026, 1, 13, 14, 15, tzinfo=UTC)


def test_unknown_release_code_gets_no_standard_time():
    raw = [{"release_code": "GDP", "release_name": "GDP", "date": "2026-01-13", "actual": "1.0"}]
    ev = only(FREDNormalizer().normalize(raw, "fred_api"))
    assert ev.timestamp_utc is None


def test_econ_calendar_normalizer_falls_back_to_standard_time_when_row_omits_it():
    # No "time" field this time — MarketWatch's page didn't include one for this row.
    raw = [{"release_code": "FOMC", "release_name": "FOMC Rate Decision",
            "date": "2026-01-13", "forecast": "4.5"}]
    ev = only(EconCalendarNormalizer().normalize(raw, "econ_calendar"))
    assert ev.timestamp_utc == datetime.datetime(2026, 1, 13, 19, 0, tzinfo=UTC)  # 14:00 ET
