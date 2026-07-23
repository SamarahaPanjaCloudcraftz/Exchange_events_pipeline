"""Unit tests for RoutingConfig + NotificationDispatcher (§5.5)."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.alerting.dispatcher import NotificationDispatcher
from exchange_events.alerting.routing import RouteRule, RoutingConfig
from exchange_events.contracts.notification_channel import DeliveryStatus, Recipient
from exchange_events.domain.alerts import Alert, AlertSeverity
from exchange_events.domain.enums import EventType
from exchange_events.domain.events import EconomicReleaseEvent, HolidayEvent
from exchange_events.infra.logging import NullLogger
from tests.fakes.channel import FakeChannel

pytestmark = pytest.mark.unit

UTC = datetime.UTC


def _alert(severity: AlertSeverity, event_type: str = "holiday") -> Alert:
    if event_type == "holiday":
        event = HolidayEvent(
            source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26), holiday_name="H"
        )
    else:
        event = EconomicReleaseEvent(
            source="fred", date=datetime.date(2026, 1, 13), release_name="CPI", release_code="CPI"
        )
    return Alert(
        rule_id="r", event=event, severity=severity, title="t", body="b",
        triggered_at=datetime.datetime(2026, 1, 1, tzinfo=UTC),
    )


TEAM = Recipient(id="team_trading", address="team@x.com")
ALL = Recipient(id="all", address="all@x.com")


def make_routing() -> RoutingConfig:
    return RoutingConfig(
        routes=[
            RouteRule(
                severity=AlertSeverity.CRITICAL,
                event_types=[EventType.ECONOMIC_RELEASE, EventType.EXPIRY],
                channels=["email", "teams"], recipients=["trading"],
            ),
            RouteRule(severity=AlertSeverity.WARNING, channels=["teams"], recipients=["trading"]),
            RouteRule(channels=["dashboard"], recipients=["all"]),  # catch-all
        ],
        recipient_groups={"trading": [TEAM], "all": [ALL]},
    )


# --- RoutingConfig matching ----------------------------------------------------------
def test_first_matching_route_wins():
    routing = make_routing()
    critical_release = _alert(AlertSeverity.CRITICAL, "release")
    route = routing.match(critical_release)
    assert route is not None
    assert route.channels == ["email", "teams"]


def test_warning_falls_to_second_route():
    routing = make_routing()
    route = routing.match(_alert(AlertSeverity.WARNING, "holiday"))
    assert route is not None
    assert route.channels == ["teams"]


def test_info_falls_to_catch_all():
    routing = make_routing()
    route = routing.match(_alert(AlertSeverity.INFO, "holiday"))
    assert route is not None
    assert route.channels == ["dashboard"]


def test_critical_holiday_does_not_match_first_route_event_type_filter():
    # First route requires event_types in {ECONOMIC_RELEASE, EXPIRY}; a CRITICAL
    # holiday alert should fall through to the catch-all, not match route 1.
    routing = make_routing()
    route = routing.match(_alert(AlertSeverity.CRITICAL, "holiday"))
    assert route is not None
    assert route.channels == ["dashboard"]


def test_resolve_recipients_dedupes_across_groups():
    routing = RoutingConfig(recipient_groups={"a": [TEAM], "b": [TEAM, ALL]})
    rule = RouteRule(channels=["x"], recipients=["a", "b"])
    resolved = routing.resolve_recipients(rule)
    assert {r.id for r in resolved} == {"team_trading", "all"}
    assert len(resolved) == 2  # TEAM not duplicated despite being in both groups


# --- NotificationDispatcher ------------------------------------------------------------
def test_dispatch_routes_to_correct_channel():
    dashboard = FakeChannel("dashboard")
    dispatcher = NotificationDispatcher(
        channels=[dashboard], routing_config=make_routing(), logger=NullLogger()
    )
    results = dispatcher.dispatch([_alert(AlertSeverity.INFO)])
    assert len(dashboard.sent) == 1
    assert all(r.succeeded for r in results)


def test_dispatch_to_multiple_channels_for_one_alert():
    email = FakeChannel("email")
    teams = FakeChannel("teams")
    dispatcher = NotificationDispatcher(
        channels=[email, teams], routing_config=make_routing(), logger=NullLogger()
    )
    dispatcher.dispatch([_alert(AlertSeverity.CRITICAL, "release")])
    assert len(email.sent) == 1
    assert len(teams.sent) == 1


def test_dispatch_isolates_a_down_channel():
    working = FakeChannel("teams")
    broken = FakeChannel("email", unavailable=True)
    dispatcher = NotificationDispatcher(
        channels=[broken, working], routing_config=make_routing(), logger=NullLogger()
    )
    results = dispatcher.dispatch([_alert(AlertSeverity.CRITICAL, "release")])

    assert len(working.sent) == 1  # teams still got it
    by_channel = {r.channel: r for r in results}
    assert by_channel["email"].status == DeliveryStatus.FAILED
    assert by_channel["teams"].status == DeliveryStatus.SUCCESS


def test_dispatch_unknown_channel_in_routing_is_skipped_gracefully():
    routing = RoutingConfig(
        routes=[RouteRule(channels=["nonexistent"], recipients=["all"])],
        recipient_groups={"all": [ALL]},
    )
    dispatcher = NotificationDispatcher(channels=[], routing_config=routing, logger=NullLogger())
    assert dispatcher.dispatch([_alert(AlertSeverity.INFO)]) == []


def test_dispatch_no_matching_route_is_skipped():
    routing = RoutingConfig(routes=[], recipient_groups={})
    dashboard = FakeChannel("dashboard")
    dispatcher = NotificationDispatcher(
        channels=[dashboard], routing_config=routing, logger=NullLogger()
    )
    assert dispatcher.dispatch([_alert(AlertSeverity.INFO)]) == []
    assert dashboard.sent == []


def test_dispatch_multiple_alerts_each_routed_independently():
    dashboard = FakeChannel("dashboard")
    teams = FakeChannel("teams")
    dispatcher = NotificationDispatcher(
        channels=[dashboard, teams], routing_config=make_routing(), logger=NullLogger()
    )
    dispatcher.dispatch([_alert(AlertSeverity.INFO), _alert(AlertSeverity.WARNING)])
    assert len(dashboard.sent) == 1
    assert len(teams.sent) == 1
