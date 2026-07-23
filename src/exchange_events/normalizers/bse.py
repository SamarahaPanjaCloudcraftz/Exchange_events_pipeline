"""BSE normalizer (design doc §5.2) — XBOM holidays + expiries."""

from __future__ import annotations

from .exchange import ExchangeCalendarNormalizer


class BSENormalizer(ExchangeCalendarNormalizer):
    exchange = "XBOM"
    source = "bse_circular"
    # BSE dates appear as "26/01/2026" or "26 January 2026".
    date_formats = ("%d/%m/%Y", "%d %B %Y", "%d-%b-%Y")
