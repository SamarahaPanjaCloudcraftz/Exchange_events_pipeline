"""Unit tests for the CLI entry point (§5.3, §13). Each command is exercised
end-to-end against a temp SQLite file — no mocking of the wiring layer, since
the whole point of the CLI is to prove build_application() + load_config()
work together for a real user-facing invocation."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.main import cmd_serve, main

pytestmark = pytest.mark.unit


@pytest.fixture
def config_path(tmp_path):
    cfg = tmp_path / "config.toml"
    db = tmp_path / "ee.db"
    cfg.write_text(
        f'[database]\nbackend = "sqlite"\nsqlite_path = "{db}"\n'
        '[ingestion]\ndefault_range_days = 30\n',
        encoding="utf-8",
    )
    return cfg


# --- init-db ---------------------------------------------------------------------
def test_init_db_creates_schema_and_returns_zero(config_path, capsys):
    code = main(["--config", str(config_path), "init-db"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Database ready" in out
    assert "sqlite" in out


def test_init_db_is_idempotent(config_path):
    assert main(["--config", str(config_path), "init-db"]) == 0
    assert main(["--config", str(config_path), "init-db"]) == 0  # re-running is safe


# --- ingest ------------------------------------------------------------------------
def test_ingest_single_source_offline_iana(config_path, capsys):
    code = main([
        "--config", str(config_path), "ingest",
        "--source", "iana_tz", "--from", "2026-01-01", "--to", "2026-12-31",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "[iana_tz]" in out
    assert "(OK)" in out
    assert "Total upserted:" in out


def test_ingest_unknown_source_returns_error(config_path):
    code = main([
        "--config", str(config_path), "ingest",
        "--source", "nonexistent_source", "--from", "2026-01-01", "--to", "2026-12-31",
    ])
    assert code == 1


def test_ingest_defaults_date_range_when_omitted(config_path, capsys):
    code = main(["--config", str(config_path), "ingest", "--source", "iana_tz"])
    assert code == 0
    assert "Total upserted:" in capsys.readouterr().out


# --- alert ---------------------------------------------------------------------------
def test_alert_runs_cleanly_with_no_events(config_path, capsys):
    code = main(["--config", str(config_path), "alert"])
    assert code == 0
    assert "new alert(s) fired" in capsys.readouterr().out


def test_alert_no_dispatch_flag_skips_delivery(config_path, capsys):
    # Seed an expiry that ExpiryProximityRule will classify WARNING (1 day away,
    # within its default warning_days=2) relative to the real system clock, then
    # check --no-dispatch never prints "Dispatched".
    from exchange_events.config.loader import load_config
    from exchange_events.domain.events import ExpiryEvent
    from exchange_events.wiring import build_application

    config = load_config(str(config_path))
    app = build_application(config)
    tomorrow = app.clock.today_utc() + datetime.timedelta(days=1)
    app.repository.upsert([ExpiryEvent(
        source="cme", exchange="XCME", date=tomorrow, instrument_type="futures",
        underlying="ES", series="quarterly", expiry_date=tomorrow,
    )])

    code = main(["--config", str(config_path), "alert", "--no-dispatch"])
    assert code == 0
    out = capsys.readouterr().out
    assert "1 new alert(s) fired." in out
    assert "Dispatched" not in out


def test_alert_dispatches_by_default(config_path, capsys):
    from exchange_events.config.loader import load_config
    from exchange_events.domain.events import ExpiryEvent
    from exchange_events.wiring import build_application

    config = load_config(str(config_path))
    app = build_application(config)
    tomorrow = app.clock.today_utc() + datetime.timedelta(days=1)
    app.repository.upsert([ExpiryEvent(
        source="cme", exchange="XCME", date=tomorrow, instrument_type="futures",
        underlying="ES", series="quarterly", expiry_date=tomorrow,
    )])

    code = main(["--config", str(config_path), "alert"])
    assert code == 0
    out = capsys.readouterr().out
    assert "1 new alert(s) fired." in out
    assert "Dispatched:" in out


# --- serve (never actually binds a socket in tests) ------------------------------------
def test_serve_builds_app_and_invokes_injected_runner(config_path):
    import argparse

    args = argparse.Namespace(config=str(config_path), host=None, port=None, debug=False)
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)

    code = cmd_serve(args, run_server=fake_run)
    assert code == 0
    assert captured["host"]  # defaults come from config.api
    assert isinstance(captured["port"], int)
    assert captured["debug"] is False


def test_serve_cli_flags_override_config_defaults(config_path):
    import argparse

    args = argparse.Namespace(
        config=str(config_path), host="127.0.0.1", port=9999, debug=True
    )
    captured = {}
    cmd_serve(args, run_server=lambda **kw: captured.update(kw))
    assert captured == {"host": "127.0.0.1", "port": 9999, "debug": True}


# --- top-level main() dispatch -----------------------------------------------------
def test_main_requires_a_subcommand(config_path):
    with pytest.raises(SystemExit):
        main(["--config", str(config_path)])


def test_main_unknown_command_exits_nonzero(config_path):
    with pytest.raises(SystemExit):
        main(["--config", str(config_path), "not-a-real-command"])
