"""ExpiryProximityRule (post-delivery: proximity-based alert taxonomy, see
DECISIONS.md "Proximity-based alert severity").

Classified purely by days-until-expiry: INFO while distant, WARNING within
``warning_days``. No CRITICAL tier for expiries, per the user's own taxonomy
(a routine calendar expiry never needs to escalate as urgently as a DST shift
or an economic release).

Deliberately scoped to ``ALERT_EXPIRY_UNDERLYINGS`` (ES/NQ only) rather than
every configured CME product (11, spanning 4 real venues -- see
``adapters/cme.py``). Mirrors the dashboard's own ``CALENDAR_EXPIRY_UNDERLYINGS``
restriction and ``EconomicReleaseProximityRule``'s ``CORE_RELEASE_CODES``
pattern: an explicit allow-list, easy to extend later (constructor arg), not a
hardcoded per-product check.
"""

from __future__ import annotations

from ...contracts.alert_rule import AlertRule
from ...domain.alerts import Alert, AlertContext, AlertSeverity
from ...domain.events import Event, ExpiryEvent

ALERT_EXPIRY_UNDERLYINGS: frozenset[str] = frozenset({"ES", "NQ"})


class ExpiryProximityRule(AlertRule):
    def __init__(
        self,
        warning_days: int = 2,
        underlyings: frozenset[str] = ALERT_EXPIRY_UNDERLYINGS,
    ) -> None:
        self._warning_days = warning_days
        self._underlyings = underlyings

    def rule_id(self) -> str:
        return f"expiry_proximity:{self._warning_days}"

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        alerts = []
        for event in events:
            if not isinstance(event, ExpiryEvent) or event.underlying not in self._underlyings:
                continue
            days_away = (event.expiry_date - context.today_utc).days
            if days_away < 0:
                continue
            severity = (
                AlertSeverity.WARNING if days_away <= self._warning_days else AlertSeverity.INFO
            )
            # Title carries what + when + exchange (CME Group spans 4 real
            # venues -- XCME/XCBT/XNYM/XCEC -- so underlying alone doesn't
            # uniquely identify the venue in general, even though ES/NQ both
            # happen to be XCME today). Body adds the instrument type and, if
            # the adapter supplied a real contract symbol (e.g. "ESU6"), that --
            # none of this is already in the title.
            body = f"Instrument: {event.instrument_type}."
            if event.source_raw_id:
                body = f"{body} Contract: {event.source_raw_id}."
            alerts.append(
                Alert(
                    rule_id=self.rule_id(),
                    event=event,
                    severity=severity,
                    title=(
                        f"{event.underlying} ({event.exchange}) {event.series} expiry in "
                        f"{days_away} day(s) ({event.expiry_date.isoformat()})"
                    ),
                    body=body,
                    triggered_at=context.now_utc,
                )
            )
        return alerts
