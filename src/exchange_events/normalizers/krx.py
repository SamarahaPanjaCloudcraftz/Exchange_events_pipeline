"""KRX normalizer (design doc §5.2) — XKRX holidays + expiries.

Built structurally now; the KRX *adapter* live fetch is deferred (per DECISIONS),
so this normalizer is exercised via fixtures only until KRX goes live.
"""

from __future__ import annotations

from .exchange import ExchangeCalendarNormalizer


class KRXNormalizer(ExchangeCalendarNormalizer):
    exchange = "XKRX"
    source = "krx_calendar"
    # KRX calendar dates are commonly "20260101".
    date_formats = ("%Y%m%d", "%Y.%m.%d")
