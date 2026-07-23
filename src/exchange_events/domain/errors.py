"""Typed exception hierarchy (design doc §4, §7).

Errors are categorized so each layer can catch exactly what it must and let the
rest propagate. The guiding rule from §7: *fail locally, report globally, never
cascade.* Every custom exception derives from :class:`ExchangeEventsError`.
"""

from __future__ import annotations

from typing import Any


class ExchangeEventsError(Exception):
    """Root of all pipeline-specific exceptions."""


# --- Source adapter errors (§4.1) -------------------------------------------------
class SourceError(ExchangeEventsError):
    """Base for anything that goes wrong talking to an external source."""


class SourceUnavailableError(SourceError):
    """The source is down, unreachable, or returned an unusable response."""


class SourceRateLimitError(SourceError):
    """We hit the source's rate limit; retry after backoff."""


# --- Normalizer errors (§4.2, §5.2) ----------------------------------------------
class NormalizationError(ExchangeEventsError):
    """A single raw record could not be transformed into a canonical event.

    Per §5.2 a normalizer never *raises* this for one bad record — it collects
    instances into a ``NormalizationResult.errors`` list and keeps going. The
    offending record and reason are retained for observability.
    """

    def __init__(
        self,
        reason: str,
        *,
        raw_record: Any | None = None,
        source: str | None = None,
    ) -> None:
        self.reason = reason
        self.raw_record = raw_record
        self.source = source
        super().__init__(reason)


# --- Storage errors ---------------------------------------------------------------
class RepositoryError(ExchangeEventsError):
    """Persistence failure (connection, constraint, serialization)."""


# --- Notification errors (§4.5) ---------------------------------------------------
class ChannelUnavailableError(ExchangeEventsError):
    """A notification channel itself is down (not a per-recipient failure)."""


# --- Configuration errors (§8) ----------------------------------------------------
class ConfigError(ExchangeEventsError):
    """Configuration is missing or invalid."""
