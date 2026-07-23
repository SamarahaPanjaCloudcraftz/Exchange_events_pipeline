"""FOMC schedule adapter (design doc §5.1) — forward FOMC meeting/decision calendar.

Parses the Federal Reserve's own published FOMC calendar
(federalreserve.gov/monetarypolicy/fomccalendars.htm) for upcoming meeting/decision
dates. Deliberately separate from ``FREDAdapter``'s generic release-schedule
mechanism: ``DFEDTARU`` (the FRED series ``FREDAdapter`` tracks for FOMC's rate
outcome) belongs to a *daily*-updating FRED release (H.15 Selected Interest
Rates), unrelated to specific FOMC meeting dates — a generic ``fred/release/dates``
lookup for it would be noisy and wrong (see ``skip_schedule`` in
``adapters/fred.py``). This adapter instead reads the actual meeting calendar
directly from the Fed's own site — verified reachable from this sandbox on
2026-07-22 (200 OK), unlike BLS's own schedule page (403s here).

**Real page structure (captured and inspected directly, not guessed):** each year
is a ``div.panel.panel-default`` whose heading reads "YYYY FOMC Meetings"; its
direct children alternate ``row fomc-meeting`` / ``fomc-meeting--shaded row
fomc-meeting`` divs, one per meeting, each containing a
``fomc-meeting__month`` (e.g. "July") and a ``fomc-meeting__date`` day-range
(e.g. "28-29", "17-18*", or "22 (notation vote)" for single-day meetings).

Once a meeting has happened, the block also contains a Statement press-release
link (``/newsevents/pressreleases/monetary20260128a.htm``) whose embedded date is
authoritative and preferred when present. **Future meetings have no such link at
all** (confirmed directly — the Fed doesn't create the press-release page until
after the decision) — for those, the decision date is computed from the year +
month name + the *last* day number in the range (the second, decision day of the
2-day meeting).

Produces only *schedule* records (no actual/forecast/previous — just marking the
date), using the same raw schema as ``normalizers/government_release.py``. The
eventual rate outcome comes from ``FREDAdapter``'s ``DFEDTARU`` series and is
merged in at read time by ``domain.reconciliation`` — the same mechanism used for
every other cross-source merge, not something special-cased here.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from lxml import html as lxml_html

from ..domain.enums import EventType
from ..domain.errors import NormalizationError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

DEFAULT_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

RELEASE_CODE = "FOMC"
RELEASE_NAME = "Federal Funds Target Range (Upper Limit)"

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_NUMBER = {name: i + 1 for i, name in enumerate(MONTHS)}

# The trailing `a\.htm` (not `a1\.htm`) deliberately excludes the "Implementation
# Note" variant link, which shares the same date but a different suffix.
_STATEMENT_LINK_RE = re.compile(r"monetary(\d{4})(\d{2})(\d{2})a\.htm")
_YEAR_RE = re.compile(r"(\d{4})")
_TRAILING_DIGITS_RE = re.compile(r"\d+")


class FOMCScheduleAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "fomc_schedule"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.ECONOMIC_RELEASE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        url = self._config.url("calendar", DEFAULT_CALENDAR_URL)
        html = self._get_text(url)
        return self.parse_html(html, params)

    def parse_html(self, page_html: str, params: FetchParams) -> list[dict[str, Any]]:
        """Parse the calendar page into raw schedule records. Public/pure for
        fixture tests — no network involved."""
        try:
            tree = lxml_html.fromstring(page_html)
        except Exception as exc:  # noqa: BLE001
            raise NormalizationError(f"unparseable FOMC calendar HTML: {exc}") from exc

        out: list[dict[str, Any]] = []
        panels: Any = tree.xpath(
            '//div[contains(@class,"panel-default")][.//a[contains(text(),"FOMC Meetings")]]'
        )
        for panel in panels:
            year = self._panel_year(panel)
            if year is None:
                continue
            rows: Any = panel.xpath(
                './div[contains(@class,"fomc-meeting")'
                ' and not(contains(@class,"__month"))'
                ' and not(contains(@class,"__date"))]'
            )
            for row in rows:
                day_date = self._meeting_date(row, year)
                if day_date is None or not params.date_range.contains(day_date):
                    continue
                out.append(
                    {
                        "release_code": RELEASE_CODE,
                        "release_name": RELEASE_NAME,
                        "date": day_date.isoformat(),
                        "actual": None,
                        "previous": None,
                        "unit": "%",
                        "agency": "Federal Reserve",
                        "id": f"fomc:{day_date.isoformat()}",
                    }
                )
        return out

    @staticmethod
    def _panel_year(panel: Any) -> int | None:
        heading = panel.xpath('.//h4/a[contains(text(),"FOMC Meetings")]')
        if not heading:
            return None
        match = _YEAR_RE.search(heading[0].text_content())
        return int(match.group(1)) if match else None

    @classmethod
    def _meeting_date(cls, row: Any, year: int) -> datetime.date | None:
        # Authoritative once the meeting has happened: the Statement link's own date.
        for href in row.xpath(".//a/@href"):
            match = _STATEMENT_LINK_RE.search(href)
            if match:
                y, m, d = match.groups()
                return datetime.date(int(y), int(m), int(d))

        # Future meeting: compute from month name + the last day number in the
        # range (the decision day is the second/final day of the meeting).
        month_el = row.xpath('.//div[contains(@class,"fomc-meeting__month")]')
        date_el = row.xpath('.//div[contains(@class,"fomc-meeting__date")]')
        if not month_el or not date_el:
            return None
        month_name = month_el[0].text_content().strip()
        month_num = _MONTH_NUMBER.get(month_name)
        if month_num is None:
            return None
        day_digits = _TRAILING_DIGITS_RE.findall(date_el[0].text_content())
        if not day_digits:
            return None
        try:
            return datetime.date(year, month_num, int(day_digits[-1]))
        except ValueError:
            return None
