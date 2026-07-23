"""Config loader (design doc §8.1) — TOML for structure, environment for secrets.

TOML never contains secrets (see ``.env.example`` at the repo root); this loader
reads structural config from a TOML file and overlays secret values from the
environment (``pydantic-settings``) on top, matching each variable in
``.env.example`` exactly. No other module reads a file or an env var directly —
``build_application`` is handed a single fully-resolved ``AppConfig``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain.errors import ConfigError
from .schema import AdapterConfigModel, AppConfig

DEFAULTS_PATH = Path(__file__).parent / "defaults.toml"


class Secrets(BaseSettings):
    """Mirrors ``.env.example`` exactly — one field per documented variable."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cme_api_id: str | None = None
    cme_api_secret: str | None = None
    fred_api_key: str | None = None
    bls_api_key: str | None = None
    bea_api_key: str | None = None
    ism_api_key: str | None = None
    ism_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    teams_webhook_url: str | None = None
    alert_recipient_email: str | None = None
    alert_recipient_name: str | None = None
    exchange_events_pg_dsn: str | None = None
    exchange_events_sqlite_path: str | None = None


def load_toml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {p}: {exc}") from exc


def load_config(path: str | Path | None = None, *, env_file: str | Path = ".env") -> AppConfig:
    """Load and validate the full application config.

    ``path`` defaults to the bundled ``defaults.toml``. Secrets are read from the
    environment (and ``env_file`` if present) and merged in — env values always
    take precedence over anything (accidentally) present in TOML, since secrets
    should never live there.
    """
    raw = load_toml(path or DEFAULTS_PATH)
    try:
        config = AppConfig.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - surfaced as a single clear ConfigError
        raise ConfigError(f"invalid configuration: {exc}") from exc

    secrets = Secrets(_env_file=env_file)  # type: ignore[call-arg]
    return _merge_secrets(config, secrets)


def _merge_secrets(config: AppConfig, secrets: Secrets) -> AppConfig:
    if secrets.exchange_events_pg_dsn:
        config.database.postgres_dsn = secrets.exchange_events_pg_dsn

    # Deployment-specific storage path, not really a "secret" -- but env-driven
    # for the same reason as the Postgres DSN above: it varies per environment
    # and shouldn't require a separate committed TOML just to change one path.
    if secrets.exchange_events_sqlite_path:
        config.database.sqlite_path = secrets.exchange_events_sqlite_path

    # CME's Reference Data API v3 needs both an OAuth client ID and secret (unlike
    # the single api_key other adapters use) — the secret rides in options since
    # AdapterConfig only has one dedicated api_key slot (see adapters/cme.py).
    if secrets.cme_api_id:
        cme_cfg = config.adapters.setdefault("cme_calendar", AdapterConfigModel())
        cme_cfg.api_key = secrets.cme_api_id
    if secrets.cme_api_secret:
        cme_cfg = config.adapters.setdefault("cme_calendar", AdapterConfigModel())
        cme_cfg.options["api_secret"] = secrets.cme_api_secret

    if secrets.fred_api_key:
        fred_cfg = config.adapters.setdefault("fred_api", AdapterConfigModel())
        fred_cfg.api_key = secrets.fred_api_key

    # BLS works without a key (25 series, less history); the key just raises the
    # limit (§ adapters/bls.py docstring) — so it's optional here, unlike FRED/BEA.
    if secrets.bls_api_key:
        bls_cfg = config.adapters.setdefault("bls_api", AdapterConfigModel())
        bls_cfg.api_key = secrets.bls_api_key

    if secrets.bea_api_key:
        bea_cfg = config.adapters.setdefault("bea_api", AdapterConfigModel())
        bea_cfg.api_key = secrets.bea_api_key

    # ISM is best-effort and provider-agnostic (adapters/ism.py) — both the key and
    # the endpoint URL come from whichever aggregator is eventually chosen.
    if secrets.ism_api_key:
        ism_cfg = config.adapters.setdefault("ism_pmi", AdapterConfigModel())
        ism_cfg.api_key = secrets.ism_api_key
    if secrets.ism_url:
        ism_cfg = config.adapters.setdefault("ism_pmi", AdapterConfigModel())
        ism_cfg.urls["ism"] = secrets.ism_url

    if secrets.smtp_host:
        config.notification.email.smtp_host = secrets.smtp_host
    config.notification.email.smtp_port = secrets.smtp_port
    if secrets.smtp_username:
        config.notification.email.smtp_username = secrets.smtp_username
    if secrets.smtp_password:
        config.notification.email.smtp_password = secrets.smtp_password
    if secrets.smtp_from_address:
        config.notification.email.from_address = secrets.smtp_from_address

    if secrets.teams_webhook_url:
        config.notification.teams.webhook_url = secrets.teams_webhook_url

    # Real recipient address never lives in the committed TOML (see defaults.toml's
    # "placeholder@example.com") -- it overrides whatever's there, same pattern as
    # every other secret above.
    if secrets.alert_recipient_email:
        for recipient in config.notification.recipient_groups.get("team_trading", []):
            recipient.address = secrets.alert_recipient_email
            if secrets.alert_recipient_name:
                recipient.display_name = secrets.alert_recipient_name

    return config
