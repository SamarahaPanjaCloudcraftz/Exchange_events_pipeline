"""Dashboard convenience endpoints (design doc §5.6, §5.7).

    GET /api/v1/calendar/<year>/<month>  -> events for that month, grouped by date
    GET /api/v1/exchanges                -> static list of configured exchanges
"""

from __future__ import annotations

import calendar
import datetime
from typing import Any

from flask import Blueprint, current_app, jsonify
from flask.typing import ResponseReturnValue

from ...contracts.repository import EventRepository
from ...domain.query import EventQuery
from ...domain.reconciliation import reconcile_economic_releases
from ..serializers import error_envelope, event_to_dict

bp = Blueprint("calendar", __name__, url_prefix="/api/v1")

# Static exchange metadata (§5.6 "Static list of configured exchanges with metadata").
# Adding a new exchange here is additive (P4) — no other route changes. "country"
# lets the dashboard associate an exchange with that country's economic releases
# (e.g. showing US releases under the CME tab) — any future US exchange added
# here automatically gets the same association, no dashboard code change needed.
# "timezone" is the IANA zone the exchange actually operates in (matching
# adapters/iana.py's DEFAULT_ZONES) — lets the dashboard surface each exchange's
# own next DST transition, since a strategy's session-time parameters need to
# track the exchange's clock, not the viewer's.
EXCHANGES = [
    {"mic": "XNSE", "name": "National Stock Exchange of India", "source": "nse_circular",
     "country": "IN", "timezone": "Asia/Kolkata"},
    {"mic": "XBOM", "name": "BSE Ltd (Bombay Stock Exchange)", "source": "bse_circular",
     "country": "IN", "timezone": "Asia/Kolkata"},
    {"mic": "XKRX", "name": "Korea Exchange", "source": "krx_calendar", "country": "KR",
     "timezone": "Asia/Seoul"},
    {"mic": "XCME", "name": "CME Group", "source": "cme_calendar", "country": "US",
     "timezone": "America/Chicago"},
]


@bp.get("/calendar/<int:year>/<int:month>")
def month_calendar(year: int, month: int) -> ResponseReturnValue:
    if not (1 <= month <= 12):
        return jsonify(error_envelope(f"invalid month: {month} (expected 1-12)")), 400
    try:
        last_day = calendar.monthrange(year, month)[1]
        date_from = datetime.date(year, month, 1)
        date_to = datetime.date(year, month, last_day)
    except ValueError as exc:
        return jsonify(error_envelope(f"invalid year/month: {exc}")), 400

    repository: EventRepository = current_app.config["EE_REPOSITORY"]
    query = EventQuery(date_from=date_from, date_to=date_to)
    events = reconcile_economic_releases(repository.query(query))

    by_date: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_date.setdefault(event.date.isoformat(), []).append(event_to_dict(event))

    return jsonify({"year": year, "month": month, "days": by_date})


@bp.get("/exchanges")
def exchanges() -> ResponseReturnValue:
    return jsonify(EXCHANGES)
