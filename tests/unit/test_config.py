"""Unit tests for config loading/validation (§8.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from exchange_events.config.loader import Secrets, _merge_secrets, load_config, load_toml
from exchange_events.config.schema import AdapterConfigModel, AppConfig
from exchange_events.domain.errors import ConfigError

pytestmark = pytest.mark.unit


def test_load_toml_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_toml(tmp_path / "nope.toml")


def test_load_toml_invalid_syntax_raises_config_error(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not [valid toml", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_toml(bad)


def test_default_config_validates():
    cfg = AppConfig()
    assert cfg.database.backend == "sqlite"
    assert cfg.notification.enabled_channels == ["dashboard"]


def test_app_config_rejects_unknown_backend():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"database": {"backend": "mongodb"}})


def test_load_config_bundled_defaults_toml():
    cfg = load_config(env_file="/nonexistent/.env")  # avoid picking up a real .env
    assert len(cfg.notification.routes) == 3
    assert "team_trading" in cfg.notification.recipient_groups
    assert set(cfg.adapters.keys()) == {
        "cme_calendar", "nse_circular", "bse_circular", "krx_calendar", "iana_tz",
        "fred_api", "bls_api", "bea_api", "ism_pmi", "fomc_schedule", "econ_calendar",
    }


def test_load_config_custom_path(tmp_path):
    custom = tmp_path / "custom.toml"
    custom.write_text('[database]\nbackend = "postgres"\n', encoding="utf-8")
    cfg = load_config(custom, env_file="/nonexistent/.env")
    assert cfg.database.backend == "postgres"


# --- secrets merging -------------------------------------------------------------------
def test_merge_secrets_overlays_pg_dsn():
    cfg = AppConfig()
    secrets = Secrets(exchange_events_pg_dsn="postgresql://x", _env_file=None)
    merged = _merge_secrets(cfg, secrets)
    assert merged.database.postgres_dsn == "postgresql://x"


def test_merge_secrets_sets_fred_api_key_creating_adapter_entry_if_absent():
    cfg = AppConfig()
    assert "fred_api" not in cfg.adapters
    secrets = Secrets(fred_api_key="abc123", _env_file=None)
    merged = _merge_secrets(cfg, secrets)
    assert merged.adapters["fred_api"].api_key == "abc123"


def test_merge_secrets_preserves_existing_fred_adapter_options():
    cfg = AppConfig(adapters={"fred_api": AdapterConfigModel(options={"series": {}})})
    secrets = Secrets(fred_api_key="abc123", _env_file=None)
    merged = _merge_secrets(cfg, secrets)
    assert merged.adapters["fred_api"].api_key == "abc123"
    assert merged.adapters["fred_api"].options == {"series": {}}


def test_merge_secrets_sets_email_fields():
    cfg = AppConfig()
    secrets = Secrets(
        smtp_host="smtp.example.com", smtp_username="u", smtp_password="p",
        smtp_from_address="alerts@example.com", _env_file=None,
    )
    merged = _merge_secrets(cfg, secrets)
    assert merged.notification.email.smtp_host == "smtp.example.com"
    assert merged.notification.email.smtp_username == "u"
    assert merged.notification.email.smtp_password == "p"
    assert merged.notification.email.from_address == "alerts@example.com"


def test_merge_secrets_sets_teams_webhook():
    cfg = AppConfig()
    secrets = Secrets(teams_webhook_url="https://hook", _env_file=None)
    merged = _merge_secrets(cfg, secrets)
    assert merged.notification.teams.webhook_url == "https://hook"


def test_merge_secrets_no_op_when_nothing_set():
    cfg = AppConfig()
    secrets = Secrets(_env_file=None)
    merged = _merge_secrets(cfg, secrets)
    assert merged.database.postgres_dsn is None
    assert merged.notification.email.smtp_host is None
    assert merged.notification.teams.webhook_url is None
