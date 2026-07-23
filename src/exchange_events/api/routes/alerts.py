"""Alert feed endpoint (design doc §5.6): GET /api/v1/alerts -> AlertLog.recent()."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from ...contracts.alert_log import AlertLog
from ..query_params import QueryParamError, parse_optional_int
from ..serializers import alert_to_dict, error_envelope

bp = Blueprint("alerts", __name__, url_prefix="/api/v1/alerts")

DEFAULT_LIMIT = 50


@bp.get("")
def recent_alerts() -> ResponseReturnValue:
    alert_log: AlertLog = current_app.config["EE_ALERT_LOG"]
    try:
        limit = parse_optional_int(request.args, "limit") or DEFAULT_LIMIT
    except QueryParamError as exc:
        return jsonify(error_envelope(str(exc))), 400
    alerts = alert_log.recent(limit=limit)
    return jsonify([alert_to_dict(a) for a in alerts])
