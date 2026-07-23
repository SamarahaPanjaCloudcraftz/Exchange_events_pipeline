"""Ingestion engine (design doc §5.3) — orchestrates fetch → normalize → store."""

from __future__ import annotations

from .engine import IngestionEngine
from .normalizer_registry import NormalizerRegistry
from .report import IngestionReport, SourceIngestResult
from .retry import RetryPolicy

__all__ = [
    "IngestionEngine",
    "NormalizerRegistry",
    "RetryPolicy",
    "IngestionReport",
    "SourceIngestResult",
]
