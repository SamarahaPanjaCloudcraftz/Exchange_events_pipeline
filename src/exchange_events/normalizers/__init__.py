"""Normalizers (design doc §5.2) — one per source adapter.

Each transforms raw source dicts into canonical events with partial-success
semantics (bad records captured, not fatal).
"""

from __future__ import annotations

from .base import BaseNormalizer
from .bea import BEANormalizer
from .bls import BLSNormalizer
from .bse import BSENormalizer
from .cme import CMENormalizer
from .econ import EconCalendarNormalizer
from .exchange import ExchangeCalendarNormalizer
from .fomc import FOMCScheduleNormalizer
from .fred import FREDNormalizer
from .government_release import GovernmentReleaseNormalizer
from .ism import ISMNormalizer
from .krx import KRXNormalizer
from .nse import NSENormalizer
from .tz import TimezoneNormalizer

__all__ = [
    "BaseNormalizer",
    "ExchangeCalendarNormalizer",
    "CMENormalizer",
    "NSENormalizer",
    "BSENormalizer",
    "KRXNormalizer",
    "GovernmentReleaseNormalizer",
    "FREDNormalizer",
    "BLSNormalizer",
    "BEANormalizer",
    "ISMNormalizer",
    "FOMCScheduleNormalizer",
    "TimezoneNormalizer",
    "EconCalendarNormalizer",
]
