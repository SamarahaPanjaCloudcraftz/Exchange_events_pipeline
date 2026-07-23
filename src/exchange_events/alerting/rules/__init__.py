"""Alert rules (design doc §5.4, §12) — one stateless evaluator per condition.

Post-delivery redesign (DECISIONS.md "Proximity-based alert severity"): the
four required event categories each get a pure days-until-event classifier
(INFO -> WARNING -> CRITICAL) instead of the original fixed-lookahead /
deviation-based rules.
"""

from __future__ import annotations

from .dst_shift_proximity import DstShiftProximityRule
from .economic_release_proximity import CORE_RELEASE_CODES, EconomicReleaseProximityRule
from .expiry_proximity import ALERT_EXPIRY_UNDERLYINGS, ExpiryProximityRule
from .holiday_proximity import HolidayProximityRule
from .iv_threshold import IVThresholdRule

__all__ = [
    "HolidayProximityRule",
    "DstShiftProximityRule",
    "ExpiryProximityRule",
    "ALERT_EXPIRY_UNDERLYINGS",
    "EconomicReleaseProximityRule",
    "CORE_RELEASE_CODES",
    "IVThresholdRule",
]
