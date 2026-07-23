"""Canonical event types — the single shared vocabulary (design doc §3).

Every upstream component (adapters, normalizers) produces these; every downstream
component (repository, alert engine, API) consumes them. No raw/source-specific
structure leaks past the normalizer.

Design refinements over the doc's sketch, all faithful to the stated principles:

* ``kw_only=True`` frozen dataclasses — keyword-only construction reads clearly and
  sidesteps the "non-default follows default" pitfall of dataclass inheritance.
* ``event_id`` is **auto-derived** in ``__post_init__`` from the natural key
  (§3.4) unless explicitly supplied. This centralizes idempotency (P6) so a
  normalizer physically cannot forget to compute it. Each subclass supplies its
  category-specific ``discriminator()``.
* Datetimes are **required to be timezone-aware and normalized to UTC** at the
  boundary (P5). Naive datetimes raise immediately.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from .enums import EventType, SessionType
from .ids import make_event_id

_UTC = datetime.UTC


def _to_utc(name: str, value: datetime.datetime | None) -> datetime.datetime | None:
    """Enforce P5: reject naive datetimes, normalize aware ones to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (UTC); got naive {value!r}")
    return value.astimezone(_UTC)


@dataclass(frozen=True, kw_only=True)
class Event:
    """Base event shared by all categories (§3.1).

    Not meant to be instantiated directly — subclasses define ``discriminator()``.
    ``ingested_at`` / ``updated_at`` are populated by the repository on write and
    are ``None`` on freshly normalized events.
    """

    event_type: EventType
    source: str
    date: datetime.date
    exchange: str | None = None
    timestamp_utc: datetime.datetime | None = None
    source_raw_id: str | None = None
    ingested_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""  # auto-derived from the natural key if left empty

    def __post_init__(self) -> None:
        # Normalize/validate all datetimes to UTC (P5).
        object.__setattr__(self, "timestamp_utc", _to_utc("timestamp_utc", self.timestamp_utc))
        object.__setattr__(self, "ingested_at", _to_utc("ingested_at", self.ingested_at))
        object.__setattr__(self, "updated_at", _to_utc("updated_at", self.updated_at))
        # Derive the deterministic id from the natural key unless one was supplied.
        if not self.event_id:
            object.__setattr__(
                self,
                "event_id",
                make_event_id(
                    source=self.source,
                    event_type=self.event_type,
                    exchange=self.exchange,
                    date=self.date,
                    discriminator=self.discriminator(),
                ),
            )

    def discriminator(self) -> str:
        """Category-specific component of the natural key (§3.4)."""
        raise NotImplementedError("Event subclasses must implement discriminator()")


@dataclass(frozen=True, kw_only=True)
class HolidayEvent(Event):
    """An exchange holiday / special session (§3.2)."""

    event_type: EventType = EventType.HOLIDAY
    holiday_name: str
    session_type: SessionType = SessionType.FULL_CLOSE
    affected_segments: list[str] = field(default_factory=list)  # e.g. ["EQ", "FO", "CD"]

    def discriminator(self) -> str:
        return self.holiday_name


@dataclass(frozen=True, kw_only=True)
class DSTChangeEvent(Event):
    """A daylight-saving-time transition (§3.2). ``exchange`` is ``None``."""

    event_type: EventType = EventType.DST_CHANGE
    region: str
    old_utc_offset: str
    new_utc_offset: str
    iana_zone: str

    def discriminator(self) -> str:
        return self.iana_zone


@dataclass(frozen=True, kw_only=True)
class ExpiryEvent(Event):
    """A derivatives expiry (§3.2)."""

    event_type: EventType = EventType.EXPIRY
    instrument_type: str            # "options" | "futures"
    underlying: str                 # "NIFTY", "BANKNIFTY", "KOSPI200", "ES"
    series: str                     # "weekly" | "monthly" | "quarterly"
    expiry_date: datetime.date
    rollover_to: datetime.date | None = None
    is_revised: bool = False

    def discriminator(self) -> str:
        return f"{self.underlying}:{self.series}"


@dataclass(frozen=True, kw_only=True)
class EconomicReleaseEvent(Event):
    """A scheduled macroeconomic data release (§3.2)."""

    event_type: EventType = EventType.ECONOMIC_RELEASE
    release_name: str               # "Nonfarm Payrolls"
    release_code: str               # "NFP", "CPI", "FOMC", ...
    agency: str = ""                # "BLS", "BEA", "Federal Reserve"
    period: str = ""                # "June 2026", "Q2 2026"
    forecast: float | None = None
    previous: float | None = None
    actual: float | None = None     # None until released
    revision: float | None = None
    unit: str = ""                  # "%", "thousands", "index", "bps"
    country: str | None = None      # ISO-ish code, e.g. "US" — which country's
                                     # release this is (all current sources are
                                     # US-only; lets the dashboard associate a
                                     # release with the exchanges in that country)

    def discriminator(self) -> str:
        return self.release_code

    @property
    def surprise(self) -> float | None:
        """actual − forecast, computed on demand (§3.2 — not stored raw).

        Rounded to 6 decimal places to avoid float-subtraction artifacts (e.g.
        ``3.4 - 3.1 == 0.2999999999999998``) leaking into the API/dashboard —
        no real release value in this pipeline carries more precision than that.
        """
        if self.actual is None or self.forecast is None:
            return None
        return round(self.actual - self.forecast, 6)
