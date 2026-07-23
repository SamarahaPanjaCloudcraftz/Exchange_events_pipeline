"""Cross-source reconciliation for economic-release events (design doc §3.2, §5.6).

Multiple sources can independently produce an `EconomicReleaseEvent` for the same
real-world release (e.g. FRED's "CPI" for 2026-01-13 and BLS's "CPI" for the same
date) — each gets its own ``event_id`` because ``source`` is part of the natural
key (§3.4), by design, so per-source ingestion stays simple and idempotent (P6:
each source's own history is preserved untouched in storage). But showing two
near-duplicate rows for the same release in the dashboard/API is a poor
presentation, and (historically) it silently defeated any rule needing both
``forecast`` and ``actual`` together if one source only had one of the two —
neither event alone had both.

This module is a pure, read-time reconciliation step (no storage/ingestion
changes, no mutation of persisted events): callers that display or evaluate
economic-release events run their query results through
:func:`reconcile_economic_releases` before use. It groups events by
``(release_code, date)``, and for each group builds one merged event by taking,
field by field, the value from the highest-priority source that has a non-``None``
value for that field — so e.g. a MarketWatch forecast and a FRED actual for the
same release combine into a single event with both populated. It's also what
keeps ``EconomicReleaseProximityRule`` (``alerting/rules/economic_release_proximity.py``)
from producing two alert rows for the same real-world release when it's
ingested from more than one source.

Source priority (highest first) mirrors the waterfall's reliability ranking
(DECISIONS.md "Economic-release waterfall"): official government/Fed APIs first,
the best-effort ISM aggregator next, and the (currently blocked) MarketWatch
scraper last — it contributes only if it's ever re-enabled from an unblocked host.
Non-economic-release events pass through untouched.
"""

from __future__ import annotations

from collections.abc import Iterable

from .events import EconomicReleaseEvent, Event

DEFAULT_SOURCE_PRIORITY: tuple[str, ...] = (
    "fred_api",        # tier 1 — primary, covers 6 of 7 releases
    "fomc_schedule",   # Fed's own meeting calendar — most authoritative for FOMC
                       # dates specifically, but never sets actual/forecast, so its
                       # ranking above fred_api's DFEDTARU never matters in practice
                       # (they're complementary: one supplies the date, one the rate)
    "bls_api",         # tier 2 — official backstop (NFP/CPI/PPI/JOLTS)
    "bea_api",         # tier 3 — official backstop (PCE)
    "ism_pmi",         # best-effort — ISM Manufacturing PMI only
    "econ_calendar",   # MarketWatch — currently blocked; lowest priority if revived
)

_MERGE_FIELDS = (
    "forecast", "previous", "actual", "revision", "unit", "agency", "period", "country",
)


def _priority_rank(source: str, priority: tuple[str, ...]) -> int:
    try:
        return priority.index(source)
    except ValueError:
        return len(priority)  # unranked sources sort last, not dropped


def reconcile_economic_releases(
    events: Iterable[Event],
    *,
    source_priority: tuple[str, ...] = DEFAULT_SOURCE_PRIORITY,
) -> list[Event]:
    """Merge same-(release_code, date) events from multiple sources into one.

    Preserves input order for the first occurrence of each group and for every
    non-``EconomicReleaseEvent`` (passed through unchanged). Field-level merge:
    for each of forecast/previous/actual/revision/unit/agency/period, take the
    first non-``None``/non-empty value found while walking the group's events in
    priority order.
    """
    groups: dict[tuple[str, object], list[EconomicReleaseEvent]] = {}
    order: list[tuple[str, object] | int] = []
    passthrough: dict[int, Event] = {}

    for i, event in enumerate(events):
        if not isinstance(event, EconomicReleaseEvent):
            passthrough[i] = event
            order.append(i)
            continue
        key = (event.release_code, event.date)
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(event)

    result: list[Event] = []
    for item in order:
        if isinstance(item, int):
            result.append(passthrough[item])
            continue
        result.append(_merge_group(groups[item], source_priority))
    return result


def _merge_group(
    group: list[EconomicReleaseEvent], source_priority: tuple[str, ...]
) -> EconomicReleaseEvent:
    if len(group) == 1:
        return group[0]

    ranked = sorted(group, key=lambda e: _priority_rank(e.source, source_priority))
    base = ranked[0]
    merged_fields: dict[str, object] = {}
    for field_name in _MERGE_FIELDS:
        for event in ranked:
            value = getattr(event, field_name)
            if value not in (None, ""):
                merged_fields[field_name] = value
                break

    contributing_sources = sorted({e.source for e in group})
    metadata = dict(base.metadata)
    metadata["reconciled_from"] = contributing_sources

    return EconomicReleaseEvent(
        event_id=base.event_id,
        source=base.source,
        exchange=base.exchange,
        date=base.date,
        timestamp_utc=base.timestamp_utc,
        source_raw_id=base.source_raw_id,
        ingested_at=base.ingested_at,
        updated_at=base.updated_at,
        metadata=metadata,
        release_name=base.release_name,
        release_code=base.release_code,
        agency=str(merged_fields.get("agency", base.agency)),
        period=str(merged_fields.get("period", base.period)),
        forecast=merged_fields.get("forecast"),  # type: ignore[arg-type]
        previous=merged_fields.get("previous"),  # type: ignore[arg-type]
        actual=merged_fields.get("actual"),  # type: ignore[arg-type]
        revision=merged_fields.get("revision"),  # type: ignore[arg-type]
        unit=str(merged_fields.get("unit", base.unit)),
        country=merged_fields.get("country", base.country),  # type: ignore[arg-type]
    )
