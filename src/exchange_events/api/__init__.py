"""HTTP API layer (design doc §5.6) — a thin Flask boundary over the pipeline."""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
