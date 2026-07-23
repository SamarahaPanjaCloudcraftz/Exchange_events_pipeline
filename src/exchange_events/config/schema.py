"""Configuration schema (design doc §8.1).

Structured, validated config loaded from TOML (see ``loader.py``); secrets come
from the environment separately and are merged in by the loader — never stored
in TOML (see ``.env.example``). No component reads this directly except
``wiring.py``; everything downstream receives already-resolved values through
its constructor (P1/P3).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    backend: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: str = "exchange_events.db"
    postgres_dsn: str | None = None  # filled from EXCHANGE_EVENTS_PG_DSN env var


class AdapterConfigModel(BaseModel):
    """TOML-shaped mirror of ``adapters.config.AdapterConfig`` (a dataclass, not
    a pydantic model, since adapters shouldn't depend on pydantic)."""

    urls: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 30.0
    api_key: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class IngestionConfig(BaseModel):
    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    incremental: bool = True
    default_range_days: int = 365  # how far ahead a full ingest looks by default


class AlertingConfig(BaseModel):
    lookback_days: int = 1
    lookahead_days: int = 30  # wide enough that far-out events get an INFO row early
    dst_warning_days: int = 2
    dst_critical_days: int = 1
    expiry_warning_days: int = 2
    economic_release_warning_days: int = 2
    economic_release_critical_days: int = 1


class RecipientModel(BaseModel):
    id: str
    address: str
    display_name: str = ""


class RouteRuleModel(BaseModel):
    severity: str | None = None          # "info" | "warning" | "critical" | None (any)
    event_types: list[str] | None = None  # canonical EventType values, or None (any)
    channels: list[str] = Field(default_factory=list)
    recipients: list[str] = Field(default_factory=list)  # recipient group names


class EmailConfig(BaseModel):
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None      # from SMTP_PASSWORD env
    from_address: str | None = None


class TeamsConfig(BaseModel):
    webhook_url: str | None = None        # from TEAMS_WEBHOOK_URL env


class NotificationConfig(BaseModel):
    enabled_channels: list[str] = Field(default_factory=lambda: ["dashboard"])
    email: EmailConfig = Field(default_factory=EmailConfig)
    teams: TeamsConfig = Field(default_factory=TeamsConfig)
    routes: list[RouteRuleModel] = Field(default_factory=list)
    recipient_groups: dict[str, list[RecipientModel]] = Field(default_factory=dict)


class IVConfig(BaseModel):
    enabled: bool = False
    default_threshold: float = 0.30
    thresholds: dict[str, float] = Field(default_factory=dict)


class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False


class AppConfig(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    adapters: dict[str, AdapterConfigModel] = Field(default_factory=dict)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    iv: IVConfig = Field(default_factory=IVConfig)
    api: APIConfig = Field(default_factory=APIConfig)
