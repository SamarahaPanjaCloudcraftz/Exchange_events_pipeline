"""CLI entry point (design doc §5.3, §13 "Entry point").

Four commands, all built on the same two calls every other consumer uses —
``config.load_config()`` and ``wiring.build_application()`` — so the CLI has no
logic of its own beyond argument parsing and result formatting:

    init-db   create/verify the schema for the configured backend
    ingest    run the ingestion engine (single source or all adapters)
    alert     evaluate alert rules and dispatch newly-fired alerts
    serve     mount the API + dashboard on one Flask app and run it

Scheduling is deliberately **not** built in (§5.3: "the ingestion engine itself
is not a scheduler — it's a callable"). A deployment's cron/systemd-timer calls
``exchange-events ingest`` / ``exchange-events alert`` on whatever cadence it
needs; see README.md for example crontab lines.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections.abc import Callable, Sequence

from .config.loader import load_config
from .domain.errors import ExchangeEventsError
from .domain.query import DateRange
from .wiring import Application, build_application


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exchange-events", description=__doc__)
    parser.add_argument(
        "--config", default=None, help="path to a TOML config file (default: bundled defaults)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create/verify the database schema")

    p_ingest = sub.add_parser("ingest", help="run the ingestion engine")
    p_ingest.add_argument("--source", default=None, help="ingest a single named source only")
    p_ingest.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD")
    p_ingest.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD")
    p_ingest.add_argument("--incremental", action="store_true", default=False)

    p_alert = sub.add_parser("alert", help="evaluate alert rules and dispatch new alerts")
    p_alert.add_argument(
        "--no-dispatch", action="store_true", default=False,
        help="evaluate only; skip notification delivery",
    )

    p_serve = sub.add_parser("serve", help="run the API + dashboard HTTP server")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--debug", action="store_true", default=False)

    return parser


def _load_app(config_path: str | None) -> Application:
    config = load_config(config_path)
    return build_application(config)


# --- init-db ---------------------------------------------------------------------
def cmd_init_db(args: argparse.Namespace) -> int:
    app = _load_app(args.config)
    print(f"Database ready: backend={app.config.database.backend!r}")
    if app.config.database.backend == "sqlite":
        print(f"  path: {app.config.database.sqlite_path}")
    else:
        print("  dsn: (from EXCHANGE_EVENTS_PG_DSN)")
    return 0


# --- ingest ------------------------------------------------------------------------
def cmd_ingest(args: argparse.Namespace) -> int:
    app = _load_app(args.config)
    today = app.clock.today_utc()
    date_from = (
        datetime.date.fromisoformat(args.date_from) if args.date_from else today
    )
    date_to = (
        datetime.date.fromisoformat(args.date_to)
        if args.date_to
        else today + datetime.timedelta(days=app.config.ingestion.default_range_days)
    )
    date_range = DateRange(date_from, date_to)

    try:
        if args.source:
            report = app.ingestion_engine.run_single_source(
                args.source, date_range, incremental=args.incremental
            )
        else:
            report = app.ingestion_engine.run_full_ingest(
                date_range, incremental=args.incremental
            )
    except ValueError as exc:
        # e.g. an unknown --source name (a likely typo, not a code bug).
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for result in report.results:
        status = "OK" if result.succeeded else f"FAILED: {result.error}"
        print(
            f"[{result.source_name}] fetched={result.fetched} normalized={result.normalized} "
            f"errors={result.normalization_errors} upserted={result.upserted_total} "
            f"({status})"
        )
    print(f"Total upserted: {report.total_upserted}")
    return 1 if report.any_source_failed else 0


# --- alert ---------------------------------------------------------------------------
def cmd_alert(args: argparse.Namespace) -> int:
    app = _load_app(args.config)
    alerts = app.alert_engine.evaluate()
    print(f"{len(alerts)} new alert(s) fired.")
    for alert in alerts:
        print(f"  [{alert.severity}] {alert.title}")

    if alerts and not args.no_dispatch:
        results = app.dispatcher.dispatch(alerts)
        succeeded = sum(1 for r in results if r.succeeded)
        print(f"Dispatched: {succeeded}/{len(results)} deliveries succeeded.")
    return 0


# --- serve -----------------------------------------------------------------------------
def cmd_serve(
    args: argparse.Namespace,
    *,
    run_server: Callable[..., None] | None = None,
) -> int:
    """Build the Flask app (API + dashboard) and run it.

    ``run_server`` is an injectable seam over ``Flask.run`` purely for
    testability (P3) — tests pass a no-op so `serve` never actually blocks.
    """
    from .api.app import create_app
    from .dashboard.server import bp as dashboard_bp

    app = _load_app(args.config)
    flask_app = create_app(
        repository=app.repository,
        alert_log=app.alert_log,
        ingestion_engine=app.ingestion_engine,
        clock=app.clock,
        iv_provider=app.iv_provider,
        default_range_days=app.config.ingestion.default_range_days,
    )
    flask_app.register_blueprint(dashboard_bp)

    host = args.host or app.config.api.host
    port = args.port or app.config.api.port
    debug = args.debug or app.config.api.debug

    runner = run_server or flask_app.run
    runner(host=host, port=port, debug=debug)
    return 0


_COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "init-db": cmd_init_db,
    "ingest": cmd_ingest,
    "alert": cmd_alert,
    "serve": cmd_serve,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except ExchangeEventsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
