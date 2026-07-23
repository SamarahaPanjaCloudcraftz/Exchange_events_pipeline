"""Deterministic identifier generation (design doc §3.4).

Event IDs are derived from the natural key, which is what makes ingestion
idempotent (P6): re-fetching the same event from the same source yields the
same ID, so storage upserts instead of duplicating.

    event_id = sha256(f"{source}:{event_type}:{exchange}:{date}:{discriminator}")

where ``discriminator`` is category-specific:
    - holiday          -> holiday_name
    - expiry           -> f"{underlying}:{series}"
    - economic_release -> release_code
    - dst_change       -> iana_zone

Alert IDs follow the same idea, but for a different purpose — *not* per-firing
dedup, but a stable identity per (rule, event) so severity can be re-classified
in place as time passes (§5.4 post-delivery: "proximity-based severity, one
record per event, escalates over time" — see DECISIONS.md):

    alert_id = sha256(f"{rule_id}:{event_id}")
"""

from __future__ import annotations

import datetime
import hashlib

from .enums import EventType


def make_event_id(
    *,
    source: str,
    event_type: EventType | str,
    exchange: str | None,
    date: datetime.date,
    discriminator: str,
) -> str:
    """Derive a deterministic event ID from its natural key (§3.4).

    ``exchange`` may be ``None`` (e.g. DST changes) and is rendered as the empty
    string so the key stays stable. ``event_type`` accepts either the enum or its
    string value so callers reconstructing from storage need no conversion.
    """
    et = event_type.value if isinstance(event_type, EventType) else str(event_type)
    key = f"{source}:{et}:{exchange or ''}:{date.isoformat()}:{discriminator}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def make_alert_id(*, rule_id: str, event_id: str) -> str:
    """Derive a deterministic, time-stable alert ID (§4.4).

    Deliberately excludes any date/time component: the same (rule, event) pair
    must always resolve to the same id so ``AlertLog.upsert`` updates a single
    row in place as an event's classified severity escalates (INFO -> WARNING
    -> CRITICAL) across repeated pipeline runs, rather than creating a new row
    per evaluation.
    """
    key = f"{rule_id}:{event_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
