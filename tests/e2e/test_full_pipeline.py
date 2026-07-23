"""End-to-end test (design doc §9.1): ingest -> store -> query -> alert -> dispatch.

Uses only fixtures/fakes for the source adapter (no real network — that's what
`tests/contract/` is for) but every other component is the **real** production
class: `CMENormalizer`, `SqliteEventRepository`, `SqliteAlertLog`,
`IngestionEngine`, the real Flask API (`create_app` + test client),
`AlertEngine` with the real `ExpiryProximityRule`, and `NotificationDispatcher`
with a real `RoutingConfig`. Only the final notification channel is a fake, so
the test can assert on what was "delivered" without touching SMTP/Teams.

This is deliberately the one test in the suite that exercises the full chain
in a single flow — everything else tests one layer against fakes for its
neighbors (§9.1: unit tests are the majority; this is one of the "few" e2e
tests).
"""

from __future__ import annotations

import datetime

import pytest

from exchange_events.alerting.dispatcher import NotificationDispatcher
from exchange_events.alerting.engine import AlertEngine
from exchange_events.alerting.routing import RouteRule, RoutingConfig
from exchange_events.alerting.rules import ExpiryProximityRule, HolidayProximityRule
from exchange_events.api.app import create_app
from exchange_events.contracts.notification_channel import Recipient
from exchange_events.domain.alerts import AlertSeverity
from exchange_events.domain.enums import EventType
from exchange_events.domain.query import DateRange
from exchange_events.infra.logging import NullLogger
from exchange_events.ingestion.engine import IngestionEngine
from exchange_events.ingestion.normalizer_registry import NormalizerRegistry
from exchange_events.normalizers.cme import CMENormalizer
from exchange_events.storage.alert_log import SqliteAlertLog
from exchange_events.storage.sqlite_repository import SqliteEventRepository
from tests.fakes.channel import FakeChannel
from tests.fakes.clock import FakeClock
from tests.fakes.source_adapter import FakeSourceAdapter

pytestmark = pytest.mark.e2e

UTC = datetime.UTC


def test_full_pipeline_ingest_store_query_alert_dispatch():
    # "Today" is fixed so the expiry seeded below is deterministically "tomorrow".
    today = datetime.date(2026, 3, 19)
    clock = FakeClock(datetime.datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC))
    logger = NullLogger()

    repository = SqliteEventRepository(":memory:", clock=clock, logger=logger)
    alert_log = SqliteAlertLog(":memory:", clock=clock, logger=logger)

    # --- 1. Ingest: a fake adapter emitting realistic CME-shaped raw records,
    #        through the real CMENormalizer, into the real SQLite repository.
    raw_records = [
        {"record_type": "holiday", "date": "2026-01-01", "name": "New Year's Day",
         "session": "closed", "products": ["ES"]},
        {"record_type": "expiry", "product": "ES", "instrument_type": "futures",
         "series": "quarterly", "expiry_date": "2026-03-20", "is_revised": False},
    ]
    adapter = FakeSourceAdapter(
        "cme_calendar", script=[raw_records],
        event_types=[EventType.HOLIDAY, EventType.EXPIRY], exchanges=["XCME"],
    )
    engine = IngestionEngine(
        adapters=[adapter],
        normalizer_registry=NormalizerRegistry.from_list([CMENormalizer()]),
        repository=repository,
        clock=clock,
        logger=logger,
    )
    full_year = DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    report = engine.run_full_ingest(full_year)

    assert report.results[0].succeeded
    assert report.results[0].fetched == 2
    assert report.results[0].upserted_inserted == 2
    assert not report.any_source_failed

    # --- 2. Query through the real Flask API (not the repository directly) ---
    app = create_app(
        repository=repository, alert_log=alert_log, ingestion_engine=engine, clock=clock
    )
    client = app.test_client()

    events_resp = client.get("/api/v1/events?exchanges=XCME")
    assert events_resp.status_code == 200
    assert len(events_resp.get_json()) == 2

    calendar_resp = client.get("/api/v1/calendar/2026/3")
    assert calendar_resp.status_code == 200
    assert "2026-03-20" in calendar_resp.get_json()["days"]

    # --- 3. Evaluate alerts: ExpiryProximityRule should fire (expiry is "tomorrow",
    #        within warning_days=2). HolidayProximityRule finds nothing in-window
    #        (the seeded holiday is months in the past relative to "today").
    alert_engine = AlertEngine(
        rules=[ExpiryProximityRule(warning_days=2), HolidayProximityRule()],
        repository=repository,
        alert_log=alert_log,
        clock=clock,
        logger=logger,
        lookback_days=1,
        lookahead_days=7,
    )
    alerts = alert_engine.evaluate()
    assert len(alerts) == 1
    assert alerts[0].rule_id == "expiry_proximity:2"
    assert alerts[0].severity == AlertSeverity.WARNING

    # Re-evaluating must not re-fire the same alert (P6-style dedup at the alert layer).
    assert alert_engine.evaluate() == []

    # Alerts are now visible through the API's alert feed too.
    alerts_resp = client.get("/api/v1/alerts")
    assert len(alerts_resp.get_json()) == 1
    assert alerts_resp.get_json()[0]["alert_id"] == alerts[0].alert_id

    # --- 4. Dispatch to a fake channel through the real routing/dispatcher ---
    channel = FakeChannel("dashboard")
    routing = RoutingConfig(
        routes=[RouteRule(channels=["dashboard"], recipients=["all"])],
        recipient_groups={"all": [Recipient(id="everyone", address="all@example.com")]},
    )
    dispatcher = NotificationDispatcher(channels=[channel], routing_config=routing, logger=logger)
    results = dispatcher.dispatch(alerts)

    assert len(results) == 1
    assert results[0].succeeded
    assert len(channel.sent) == 1
    delivered_alert, delivered_recipients = channel.sent[0]
    assert delivered_alert.alert_id == alerts[0].alert_id
    assert [r.id for r in delivered_recipients] == ["everyone"]

    repository.close()
    alert_log.close()
