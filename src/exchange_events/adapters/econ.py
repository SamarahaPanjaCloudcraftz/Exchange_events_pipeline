"""Economic-calendar adapter (design doc §5.1) — MarketWatch, config-driven.

Parses the calendar table at ``marketwatch.com/economy-politics/calendar`` with
lxml. Release codes are **config, not hardcoded** (§5.1 design note): a mapping of
page label -> canonical release code is supplied via
``config.options["release_codes"]``, defaulting to the 7 releases named in the
requirements doc. Adding a release the page already lists is a config change.

**Known operational risk (recorded in DECISIONS.md):** MarketWatch fronts this
page with DataDome, a JavaScript-challenge bot wall — verified during the
Phase-6 spike, every plain request (with or without a warmed cookie jar) returns
HTTP 401 and a DataDome challenge stub, never the calendar HTML. This cannot be
solved by header/session tuning alone; it needs either a headless-browser fetch
layer (e.g. Playwright) or a DataDome-aware unblocking proxy, neither of which is
built here. Until one is wired in, treat this adapter as **fixture-validated,
not live-validated**; `EventRepository` still receives FRED actuals regardless,
per the fallback already recorded in DECISIONS.md.

Emits the raw schema documented in ``normalizers/econ.py``.
"""

from __future__ import annotations

import datetime
from typing import Any

from lxml import html as lxml_html

from ..domain.enums import EventType
from ..domain.errors import NormalizationError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

# Common formats MarketWatch's calendar page has used for its date column.
# Kept local (not imported from normalizers/) — adapters and normalizers are
# sibling packages, neither imports the other (P1/P2 layering).
_DATE_FORMATS = ("%m/%d/%y", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d")


def _try_parse_date(value: str) -> datetime.date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None

DEFAULT_CALENDAR_URL = "https://www.marketwatch.com/economy-politics/calendar"

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.marketwatch.com/",
}

# The 7 releases named in the requirements doc, mapped to canonical codes.
# Purely config (§5.1 design note) — overridable via config.options["release_codes"].
DEFAULT_RELEASE_CODES: dict[str, str] = {
    "Nonfarm Payrolls": "NFP",
    "CPI": "CPI",
    "Consumer Price Index": "CPI",
    "PPI": "PPI",
    "Producer Price Index": "PPI",
    "PCE Index": "PCE",
    "ISM Manufacturing": "ISM_PMI",
    "ISM Manufacturing PMI": "ISM_PMI",
    "JOLTS Job Openings": "JOLTS",
    "FOMC Rate Decision": "FOMC",
    "FOMC Announcement": "FOMC",
}

# Table row selector is a best-effort default for MarketWatch's current markup;
# overridable via config.options["row_xpath"] if the page structure changes.
DEFAULT_ROW_XPATH = "//table[contains(@class,'calendar')]//tbody/tr"


class EconCalendarAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "econ_calendar"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.ECONOMIC_RELEASE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    @property
    def _release_codes(self) -> dict[str, str]:
        return self._config.option("release_codes") or DEFAULT_RELEASE_CODES

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        url = self._config.url("calendar", DEFAULT_CALENDAR_URL)
        page_html = self._get_text(url, headers=DEFAULT_HEADERS)
        return self.parse_html(page_html, params)

    def parse_html(self, page_html: str, params: FetchParams) -> list[dict[str, Any]]:
        """Parse the calendar HTML into raw records. Public/pure for fixture tests."""
        try:
            tree = lxml_html.fromstring(page_html)
        except Exception as exc:  # noqa: BLE001
            raise NormalizationError(f"unparseable calendar HTML: {exc}") from exc

        row_xpath = self._config.option("row_xpath") or DEFAULT_ROW_XPATH
        records: list[dict[str, Any]] = []
        rows: Any = tree.xpath(row_xpath)  # lxml's xpath return type is a broad union
        for row in rows:
            cells = [c.text_content().strip() for c in row.xpath(".//td")]
            if len(cells) < 5:
                continue
            date_str, time_str, label, actual, forecast, *rest = (*cells, "", "", "", "", "")
            code = self._release_codes.get(label.strip())
            if code is None:
                continue  # not one of the configured releases — skip silently
            previous = rest[0] if rest else ""
            parsed_date = _try_parse_date(date_str.strip())
            # Unparseable dates are passed through — the normalizer will raise a
            # captured NormalizationError for them (partial-failure contract,
            # §5.2) rather than the adapter silently dropping the row.
            if parsed_date is not None and not params.date_range.contains(parsed_date):
                continue
            records.append(
                {
                    "release_code": code,
                    "release_name": label.strip(),
                    "date": date_str.strip(),
                    "time": time_str.strip() or None,
                    "forecast": forecast.strip() or None,
                    "previous": previous.strip() or None,
                    "actual": actual.strip() or None,
                }
            )
        return records
