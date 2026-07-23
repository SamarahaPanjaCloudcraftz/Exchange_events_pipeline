"""FRED normalizer (design doc §5.2) — tier 1 of the economic-release waterfall.

Thin subclass of :class:`GovernmentReleaseNormalizer` (see that module for the
shared raw-record schema and rationale). FRED is the primary source: it covers
6 of the 7 required releases (NFP, CPI, PPI, PCE, JOLTS, FOMC target rate) —
see ``adapters/fred.py`` for the exact series mapping.
"""

from __future__ import annotations

from .government_release import GovernmentReleaseNormalizer


class FREDNormalizer(GovernmentReleaseNormalizer):
    def target_source(self) -> str:
        return "fred_api"
