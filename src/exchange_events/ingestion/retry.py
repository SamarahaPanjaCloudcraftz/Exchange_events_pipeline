"""Retry policy (design doc §5.3).

Injected into the ingestion engine, not hardcoded — a config change, not a code
change, to adjust retry behavior per deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.errors import SourceRateLimitError, SourceUnavailableError


@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    retryable_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: (SourceUnavailableError, SourceRateLimitError)
    )

    def backoff_for(self, attempt: int) -> float:
        """Exponential backoff (attempt 0-indexed), capped at ``backoff_max_seconds``."""
        return min(self.backoff_max_seconds, self.backoff_base_seconds * (2.0**attempt))
