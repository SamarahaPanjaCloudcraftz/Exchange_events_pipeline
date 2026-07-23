"""CME normalizer (design doc §5.2) — XCME holidays + expiries. Production priority."""

from __future__ import annotations

from .exchange import ExchangeCalendarNormalizer


class CMENormalizer(ExchangeCalendarNormalizer):
    exchange = "XCME"
    source = "cme_calendar"
    # CME service dates are typically ISO or "01 Jan 2026" / "Jan 01, 2026".
    date_formats = ("%d %b %Y", "%b %d, %Y", "%m/%d/%Y")
