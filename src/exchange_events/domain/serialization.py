"""Canonical (de)serialization of events to/from plain JSON-safe dicts.

Lives in ``domain/`` so every layer that needs the wire form — both storage
repositories, the alert log, and the API serializer — shares one round-trippable
representation without importing a sibling concrete package.

Datetimes are written as fixed-width UTC ISO strings (``...+00:00`` with 6-digit
microseconds) so they also sort correctly lexicographically in TEXT columns.
Dates are ``YYYY-MM-DD``. ``deserialize_event`` is the exact inverse of
``serialize_event`` (round-trip fidelity is covered by tests).
"""

from __future__ import annotations

import datetime
from typing import Any

from .enums import EventType, SessionType
from .events import (
    DSTChangeEvent,
    EconomicReleaseEvent,
    Event,
    ExpiryEvent,
    HolidayEvent,
)

_UTC = datetime.UTC
_DT_FMT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def dt_to_iso(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_UTC).strftime(_DT_FMT)


def dt_from_iso(value: str | None) -> datetime.datetime | None:
    if value is None:
        return None
    return datetime.datetime.fromisoformat(value)


def _date_from_iso(value: str | None) -> datetime.date | None:
    if value is None:
        return None
    return datetime.date.fromisoformat(value)


def _common(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": str(event.event_type),
        "source": event.source,
        "exchange": event.exchange,
        "date": event.date.isoformat(),
        "timestamp_utc": dt_to_iso(event.timestamp_utc),
        "source_raw_id": event.source_raw_id,
        "ingested_at": dt_to_iso(event.ingested_at),
        "updated_at": dt_to_iso(event.updated_at),
        "metadata": dict(event.metadata),
    }


def serialize_event(event: Event) -> dict[str, Any]:
    """Convert an event to a JSON-safe dict (round-trippable)."""
    data = _common(event)
    if isinstance(event, HolidayEvent):
        data.update(
            holiday_name=event.holiday_name,
            session_type=str(event.session_type),
            affected_segments=list(event.affected_segments),
        )
    elif isinstance(event, DSTChangeEvent):
        data.update(
            region=event.region,
            old_utc_offset=event.old_utc_offset,
            new_utc_offset=event.new_utc_offset,
            iana_zone=event.iana_zone,
        )
    elif isinstance(event, ExpiryEvent):
        data.update(
            instrument_type=event.instrument_type,
            underlying=event.underlying,
            series=event.series,
            expiry_date=event.expiry_date.isoformat(),
            rollover_to=event.rollover_to.isoformat() if event.rollover_to else None,
            is_revised=event.is_revised,
        )
    elif isinstance(event, EconomicReleaseEvent):
        data.update(
            release_name=event.release_name,
            release_code=event.release_code,
            agency=event.agency,
            period=event.period,
            forecast=event.forecast,
            previous=event.previous,
            actual=event.actual,
            revision=event.revision,
            unit=event.unit,
            country=event.country,
        )
    else:  # pragma: no cover - defensive; all concrete types handled above
        raise TypeError(f"Cannot serialize unknown event type: {type(event)!r}")
    return data


def _common_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": data["event_id"],
        "source": data["source"],
        "exchange": data.get("exchange"),
        "date": _date_from_iso(data["date"]),
        "timestamp_utc": dt_from_iso(data.get("timestamp_utc")),
        "source_raw_id": data.get("source_raw_id"),
        "ingested_at": dt_from_iso(data.get("ingested_at")),
        "updated_at": dt_from_iso(data.get("updated_at")),
        "metadata": dict(data.get("metadata") or {}),
    }


def deserialize_event(data: dict[str, Any]) -> Event:
    """Reconstruct the correct Event subclass from a serialized dict."""
    event_type = EventType(data["event_type"])
    common = _common_kwargs(data)
    if event_type is EventType.HOLIDAY:
        return HolidayEvent(
            **common,
            holiday_name=data["holiday_name"],
            session_type=SessionType(data["session_type"]),
            affected_segments=list(data.get("affected_segments") or []),
        )
    if event_type is EventType.DST_CHANGE:
        return DSTChangeEvent(
            **common,
            region=data["region"],
            old_utc_offset=data["old_utc_offset"],
            new_utc_offset=data["new_utc_offset"],
            iana_zone=data["iana_zone"],
        )
    if event_type is EventType.EXPIRY:
        return ExpiryEvent(
            **common,
            instrument_type=data["instrument_type"],
            underlying=data["underlying"],
            series=data["series"],
            expiry_date=datetime.date.fromisoformat(data["expiry_date"]),
            rollover_to=_date_from_iso(data.get("rollover_to")),
            is_revised=bool(data.get("is_revised", False)),
        )
    if event_type is EventType.ECONOMIC_RELEASE:
        return EconomicReleaseEvent(
            **common,
            release_name=data["release_name"],
            release_code=data["release_code"],
            agency=data.get("agency", ""),
            period=data.get("period", ""),
            forecast=data.get("forecast"),
            previous=data.get("previous"),
            actual=data.get("actual"),
            revision=data.get("revision"),
            unit=data.get("unit", ""),
            country=data.get("country"),
        )
    raise ValueError(f"Unknown event_type: {event_type!r}")  # pragma: no cover
