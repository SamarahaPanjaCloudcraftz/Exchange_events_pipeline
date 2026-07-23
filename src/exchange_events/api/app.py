"""Flask app factory (design doc §5.6).

A thin HTTP layer over the repository, alert log, IV provider, and ingestion
engine — no business logic lives here (§5.6: "just request parsing, auth, and
response serialization"). Dependencies are injected as explicit parameters
(never imported concretely), consistent with P1/P3: this module could be handed
fakes in a test and never know the difference.
"""

from __future__ import annotations

from flask import Flask, jsonify
from flask.typing import ResponseReturnValue

from ..contracts.alert_log import AlertLog
from ..contracts.clock import Clock
from ..contracts.iv_provider import IVThresholdProvider
from ..contracts.repository import EventRepository
from ..domain.errors import ExchangeEventsError
from ..ingestion.engine import IngestionEngine
from .query_params import QueryParamError
from .routes import alerts, calendar, events, ingest, iv
from .serializers import error_envelope


def create_app(
    *,
    repository: EventRepository,
    alert_log: AlertLog,
    ingestion_engine: IngestionEngine,
    clock: Clock,
    iv_provider: IVThresholdProvider | None = None,
    default_range_days: int = 365,
) -> Flask:
    app = Flask(__name__)
    app.config["EE_REPOSITORY"] = repository
    app.config["EE_ALERT_LOG"] = alert_log
    app.config["EE_INGESTION_ENGINE"] = ingestion_engine
    app.config["EE_CLOCK"] = clock
    app.config["EE_IV_PROVIDER"] = iv_provider
    app.config["EE_DEFAULT_RANGE_DAYS"] = default_range_days

    app.register_blueprint(events.bp)
    app.register_blueprint(alerts.bp)
    app.register_blueprint(iv.bp)
    app.register_blueprint(calendar.bp)
    app.register_blueprint(ingest.bp)

    @app.errorhandler(QueryParamError)
    def _handle_query_param_error(exc: QueryParamError) -> ResponseReturnValue:
        return jsonify(error_envelope(str(exc))), 400

    @app.errorhandler(ExchangeEventsError)
    def _handle_domain_error(exc: ExchangeEventsError) -> ResponseReturnValue:
        return jsonify(error_envelope(str(exc))), 500

    @app.errorhandler(404)
    def _handle_not_found(exc: Exception) -> ResponseReturnValue:
        return jsonify(error_envelope("resource not found", code="not_found")), 404

    return app
