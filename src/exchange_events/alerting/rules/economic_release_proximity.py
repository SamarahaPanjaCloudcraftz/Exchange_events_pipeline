"""EconomicReleaseProximityRule (post-delivery: proximity-based alert taxonomy,
see DECISIONS.md "Proximity-based alert severity").

Classified purely by days-until-release: INFO while distant, WARNING within
``warning_days``, CRITICAL within ``critical_days``.

Deliberately scoped to the 7 releases the requirements doc actually asks for
(``CORE_RELEASE_CODES`` - matches the dashboard's own filter, see
``dashboard/static/index.html``'s ``CORE_RELEASE_CODES``). FRED also carries
extra daily-updating series beyond those 7 (e.g. ``FEDFUNDS``, FOMC's own
``DFEDTARU``) - alerting on those would mean an almost-permanent WARNING/
CRITICAL row for a series that updates every business day, which is noise,
not a signal.
"""

from __future__ import annotations

from ...contracts.alert_rule import AlertRule
from ...domain.alerts import Alert, AlertContext, AlertSeverity
from ...domain.events import EconomicReleaseEvent, Event

CORE_RELEASE_CODES: frozenset[str] = frozenset(
    {"NFP", "CPI", "PPI", "PCE", "JOLTS", "FOMC", "ISM_PMI"}
)


class EconomicReleaseProximityRule(AlertRule):
    def __init__(
        self,
        warning_days: int = 2,
        critical_days: int = 1,
        release_codes: frozenset[str] = CORE_RELEASE_CODES,
    ) -> None:
        self._warning_days = warning_days
        self._critical_days = critical_days
        self._codes = release_codes

    def rule_id(self) -> str:
        return f"economic_release_proximity:{self._warning_days}:{self._critical_days}"

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        alerts = []
        for event in events:
            if not isinstance(event, EconomicReleaseEvent) or event.release_code not in self._codes:
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
            # Title carries what + when + country (economic releases are
            # country-specific, not exchange-specific -- EconomicReleaseEvent
            # has no `exchange`, only `country`); body adds only the
            # publishing agency, which isn't already in the title.
            body = f"Agency: {event.agency}." if event.agency else ""
            alerts.append(
                Alert(
                    rule_id=self.rule_id(),
                    event=event,
                    severity=severity,
                    title=(
                        f"{event.release_name} ({event.release_code}, {event.country}) "
                        f"in {days_away} day(s) ({event.date.isoformat()})"
                    ),
                    body=body,
                    triggered_at=context.now_utc,
                )
            )
        return alerts
