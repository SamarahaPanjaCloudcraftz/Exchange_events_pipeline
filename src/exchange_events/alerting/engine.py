"""Alert engine (design doc §5.4; post-delivery redesign, see DECISIONS.md
"Proximity-based alert severity").

Evaluates alert rules against events in the alerting window. Separated from
notification delivery (the ``NotificationDispatcher``, Phase 9, consumes what
this returns). Per-rule failures are isolated (§7) - one broken rule never
blocks the others from evaluating.

**Severity model:** each rule classifies every matching event's *current*
severity purely from proximity (INFO far out, escalating to WARNING/CRITICAL
as the event approaches - see ``alerting/rules/*_proximity.py``). Because
``Alert.alert_id`` is stable per (rule, event) - no time component - the same
event maps to a single row in the ``AlertLog`` across every pipeline run,
upserted in place as its severity is re-classified. Only an *escalation*
(severity strictly increasing since the last stored value) is returned for
notification dispatch; re-evaluating an unchanged or resolving event still
refreshes its stored row (so displayed text/severity never goes stale) but
never re-notifies.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from ..contracts.alert_log import AlertLog
from ..contracts.alert_rule import AlertRule
from ..contracts.clock import Clock
from ..contracts.iv_provider import IVThresholdProvider
from ..contracts.logger import Logger
from ..contracts.repository import EventRepository
from ..domain.alerts import Alert, AlertContext, AlertSeverity
from ..domain.events import Event, ExpiryEvent
from ..domain.iv import IVSnapshot
from ..domain.query import EventQuery
from ..domain.reconciliation import reconcile_economic_releases

_SEVERITY_RANK = {AlertSeverity.INFO: 0, AlertSeverity.WARNING: 1, AlertSeverity.CRITICAL: 2}


@dataclass
class AlertEngine:
    rules: list[AlertRule]
    repository: EventRepository
    alert_log: AlertLog
    clock: Clock
    logger: Logger
    iv_provider: IVThresholdProvider | None = None
    lookback_days: int = 1      # include just-passed events briefly (e.g. IV rule)
    lookahead_days: int = 30    # include far-out events so their INFO row exists early

    def evaluate(self) -> list[Alert]:
        """Run all rules against the alerting window; return newly *escalated* alerts.

        1. Query the repository for events in [today - lookback, today + lookahead].
        2. Reconcile economic-release events across sources (domain.reconciliation) -
           avoids double-counting the same real-world release ingested from more
           than one source as two separate alert rows.
        3. Build an AlertContext (now, IV snapshots if a provider is wired).
        4. Pass events + context to each rule, isolating per-rule failures.
        5. For each candidate, compare against the alert log's currently stored
           severity for that (rule, event); upsert the current classification
           unconditionally (keeps displayed text/severity fresh).
        6. Return only the alerts whose severity just escalated (and isn't
           INFO) - those are what actually warrants a notification.
        """
        today = self.clock.today_utc()
        window = EventQuery(
            date_from=today - datetime.timedelta(days=self.lookback_days),
            date_to=today + datetime.timedelta(days=self.lookahead_days),
            # EventQuery.include_metadata defaults to False (keeps the public API's
            # JSON responses lean unless a client asks for it) -- but this is an
            # internal query, and rules need full domain data (e.g.
            # DstShiftProximityRule reads event.metadata["transition"] to label a
            # DST shift "CDT -> CST" rather than raw UTC offsets). Never strip it here.
            include_metadata=True,
        )
        events = reconcile_economic_releases(self.repository.query(window))
        context = self._build_context(events)

        candidates: list[Alert] = []
        for rule in self.rules:
            try:
                candidates.extend(rule.evaluate(events, context))
            except Exception as exc:  # noqa: BLE001 - isolate this rule's failure (§7)
                self.logger.error("alert rule failed", rule_id=rule.rule_id(), error=str(exc))

        escalated: list[Alert] = []
        for alert in candidates:
            previous = self.alert_log.get(alert.alert_id)
            is_escalation = previous is None or (
                _SEVERITY_RANK[alert.severity] > _SEVERITY_RANK[previous.severity]
            )
            self.alert_log.upsert(alert)
            if is_escalation and alert.severity != AlertSeverity.INFO:
                escalated.append(alert)
        return escalated

    def _build_context(self, events: list[Event]) -> AlertContext:
        iv_snapshots: dict[tuple[str, str], IVSnapshot] = {}
        if self.iv_provider is not None:
            today = self.clock.today_utc()
            seen: set[tuple[str, str]] = set()
            for event in events:
                if not isinstance(event, ExpiryEvent) or event.exchange is None:
                    continue
                key = (event.exchange, event.underlying)
                if key in seen:
                    continue
                seen.add(key)
                snapshot = self.iv_provider.get_iv_snapshot(
                    event.exchange, event.underlying, today
                )
                if snapshot is not None:
                    iv_snapshots[key] = snapshot
        return AlertContext(now_utc=self.clock.now_utc(), iv_snapshots=iv_snapshots)
