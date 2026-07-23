"""BLS normalizer (design doc §5.2) — tier 2 of the economic-release waterfall.

The Bureau of Labor Statistics is the *original publisher* of NFP, CPI, PPI, and
JOLTS — used as the official backstop when FRED is stale or unreachable. Thin
subclass of :class:`GovernmentReleaseNormalizer`.
"""

from __future__ import annotations

from .government_release import GovernmentReleaseNormalizer


class BLSNormalizer(GovernmentReleaseNormalizer):
    def target_source(self) -> str:
        return "bls_api"
