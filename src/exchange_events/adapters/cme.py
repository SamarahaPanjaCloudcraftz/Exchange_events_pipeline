"""CME adapter (design doc §5.1) — XCME holidays + expiries. Production priority.

**v2 rewrite (2026-07-22):** the original ``cmegroup.com/CmeWS/mvc/`` AJAX
endpoints this adapter used are blocked domain-wide from every sandbox tested
here — confirmed the block covers plain static HTML pages too, not just the
JSON calendar service, so no header/session trick fixes it (see DECISIONS.md
"CME Reference Data API"). Replaced with CME's own **Reference Data API v3**
(``refdata.api.cmegroup.com``), a genuinely free, officially documented,
OAuth-authenticated API distinct from CME's paid real-time market-data feeds —
confirmed live and reachable from this sandbox, unlike the main website.

**Auth:** OAuth2 client-credentials grant against ``auth.cmegroup.com`` (HTTP
Basic auth with the API ID/secret from a CME Group Customer Center account —
``CME_API_ID`` / ``CME_API_SECRET``). A fresh token is fetched per ``fetch()``
call rather than cached/refreshed (tokens last ~30 minutes per the live
response's ``expires_in``, comfortably longer than one ingestion run).

**Expiries:** ``/refdata/v3/products`` resolves each configured underlying
(``globexProductCode`` + ``exchangeGlobex=XCME`` + ``securityType=FUT``) to its
``productGuid``, then ``/refdata/v3/instruments?productGuid=...`` (paginated via
the response's HAL ``_links.next``) returns real per-contract data — confirmed
live: exact symbols (e.g. "ESU6"), ``lastTradeDate``, ``finalSettlementDate``,
``contractMonth``. Note: the endpoint's date-filter params (``startedAfter``
etc.) reject every format tried here (400 "Bad request data type in filter");
unresolved, so filtering to ``params.date_range`` is done client-side instead —
the same pattern normalizers/other adapters already use, and the instrument
counts per product are small enough (tens, not thousands) that this is cheap.

**Holidays:** there is no direct "list of holidays" endpoint. Instead,
``/refdata/v3/tradingSchedules`` (filtered by ``globexGroupCode``) returns each
trading day's open/preopen/close timestamps — a full CME holiday closure shows
up as that calendar date being **entirely absent** from the schedule, not as a
flagged/labeled entry. Verified against a real, known holiday (Labor Day
2026-09-07: confirmed absent from the ES equity-index schedule, while every
surrounding weekday was present) and confirmed present dates are always
Monday-Friday (weekends are naturally absent too, not holidays). Holidays are
therefore *derived* via gap analysis: any Mon-Fri date within the schedule's own
covered range that's missing from its trading-date set. The schedule used is
the equity-index group (``DEFAULT_HOLIDAY_GROUP_CODE = "ES"``) since that's what
this adapter's configured products (ES, NQ) actually need — other CME product
classes (e.g. agricultural, FX) can run on different session calendars, so this
is deliberately scoped to equities, not asserted as CME's universal calendar.

**Known limitation:** the Reference Data API's own schedule window only covers
today forward roughly a year (confirmed live), not arbitrary history — holiday
derivation is clamped to the schedule's own covered range intersected with the
requested ``params.date_range``, so a request reaching further into the past
than the schedule covers silently yields no holidays for that portion (never
false positives from treating out-of-coverage dates as holidays).

Emits the raw schema documented in ``normalizers/exchange.py``.
"""

from __future__ import annotations

import datetime
from typing import Any

from ..domain.enums import EventType
from ..domain.errors import SourceUnavailableError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_TOKEN_URL = "https://auth.cmegroup.com/as/token.oauth2"
DEFAULT_REFDATA_BASE_URL = "https://refdata.api.cmegroup.com/refdata/v3"

# Underlyings the ingestion engine pulls expiries for by default; overridable via
# config.options["products"] (P4: extending coverage is a config change).
#
# "CME Group" is a holding company for four exchanges with their own real MIC
# codes — CME itself (XCME), CBOT (XCBT), NYMEX (XNYM), COMEX (XCEC) — and the
# Reference Data API's ``/products`` lookup needs each product's *real* venue,
# confirmed live per code (not assumed): YM/ZN/ZB are XCBT, CL/NG are XNYM,
# GC/SI are XCEC; only ES/NQ/RTY/6E are actually XCME. Per the user's explicit
# choice, this dashboard still shows all of them under the single "XCME"/"CME
# Group" tab — "exchange_globex" here is purely which venue to query against,
# not the domain event's ``exchange`` field (always "XCME" via CMENormalizer).
DEFAULT_PRODUCTS: list[dict[str, str]] = [
    {"code": "ES", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCME"},
    {"code": "NQ", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCME"},
    {"code": "YM", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCBT"},
    {"code": "RTY", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCME"},
    {"code": "ZN", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCBT"},
    {"code": "ZB", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCBT"},
    {"code": "CL", "instrument_type": "futures", "series": "monthly", "exchange_globex": "XNYM"},
    {"code": "NG", "instrument_type": "futures", "series": "monthly", "exchange_globex": "XNYM"},
    {"code": "GC", "instrument_type": "futures", "series": "monthly", "exchange_globex": "XCEC"},
    {"code": "SI", "instrument_type": "futures", "series": "monthly", "exchange_globex": "XCEC"},
    {"code": "6E", "instrument_type": "futures", "series": "quarterly", "exchange_globex": "XCME"},
]

# The trading-schedule group used to derive holidays via gap analysis (see
# module docstring — deliberately the equity-index calendar, not asserted as
# every CME product class's calendar).
DEFAULT_HOLIDAY_GROUP_CODE = "ES"

_WEEKEND = (5, 6)  # datetime.date.weekday(): Saturday, Sunday


class CMEAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "cme_calendar"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.HOLIDAY, EventType.EXPIRY]

    def supported_exchanges(self) -> list[str] | None:
        return ["XCME"]

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        client_id = self._config.api_key
        client_secret = self._config.option("api_secret")
        if not client_id or not client_secret:
            raise SourceUnavailableError(
                "cme_calendar: CME_API_ID and CME_API_SECRET are required "
                "(CME Reference Data API v3 — see adapters/cme.py docstring)"
            )
        token = self._get_token(client_id, client_secret)
        want = params.event_types
        records: list[dict[str, Any]] = []
        if want is None or EventType.HOLIDAY in want:
            records.extend(self._fetch_holidays(token, params))
        if want is None or EventType.EXPIRY in want:
            records.extend(self._fetch_expiries(token, params))
        return records

    def _get_token(self, client_id: str, client_secret: str) -> str:
        url = self._config.url("token", DEFAULT_TOKEN_URL)
        payload = self._post_form(
            url, {"grant_type": "client_credentials"}, basic_auth=(client_id, client_secret)
        )
        token = payload.get("access_token")
        if not token:
            raise SourceUnavailableError(
                "cme_calendar: OAuth token response missing access_token"
            )
        return str(token)

    def _bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _refdata_get(self, token: str, path: str, query: dict[str, Any]) -> Any:
        base = self._config.url("refdata", DEFAULT_REFDATA_BASE_URL)
        return self._get_json(f"{base}{path}", params=query, headers=self._bearer(token))

    # --- holidays (derived via trading-schedule gap analysis) ----------------------
    def _fetch_holidays(self, token: str, params: FetchParams) -> list[dict[str, Any]]:
        group_code = self._config.option("holiday_group_code", DEFAULT_HOLIDAY_GROUP_CODE)
        listing = self._refdata_get(
            token, "/tradingSchedules", {"globexGroupCode": group_code, "size": 5}
        )
        schedules = listing.get("_embedded", {}).get("tradingSchedules", [])
        if not schedules:
            self._logger.warning(
                "cme_calendar: no trading schedule found for holiday derivation",
                group_code=group_code,
            )
            return []
        schedule_id = schedules[0]["tradingScheduleId"]
        full = self._refdata_get(token, f"/tradingSchedules/{schedule_id}", {})
        entries = full.get("marketEventsByDate", [])
        trading_dates: set[datetime.date] = set()
        for entry in entries:
            trading_dates.add(datetime.datetime.strptime(entry["tradingDate"], "%m-%d-%y").date())
        if not trading_dates:
            return []

        # Clamp to what the schedule itself actually covers — never flag a date
        # outside the API's own returned window as a "holiday" by absence.
        lo = max(params.date_range.start, min(trading_dates))
        hi = min(params.date_range.end, max(trading_dates))

        out: list[dict[str, Any]] = []
        day = lo
        while day <= hi:
            if day.weekday() not in _WEEKEND and day not in trading_dates:
                out.append(
                    {
                        "record_type": "holiday",
                        "date": day.isoformat(),
                        "name": "CME Holiday (derived: no trading session scheduled)",
                        "session": "closed",
                        "segments": [group_code],
                        "id": f"cme-holiday:{group_code}:{day.isoformat()}",
                    }
                )
            day += datetime.timedelta(days=1)
        return out

    # --- expiries (products -> instruments, paginated) ------------------------------
    def _fetch_expiries(self, token: str, params: FetchParams) -> list[dict[str, Any]]:
        products = self._config.option("products") or DEFAULT_PRODUCTS
        out: list[dict[str, Any]] = []
        for product in products:
            code = product["code"]
            exchange_globex = product.get("exchange_globex", "XCME")
            guid = self._resolve_product_guid(token, code, exchange_globex)
            if guid is None:
                self._logger.warning(
                    "cme_calendar: no futures product found",
                    globex_product_code=code, exchange_globex=exchange_globex,
                )
                continue
            out.extend(self._fetch_instrument_expiries(token, guid, product, params))
        return out

    def _resolve_product_guid(
        self, token: str, globex_product_code: str, exchange_globex: str = "XCME"
    ) -> str | None:
        listing = self._refdata_get(
            token,
            "/products",
            {
                "exchangeGlobex": exchange_globex,
                "globexProductCode": globex_product_code,
                "securityType": "FUT",
            },
        )
        entries = listing.get("_embedded", {}).get("products", [])
        if not entries:
            return None
        return str(entries[0]["productGuid"])

    def _fetch_instrument_expiries(
        self, token: str, product_guid: str, product: dict[str, str], params: FetchParams
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 0
        while True:
            payload = self._refdata_get(
                token, "/instruments", {"productGuid": product_guid, "page": page, "size": 100}
            )
            instruments = payload.get("_embedded", {}).get("instruments", [])
            for inst in instruments:
                last_trade = inst.get("lastTradeDate")
                if not last_trade:
                    continue
                day = datetime.date.fromisoformat(last_trade)
                if not params.date_range.contains(day):
                    continue
                out.append(
                    {
                        "record_type": "expiry",
                        "product": product["code"],
                        "instrument_type": product.get("instrument_type", "futures"),
                        "series": product.get("series", "quarterly"),
                        "expiry_date": last_trade,
                        "id": inst.get("globexSymbol"),
                    }
                )
            if not payload.get("_links", {}).get("next"):
                break
            page += 1
        return out
