"""Query-string -> domain value-object parsing (design doc §5.6).

Kept separate from the route handlers so the parsing logic (and its error
messages) is independently testable and reusable across endpoints.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping

from ..domain.enums import EventType
from ..domain.errors import ExchangeEventsError
from ..domain.query import EventQuery


class QueryParamError(ExchangeEventsError):
    """A query parameter could not be parsed (surfaced as HTTP 400)."""


def _csv(args: Mapping[str, str], key: str) -> list[str] | None:
    value = args.get(key)
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_date(args: Mapping[str, str], key: str) -> datetime.date | None:
    value = args.get(key)
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise QueryParamError(f"invalid date for {key!r}: {value!r} (expected YYYY-MM-DD)") from exc


def _parse_int(args: Mapping[str, str], key: str, default: int) -> int:
    value = args.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise QueryParamError(f"invalid integer for {key!r}: {value!r}") from exc


def parse_optional_int(args: Mapping[str, str], key: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise QueryParamError(f"invalid integer for {key!r}: {value!r}") from exc


def parse_event_query(args: Mapping[str, str]) -> EventQuery:
    """Build an ``EventQuery`` from Flask's ``request.args`` (§4.3.1)."""
    event_types_raw = _csv(args, "event_types")
    event_types = None
    if event_types_raw is not None:
        try:
            event_types = [EventType(v) for v in event_types_raw]
        except ValueError as exc:
            raise QueryParamError(f"invalid event_types value: {exc}") from exc

    return EventQuery(
        event_types=event_types,
        exchanges=_csv(args, "exchanges"),
        date_from=_parse_date(args, "date_from"),
        date_to=_parse_date(args, "date_to"),
        release_codes=_csv(args, "release_codes"),
        include_metadata=args.get("include_metadata", "").lower() in ("1", "true", "yes"),
        limit=parse_optional_int(args, "limit"),
        offset=_parse_int(args, "offset", default=0),
    )
