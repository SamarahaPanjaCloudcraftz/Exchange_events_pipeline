"""Unit tests for the test fakes themselves — they are test-critical (§9.2).

FakeEventRepository is also the reference the real repositories are held to, so its
semantics are exercised thoroughly here.
"""

from __future__ import annotations

import datetime

import pytest

from exchange_events.domain.enums import EventType
from exchange_events.domain.events import (
    EconomicReleaseEvent,
    ExpiryEvent,
    HolidayEvent,
)
from exchange_events.domain.query import EventQuery
from tests.fakes import (
    FakeAlertLog,
    FakeChannel,
    FakeClock,
    FakeEventRepository,
    FakeHttpClient,
)
from tests.fakes.channel import Recipient

pytestmark = pytest.mark.unit

UTC = datetime.UTC
T0 = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# --- FakeClock ---------------------------------------------------------------------
def test_fake_clock_fixed_and_advance():
    clk = FakeClock(T0)
    assert clk.now_utc() == T0
    assert clk.today_utc() == datetime.date(2026, 1, 1)
    clk.advance(days=1, hours=1)
    assert clk.now_utc() == datetime.datetime(2026, 1, 2, 13, 0, tzinfo=UTC)


def test_fake_clock_rejects_naive():
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime.datetime(2026, 1, 1, 12, 0))


def test_fake_clock_normalizes_to_utc():
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    clk = FakeClock(datetime.datetime(2026, 1, 1, 17, 30, tzinfo=ist))  # 12:00 UTC
    assert clk.now_utc() == T0


# --- FakeHttpClient ----------------------------------------------------------------
def test_fake_http_returns_registered_and_records_calls():
    http = FakeHttpClient()
    http.register_json("https://api/x", {"ok": True})
    resp = http.get("https://api/x", params={"a": 1})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert http.calls[0].method == "GET"
    assert http.calls[0].params == {"a": 1}


def test_fake_http_unknown_url_is_404():
    assert FakeHttpClient().get("https://nope").status_code == 404


def test_fake_http_matches_base_url_ignoring_query():
    http = FakeHttpClient()
    http.register_text("https://api/data", "hello")
    assert http.get("https://api/data?year=2026").text == "hello"


def test_fake_http_post_records_json_body():
    http = FakeHttpClient()
    http.register_json("https://hook", {"received": True})
    http.post("https://hook", json={"msg": "hi"})
    assert http.calls[0].method == "POST"
    assert http.calls[0].json == {"msg": "hi"}


# --- FakeEventRepository -----------------------------------------------------------
def _holiday(name: str, day: datetime.date, exchange: str = "XNSE") -> HolidayEvent:
    return HolidayEvent(source="nse", exchange=exchange, date=day, holiday_name=name)


def test_repo_insert_then_unchanged_then_updated():
    clk = FakeClock(T0)
    repo = FakeEventRepository(clock=clk)
    ev = _holiday("Republic Day", datetime.date(2026, 1, 26))

    r1 = repo.upsert([ev])
    assert (r1.inserted, r1.updated, r1.unchanged) == (1, 0, 0)

    r2 = repo.upsert([ev])
    assert (r2.inserted, r2.updated, r2.unchanged) == (0, 0, 1)

    changed = HolidayEvent(
        source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
        holiday_name="Republic Day", affected_segments=["EQ", "FO"],
    )
    clk.advance(hours=1)
    r3 = repo.upsert([changed])
    assert (r3.inserted, r3.updated, r3.unchanged) == (0, 1, 0)


def test_repo_sets_ingested_and_updated_at():
    clk = FakeClock(T0)
    repo = FakeEventRepository(clock=clk)
    ev = _holiday("Holi", datetime.date(2026, 3, 14))
    repo.upsert([ev])
    stored = repo.get_by_id(ev.event_id)
    assert stored is not None
    assert stored.ingested_at == T0
    assert stored.updated_at == T0

    # update keeps ingested_at, bumps updated_at
    clk.advance(days=1)
    repo.upsert([HolidayEvent(
        source="nse", exchange="XNSE", date=datetime.date(2026, 3, 14),
        holiday_name="Holi", affected_segments=["EQ"],
    )])
    stored2 = repo.get_by_id(ev.event_id)
    assert stored2.ingested_at == T0
    assert stored2.updated_at == datetime.datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def test_repo_get_by_id_missing_returns_none():
    assert FakeEventRepository().get_by_id("nope") is None


def test_repo_query_orders_by_date_ascending():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([
        _holiday("B", datetime.date(2026, 3, 1)),
        _holiday("A", datetime.date(2026, 1, 1)),
        _holiday("C", datetime.date(2026, 2, 1)),
    ])
    dates = [e.date for e in repo.query(EventQuery())]
    assert dates == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
        datetime.date(2026, 3, 1),
    ]


def test_repo_query_filters():
    repo = FakeEventRepository(clock=FakeClock(T0))
    nse = _holiday("Republic Day", datetime.date(2026, 1, 26), exchange="XNSE")
    cme = _holiday("New Year", datetime.date(2026, 1, 1), exchange="XCME")
    expiry = ExpiryEvent(
        source="nse", exchange="XNSE", date=datetime.date(2026, 1, 29),
        instrument_type="options", underlying="NIFTY", series="weekly",
        expiry_date=datetime.date(2026, 1, 29),
    )
    repo.upsert([nse, cme, expiry])

    by_exchange = repo.query(EventQuery(exchanges=["XCME"]))
    assert [e.exchange for e in by_exchange] == ["XCME"]

    by_type = repo.query(EventQuery(event_types=[EventType.EXPIRY]))
    assert all(e.event_type == EventType.EXPIRY for e in by_type)
    assert len(by_type) == 1

    windowed = repo.query(EventQuery(
        date_from=datetime.date(2026, 1, 2), date_to=datetime.date(2026, 1, 28)
    ))
    assert [e.date for e in windowed] == [datetime.date(2026, 1, 26)]


def test_repo_query_release_codes_filter_excludes_non_releases():
    repo = FakeEventRepository(clock=FakeClock(T0))
    cpi = EconomicReleaseEvent(
        source="fred", date=datetime.date(2026, 1, 13), release_name="CPI", release_code="CPI",
    )
    nfp = EconomicReleaseEvent(
        source="fred", date=datetime.date(2026, 1, 9), release_name="NFP", release_code="NFP",
    )
    holiday = _holiday("New Year", datetime.date(2026, 1, 1))
    repo.upsert([cpi, nfp, holiday])

    result = repo.query(EventQuery(release_codes=["CPI"]))
    assert len(result) == 1
    assert isinstance(result[0], EconomicReleaseEvent)
    assert result[0].release_code == "CPI"


def test_repo_query_limit_and_offset():
    repo = FakeEventRepository(clock=FakeClock(T0))
    repo.upsert([_holiday(f"H{i}", datetime.date(2026, 1, i + 1)) for i in range(5)])
    page = repo.query(EventQuery(limit=2, offset=1))
    assert [e.date.day for e in page] == [2, 3]


def test_repo_query_metadata_stripped_unless_requested():
    repo = FakeEventRepository(clock=FakeClock(T0))
    ev = HolidayEvent(
        source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26),
        holiday_name="Republic Day", metadata={"circular": "NSE/2026/001"},
    )
    repo.upsert([ev])
    assert repo.query(EventQuery())[0].metadata == {}
    assert repo.query(EventQuery(include_metadata=True))[0].metadata == {"circular": "NSE/2026/001"}


def test_repo_get_latest_ingest_time_per_source():
    clk = FakeClock(T0)
    repo = FakeEventRepository(clock=clk)
    repo.upsert([_holiday("A", datetime.date(2026, 1, 1))])
    clk.advance(days=2)
    repo.upsert([ExpiryEvent(
        source="cme", exchange="XCME", date=datetime.date(2026, 1, 16),
        instrument_type="futures", underlying="ES", series="monthly",
        expiry_date=datetime.date(2026, 1, 16),
    )])
    assert repo.get_latest_ingest_time("nse") == T0
    assert repo.get_latest_ingest_time("cme") == datetime.datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
    assert repo.get_latest_ingest_time("unknown") is None


# --- FakeAlertLog ------------------------------------------------------------------
def _alert(rule: str, when: datetime.datetime):
    from exchange_events.domain.alerts import Alert, AlertSeverity
    return Alert(
        rule_id=rule, event=_holiday("Republic Day", datetime.date(2026, 1, 26)),
        severity=AlertSeverity.WARNING, title="t", body="b", triggered_at=when,
    )


def test_alert_log_get_and_upsert_idempotent():
    log = FakeAlertLog()
    a = _alert("r1", T0)
    assert log.get(a.alert_id) is None
    log.upsert(a)
    assert log.get(a.alert_id) is not None
    log.upsert(a)  # idempotent -- same id, same row
    assert len(log.recent()) == 1


def test_alert_log_upsert_same_id_updates_in_place():
    from exchange_events.domain.alerts import Alert, AlertSeverity

    log = FakeAlertLog()
    a = _alert("r1", T0)
    log.upsert(a)
    escalated = Alert(
        rule_id="r1", event=a.event, severity=AlertSeverity.CRITICAL,
        title="escalated", body="b", triggered_at=T0,
    )
    assert escalated.alert_id == a.alert_id
    log.upsert(escalated)
    assert len(log.recent()) == 1
    assert log.get(a.alert_id).severity == AlertSeverity.CRITICAL


def test_alert_log_recent_newest_first_and_limited():
    log = FakeAlertLog()
    a1 = _alert("r1", datetime.datetime(2026, 1, 1, tzinfo=UTC))
    a2 = _alert("r2", datetime.datetime(2026, 1, 3, tzinfo=UTC))
    a3 = _alert("r3", datetime.datetime(2026, 1, 2, tzinfo=UTC))
    for a in (a1, a2, a3):
        log.upsert(a)
    recent = log.recent(limit=2)
    assert [a.rule_id for a in recent] == ["r2", "r3"]


# --- FakeChannel -------------------------------------------------------------------
def test_fake_channel_records_and_returns_per_recipient():
    ch = FakeChannel("email")
    recipients = [Recipient(id="a", address="a@x"), Recipient(id="b", address="b@x")]
    results = ch.send(_alert("r1", T0), recipients)
    assert ch.channel_name() == "email"
    assert len(ch.sent) == 1
    assert [r.recipient_id for r in results] == ["a", "b"]
    assert all(r.succeeded for r in results)


def test_fake_channel_fail_mode():
    ch = FakeChannel("email", fail=True)
    results = ch.send(_alert("r1", T0), [Recipient(id="a", address="a@x")])
    assert not results[0].succeeded


def test_fake_channel_unavailable_raises():
    from exchange_events.domain.errors import ChannelUnavailableError
    ch = FakeChannel("email", unavailable=True)
    with pytest.raises(ChannelUnavailableError):
        ch.send(_alert("r1", T0), [Recipient(id="a", address="a@x")])
