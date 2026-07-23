"""NSE normalizer (design doc §5.2) — XNSE holidays + expiries."""

from __future__ import annotations

from .exchange import ExchangeCalendarNormalizer


class NSENormalizer(ExchangeCalendarNormalizer):
    exchange = "XNSE"
    source = "nse_circular"
    # NSE publishes dates like "26-Jan-2026".
    date_formats = ("%d-%b-%Y", "%d-%B-%Y")
