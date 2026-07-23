"""API response serialization (design doc §5.6).

Reuses ``domain.serialization`` (the same round-trippable form the storage layer
uses) and adds API-only conveniences (e.g. the computed ``surprise`` field on
economic releases) that don't belong in the storage representation.
"""

from __future__ import annotations

from typing import Any

from ..domain.alerts import Alert
from ..domain.events import EconomicReleaseEvent, Event
from ..domain.iv import IVSnapshot
from ..domain.serialization import dt_to_iso, serialize_event


def event_to_dict(event: Event) -> dict[str, Any]:
    data = serialize_event(event)
    if isinstance(event, EconomicReleaseEvent):
        data["surprise"] = event.surprise
    return data


def alert_to_dict(alert: Alert) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "rule_id": alert.rule_id,
        "severity": str(alert.severity),
        "title": alert.title,
        "body": alert.body,
        "triggered_at": dt_to_iso(alert.triggered_at),
        "event": event_to_dict(alert.event),
    }


def iv_snapshot_to_dict(snapshot: IVSnapshot) -> dict[str, Any]:
    return {
        "exchange": snapshot.exchange,
        "underlying": snapshot.underlying,
        "date": snapshot.date.isoformat(),
        "iv": snapshot.iv,
        "iv_rank": snapshot.iv_rank,
        "source": snapshot.source,
    }


def error_envelope(message: str, *, code: str = "error") -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
