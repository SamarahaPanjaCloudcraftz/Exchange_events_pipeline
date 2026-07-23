"""FOMC schedule normalizer (design doc §5.2) — thin subclass, same shared base
as FRED/BLS/BEA/ISM (`GovernmentReleaseNormalizer`). ``FOMCScheduleAdapter`` only
ever emits schedule-only records (no actual/forecast), so this needs no
overrides beyond ``target_source()``; the base class's standard-release-time
fallback (``STANDARD_RELEASE_TIMES_ET["FOMC"]`` = 14:00 ET) applies automatically.
"""

from __future__ import annotations

from .government_release import GovernmentReleaseNormalizer


class FOMCScheduleNormalizer(GovernmentReleaseNormalizer):
    def target_source(self) -> str:
        return "fomc_schedule"
