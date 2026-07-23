"""Adapter configuration (design doc §5.1, §8).

One generic config type carries per-source overrides. Phase-10 ``AppConfig``
populates it from TOML/env; adapters fall back to their documented default
endpoints when a field is empty, so they are usable with zero config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterConfig:
    urls: dict[str, str] = field(default_factory=dict)      # named endpoint overrides
    headers: dict[str, str] = field(default_factory=dict)   # extra request headers/cookies
    params: dict[str, Any] = field(default_factory=dict)    # extra query params
    timeout: float = 30.0
    api_key: str | None = None
    options: dict[str, Any] = field(default_factory=dict)   # adapter-specific knobs

    def url(self, name: str, default: str) -> str:
        return self.urls.get(name, default)

    def option(self, name: str, default: Any = None) -> Any:
        return self.options.get(name, default)
