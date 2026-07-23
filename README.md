# Exchange Events Pipeline

A production-grade pipeline that fetches market-moving events — exchange **holidays**,
**DST changes**, derivative **expiries**, and US **economic releases** — from multiple
sources, normalizes them into a canonical model, stores them idempotently, and exposes
them via a REST API, a lightweight dashboard, and an alert/notification system.

Built contract-first per [`exchange_events_dashboard_design_doc.md`](exchange_events_dashboard_design_doc.md).
For the full build history, decisions, and current status, see:

- [CLAUDE.md](CLAUDE.md) — living project guide, status checklist, "resume here" pointer
- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) — the phased plan this was built from
- [docs/DECISIONS.md](docs/DECISIONS.md) — every non-obvious decision and its rationale
- [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md) — chronological build journal, phase by phase
- [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) — deploying this onto a server
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — accessing the live dashboard day to day

## Status

All 15 planned phases are complete. **453 tests pass** (unit + integration + e2e), 19
skip cleanly without a Postgres server, 6 live-network contract tests are opt-in.
`ruff` and `mypy --strict` are clean across the whole `src/` tree.

## Install

```bash
python -m venv .venv && source .venv/bin/activate   # or use your existing environment
pip install -e ".[dev,postgres]"                     # dev tools + optional Postgres support
cp .env.example .env                                  # fill in secrets (see below) — never committed
```

Core dependencies (Flask, pydantic, pydantic-settings, requests, lxml) install with the
base package; `psycopg` (Postgres) and `pytest-cov`/`ruff`/`mypy`/`types-requests` are
optional extras.

## Configure

Structural config lives in TOML (`src/exchange_events/config/defaults.toml` ships as the
zero-config default — copy and edit it, or pass `--config path/to/yours.toml`). **Secrets
never go in TOML** — they're read from the environment (or a local `.env`), matching
`.env.example` exactly:

| Variable | Used by |
|---|---|
| `FRED_API_KEY` | FRED adapter — tier 1 of the economic-release waterfall (6/7 releases) |
| `BLS_API_KEY` | BLS adapter — tier 2, optional (works unkeyed at a lower rate limit) |
| `BEA_API_KEY` | BEA adapter — tier 3 (PCE official backstop) |
| `ISM_API_KEY` / `ISM_URL` | ISM adapter — best-effort only, no default (see `adapters/ism.py`) |
| `SMTP_HOST`/`PORT`/`USERNAME`/`PASSWORD`/`FROM_ADDRESS` | Email notification channel |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams notification channel |
| `EXCHANGE_EVENTS_PG_DSN` | Postgres backend (omit to use the SQLite default) |

With no `.env` at all, the app still runs correctly — it falls back to SQLite storage
and the in-memory `dashboard` notification channel only (Email/Teams stay unconfigured
with a clear warning, not a crash).

## Run

```bash
exchange-events init-db                                   # create/verify the schema
exchange-events ingest --source iana_tz --from 2026-01-01 --to 2026-12-31   # one source
exchange-events ingest --from 2026-01-01 --to 2026-12-31   # every adapter (live network)
exchange-events alert                                       # evaluate rules + dispatch
exchange-events serve --host 0.0.0.0 --port 8080             # API + dashboard
```

Every command accepts `--config path/to.toml` (defaults to the bundled `defaults.toml`).
Once `serve` is running, open `http://localhost:8080/` for the dashboard, or query the
API directly, e.g. `curl http://localhost:8080/api/v1/events/upcoming`.

### Scheduling (the pipeline is not its own scheduler)

Per the design doc, the ingestion/alert engines are plain callables — *something else*
schedules them. A typical crontab:

```cron
# Ingest every 6 hours, alert every 15 minutes, both logged.
0 */6 * * *  cd /opt/exchange-events && exchange-events ingest --incremental >> /var/log/ee-ingest.log 2>&1
*/15 * * * * cd /opt/exchange-events && exchange-events alert                >> /var/log/ee-alert.log  2>&1
```

Run `serve` under your process manager of choice (systemd, supervisor, a container
entrypoint) — it's a long-running Flask process, not a one-shot command.

## Test

```bash
pytest                       # unit + integration + e2e (fast, fully offline) — the default
pytest -m unit                # unit only
pytest -m integration         # + SQLite integration (Postgres too, if EXCHANGE_EVENTS_PG_DSN is set)
pytest -m e2e                  # the full ingest→store→API→alert→dispatch pipeline test
pytest -m contract             # live external sources — slow, network-dependent, run on a schedule
pytest --cov=exchange_events --cov-report=term-missing   # coverage report
ruff check src tests          # lint
mypy src/exchange_events        # strict type-check
```

## Live source status (read before relying on any of these in production)

Verified in this environment (full detail: [docs/DECISIONS.md](docs/DECISIONS.md)
§ "Source adapter findings" and § "Economic-release waterfall"):

| Source | Status | Note |
|---|---|---|
| **NSE** | ✅ Live-validated | Session-warm-up + browser headers reach the real API. |
| **CME** | ⚠️ Blocked from this sandbox | Explicit IP-reputation block (Akamai-style). Validate from the real deployment host — the endpoint shape itself is believed correct. |
| **BSE** | ⚠️ Endpoint needs discovery | Guessed URL returns a soft-404; capture the real API path from browser devtools before relying on it. |
| **IANA** (DST) | ✅ Fully offline | Stdlib `zoneinfo`, deterministic, no network. |
| **KRX** | Deliberately deferred | Structural stub only — fully wired, not fetching live data yet (future work). |

**Economic releases** (NFP, CPI, PPI, PCE, ISM PMI, JOLTS, FOMC) use a 4-source
reliability waterfall instead of scraping a calendar site — the requirement only calls
for *released* data, and government/Fed APIs publish exactly that, with no anti-bot
wall at all:

| Tier | Source | Covers | Status |
|---|---|---|---|
| 1 | **FRED** | NFP, CPI, PPI, PCE, JOLTS, FOMC (6/7) | Needs `FRED_API_KEY` — plain keyed REST API, expected to work everywhere. |
| 2 | **BLS** | NFP, CPI, PPI, JOLTS (official backstop) | Works unkeyed at a lower rate limit; `BLS_API_KEY` optional. |
| 3 | **BEA** | PCE (official backstop) | Needs `BEA_API_KEY` — **not live-tested here**; table/line mapping believed correct, confirm before go-live. |
| best-effort | **ISM** | ISM Manufacturing PMI only | No free official source exists (FRED dropped it in 2016) — provider-agnostic, needs a chosen aggregator wired via `ISM_URL`/`ISM_API_KEY`. |

MarketWatch's calendar (`econ_calendar`) is left wired but not load-bearing — it's
blocked by an actual DataDome CAPTCHA (confirmed with a real headless browser, not just
a header/JS-challenge issue) and would only add forecast data, which isn't required.

Every adapter is unit-tested offline against realistic fixtures regardless of live
status; `pytest -m contract` is where the live checks above actually run.

## Package layout

```
src/exchange_events/
  domain/        canonical types (Event subclasses, Alert, EventQuery, ids, errors)
  contracts/     ABCs only (SourceAdapter, EventRepository, AlertRule, ...)
  infra/         production infra concretes (SystemClock, RealHttpClient, loggers)
  adapters/      SourceAdapter implementations — one per source
  normalizers/   EventNormalizer implementations — one per adapter
  storage/       EventRepository/AlertLog impls (SQLite + Postgres)
  ingestion/     IngestionEngine, NormalizerRegistry, RetryPolicy
  alerting/      AlertEngine, rules/, NotificationDispatcher, RoutingConfig
  notifications/ NotificationChannel impls (Email, Teams, Dashboard)
  api/           Flask app + routes + serializers
  dashboard/     static HTML/JS consumer of the API (no build step)
  config/        AppConfig schema + TOML/env loader + defaults.toml
  wiring.py      composition root — build_application()
  main.py        CLI entry point
tests/{unit,integration,contract,e2e,fakes,fixtures}
```

**Import rule:** every package above imports only `contracts/` and `domain/`. Only
`wiring.py` knows about concrete classes across packages — swapping SQLite for
Postgres, or adding a new adapter/rule/channel, means editing `wiring.py` plus writing
that one new class. Nothing else changes.

## Known scope boundaries (v1, per the design doc's §12/§13)

- **IV threshold integration is not built** — `IVThresholdProvider` is fully specified
  as a contract and every alert-engine/API seam that needs it degrades gracefully
  (no crash, no false alerts, a clean HTTP 501 on `/api/v1/iv/...`), but no concrete
  provider ships. Wiring one in later is additive (see `wiring._build_iv_provider`).
- **KRX** is a structural stub, not a live adapter.
- Advanced per-user subscription routing and a richer (React) dashboard are out of
  scope for this pass.
