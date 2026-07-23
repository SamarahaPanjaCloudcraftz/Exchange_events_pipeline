"""Unit tests for AlertEngine (§5.4, post-delivery proximity redesign) — window
query, escalation-based notify semantics, per-rule isolation, IV-context
building. All fakes, no I/O."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.alerting.engine import AlertEngine
from exchange_events.contracts.alert_rule import AlertRule
from exchange_events.domain.alerts import Alert, AlertContext, AlertSeverity
from exchange_events.domain.events import EconomicReleaseEvent, Event, ExpiryEvent
from exchange_events.infra.logging import NullLogger
from tests.fakes.alert_log import FakeAlertLog
from tests.fakes.clock import FakeClock
from tests.fakes.iv_provider import FakeIVProvider
from tests.fakes.repository import FakeEventRepository

pytestmark = pytest.mark.unit

UTC = datetime.UTC
T0 = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=UTC)  # today = 2026-08-06


class FixedSeverityRule(AlertRule):
    """Reports a caller-supplied severity for every event, tagged with a
    configurable rule_id — used to drive the engine's escalation logic directly
    without depending on any of the real proximity classifiers."""

    def __init__(self, rule_id: str = "fixed", severity: AlertSeverity = AlertSeverity.INFO):
        self._id = rule_id
        self._severity = severity

    def rule_id(self) -> str:
        return self._id

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        return [
            Alert(
                rule_id=self.rule_id(), event=e, severity=self._severity,
                title="t", body="b", triggered_at=context.now_utc,
            )
            for e in events
        ]


class BrokenRule(AlertRule):
    def rule_id(self) -> str:
        return "broken"

    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        raise RuntimeError("rule bug")


def _nfp(date: datetime.date) -> EconomicReleaseEvent:
    return EconomicReleaseEvent(source="fred", date=date, release_name="NFP", release_code="NFP")


def make_engine(rules, *, repo=None, alert_log=None, iv_provider=None, clock=None, **kw):
    clock = clock or FakeClock(T0)
    repo = repo if repo is not None else FakeEventRepository(clock=clock)
    alert_log = alert_log or FakeAlertLog()
    engine = AlertEngine(
        rules=rules, repository=repo, alert_log=alert_log, clock=clock,
        logger=NullLogger(), iv_provider=iv_provider, **kw,
    )
    return engine, repo, alert_log, clock


# --- window query --------------------------------------------------------------------
def test_evaluate_queries_events_within_lookback_and_lookahead_window():
    clock = FakeClock(T0)
    repo = FakeEventRepository(clock=clock)
    repo.upsert([
        _nfp(datetime.date(2026, 8, 5)),   # yesterday - inside lookback=1
        _nfp(datetime.date(2026, 8, 6)),   # today
        _nfp(datetime.date(2026, 8, 13)),  # +7 - inside lookahead=7
        _nfp(datetime.date(2026, 8, 14)),  # +8 - outside window
        _nfp(datetime.date(2026, 8, 3)),   # -3 - outside lookback
    ])
    rule = FixedSeverityRule(severity=AlertSeverity.WARNING)
    engine, _, _, _ = make_engine([rule], repo=repo, clock=clock, lookback_days=1, lookahead_days=7)
    alerts = engine.evaluate()
    dates = sorted(a.event.date for a in alerts)
    assert dates == [
        datetime.date(2026, 8, 5),
        datetime.date(2026, 8, 6),
        datetime.date(2026, 8, 13),
    ]


# --- escalation-based notify (engine enforces, not rules) -----------------------------
def test_evaluate_does_not_notify_for_info_severity():
    """INFO alerts are always upserted (so the dashboard/API sees them) but never
    returned for notification dispatch — INFO never warrants an email/Teams ping."""
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    rule = FixedSeverityRule(severity=AlertSeverity.INFO)
    engine, _, alert_log, _ = make_engine([rule], repo=repo)

    fired = engine.evaluate()

    assert fired == []
    assert len(alert_log.recent()) == 1  # still recorded for display


def test_evaluate_notifies_on_first_warning_or_critical():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    rule = FixedSeverityRule(severity=AlertSeverity.WARNING)
    engine, _, _, _ = make_engine([rule], repo=repo)
    fired = engine.evaluate()
    assert len(fired) == 1
    assert fired[0].severity == AlertSeverity.WARNING


def test_evaluate_does_not_renotify_at_unchanged_severity():
    """Re-evaluating the same event at the same severity refreshes the stored
    row but must not fire a second notification (no daily Teams/email spam)."""
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    rule = FixedSeverityRule(severity=AlertSeverity.WARNING)
    engine, _, alert_log, _ = make_engine([rule], repo=repo)

    first = engine.evaluate()
    second = engine.evaluate()

    assert len(first) == 1
    assert len(second) == 0
    assert len(alert_log.recent()) == 1  # one row, not two


def test_evaluate_notifies_again_on_escalation_from_warning_to_critical():
    """The exact scenario the redesign exists for: an event starts INFO, crosses
    into WARNING (notify), then crosses into CRITICAL (notify again) — same
    alert_id/row throughout, escalating in place."""
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    alert_log = FakeAlertLog()

    rule_info = FixedSeverityRule(rule_id="r", severity=AlertSeverity.INFO)
    engine, _, _, _ = make_engine([rule_info], repo=repo, alert_log=alert_log)
    assert engine.evaluate() == []

    rule_warning = FixedSeverityRule(rule_id="r", severity=AlertSeverity.WARNING)
    engine, _, _, _ = make_engine([rule_warning], repo=repo, alert_log=alert_log)
    warned = engine.evaluate()
    assert len(warned) == 1 and warned[0].severity == AlertSeverity.WARNING

    rule_critical = FixedSeverityRule(rule_id="r", severity=AlertSeverity.CRITICAL)
    engine, _, _, _ = make_engine([rule_critical], repo=repo, alert_log=alert_log)
    critical = engine.evaluate()
    assert len(critical) == 1 and critical[0].severity == AlertSeverity.CRITICAL

    assert len(alert_log.recent()) == 1  # still just one row for this event


def test_evaluate_does_not_renotify_on_deescalation():
    """Severity dropping back down (e.g. a date revision pushed an event further
    out) updates the stored row but is not itself notification-worthy."""
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    alert_log = FakeAlertLog()

    rule_critical = FixedSeverityRule(rule_id="r", severity=AlertSeverity.CRITICAL)
    engine, _, _, _ = make_engine([rule_critical], repo=repo, alert_log=alert_log)
    engine.evaluate()

    rule_info = FixedSeverityRule(rule_id="r", severity=AlertSeverity.INFO)
    engine, _, _, _ = make_engine([rule_info], repo=repo, alert_log=alert_log)
    fired = engine.evaluate()

    assert fired == []
    assert alert_log.recent()[0].severity == AlertSeverity.INFO  # row refreshed in place


def test_evaluate_stores_alert_retrievable_via_get():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    rule = FixedSeverityRule(severity=AlertSeverity.WARNING)
    engine, _, alert_log, _ = make_engine([rule], repo=repo)
    alerts = engine.evaluate()
    assert alert_log.get(alerts[0].alert_id) is not None


# --- per-rule failure isolation (§7) ---------------------------------------------------
def test_broken_rule_does_not_block_other_rules():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    engine, _, _, _ = make_engine(
        [BrokenRule(), FixedSeverityRule(rule_id="fixed", severity=AlertSeverity.WARNING)],
        repo=repo,
    )
    alerts = engine.evaluate()
    assert len(alerts) == 1
    assert alerts[0].rule_id == "fixed"


def test_all_rules_broken_yields_no_alerts_no_crash():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    engine, _, _, _ = make_engine([BrokenRule()], repo=repo)
    assert engine.evaluate() == []


# --- multiple rules produce independent alert streams ----------------------------------
def test_multiple_rules_each_produce_alerts_with_distinct_ids():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    rule_a = FixedSeverityRule(rule_id="rule_a", severity=AlertSeverity.WARNING)
    rule_b = FixedSeverityRule(rule_id="rule_b", severity=AlertSeverity.WARNING)
    engine, _, _, _ = make_engine([rule_a, rule_b], repo=repo)
    alerts = engine.evaluate()
    assert {a.rule_id for a in alerts} == {"rule_a", "rule_b"}
    assert len({a.alert_id for a in alerts}) == 2  # distinct ids, no accidental collision


# --- IV context building --------------------------------------------------------------
def test_iv_snapshots_populated_for_expiry_events_when_provider_present():
    clock = FakeClock(T0)
    repo = FakeEventRepository(clock=clock)
    expiry = ExpiryEvent(
        source="cme", exchange="XCME", date=datetime.date(2026, 8, 6),
        instrument_type="futures", underlying="ES", series="quarterly",
        expiry_date=datetime.date(2026, 8, 6),
    )
    repo.upsert([expiry])
    iv = FakeIVProvider()
    iv.set("XCME", "ES", datetime.date(2026, 8, 6), 0.42)

    captured_context: list[AlertContext] = []

    class CapturingRule(AlertRule):
        def rule_id(self):
            return "capture"

        def evaluate(self, events, context):
            captured_context.append(context)
            return []

    engine, _, _, _ = make_engine([CapturingRule()], repo=repo, iv_provider=iv, clock=clock)
    engine.evaluate()
    assert ("XCME", "ES") in captured_context[0].iv_snapshots
    assert captured_context[0].iv_snapshots[("XCME", "ES")].iv == pytest.approx(0.42)


def test_iv_snapshots_empty_when_no_provider():
    repo = FakeEventRepository(clock=FakeClock(T0))
    expiry = ExpiryEvent(
        source="cme", exchange="XCME", date=datetime.date(2026, 8, 6),
        instrument_type="futures", underlying="ES", series="quarterly",
        expiry_date=datetime.date(2026, 8, 6),
    )
    repo.upsert([expiry])

    captured_context: list[AlertContext] = []

    class CapturingRule(AlertRule):
        def rule_id(self):
            return "capture"

        def evaluate(self, events, context):
            captured_context.append(context)
            return []

    engine, _, _, _ = make_engine([CapturingRule()], repo=repo, iv_provider=None)
    engine.evaluate()
    assert captured_context[0].iv_snapshots == {}


def test_evaluate_with_no_rules_returns_empty():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_nfp(datetime.date(2026, 8, 6))])
    engine, _, _, _ = make_engine([], repo=repo)
    assert engine.evaluate() == []


def test_evaluate_does_not_strip_event_metadata():
    """Regression test: EventQuery.include_metadata defaults to False (it's a
    lean-JSON knob for the public API), but the alert engine's own internal
    query must never rely on that default -- rules like DstShiftProximityRule
    read event.metadata (e.g. "transition") and would silently see an empty
    dict otherwise, exactly as happened here before this was fixed."""
    from exchange_events.domain.events import HolidayEvent

    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([
        HolidayEvent(
            source="cme", exchange="XCME", date=datetime.date(2026, 8, 6),
            holiday_name="Test Holiday", metadata={"note": "should survive"},
        )
    ])

    captured_events: list[Event] = []

    class CapturingRule(AlertRule):
        def rule_id(self):
            return "capture"

        def evaluate(self, events, context):
            captured_events.extend(events)
            return []

    engine, _, _, _ = make_engine([CapturingRule()], repo=repo)
    engine.evaluate()
    assert captured_events[0].metadata == {"note": "should survive"}


# --- cross-source economic-release reconciliation (DECISIONS.md "Economic-release
# waterfall") --------------------------------------------------------------------
def test_reconciliation_does_not_create_duplicate_alerts_for_same_release():
    """The same real-world release ingested from two sources (e.g. FRED + BLS)
    must reconcile to one event before rule evaluation, or it would double up
    into two separate alert rows for what's really one release."""
    from exchange_events.alerting.rules import EconomicReleaseProximityRule

    clock = FakeClock(T0)
    repo = FakeEventRepository(clock=clock)
    tomorrow = datetime.date(2026, 8, 7)
    repo.upsert([
        EconomicReleaseEvent(source="fred_api", date=tomorrow, release_name="CPI",
                              release_code="CPI"),
        EconomicReleaseEvent(source="bls_api", date=tomorrow, release_name="CPI",
                              release_code="CPI"),
    ])
    engine, _, _, _ = make_engine([EconomicReleaseProximityRule()], repo=repo, clock=clock)
    alerts = engine.evaluate()
    assert len(alerts) == 1  # one alert, not one per source


def test_economic_release_proximity_rule_fires_from_a_schedule_only_event():
    """A schedule-only event (just release_code + date, no forecast/actual --
    exactly what FREDAdapter._fetch_schedule / FOMCScheduleAdapter produce) must
    be sufficient to classify and escalate; the proximity rules never look at
    forecast/actual at all."""
    from exchange_events.alerting.rules import EconomicReleaseProximityRule

    clock = FakeClock(T0)  # today = 2026-08-06
    repo = FakeEventRepository(clock=clock)
    tomorrow = datetime.date(2026, 8, 7)
    schedule_only = EconomicReleaseEvent(
        source="fomc_schedule", date=tomorrow, release_name="FOMC Rate Decision",
        release_code="FOMC",
    )
    repo.upsert([schedule_only])

    engine, _, _, _ = make_engine(
        [EconomicReleaseProximityRule(warning_days=2, critical_days=1)], repo=repo, clock=clock,
        lookahead_days=7,
    )
    alerts = engine.evaluate()

    assert len(alerts) == 1
    assert alerts[0].severity == AlertSeverity.CRITICAL
    assert "FOMC Rate Decision" in alerts[0].title
    assert "in 1 day(s)" in alerts[0].title
