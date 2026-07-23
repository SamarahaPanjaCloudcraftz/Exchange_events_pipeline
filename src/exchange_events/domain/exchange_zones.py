"""Exchange <-> IANA timezone mapping (post-delivery: proximity-based alert
severity, see DECISIONS.md).

``DSTChangeEvent`` carries only an ``iana_zone`` (design doc §3.2 — DST
transitions aren't tied to a single exchange), but a DST alert still needs to
say *which exchange(s)* this affects, not just the zone. This mirrors
``api/routes/calendar.py``'s ``EXCHANGES`` list, duplicated here (rather than
imported from there) because ``alerting/`` must never import from ``api/``
(dependencies point inward, §1 P1) — if a new exchange is added to that list,
add it here too.
"""

from __future__ import annotations

EXCHANGE_TIMEZONES: dict[str, str] = {
    "XNSE": "Asia/Kolkata",
    "XBOM": "Asia/Kolkata",
    "XKRX": "Asia/Seoul",
    "XCME": "America/Chicago",
}


def exchanges_for_zone(iana_zone: str) -> list[str]:
    """Configured exchange MICs whose local clock is this IANA zone (sorted,
    possibly empty for a zone we track but that isn't any configured
    exchange's own timezone, e.g. a generic reference zone)."""
    return sorted(mic for mic, zone in EXCHANGE_TIMEZONES.items() if zone == iana_zone)


# Named standard/daylight abbreviations, mirroring the dashboard's own
# ``ZONE_ABBR`` map (dashboard/static/index.html) so alert text and the
# dashboard's "Next Timezone Shift" block always agree. Zones with no DST
# (Asia/Kolkata, Asia/Seoul) are intentionally absent -- they never produce a
# transition event to label in the first place.
ZONE_ABBR: dict[str, tuple[str, str]] = {
    "America/New_York": ("EST", "EDT"),
    "America/Chicago": ("CST", "CDT"),
    "Europe/London": ("GMT", "BST"),
    "Europe/Berlin": ("CET", "CEST"),
}


def dst_transition_label(iana_zone: str, transition: str | None) -> str | None:
    """"CDT -> CST" style label for a DST transition, or ``None`` if this zone
    has no known abbreviation pair or the transition direction is unknown.
    ``transition`` is ``DSTChangeEvent.metadata["transition"]`` -- "start"
    (entering daylight saving, e.g. March) or "end" (leaving it, e.g.
    November); the adapter derives this from whether the UTC offset grew or
    shrank (adapters/iana.py)."""
    abbr = ZONE_ABBR.get(iana_zone)
    if abbr is None or transition not in ("start", "end"):
        return None
    standard, daylight = abbr
    return f"{standard} -> {daylight}" if transition == "start" else f"{daylight} -> {standard}"
