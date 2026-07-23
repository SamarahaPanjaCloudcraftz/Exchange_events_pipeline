"""IV endpoint (design doc §5.6): GET /api/v1/iv/<exchange>/<underlying>.

Optional dependency (§4.6) — returns a clear 501 if no ``IVThresholdProvider``
is wired, rather than a bare 404/500.
"""

from __future__ import annotations

import datetime

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from ...contracts.clock import Clock
from ...contracts.iv_provider import IVThresholdProvider
from ..query_params import QueryParamError
from ..serializers import error_envelope, iv_snapshot_to_dict

bp = Blueprint("iv", __name__, url_prefix="/api/v1/iv")

DEFAULT_LOOKBACK_DAYS = 90


@bp.get("/<exchange>/<underlying>")
def iv_series(exchange: str, underlying: str) -> ResponseReturnValue:
    provider: IVThresholdProvider | None = current_app.config["EE_IV_PROVIDER"]
    if provider is None:
        return (
            jsonify(error_envelope("no IV provider configured", code="not_implemented")),
            501,
        )

    clock: Clock = current_app.config["EE_CLOCK"]
    today = clock.today_utc()
    try:
        date_from_str = request.args.get("date_from")
        date_to_str = request.args.get("date_to")
        date_from = (
            datetime.date.fromisoformat(date_from_str)
            if date_from_str
            else today - datetime.timedelta(days=DEFAULT_LOOKBACK_DAYS)
        )
        date_to = datetime.date.fromisoformat(date_to_str) if date_to_str else today
    except ValueError as exc:
        raise QueryParamError(f"invalid date_from/date_to: {exc}") from exc

    series = provider.get_iv_series(exchange, underlying, date_from, date_to)
    return jsonify([iv_snapshot_to_dict(s) for s in series])


@bp.errorhandler(QueryParamError)
def _handle_query_param_error(exc: QueryParamError) -> ResponseReturnValue:
    return jsonify(error_envelope(str(exc))), 400
