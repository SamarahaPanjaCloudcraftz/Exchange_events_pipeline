"""Dashboard blueprint (design doc §5.7) — serves the static consumer UI.

Deliberately the thinnest possible layer: one static HTML file with inline
CSS/JS that calls the API (§5.6) and renders the response. No business logic,
no data transformation, no direct database/adapter access — if this blueprint
were removed, ingestion/storage/alerting/notification would keep working
unaffected (that's the point of P7 — the API is the real boundary, this is one
skin over it).
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, send_from_directory
from flask.typing import ResponseReturnValue

STATIC_DIR = Path(__file__).parent / "static"

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index() -> ResponseReturnValue:
    return send_from_directory(STATIC_DIR, "index.html")
