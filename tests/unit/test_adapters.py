"""Unit tests for source adapters (§5.1) — all offline via FakeHttpClient fixtures."""

from __future__ import annotations

import base64
import datetime
from typing import Any

import pytest

from exchange_events.adapters.bea import DEFAULT_BASE_URL as BEA_URL
from exchange_events.adapters.bea import BEAAdapter
from exchange_events.adapters.bls import DEFAULT_BASE_URL as BLS_URL
from exchange_events.adapters.bls import BLSAdapter
from exchange_events.adapters.bse import DEFAULT_EXPIRY_URL as BSE_EXPIRY_URL
from exchange_events.adapters.bse import DEFAULT_HOLIDAY_URL as BSE_HOLIDAY_URL
from exchange_events.adapters.bse import BSEAdapter
from exchange_events.adapters.cme import DEFAULT_REFDATA_BASE_URL as CME_REFDATA_URL
from exchange_events.adapters.cme import DEFAULT_TOKEN_URL as CME_TOKEN_URL
from exchange_events.adapters.cme import CMEAdapter, _series_for
from exchange_events.adapters.config import AdapterConfig
from exchange_events.adapters.econ import EconCalendarAdapter
from exchange_events.adapters.fomc import FOMCScheduleAdapter
from exchange_events.adapters.fred import DEFAULT_BASE_URL as FRED_URL
from exchange_events.adapters.fred import DEFAULT_RELEASE_DATES_URL as FRED_RELEASE_DATES_URL
from exchange_events.adapters.fred import DEFAULT_SERIES as FRED_DEFAULT_SERIES
from exchange_events.adapters.fred import DEFAULT_SERIES_RELEASE_URL as FRED_SERIES_RELEASE_URL
from exchange_events.adapters.fred import FREDAdapter
from exchange_events.adapters.iana import IANATimezoneAdapter
from exchange_events.adapters.ism import ISMAdapter
from exchange_events.adapters.krx import KRXAdapter
from exchange_events.adapters.nse import DEFAULT_EXPIRY_URL as NSE_EXPIRY_URL
from exchange_events.adapters.nse import DEFAULT_HOLIDAY_URL as NSE_HOLIDAY_URL
from exchange_events.adapters.nse import DEFAULT_HOME_URL as NSE_HOME_URL
from exchange_events.adapters.nse import NSEAdapter
from exchange_events.domain.enums import EventType
from exchange_events.domain.errors import (
    NormalizationError,
    SourceRateLimitError,
    SourceUnavailableError,
)
from exchange_events.domain.query import DateRange, FetchParams
from exchange_events.normalizers.bea import BEANormalizer
from exchange_events.normalizers.bls import BLSNormalizer
from exchange_events.normalizers.cme import CMENormalizer
from exchange_events.normalizers.econ import EconCalendarNormalizer
from exchange_events.normalizers.fomc import FOMCScheduleNormalizer
from exchange_events.normalizers.fred import FREDNormalizer
from exchange_events.normalizers.ism import ISMNormalizer
from tests.fakes.http import FakeHttpClient

pytestmark = pytest.mark.unit

YEAR_RANGE = FetchParams(
    date_range=DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
)


# --- CME (Reference Data API v3, OAuth — see adapters/cme.py docstring for the
# 2026-07-22 rewrite off the blocked CmeWS/mvc AJAX endpoints) -----------------------
def _cme_config(**options: Any) -> AdapterConfig:
    return AdapterConfig(
        api_key="cme-client-id", options={"api_secret": "cme-client-secret", **options}
    )


def _register_cme_token(http: FakeHttpClient, token: str = "tok-123") -> None:
    http.register_json(
        CME_TOKEN_URL, {"access_token": token, "token_type": "Bearer", "expires_in": 1799}
    )


def test_cme_source_metadata():
    ad = CMEAdapter(FakeHttpClient())
    assert ad.source_name() == "cme_calendar"
    assert ad.supported_exchanges() == ["XCME"]
    assert set(ad.supported_event_types()) == {EventType.HOLIDAY, EventType.EXPIRY}


def test_cme_requires_oauth_credentials():
    ad = CMEAdapter(FakeHttpClient())
    with pytest.raises(SourceUnavailableError, match="CME_API_ID"):
        ad.fetch(YEAR_RANGE)


def test_cme_fetches_token_with_basic_auth_and_client_credentials_grant():
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules", {"_embedded": {"tradingSchedules": []}}
    )
    ad = CMEAdapter(http, _cme_config())
    ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.HOLIDAY]))
    token_call = next(c for c in http.calls if c.url == CME_TOKEN_URL)
    assert token_call.method == "POST"
    assert token_call.data == {"grant_type": "client_credentials"}
    expected_basic = "Basic " + base64.b64encode(b"cme-client-id:cme-client-secret").decode()
    assert token_call.headers["Authorization"] == expected_basic


def test_cme_holiday_derived_from_trading_schedule_gap():
    """Regression test for the actual holiday-derivation mechanism: CME's Reference
    Data API has no explicit holiday flag — a full closure shows up as that
    calendar date being entirely absent from the schedule (verified live against
    real Labor Day 2026-09-07 data — see adapters/cme.py docstring)."""
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules",
        {"_embedded": {"tradingSchedules": [{"tradingScheduleId": 999}]}},
    )
    dates = ["01-05-26", "01-06-26", "01-08-26", "01-09-26"]  # skips 01-07-26 (Wed)
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules/999",
        {"marketEventsByDate": [{"tradingDate": d, "marketEvents": []} for d in dates]},
    )
    ad = CMEAdapter(http, _cme_config())
    params = FetchParams(
        date_range=DateRange(datetime.date(2026, 1, 5), datetime.date(2026, 1, 9)),
        event_types=[EventType.HOLIDAY],
    )
    raw = ad.fetch(params)
    assert len(raw) == 1
    assert raw[0]["record_type"] == "holiday"
    assert raw[0]["date"] == "2026-01-07"


def test_cme_holiday_derivation_clamps_to_schedule_coverage():
    """The Reference Data API's schedule only covers a rolling forward window
    (confirmed live) — a requested range reaching further into the past must not
    be misread as one giant holiday gap outside what the schedule ever covered."""
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules",
        {"_embedded": {"tradingSchedules": [{"tradingScheduleId": 999}]}},
    )
    dates = ["01-05-26", "01-06-26", "01-07-26", "01-08-26", "01-09-26"]  # no gaps
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules/999",
        {"marketEventsByDate": [{"tradingDate": d, "marketEvents": []} for d in dates]},
    )
    ad = CMEAdapter(http, _cme_config())
    params = FetchParams(
        date_range=DateRange(datetime.date(2025, 12, 1), datetime.date(2026, 1, 9)),
        event_types=[EventType.HOLIDAY],
    )
    assert ad.fetch(params) == []


def test_cme_fetch_expiries_resolves_product_then_paginates_instruments():
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(
        f"{CME_REFDATA_URL}/products", {"_embedded": {"products": [{"productGuid": "GUID-ES"}]}}
    )
    http.register_json_sequence(
        f"{CME_REFDATA_URL}/instruments",
        [
            {
                "_embedded": {
                    "instruments": [{"globexSymbol": "ESU6", "lastTradeDate": "2026-09-18"}]
                },
                "_links": {"next": {"href": "https://x/instruments?page=1"}},
            },
            {
                "_embedded": {
                    "instruments": [
                        {"globexSymbol": "ESZ6", "lastTradeDate": "2026-12-18"},
                        {"globexSymbol": "ESZ9", "lastTradeDate": "2029-12-21"},  # outside range
                    ]
                },
                "_links": {},
            },
        ],
    )
    ad = CMEAdapter(
        http,
        _cme_config(products=[{"code": "ES", "instrument_type": "futures", "series": "quarterly"}]),
    )
    raw = ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.EXPIRY]))
    assert {r["id"] for r in raw} == {"ESU6", "ESZ6"}  # ESZ9 filtered out (outside 2026)
    assert all(r["record_type"] == "expiry" and r["product"] == "ES" for r in raw)


def test_cme_series_derived_from_symbol_month_code_not_static_label():
    """Real bug, found live: every ES instrument was labeled "quarterly" from a
    static per-product config value, regardless of its actual contract month --
    including a genuinely non-quarterly contract CME also lists under the same
    "ES" root symbol. series must be derived per-instrument from its own Globex
    symbol's month code (standard quarterly cycle: H/M/U/Z = Mar/Jun/Sep/Dec),
    not trusted from a single "this underlying is always quarterly" assumption.
    """
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(
        f"{CME_REFDATA_URL}/products", {"_embedded": {"products": [{"productGuid": "GUID-ES"}]}}
    )
    http.register_json(
        f"{CME_REFDATA_URL}/instruments",
        {
            "_embedded": {
                "instruments": [
                    {"globexSymbol": "ESU6", "lastTradeDate": "2026-09-18"},  # Sep -> quarterly
                    {"globexSymbol": "ESN6", "lastTradeDate": "2026-07-24"},  # Jul -> NOT quarterly
                ]
            },
            "_links": {},
        },
    )
    ad = CMEAdapter(
        http,
        _cme_config(products=[{"code": "ES", "instrument_type": "futures", "series": "quarterly"}]),
    )
    raw = ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.EXPIRY]))
    by_id = {r["id"]: r for r in raw}
    assert by_id["ESU6"]["series"] == "quarterly"
    assert by_id["ESN6"]["series"] == "monthly"


def test_series_for_falls_back_to_product_default_when_symbol_unparseable():
    product = {"code": "ES", "series": "quarterly"}
    assert _series_for(None, product) == "quarterly"  # no symbol at all
    assert _series_for("XYZ123", product) == "quarterly"  # doesn't start with the product code
    assert _series_for("ES", product) == "quarterly"  # no month-code suffix present
    assert _series_for("ESA6", product) == "quarterly"  # "A" isn't a real month code


def test_cme_fetch_expiries_skips_product_with_no_futures_match():
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(f"{CME_REFDATA_URL}/products", {"_embedded": {"products": []}})
    ad = CMEAdapter(
        http, _cme_config(products=[{"code": "XX", "instrument_type": "futures", "series": "q"}])
    )
    raw = ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.EXPIRY]))
    assert raw == []


def test_cme_fetch_expiries_queries_each_products_own_real_venue():
    """CME Group spans four real exchanges (CME/CBOT/NYMEX/COMEX) under one brand —
    e.g. YM (E-mini Dow) actually trades on CBOT (XCBT), not XCME itself, confirmed
    live against the real API. The product's own `exchange_globex` must be sent,
    not a hardcoded "XCME" for every product (see DEFAULT_PRODUCTS docstring)."""
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(f"{CME_REFDATA_URL}/products", {"_embedded": {"products": []}})
    ad = CMEAdapter(
        http,
        _cme_config(products=[
            {"code": "YM", "instrument_type": "futures", "series": "quarterly",
             "exchange_globex": "XCBT"},
        ]),
    )
    ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.EXPIRY]))
    products_call = next(c for c in http.calls if c.url == f"{CME_REFDATA_URL}/products")
    assert products_call.params["exchangeGlobex"] == "XCBT"
    assert products_call.params["globexProductCode"] == "YM"


def test_cme_fetch_holidays_and_expiries_end_to_end_through_normalizer():
    http = FakeHttpClient()
    _register_cme_token(http)
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules",
        {"_embedded": {"tradingSchedules": [{"tradingScheduleId": 999}]}},
    )
    http.register_json(
        f"{CME_REFDATA_URL}/tradingSchedules/999",
        {
            "marketEventsByDate": [
                {"tradingDate": d, "marketEvents": []}
                for d in ("01-05-26", "01-06-26", "01-08-26", "01-09-26")
            ]  # 01-07-26 (Wed) absent -> derived holiday
        },
    )
    http.register_json(
        f"{CME_REFDATA_URL}/products", {"_embedded": {"products": [{"productGuid": "GUID-ES"}]}}
    )
    http.register_json(
        f"{CME_REFDATA_URL}/instruments",
        {
            "_embedded": {
                "instruments": [{"globexSymbol": "ESH6", "lastTradeDate": "2026-01-08"}]
            },
            "_links": {},
        },
    )
    ad = CMEAdapter(
        http,
        _cme_config(products=[{"code": "ES", "instrument_type": "futures", "series": "quarterly"}]),
    )
    params = FetchParams(date_range=DateRange(datetime.date(2026, 1, 5), datetime.date(2026, 1, 9)))
    raw = ad.fetch(params)
    result = CMENormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    assert len(result.events) == 2
    holiday = next(e for e in result.events if e.event_type == EventType.HOLIDAY)
    expiry = next(e for e in result.events if e.event_type == EventType.EXPIRY)
    assert holiday.exchange == "XCME"
    assert holiday.date == datetime.date(2026, 1, 7)
    assert expiry.underlying == "ES"
    assert expiry.expiry_date == datetime.date(2026, 1, 8)


def test_cme_401_maps_to_source_unavailable():
    http = FakeHttpClient()
    http.register_json(CME_TOKEN_URL, {"error": "invalid_client"}, status_code=401)
    ad = CMEAdapter(http, _cme_config())
    with pytest.raises(SourceUnavailableError, match="access denied"):
        ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.HOLIDAY]))


def test_cme_429_maps_to_rate_limit():
    http = FakeHttpClient()
    http.register_json(CME_TOKEN_URL, {}, status_code=429)
    ad = CMEAdapter(http, _cme_config())
    with pytest.raises(SourceRateLimitError):
        ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.HOLIDAY]))


# --- NSE (session warm-up) ----------------------------------------------------------
def test_nse_warms_session_before_api_calls():
    http = FakeHttpClient()
    http.register_text(NSE_HOME_URL, "<html/>")
    http.register_json(NSE_HOLIDAY_URL, {"CM": [], "FO": [], "CD": []})
    http.register_json(NSE_EXPIRY_URL, {"data": []})
    ad = NSEAdapter(http, AdapterConfig(options={"underlyings": ["NIFTY"]}))
    ad.fetch(YEAR_RANGE)
    assert http.calls[0].url == NSE_HOME_URL


def test_nse_holidays_grouped_by_segment():
    http = FakeHttpClient()
    http.register_text(NSE_HOME_URL, "<html/>")
    http.register_json(NSE_HOLIDAY_URL, {
        "CM": [{"tradingDate": "26-Jan-2026", "description": "Republic Day"}],
        "FO": [{"tradingDate": "26-Jan-2026", "description": "Republic Day"}],
        "CD": [],
    })
    ad = NSEAdapter(http)
    raw = ad._fetch_holidays()
    assert {r["segments"][0] for r in raw} == {"CM", "FO"}


def test_nse_expiries_per_underlying():
    http = FakeHttpClient()
    http.register_json(NSE_EXPIRY_URL, {"data": [
        {"instrumentType": "options", "series": "weekly", "expiryDate": "29-Jan-2026"},
    ]})
    ad = NSEAdapter(http, AdapterConfig(options={"underlyings": ["NIFTY", "BANKNIFTY"]}))
    raw = ad._fetch_expiries(YEAR_RANGE)
    assert {r["underlying"] for r in raw} == {"NIFTY", "BANKNIFTY"}


# --- BSE ------------------------------------------------------------------------
def test_bse_holidays_and_expiries():
    http = FakeHttpClient()
    http.register_json(BSE_HOLIDAY_URL, {"Table": [
        {"holiday_date": "26/01/2026", "holiday_desc": "Republic Day"}
    ]})
    http.register_json(BSE_EXPIRY_URL, {"Table": [
        {"instrument_type": "options", "series": "weekly", "expiry_date": "29/01/2026"}
    ]})
    ad = BSEAdapter(http, AdapterConfig(options={"underlyings": ["SENSEX"]}))
    raw = ad.fetch(YEAR_RANGE)
    types = {r["record_type"] for r in raw}
    assert types == {"holiday", "expiry"}


def test_bse_401_maps_to_source_unavailable():
    http = FakeHttpClient()
    http.register_json(BSE_HOLIDAY_URL, {}, status_code=401)
    ad = BSEAdapter(http)
    with pytest.raises(SourceUnavailableError):
        ad.fetch(FetchParams(date_range=YEAR_RANGE.date_range, event_types=[EventType.HOLIDAY]))


# --- KRX (deferred stub) -------------------------------------------------------------
def test_krx_stub_returns_no_records():
    ad = KRXAdapter(FakeHttpClient())
    assert ad.fetch(YEAR_RANGE) == []
    assert ad.source_name() == "krx_calendar"
    assert ad.supported_exchanges() == ["XKRX"]


# --- FRED -----------------------------------------------------------------------
def test_fred_requires_api_key():
    ad = FREDAdapter(FakeHttpClient())
    with pytest.raises(SourceUnavailableError, match="FRED_API_KEY"):
        ad.fetch(YEAR_RANGE)


def test_fred_fetch_and_normalize_end_to_end():
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": [
        {"date": "2025-12-01", "value": "3.0"},
        {"date": "2026-01-01", "value": "3.4"},
    ]})
    ad = FREDAdapter(http, AdapterConfig(
        api_key="key123", options={"series": {"CPI": {
            "series_id": "CPIAUCSL", "release_name": "CPI", "agency": "BLS", "unit": "%",
        }}},
    ))
    raw = ad.fetch(YEAR_RANGE)
    result = FREDNormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    assert len(result.events) == 2
    assert result.events[1].actual == pytest.approx(3.4)
    assert result.events[1].previous == pytest.approx(3.0)  # chained from prior obs


def test_fred_missing_value_becomes_none_actual():
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": [{"date": "2026-01-01", "value": "."}]})
    ad = FREDAdapter(http, AdapterConfig(
        api_key="key123",
        options={"series": {"CPI": {"series_id": "X", "release_name": "CPI"}}},
    ))
    raw = ad.fetch(YEAR_RANGE)
    assert raw[0]["actual"] is None


def test_fred_default_series_covers_six_of_seven_required_releases():
    # JOLTS/FOMC were added specifically to close the gap found in DECISIONS.md
    # "Economic-release waterfall" — only ISM has no free official source at all.
    assert {"NFP", "CPI", "PPI", "PCE", "JOLTS", "FOMC"} <= FRED_DEFAULT_SERIES.keys()
    assert FRED_DEFAULT_SERIES["JOLTS"]["series_id"] == "JTSJOL"
    assert FRED_DEFAULT_SERIES["FOMC"]["series_id"] == "DFEDTARU"


# --- FRED forward schedule (fred/series/release + fred/release/dates) -------------
def _cpi_config(api_key="key123", **extra_options):
    return AdapterConfig(
        api_key=api_key,
        options={"series": {"CPI": {"series_id": "CPIAUCSL", "release_name": "CPI"}},
                 **extra_options},
    )


def test_fred_schedule_adds_future_date_with_no_observation_yet():
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": [{"date": "2026-01-13", "value": "3.4"}]})
    http.register_json(FRED_SERIES_RELEASE_URL, {"releases": [{"id": 10, "name": "CPI"}]})
    http.register_json(FRED_RELEASE_DATES_URL, {"release_dates": [
        {"release_id": 10, "date": "2026-01-13"},  # already has an observation
        {"release_id": 10, "date": "2026-02-11"},  # scheduled, not published yet
    ]})
    ad = FREDAdapter(http, _cpi_config())
    raw = ad.fetch(YEAR_RANGE)
    by_date = {r["date"]: r for r in raw}
    assert set(by_date) == {"2026-01-13", "2026-02-11"}
    assert by_date["2026-01-13"]["actual"] == "3.4"
    assert by_date["2026-02-11"]["actual"] is None  # scheduled-only, no data yet


def test_fred_schedule_does_not_duplicate_a_date_with_an_observation():
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": [{"date": "2026-01-13", "value": "3.4"}]})
    http.register_json(FRED_SERIES_RELEASE_URL, {"releases": [{"id": 10, "name": "CPI"}]})
    http.register_json(FRED_RELEASE_DATES_URL, {"release_dates": [
        {"release_id": 10, "date": "2026-01-13"},
    ]})
    ad = FREDAdapter(http, _cpi_config())
    raw = ad.fetch(YEAR_RANGE)
    assert len(raw) == 1  # not two records for the same date


def test_fred_schedule_lookup_failure_is_isolated_not_raised():
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": [{"date": "2026-01-13", "value": "3.4"}]})
    # series_release / release_dates deliberately NOT registered -> 404 -> caught,
    # logged, and skipped (§7 error isolation) rather than raised.
    ad = FREDAdapter(http, _cpi_config())
    raw = ad.fetch(YEAR_RANGE)
    assert len(raw) == 1
    assert raw[0]["actual"] == "3.4"


def test_fred_schedule_can_be_disabled_via_config():
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": []})
    http.register_json(FRED_SERIES_RELEASE_URL, {"releases": [{"id": 10, "name": "CPI"}]})
    http.register_json(FRED_RELEASE_DATES_URL, {"release_dates": [
        {"release_id": 10, "date": "2026-02-11"},
    ]})
    ad = FREDAdapter(http, _cpi_config(fetch_schedule=False))
    raw = ad.fetch(YEAR_RANGE)
    assert raw == []
    assert not any(c.url == FRED_SERIES_RELEASE_URL for c in http.calls)


def test_fred_fomc_is_excluded_from_generic_schedule_fetch():
    # DFEDTARU belongs to a *daily*-updating FRED release (H.15), unrelated to
    # specific FOMC meeting dates — scheduling that is FOMCScheduleAdapter's job,
    # not a generic fred/release/dates lookup (would be noisy/wrong otherwise).
    assert FRED_DEFAULT_SERIES["FOMC"]["skip_schedule"] is True
    http = FakeHttpClient()
    http.register_json(FRED_URL, {"observations": []})
    ad = FREDAdapter(http, AdapterConfig(
        api_key="key123", options={"series": {"FOMC": FRED_DEFAULT_SERIES["FOMC"]}},
    ))
    ad.fetch(YEAR_RANGE)
    assert not any(FRED_SERIES_RELEASE_URL in c.url for c in http.calls)


# --- FOMC schedule (federalreserve.gov's own meeting calendar) ---------------------
# Structure captured directly from the real page on 2026-07-22 (not guessed):
# each year is a panel; each meeting is a row with a month + day-range, plus a
# Statement press-release link *once the meeting has happened* (absent for
# genuinely future meetings — confirmed on the live page).
FOMC_SAMPLE_HTML = """
<html><body>
<div class="col-xs-12 col-sm-8 col-md-9">
<div class="panel panel-default">
  <div class="panel-heading"><h4><a id="1">2026 FOMC Meetings</a></h4></div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month"><strong>January</strong></div>
    <div class="fomc-meeting__date">27-28</div>
    <div class="col-lg-2">
      <strong>Statement:</strong><br>
      <a href="/monetarypolicy/files/monetary20260128a1.pdf">PDF</a> |
      <a href="/newsevents/pressreleases/monetary20260128a.htm">HTML</a><br>
      <a href="/newsevents/pressreleases/monetary20260128a1.htm">Implementation Note</a>
    </div>
  </div>
  <div class="fomc-meeting--shaded row fomc-meeting">
    <div class="fomc-meeting__month"><strong>July</strong></div>
    <div class="fomc-meeting__date">28-29</div>
    <div class="col-lg-2"></div>
  </div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month"><strong>August</strong></div>
    <div class="fomc-meeting__date">22 (notation vote)</div>
    <div class="col-lg-2"></div>
  </div>
  <div class="panel-footer"></div>
</div>
</div>
</body></html>
"""


def test_fomc_source_metadata():
    ad = FOMCScheduleAdapter(FakeHttpClient())
    assert ad.source_name() == "fomc_schedule"
    assert ad.supported_exchanges() is None
    assert ad.supported_event_types() == [EventType.ECONOMIC_RELEASE]


def test_fomc_parses_past_meeting_from_statement_link():
    ad = FOMCScheduleAdapter(FakeHttpClient())
    records = ad.parse_html(FOMC_SAMPLE_HTML, YEAR_RANGE)
    by_date = {r["date"]: r for r in records}
    # The authoritative statement-link date, not the visible "27-28" range text.
    assert "2026-01-28" in by_date
    assert by_date["2026-01-28"]["release_code"] == "FOMC"
    assert by_date["2026-01-28"]["actual"] is None  # schedule marker only


def test_fomc_computes_future_meeting_date_from_month_and_day_range():
    ad = FOMCScheduleAdapter(FakeHttpClient())
    records = ad.parse_html(FOMC_SAMPLE_HTML, YEAR_RANGE)
    by_date = {r["date"]: r for r in records}
    # No statement link exists yet for July -> computed from "July" + last day "29".
    assert "2026-07-29" in by_date


def test_fomc_handles_single_day_notation_vote_format():
    ad = FOMCScheduleAdapter(FakeHttpClient())
    records = ad.parse_html(FOMC_SAMPLE_HTML, YEAR_RANGE)
    by_date = {r["date"]: r for r in records}
    assert "2026-08-22" in by_date


def test_fomc_respects_requested_date_range():
    narrow = FetchParams(
        date_range=DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    )
    ad = FOMCScheduleAdapter(FakeHttpClient())
    records = ad.parse_html(FOMC_SAMPLE_HTML, narrow)
    assert [r["date"] for r in records] == ["2026-01-28"]


def test_fomc_fetch_end_to_end_through_normalizer():
    http = FakeHttpClient()
    http.register_text("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        FOMC_SAMPLE_HTML)
    ad = FOMCScheduleAdapter(http)
    raw = ad.fetch(YEAR_RANGE)
    result = FOMCScheduleNormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    assert len(result.events) == 3
    jan = next(e for e in result.events if e.date == datetime.date(2026, 1, 28))
    assert jan.release_code == "FOMC"
    assert jan.country == "US"
    assert jan.timestamp_utc == datetime.datetime(2026, 1, 28, 19, 0, tzinfo=datetime.UTC)


# --- BLS (tier 2 — official backstop for NFP/CPI/PPI/JOLTS) ------------------------
def test_bls_source_metadata():
    ad = BLSAdapter(FakeHttpClient())
    assert ad.source_name() == "bls_api"
    assert ad.supported_exchanges() is None
    assert ad.supported_event_types() == [EventType.ECONOMIC_RELEASE]


def test_bls_fetch_and_normalize_end_to_end():
    http = FakeHttpClient()
    http.register_json(BLS_URL, {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "CUUR0000SA0", "data": [
            # BLS returns newest-first.
            {"year": "2026", "period": "M06", "periodName": "June", "value": "321.500"},
            {"year": "2026", "period": "M05", "periodName": "May", "value": "320.100"},
        ]}]}
    })
    ad = BLSAdapter(http, AdapterConfig(options={"series": {
        "CPI": {"series_id": "CUUR0000SA0", "release_name": "CPI",
                "agency": "BLS", "unit": "index"},
    }}))
    raw = ad.fetch(YEAR_RANGE)
    result = BLSNormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    assert len(result.events) == 2
    june = next(e for e in result.events if e.period == "June")
    assert june.actual == pytest.approx(321.5)
    assert june.previous == pytest.approx(320.1)  # chained from May


def test_bls_requests_multiple_series_in_one_post_body():
    # Regression test: BLS's v2 API rejects comma-joined multi-series GET
    # requests (confirmed live: REQUEST_FAILED/Results=null for 2+ ids) — POST
    # with a JSON "seriesid" array is required to fetch more than one series.
    http = FakeHttpClient()
    http.register_json(BLS_URL, {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [
            {"seriesID": "CUUR0000SA0", "data": [
                {"year": "2026", "period": "M06", "periodName": "June", "value": "321.5"},
            ]},
            {"seriesID": "CES0000000001", "data": [
                {"year": "2026", "period": "M06", "periodName": "June", "value": "159000"},
            ]},
        ]}
    })
    ad = BLSAdapter(http, AdapterConfig(options={"series": {
        "CPI": {"series_id": "CUUR0000SA0", "release_name": "CPI"},
        "NFP": {"series_id": "CES0000000001", "release_name": "NFP"},
    }}))
    raw = ad.fetch(YEAR_RANGE)
    assert {r["release_code"] for r in raw} == {"CPI", "NFP"}
    assert http.calls[0].method == "POST"
    assert set(http.calls[0].json["seriesid"]) == {"CUUR0000SA0", "CES0000000001"}


def test_bls_raises_source_unavailable_when_api_reports_failure():
    http = FakeHttpClient()
    http.register_json(BLS_URL, {
        "status": "REQUEST_NOT_PROCESSED",
        "message": ["some real BLS-side error"],
        "Results": None,
    })
    ad = BLSAdapter(http, AdapterConfig(
        options={"series": {"CPI": {"series_id": "CUUR0000SA0", "release_name": "CPI"}}}
    ))
    with pytest.raises(SourceUnavailableError, match="some real BLS-side error"):
        ad.fetch(YEAR_RANGE)


def test_bls_works_without_api_key():
    # Unlike FRED/BEA, BLS answers unkeyed at a lower rate limit (§ adapters/bls.py).
    http = FakeHttpClient()
    http.register_json(BLS_URL, {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "CUUR0000SA0", "data": [
            {"year": "2026", "period": "M06", "periodName": "June", "value": "321.5"},
        ]}]}
    })
    ad = BLSAdapter(http, AdapterConfig(
        options={"series": {"CPI": {"series_id": "CUUR0000SA0", "release_name": "CPI"}}}
    ))
    raw = ad.fetch(YEAR_RANGE)
    assert len(raw) == 1
    assert "registrationkey" not in http.calls[0].json


def test_bls_filters_to_requested_date_range():
    http = FakeHttpClient()
    http.register_json(BLS_URL, {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "CUUR0000SA0", "data": [
            {"year": "2025", "period": "M06", "periodName": "June", "value": "300.0"},
            {"year": "2026", "period": "M06", "periodName": "June", "value": "321.5"},
        ]}]}
    })
    ad = BLSAdapter(http, AdapterConfig(
        options={"series": {"CPI": {"series_id": "CUUR0000SA0", "release_name": "CPI"}}}
    ))
    raw = ad.fetch(YEAR_RANGE)  # 2026 only
    assert len(raw) == 1
    assert raw[0]["date"] == "2026-06-01"


def test_bls_unknown_series_id_in_response_is_ignored():
    http = FakeHttpClient()
    http.register_json(BLS_URL, {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "SOMETHING_ELSE", "data": [
            {"year": "2026", "period": "M06", "periodName": "June", "value": "1.0"},
        ]}]}
    })
    ad = BLSAdapter(http, AdapterConfig(
        options={"series": {"CPI": {"series_id": "CUUR0000SA0", "release_name": "CPI"}}}
    ))
    assert ad.fetch(YEAR_RANGE) == []


# --- BEA (tier 3 — official backstop for PCE) --------------------------------------
def test_bea_source_metadata():
    ad = BEAAdapter(FakeHttpClient())
    assert ad.source_name() == "bea_api"
    assert ad.supported_exchanges() is None


def test_bea_requires_api_key():
    ad = BEAAdapter(FakeHttpClient())
    with pytest.raises(SourceUnavailableError, match="UserID"):
        ad.fetch(YEAR_RANGE)


def test_bea_fetch_and_normalize_end_to_end():
    http = FakeHttpClient()
    http.register_json(BEA_URL, {"BEAAPI": {"Results": {"Data": [
        {"TableName": "T20806", "LineNumber": "1", "TimePeriod": "2026M05", "DataValue": "125.400"},
        {"TableName": "T20806", "LineNumber": "1", "TimePeriod": "2026M06", "DataValue": "126.100"},
        {"TableName": "T20806", "LineNumber": "2", "TimePeriod": "2026M06", "DataValue": "999.0"},
    ]}}})
    ad = BEAAdapter(http, AdapterConfig(api_key="userid123", options={"table": {
        "release_code": "PCE", "release_name": "PCE Price Index", "table_name": "T20806",
        "line_number": "1", "frequency": "M", "agency": "BEA", "unit": "%",
    }}))
    raw = ad.fetch(YEAR_RANGE)
    result = BEANormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    assert len(result.events) == 2
    june = next(e for e in result.events if e.date == datetime.date(2026, 6, 1))
    assert june.actual == pytest.approx(126.1)
    assert june.previous == pytest.approx(125.4)
    assert june.release_code == "PCE"


def test_bea_ignores_other_line_numbers_in_same_table():
    http = FakeHttpClient()
    http.register_json(BEA_URL, {"BEAAPI": {"Results": {"Data": [
        {"TableName": "T20806", "LineNumber": "1", "TimePeriod": "2026M06", "DataValue": "126.1"},
        {"TableName": "T20806", "LineNumber": "7", "TimePeriod": "2026M06", "DataValue": "1.0"},
    ]}}})
    ad = BEAAdapter(http, AdapterConfig(api_key="k"))
    raw = ad.fetch(YEAR_RANGE)
    assert len(raw) == 1


# --- ISM (best-effort only — no official free source exists) -----------------------
def test_ism_source_metadata():
    ad = ISMAdapter(FakeHttpClient())
    assert ad.source_name() == "ism_pmi"
    assert ad.supported_exchanges() is None


def test_ism_raises_clearly_when_unconfigured():
    ad = ISMAdapter(FakeHttpClient())
    with pytest.raises(SourceUnavailableError, match="no provider configured"):
        ad.fetch(YEAR_RANGE)


def test_ism_fetch_and_normalize_with_configured_provider():
    http = FakeHttpClient()
    http.register_json("https://example.com/ism", [
        {"date": "2026-01-02", "value": "48.5", "event": "ISM Manufacturing PMI"},
        {"date": "2026-01-02", "value": "50.1", "event": "ISM Services PMI"},
    ])
    ad = ISMAdapter(http, AdapterConfig(
        urls={"ism": "https://example.com/ism"},
        options={
            "field_map": {"date": "date", "actual": "value"},
            "indicator_match": {"event": "ISM Manufacturing PMI"},
        },
    ))
    raw = ad.fetch(YEAR_RANGE)
    result = ISMNormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    assert len(result.events) == 1
    assert result.events[0].release_code == "ISM_PMI"
    assert result.events[0].actual == pytest.approx(48.5)


def test_ism_no_indicator_match_keeps_everything():
    http = FakeHttpClient()
    http.register_json("https://example.com/ism", [{"date": "2026-01-02", "value": "48.5"}])
    ad = ISMAdapter(http, AdapterConfig(urls={"ism": "https://example.com/ism"}))
    raw = ad.fetch(YEAR_RANGE)
    assert len(raw) == 1
    assert raw[0]["actual"] == "48.5"


# --- IANA (offline, stdlib) ----------------------------------------------------------
def test_iana_detects_us_dst_transitions_2026():
    ad = IANATimezoneAdapter(AdapterConfig(options={"zones": ["America/New_York"]}))
    raw = ad.fetch(YEAR_RANGE)
    dates = {r["date"] for r in raw}
    assert "2026-03-08" in dates  # spring forward
    assert "2026-11-01" in dates  # fall back
    assert ad.source_name() == "iana_tz"
    assert ad.supported_exchanges() is None


def test_iana_no_transitions_for_non_dst_zone():
    ad = IANATimezoneAdapter(AdapterConfig(options={"zones": ["Asia/Kolkata"]}))
    assert ad.fetch(YEAR_RANGE) == []


def test_iana_default_zones_used_when_unconfigured():
    ad = IANATimezoneAdapter()
    raw = ad.fetch(FetchParams(date_range=DateRange(
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)
    )))
    assert any(r["iana_zone"] == "America/New_York" for r in raw)


# --- MarketWatch econ calendar (fixture-validated; live path uses DataDome-blocked page) --
SAMPLE_TABLE_HTML = """
<html><body>
<table class="calendar">
  <tbody>
    <tr><td>2/6/26</td><td>8:30am</td><td>Nonfarm Payrolls</td>
        <td>180K</td><td>170K</td><td>150K</td></tr>
    <tr><td>1/13/26</td><td>8:30am</td><td>CPI</td>
        <td>3.4%</td><td>3.1%</td><td>3.0%</td></tr>
    <tr><td>1/20/26</td><td>10:00am</td><td>Some Unrelated Release</td>
        <td>1</td><td>2</td><td>3</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_econ_parse_html_extracts_configured_releases_only():
    ad = EconCalendarAdapter(FakeHttpClient())
    raw = ad.parse_html(SAMPLE_TABLE_HTML, YEAR_RANGE)
    codes = {r["release_code"] for r in raw}
    assert codes == {"NFP", "CPI"}  # "Some Unrelated Release" skipped


def test_econ_parse_html_respects_date_range():
    ad = EconCalendarAdapter(FakeHttpClient())
    narrow = FetchParams(
        date_range=DateRange(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
    )
    raw = ad.parse_html(SAMPLE_TABLE_HTML, narrow)
    assert {r["release_code"] for r in raw} == {"NFP"}


def test_econ_end_to_end_through_normalizer():
    ad = EconCalendarAdapter(FakeHttpClient())
    raw = ad.parse_html(SAMPLE_TABLE_HTML, YEAR_RANGE)
    result = EconCalendarNormalizer().normalize(raw, ad.source_name())
    assert result.errors == []
    nfp = next(e for e in result.events if e.release_code == "NFP")
    assert nfp.forecast == pytest.approx(170_000.0)  # "170K" -> 170000
    assert nfp.previous == pytest.approx(150_000.0)


def test_econ_fetch_401_maps_to_source_unavailable():
    http = FakeHttpClient()
    http.register_text(
        "https://www.marketwatch.com/economy-politics/calendar", "blocked", status_code=401
    )
    ad = EconCalendarAdapter(http)
    with pytest.raises(SourceUnavailableError, match="access denied"):
        ad.fetch(YEAR_RANGE)


def test_econ_malformed_html_raises_normalization_error():
    ad = EconCalendarAdapter(FakeHttpClient())
    # lxml is extremely lenient, so force a type error instead of relying on parse failure.
    with pytest.raises(NormalizationError):
        ad.parse_html(None, YEAR_RANGE)  # type: ignore[arg-type]
