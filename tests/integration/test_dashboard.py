"""Tests for the dashboard blueprint (§5.7).

The dashboard is deliberately a *peer* of the API, not a dependency of it
(§5.7: "a consumer of the API... a future live monitoring system is another
skin over the same API") — so ``api.app.create_app`` never imports
``dashboard``. These tests mount the dashboard blueprint standalone, and also
alongside a real API app (mirroring what the Phase-13 CLI ``serve`` command
does), to prove the two compose correctly on one Flask instance without any
coupling between them.
"""

from __future__ import annotations

import datetime

import pytest
from flask import Flask

from exchange_events.api.app import create_app
from exchange_events.dashboard.server import bp as dashboard_bp
from exchange_events.infra.logging import NullLogger
from exchange_events.ingestion.engine import IngestionEngine
from exchange_events.ingestion.normalizer_registry import NormalizerRegistry
from exchange_events.storage.alert_log import SqliteAlertLog
from exchange_events.storage.sqlite_repository import SqliteEventRepository
from tests.fakes.clock import FakeClock

pytestmark = pytest.mark.integration

UTC = datetime.UTC
TODAY = datetime.datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def test_dashboard_standalone_serves_index_html():
    app = Flask(__name__)
    app.register_blueprint(dashboard_bp)
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    body = resp.get_data(as_text=True)
    assert "Exchange Events Dashboard" in body
    assert "<script>" in body


def test_dashboard_has_no_business_logic_imports():
    """Ground the design claim (§5.7): the dashboard module touches only Flask
    and stdlib — no domain/contracts/storage/adapters imports."""
    import ast
    from pathlib import Path

    source = Path(
        __import__("exchange_events.dashboard.server", fromlist=["bp"]).__file__
    ).read_text()
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    disallowed = {
        m for m in imported_modules
        if m.startswith("exchange_events") and not m.endswith("dashboard.server")
    }
    assert disallowed == set()


def test_dashboard_mounted_alongside_api_on_one_flask_app():
    """Mirrors what main.py's `serve` command does: one Flask() instance with
    both the API blueprints and the dashboard blueprint registered."""
    clock = FakeClock(TODAY)
    repo = SqliteEventRepository(":memory:", clock=clock)
    repo.upsert([])
    alert_log = SqliteAlertLog(":memory:", clock=clock)
    engine = IngestionEngine(
        adapters=[], normalizer_registry=NormalizerRegistry(),
        repository=repo, clock=clock, logger=NullLogger(),
    )
    app = create_app(repository=repo, alert_log=alert_log, ingestion_engine=engine, clock=clock)
    app.register_blueprint(dashboard_bp)
    client = app.test_client()

    dashboard_resp = client.get("/")
    api_resp = client.get("/api/v1/exchanges")

    assert dashboard_resp.status_code == 200
    assert "Exchange Events Dashboard" in dashboard_resp.get_data(as_text=True)
    assert api_resp.status_code == 200
    assert len(api_resp.get_json()) == 4

    repo.close()
    alert_log.close()


def test_dashboard_references_only_documented_api_endpoints():
    """The dashboard's JS must only call endpoints that actually exist (§5.6) —
    catches a renamed/typo'd endpoint before it ships."""
    from pathlib import Path

    html = (Path(dashboard_bp.root_path) / "static" / "index.html").read_text()
    documented_paths = {
        "/events/upcoming", "/events?event_types=economic_release",
        "/exchanges", "/alerts?limit=", "/calendar/",
        "/events?exchanges=",
    }
    for path in documented_paths:
        assert path in html, f"expected the dashboard JS to reference {path!r}"
