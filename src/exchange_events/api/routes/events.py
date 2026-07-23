"""Event endpoints (design doc §5.6).

    GET /api/v1/events            -> EventRepository.query(filters_from_query_params)
    GET /api/v1/events/<id>       -> EventRepository.get_by_id(event_id)
    GET /api/v1/events/upcoming   -> EventRepository.query(date_from=today, date_to=today+N)
"""

from __future__ import annotations

import datetime

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from ...contracts.clock import Clock
from ...contracts.repository import EventRepository
from ...domain.query import EventQuery
from ...domain.reconciliation import reconcile_economic_releases
from ..query_params import QueryParamError, parse_event_query
from ..serializers import error_envelope, event_to_dict

bp = Blueprint("events", __name__, url_prefix="/api/v1/events")

DEFAULT_UPCOMING_DAYS = 14


@bp.get("")
def list_events() -> ResponseReturnValue:
    repository: EventRepository = current_app.config["EE_REPOSITORY"]
    try:
        query = parse_event_query(request.args)
    except QueryParamError as exc:
        return jsonify(error_envelope(str(exc))), 400
    events = reconcile_economic_releases(repository.query(query))
    return jsonify([event_to_dict(e) for e in events])


@bp.get("/upcoming")
def upcoming_events() -> ResponseReturnValue:
    repository: EventRepository = current_app.config["EE_REPOSITORY"]
    clock: Clock = current_app.config["EE_CLOCK"]
    days = request.args.get("days", str(DEFAULT_UPCOMING_DAYS))
    try:
        days_int = int(days)
    except ValueError:
        return jsonify(error_envelope(f"invalid 'days' value: {days!r}")), 400

    today = clock.today_utc()
    query = EventQuery(date_from=today, date_to=today + datetime.timedelta(days=days_int))
    events = reconcile_economic_releases(repository.query(query))
    return jsonify([event_to_dict(e) for e in events])


@bp.get("/<event_id>")
def get_event(event_id: str) -> ResponseReturnValue:
    repository: EventRepository = current_app.config["EE_REPOSITORY"]
    event = repository.get_by_id(event_id)
    if event is None:
        return jsonify(error_envelope(f"no event with id {event_id!r}", code="not_found")), 404
    return jsonify(event_to_dict(event))
