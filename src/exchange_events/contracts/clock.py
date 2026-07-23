"""Clock contract (design doc §4.7).

Abstracts the system clock purely for testability. Every component that needs
"now" receives a Clock rather than calling ``datetime.now()`` directly, so tests
inject a ``FakeClock`` fixed at whatever instant the scenario requires.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now_utc(self) -> datetime.datetime:
        """Current instant as a timezone-aware UTC datetime."""
        ...

    @abstractmethod
    def today_utc(self) -> datetime.date:
        """Current UTC calendar date."""
        ...
