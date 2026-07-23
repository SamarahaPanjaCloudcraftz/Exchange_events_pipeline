"""Smoke tests for the composition root (§8.2) — build_application() over a
real (temp-file) SQLite backend, asserting the whole graph wires correctly."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.config.loader import DEFAULTS_PATH, load_toml
from exchange_events.config.schema import AppConfig
from exchange_events.domain.errors import ConfigError
from exchange_events.domain.query import DateRange
from exchange_events.wiring import build_application

pytestmark = pytest.mark.unit


def default_config(sqlite_path: str) -> AppConfig:
    cfg = AppConfig.model_validate(load_toml(DEFAULTS_PATH))
    cfg.database.sqlite_path = sqlite_path
    return cfg


def test_build_application_wires_full_graph(tmp_path):
    cfg = default_config(str(tmp_path / "test.db"))
    app = build_application(cfg)

    adapter_names = {a.source_name() for a in app.ingestion_engine.adapters}
    assert adapter_names == {
        "cme_calendar", "nse_circular", "bse_circular", "krx_calendar", "iana_tz",
        "fred_api", "bls_api", "bea_api", "ism_pmi", "fomc_schedule", "econ_calendar",
    }
    rule_ids = {r.rule_id() for r in app.alert_engine.rules}
    assert rule_ids == {
        "holiday_proximity", "dst_shift_proximity:2:1",
        "expiry_proximity:2", "economic_release_proximity:2:1",
    }
    # No email/teams secrets configured in this test -> only dashboard channel wired.
    assert [c.channel_name() for c in app.dispatcher.channels] == ["dashboard"]
    assert app.iv_provider is None  # v2-deferred, never built in v1


def test_build_application_every_adapter_has_a_normalizer(tmp_path):
    cfg = default_config(str(tmp_path / "test.db"))
    app = build_application(cfg)
    registry = app.ingestion_engine.normalizer_registry
    for adapter in app.ingestion_engine.adapters:
        assert registry.get(adapter.source_name()) is not None


def test_build_application_postgres_backend_without_dsn_raises_config_error(tmp_path):
    cfg = default_config(str(tmp_path / "test.db"))
    cfg.database.backend = "postgres"
    cfg.database.postgres_dsn = None
    with pytest.raises(ConfigError, match="postgres"):
        build_application(cfg)


def test_build_application_email_channel_wired_when_configured(tmp_path):
    cfg = default_config(str(tmp_path / "test.db"))
    cfg.notification.email.smtp_host = "smtp.example.com"
    cfg.notification.email.from_address = "alerts@example.com"
    app = build_application(cfg)
    assert "email" in [c.channel_name() for c in app.dispatcher.channels]


def test_build_application_teams_channel_wired_when_configured(tmp_path):
    cfg = default_config(str(tmp_path / "test.db"))
    cfg.notification.teams.webhook_url = "https://hook.example.com"
    app = build_application(cfg)
    assert "teams" in [c.channel_name() for c in app.dispatcher.channels]


def test_build_application_end_to_end_smoke_ingest_alert_dispatch(tmp_path):
    """A true smoke test: run a tiny ingest through the wired app, evaluate
    alerts, dispatch them — nothing should raise."""
    cfg = default_config(str(tmp_path / "test.db"))
    app = build_application(cfg)

    # IANA is fully offline/live; a real ingest of just that source is safe here.
    date_range = DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    report = app.ingestion_engine.run_single_source("iana_tz", date_range)
    assert report.results[0].succeeded

    alerts = app.alert_engine.evaluate()
    results = app.dispatcher.dispatch(alerts)
    assert isinstance(results, list)  # no crash, whatever the routing produced
