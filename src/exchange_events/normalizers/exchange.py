"""Shared base for exchange-calendar normalizers (CME/NSE/BSE/KRX).

All four exchanges publish the same *shape* — holidays and derivative expiries —
so they share this base, which handles ``record_type`` dispatch and canonical
event construction. Each concrete subclass only declares its ``exchange`` MIC,
``source`` name, and accepted date formats (P4: a new exchange is a new subclass).

Raw record schema (produced by the Phase-6 adapters):

    holiday: {"record_type": "holiday", "date": <str>, "name"/"description": <str>,
              "session": "closed"|"early_close"|"special" (optional),
              "segments"/"products": [<str>, ...] (optional),
              "id": <str> (optional), "metadata": {...} (optional)}

    expiry:  {"record_type": "expiry", "expiry_date"/"date": <str>,
              "underlying"/"product"/"symbol": <str>,
              "instrument_type"/"instrument": "options"|"futures" (optional),
              "series": "weekly"|"monthly"|"quarterly" (optional),
              "is_revised": <bool> (optional), "rollover_to": <str> (optional),
              "id": <str> (optional), "metadata": {...} (optional)}
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..domain.errors import NormalizationError
from ..domain.events import Event, ExpiryEvent, HolidayEvent
from .base import BaseNormalizer
from .util import first, parse_date, to_session_type


class ExchangeCalendarNormalizer(BaseNormalizer):
    exchange: ClassVar[str]
    source: ClassVar[str]
    date_formats: ClassVar[tuple[str, ...]] = ()

    def target_source(self) -> str:
        return self.source

    def _normalize_one(self, record: dict[str, Any], source_name: str) -> Event | None:
        record_type = record.get("record_type")
        if record_type == "holiday":
            return self._holiday(record, source_name)
        if record_type == "expiry":
            return self._expiry(record, source_name)
        raise NormalizationError(
            f"unknown record_type {record_type!r}", raw_record=record
        )

    def _holiday(self, r: dict[str, Any], source: str) -> HolidayEvent:
        day = parse_date(first(r, ("date", "holiday_date"), "holiday date"), self.date_formats)
        name = str(first(r, ("name", "description", "holiday_name"), "holiday name"))
        segments = list(r.get("segments") or r.get("products") or [])
        return HolidayEvent(
            source=source,
            exchange=self.exchange,
            date=day,
            holiday_name=name,
            session_type=to_session_type(r.get("session")),
            affected_segments=[str(s) for s in segments],
            source_raw_id=_opt_str(r.get("id")),
            metadata=dict(r.get("metadata") or {}),
        )

    def _expiry(self, r: dict[str, Any], source: str) -> ExpiryEvent:
        day = parse_date(first(r, ("expiry_date", "date"), "expiry_date"), self.date_formats)
        underlying = str(first(r, ("underlying", "product", "symbol"), "underlying"))
        instrument = str(r.get("instrument_type") or r.get("instrument") or "futures")
        series = str(r.get("series") or "monthly")
        rollover = r.get("rollover_to")
        return ExpiryEvent(
            source=source,
            exchange=self.exchange,
            date=day,
            instrument_type=instrument,
            underlying=underlying,
            series=series,
            expiry_date=day,
            rollover_to=parse_date(rollover, self.date_formats) if rollover else None,
            is_revised=bool(r.get("is_revised", False)),
            source_raw_id=_opt_str(r.get("id")),
            metadata=dict(r.get("metadata") or {}),
        )


def _opt_str(value: object) -> str | None:
    return None if value in (None, "") else str(value)
