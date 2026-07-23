"""HolidayProximityRule (post-delivery: proximity-based alert taxonomy, see
DECISIONS.md "Proximity-based alert severity").

Holidays are deliberately flat: always INFO, regardless of how close they
are. Unlike DST shifts, expiries, and economic releases (which need active
attention as they approach), a holiday is a passive calendar fact worth
surfacing for planning purposes but never worth escalating.
"""

from __future__ import annotations

from ...contracts.alert_rule import AlertRule
from ...domain.alerts import Alert, AlertContext, AlertSeverity
from ...domain.enums import SessionType
from ...domain.events import Event, HolidayEvent

_SESSION_LABEL = {
    SessionType.FULL_CLOSE: "Full market closure.",
    SessionType.HALF_DAY: "Half-day / early close.",
    SessionType.SPECIAL_SESSION: "Special session (e.g. Muhurat trading).",
}


class HolidayProximityRule(AlertRule):
    def rule_id(self) -> str:
        return "holiday_proximity"

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        alerts = []
        for event in events:
            if not isinstance(event, HolidayEvent) or event.date < context.today_utc:
                continue
            # Title carries the full "what + when"; body adds only what isn't
            # already there -- the session type and, if narrower than the whole
            # exchange, which segments are affected.
            body = _SESSION_LABEL.get(event.session_type, "")
            if event.affected_segments:
                body = f"{body} Affected: {', '.join(event.affected_segments)}.".strip()
            alerts.append(
                Alert(
                    rule_id=self.rule_id(),
                    event=event,
                    severity=AlertSeverity.INFO,
                    title=f"{event.holiday_name} — {event.exchange} on {event.date.isoformat()}",
                    body=body,
                    triggered_at=context.now_utc,
                )
            )
        return alerts
