"""Integration tests for the Flask API (§5.6) — Flask test client against a
seeded in-memory SQLite repository."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.api.app import create_app
from exchange_events.domain.events import (
    EconomicReleaseEvent,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.infra.logging import NullLogger
from exchange_events.ingestion.engine import IngestionEngine
from exchange_events.ingestion.normalizer_registry import NormalizerRegistry
from exchange_events.storage.alert_log import SqliteAlertLog
from exchange_events.storage.sqlite_repository import SqliteEventRepository
from tests.fakes.clock import FakeClock
from tests.fakes.iv_provider import FakeIVProvider
from tests.fakes.normalizer import FakeNormalizer
from tests.fakes.source_adapter import FakeSourceAdapter

pytestmark = pytest.mark.integration

UTC = datetime.UTC
TODAY = datetime.datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock():
    return FakeClock(TODAY)


@pytest.fixture
def repository(clock):
    repo = SqliteEventRepository(":memory:", clock=clock)
    repo.upsert([
        HolidayEvent(source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
                     holiday_name="Republic Day"),
        HolidayEvent(source="cme", exchange="XCME", date=datetime.date(2026, 1, 1),
                     holiday_name="New Year"),
        ExpiryEvent(source="cme", exchange="XCME", date=datetime.date(2026, 1, 20),
                    instrument_type="futures", underlying="ES", series="quarterly",
                    expiry_date=datetime.date(2026, 1, 20)),
        EconomicReleaseEvent(source="fred", date=datetime.date(2026, 1, 13),
                              release_name="CPI", release_code="CPI",
                              forecast=3.1, actual=3.4),
    ])
    yield repo
    repo.close()


@pytest.fixture
def alert_log(clock):
    log = SqliteAlertLog(":memory:", clock=clock)
    yield log
    log.close()


@pytest.fixture
def app(repository, alert_log, clock, iv_provider=None):
    engine = IngestionEngine(
        adapters=[FakeSourceAdapter("src_a", script=[[]])],
        normalizer_registry=NormalizerRegistry.from_list([FakeNormalizer("src_a")]),
        repository=repository, clock=clock, logger=NullLogger(),
    )
    return create_app(
        repository=repository, alert_log=alert_log, ingestion_engine=engine,
        clock=clock, iv_provider=iv_provider,
    )


@pytest.fixture
def client(app):
    return app.test_client()


# --- GET /api/v1/events -------------------------------------------------------------
def test_list_events_no_filters(client):
    resp = client.get("/api/v1/events")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 4


def test_list_events_filter_by_exchange(client):
    resp = client.get("/api/v1/events?exchanges=XCME")
    data = resp.get_json()
    assert len(data) == 2
    assert all(e["exchange"] == "XCME" for e in data)


def test_list_events_filter_by_event_type(client):
    resp = client.get("/api/v1/events?event_types=expiry")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["event_type"] == "expiry"


def test_list_events_filter_by_date_range(client):
    resp = client.get("/api/v1/events?date_from=2026-01-10&date_to=2026-01-31")
    data = resp.get_json()
    dates = {e["date"] for e in data}
    assert dates == {"2026-01-13", "2026-01-20", "2026-01-26"}


def test_list_events_release_codes_filter(client):
    resp = client.get("/api/v1/events?release_codes=CPI")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["release_code"] == "CPI"
    assert data[0]["surprise"] == pytest.approx(0.3)  # API-only computed field


def test_list_events_invalid_event_type_returns_400(client):
    resp = client.get("/api/v1/events?event_types=not_a_type")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_list_events_invalid_date_returns_400(client):
    resp = client.get("/api/v1/events?date_from=not-a-date")
    assert resp.status_code == 400


def test_list_events_limit_offset(client):
    resp = client.get("/api/v1/events?limit=2&offset=1")
    assert len(resp.get_json()) == 2


def test_list_events_metadata_hidden_by_default(client):
    resp = client.get("/api/v1/events?exchanges=XNSE")
    assert resp.get_json()[0]["metadata"] == {}


# --- GET /api/v1/events/<id> ---------------------------------------------------------
def test_get_event_by_id(client):
    all_events = client.get("/api/v1/events").get_json()
    event_id = all_events[0]["event_id"]
    resp = client.get(f"/api/v1/events/{event_id}")
    assert resp.status_code == 200
    assert resp.get_json()["event_id"] == event_id


def test_get_event_by_id_404(client):
    resp = client.get("/api/v1/events/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


# --- GET /api/v1/events/upcoming ------------------------------------------------------
def test_upcoming_events_default_window(client):
    # "today" is 2026-01-15; default window is 14 days -> through 2026-01-29.
    resp = client.get("/api/v1/events/upcoming")
    dates = {e["date"] for e in resp.get_json()}
    assert dates == {"2026-01-20", "2026-01-26"}


def test_upcoming_events_custom_days(client):
    resp = client.get("/api/v1/events/upcoming?days=3")
    assert resp.get_json() == []  # nothing within 3 days of 2026-01-15


def test_upcoming_events_invalid_days_400(client):
    resp = client.get("/api/v1/events/upcoming?days=abc")
    assert resp.status_code == 400


# --- GET /api/v1/calendar/<year>/<month> ----------------------------------------------
def test_calendar_groups_events_by_date(client):
    resp = client.get("/api/v1/calendar/2026/1")
    data = resp.get_json()
    assert data["year"] == 2026
    assert data["month"] == 1
    assert set(data["days"].keys()) == {"2026-01-01", "2026-01-13", "2026-01-20", "2026-01-26"}
    assert len(data["days"]["2026-01-01"]) == 1


def test_calendar_invalid_month_400(client):
    resp = client.get("/api/v1/calendar/2026/13")
    assert resp.status_code == 400


def test_calendar_empty_month(client):
    resp = client.get("/api/v1/calendar/2026/6")
    assert resp.get_json()["days"] == {}


# --- GET /api/v1/exchanges -------------------------------------------------------------
def test_exchanges_static_list(client):
    resp = client.get("/api/v1/exchanges")
    mics = {e["mic"] for e in resp.get_json()}
    assert mics == {"XNSE", "XBOM", "XKRX", "XCME"}


# --- GET /api/v1/alerts ----------------------------------------------------------------
def test_alerts_empty_initially(client):
    assert client.get("/api/v1/alerts").get_json() == []


def test_alerts_reflects_recorded_alerts(client, alert_log):
    from exchange_events.domain.alerts import Alert, AlertSeverity
    event = HolidayEvent(source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
                          holiday_name="Republic Day")
    alert = Alert(rule_id="r", event=event, severity=AlertSeverity.WARNING,
                   title="t", body="b", triggered_at=TODAY)
    alert_log.upsert(alert)
    resp = client.get("/api/v1/alerts")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["alert_id"] == alert.alert_id
    assert data[0]["event"]["holiday_name"] == "Republic Day"


def test_alerts_limit(client, alert_log):
    from exchange_events.domain.alerts import Alert, AlertSeverity
    event = HolidayEvent(source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
                          holiday_name="H")
    for i in range(3):
        alert_log.upsert(Alert(
            rule_id=f"r{i}", event=event, severity=AlertSeverity.INFO, title="t", body="b",
            triggered_at=TODAY + datetime.timedelta(hours=i),
        ))
    resp = client.get("/api/v1/alerts?limit=2")
    assert len(resp.get_json()) == 2


# --- GET /api/v1/iv/<exchange>/<underlying> ---------------------------------------------
def test_iv_returns_501_without_provider(client):
    resp = client.get("/api/v1/iv/XCME/ES")
    assert resp.status_code == 501
    assert resp.get_json()["error"]["code"] == "not_implemented"


def test_iv_returns_series_with_provider(repository, alert_log, clock):
    provider = FakeIVProvider()
    provider.set("XCME", "ES", datetime.date(2026, 1, 10), 0.25)
    provider.set("XCME", "ES", datetime.date(2026, 1, 12), 0.30)
    engine = IngestionEngine(
        adapters=[], normalizer_registry=NormalizerRegistry(),
        repository=repository, clock=clock, logger=NullLogger(),
    )
    app = create_app(
        repository=repository, alert_log=alert_log, ingestion_engine=engine,
        clock=clock, iv_provider=provider,
    )
    resp = app.test_client().get(
        "/api/v1/iv/XCME/ES?date_from=2026-01-01&date_to=2026-01-31"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 2
    assert {d["iv"] for d in data} == {0.25, 0.30}


def test_iv_invalid_date_400(repository, alert_log, clock):
    engine = IngestionEngine(
        adapters=[], normalizer_registry=NormalizerRegistry(),
        repository=repository, clock=clock, logger=NullLogger(),
    )
    app = create_app(
        repository=repository, alert_log=alert_log, ingestion_engine=engine,
        clock=clock, iv_provider=FakeIVProvider(),
    )
    resp = app.test_client().get("/api/v1/iv/XCME/ES?date_from=not-a-date")
    assert resp.status_code == 400


# --- POST /api/v1/ingest/trigger --------------------------------------------------------
def test_ingest_trigger_full(client):
    resp = client.post("/api/v1/ingest/trigger", json={
        "date_from": "2026-01-01", "date_to": "2026-01-31",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 1
    assert data["results"][0]["source_name"] == "src_a"
    assert data["results"][0]["succeeded"] is True


def test_ingest_trigger_single_source(client):
    resp = client.post("/api/v1/ingest/trigger", json={
        "source": "src_a", "date_from": "2026-01-01", "date_to": "2026-01-31",
    })
    assert resp.status_code == 200
    assert len(resp.get_json()["results"]) == 1


def test_ingest_trigger_unknown_source_404(client):
    resp = client.post("/api/v1/ingest/trigger", json={
        "source": "nonexistent", "date_from": "2026-01-01", "date_to": "2026-01-31",
    })
    assert resp.status_code == 404


def test_ingest_trigger_defaults_date_range_when_body_empty(client):
    resp = client.post("/api/v1/ingest/trigger", json={})
    assert resp.status_code == 200


def test_ingest_trigger_invalid_date_400(client):
    resp = client.post("/api/v1/ingest/trigger", json={"date_from": "not-a-date"})
    assert resp.status_code == 400
