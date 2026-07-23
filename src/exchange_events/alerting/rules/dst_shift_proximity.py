"""DstShiftProximityRule (post-delivery: proximity-based alert taxonomy, see
DECISIONS.md "Proximity-based alert severity").

A DST transition matters to any strategy whose session-time parameters key
off the exchange's own local clock (see dashboard's "Next Timezone Shift"
block). Classified purely by days-until-shift: INFO while distant, WARNING
within ``warning_days``, CRITICAL within ``critical_days``.
"""

from __future__ import annotations

from ...contracts.alert_rule import AlertRule
from ...domain.alerts import Alert, AlertContext, AlertSeverity
from ...domain.events import DSTChangeEvent, Event
from ...domain.exchange_zones import dst_transition_label, exchanges_for_zone


class DstShiftProximityRule(AlertRule):
    def __init__(self, warning_days: int = 2, critical_days: int = 1) -> None:
        self._warning_days = warning_days
        self._critical_days = critical_days

    def rule_id(self) -> str:
        return f"dst_shift_proximity:{self._warning_days}:{self._critical_days}"

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        alerts = []
        for event in events:
            if not isinstance(event, DSTChangeEvent):
                continue
            days_away = (event.date - context.today_utc).days
            if days_away < 0:
                continue
            if days_away <= self._critical_days:
                severity = AlertSeverity.CRITICAL
            elif days_away <= self._warning_days:
                severity = AlertSeverity.WARNING
            else:
                severity = AlertSeverity.INFO
            # Title carries what + when, plus which exchange(s) this affects
            # (a DST event only carries an iana_zone, not an exchange -- see
            # domain/exchange_zones.py) -- falls back to the raw zone name for
            # a tracked zone that isn't any configured exchange's own timezone.
            exchanges = exchanges_for_zone(event.iana_zone)
            exchange_label = "/".join(exchanges) if exchanges else event.iana_zone
            # Named abbreviations (e.g. "CDT -> CST") read far more clearly than
            # raw UTC offsets and match the dashboard's own "Next Timezone Shift"
            # block -- fall back to the offsets themselves if this zone/direction
            # has no known abbreviation pair (e.g. a zone with no DST at all).
            transition = event.metadata.get("transition")
            change_label = dst_transition_label(event.iana_zone, transition) or (
                f"{event.old_utc_offset} -> {event.new_utc_offset}"
            )
            alerts.append(
                Alert(
                    rule_id=self.rule_id(),
                    event=event,
                    severity=severity,
                    title=(
                        f"{exchange_label} timezone shift in {days_away} day(s): "
                        f"{change_label} ({event.date.isoformat()})"
                    ),
                    body=(
                        f"Zone: {event.iana_zone}. "
                        f"{event.old_utc_offset} -> {event.new_utc_offset}."
                    ),
                    triggered_at=context.now_utc,
                )
            )
        return alerts
