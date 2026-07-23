"""BEA normalizer (design doc §5.2) — tier 3 of the economic-release waterfall.

The Bureau of Economic Analysis is the *original publisher* of PCE / Personal
Income & Outlays — used as the official backstop for that release. Thin
subclass of :class:`GovernmentReleaseNormalizer`.
"""

from __future__ import annotations

from .government_release import GovernmentReleaseNormalizer


class BEANormalizer(GovernmentReleaseNormalizer):
    def target_source(self) -> str:
        return "bea_api"
