"""Routing configuration (design doc §5.5) — data, not code.

Mirrors the YAML shape in the design doc: an ordered list of routes, each
matching on severity/event_type, mapping to channels + named recipient groups.
Routes are evaluated in order; the **first match wins** (same semantics as the
doc's example: a specific CRITICAL rule before a catch-all WARNING rule, before
a catch-all "any severity" rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.notification_channel import Recipient
from ..domain.alerts import Alert, AlertSeverity
from ..domain.enums import EventType


@dataclass(frozen=True)
class RouteRule:
    channels: list[str]
    recipients: list[str]  # names of recipient groups, resolved via RoutingConfig.recipients
    severity: AlertSeverity | None = None      # None matches any severity
    event_types: list[EventType] | None = None  # None matches any event type

    def matches(self, alert: Alert) -> bool:
        if self.severity is not None and alert.severity != self.severity:
            return False
        return self.event_types is None or alert.event.event_type in self.event_types


@dataclass
class RoutingConfig:
    routes: list[RouteRule] = field(default_factory=list)
    recipient_groups: dict[str, list[Recipient]] = field(default_factory=dict)

    def match(self, alert: Alert) -> RouteRule | None:
        return next((r for r in self.routes if r.matches(alert)), None)

    def resolve_recipients(self, route: RouteRule) -> list[Recipient]:
        seen: dict[str, Recipient] = {}
        for group_name in route.recipients:
            for recipient in self.recipient_groups.get(group_name, []):
                seen[recipient.id] = recipient  # de-dup by recipient id across groups
        return list(seen.values())
