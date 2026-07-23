"""Manual ingest trigger (design doc §5.6): POST /api/v1/ingest/trigger.

Body (JSON, all optional):
    {"source": "cme_calendar", "date_from": "2026-01-01", "date_to": "2026-12-31",
     "incremental": true}

``source`` omitted -> ``run_full_ingest`` across every adapter. ``date_from``/
``date_to`` default to today..today+``default_range_days`` (from ingestion
config). Returns the ``IngestionReport`` serialized per source.
"""

from __future__ import annotations

import datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from ...contracts.clock import Clock
from ...domain.query import DateRange
from ...ingestion.engine import IngestionEngine
from ...ingestion.report import IngestionReport
from ..serializers import error_envelope

bp = Blueprint("ingest", __name__, url_prefix="/api/v1/ingest")


def _report_to_dict(report: IngestionReport) -> dict[str, Any]:
    return {
        "started_at": report.started_at.isoformat() if report.started_at else None,
        "finished_at": report.finished_at.isoformat() if report.finished_at else None,
        "total_upserted": report.total_upserted,
        "any_source_failed": report.any_source_failed,
        "results": [
            {
                "source_name": r.source_name,
                "fetched": r.fetched,
                "normalized": r.normalized,
                "normalization_errors": r.normalization_errors,
                "upserted_inserted": r.upserted_inserted,
                "upserted_updated": r.upserted_updated,
                "upserted_unchanged": r.upserted_unchanged,
                "succeeded": r.succeeded,
                "error": r.error,
                "duration_seconds": r.duration_seconds,
            }
            for r in report.results
        ],
    }


@bp.post("/trigger")
def trigger_ingest() -> ResponseReturnValue:
    engine: IngestionEngine = current_app.config["EE_INGESTION_ENGINE"]
    clock: Clock = current_app.config["EE_CLOCK"]
    default_days: int = current_app.config["EE_DEFAULT_RANGE_DAYS"]

    body = request.get_json(silent=True) or {}
    today = clock.today_utc()
    try:
        date_from = (
            datetime.date.fromisoformat(body["date_from"]) if body.get("date_from") else today
        )
        date_to = (
            datetime.date.fromisoformat(body["date_to"])
            if body.get("date_to")
            else today + datetime.timedelta(days=default_days)
        )
        date_range = DateRange(date_from, date_to)
    except (ValueError, KeyError) as exc:
        return jsonify(error_envelope(f"invalid request body: {exc}")), 400

    incremental = bool(body.get("incremental", False))
    source = body.get("source")

    try:
        if source:
            report = engine.run_single_source(source, date_range, incremental=incremental)
        else:
            report = engine.run_full_ingest(date_range, incremental=incremental)
    except ValueError as exc:
        return jsonify(error_envelope(str(exc), code="not_found")), 404

    return jsonify(_report_to_dict(report))
