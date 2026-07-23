"""Configuration (design doc §8) — pydantic schema + TOML/env loader."""

from __future__ import annotations

from .loader import Secrets, load_config, load_toml
from .schema import (
    AdapterConfigModel,
    AlertingConfig,
    APIConfig,
    AppConfig,
    DatabaseConfig,
    EmailConfig,
    IngestionConfig,
    IVConfig,
    NotificationConfig,
    RecipientModel,
    RouteRuleModel,
    TeamsConfig,
)

__all__ = [
    "AppConfig",
    "DatabaseConfig",
    "AdapterConfigModel",
    "IngestionConfig",
    "AlertingConfig",
    "NotificationConfig",
    "EmailConfig",
    "TeamsConfig",
    "RouteRuleModel",
    "RecipientModel",
    "IVConfig",
    "APIConfig",
    "load_config",
    "load_toml",
    "Secrets",
]
