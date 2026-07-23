"""WSGI entrypoint for a production server (gunicorn/uwsgi), e.g.:

    gunicorn wsgi:app --bind 0.0.0.0:8080 --workers 4

Mirrors main.py::cmd_serve exactly -- no new logic, just exposing the same
Flask app object at module level the way a WSGI server expects.
"""

from __future__ import annotations

from exchange_events.api.app import create_app
from exchange_events.config.loader import load_config
from exchange_events.dashboard.server import bp as dashboard_bp
from exchange_events.wiring import build_application

_app_state = build_application(load_config())

app = create_app(
    repository=_app_state.repository,
    alert_log=_app_state.alert_log,
    ingestion_engine=_app_state.ingestion_engine,
    clock=_app_state.clock,
    iv_provider=_app_state.iv_provider,
    default_range_days=_app_state.config.ingestion.default_range_days,
)
app.register_blueprint(dashboard_bp)
