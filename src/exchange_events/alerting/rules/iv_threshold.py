"""IVThresholdRule (design doc §4.6, §8.2 — optional, gated on an IV provider).

Fires when an expiring underlying's implied volatility is at/above a configured
threshold. Skips gracefully whenever no IV snapshot is available for an event —
either because no ``IVThresholdProvider`` is wired at all, or the provider simply
has no data for that underlying/date. This is the only rule that reads
``AlertContext.iv_snapshots`` (populated by the engine only when a provider
exists), so it degrades to a no-op with zero configuration changes when IV
integration isn't enabled (§12: deferred to v2 by default).
"""

from __future__ import annotations

from ...contracts.alert_rule import AlertRule
from ...domain.alerts import Alert, AlertContext, AlertSeverity
from ...domain.events import Event, ExpiryEvent

DEFAULT_THRESHOLD = 0.30  # 30% IV, a reasonable generic default


class IVThresholdRule(AlertRule):
    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
        default_threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._thresholds = thresholds or {}
        self._default_threshold = default_threshold

    def rule_id(self) -> str:
        return "iv_threshold"

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        alerts = []
        for event in events:
            if not isinstance(event, ExpiryEvent) or event.exchange is None:
                continue
            snapshot = context.iv_snapshots.get((event.exchange, event.underlying))
            if snapshot is None:
                continue  # no IV provider wired, or no data for this underlying
            threshold = self._thresholds.get(event.underlying, self._default_threshold)
            if snapshot.iv < threshold:
                continue
            alerts.append(
                Alert(
                    rule_id=self.rule_id(),
                    event=event,
                    severity=AlertSeverity.WARNING,
                    title=f"{event.underlying} IV above threshold ahead of expiry",
                    body=(
                        f"{event.underlying} IV is {snapshot.iv:.2%}, at/above the "
                        f"{threshold:.2%} threshold, with expiry on "
                        f"{event.expiry_date.isoformat()}."
                    ),
                    triggered_at=context.now_utc,
                )
            )
        return alerts
