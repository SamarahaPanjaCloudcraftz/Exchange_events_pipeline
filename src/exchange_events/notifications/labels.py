"""Shared display labels for notification channels (Email + Teams).

Human-readable category label per event type -- so a recipient can tell what
kind of alert this is at a glance, without having to parse the title's
wording or (worse) the internal ``rule_id``.
"""

from __future__ import annotations

from ..domain.enums import EventType

EVENT_TYPE_LABEL: dict[EventType, str] = {
    EventType.HOLIDAY: "Holiday",
    EventType.DST_CHANGE: "Timezone Shift",
    EventType.EXPIRY: "Expiry",
    EventType.ECONOMIC_RELEASE: "Economic Release",
}


def event_type_label(event_type: EventType) -> str:
    return EVENT_TYPE_LABEL.get(event_type, str(event_type).replace("_", " ").title())
