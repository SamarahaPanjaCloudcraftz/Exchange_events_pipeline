# Deployment Checklist

Practical checklist for getting this pipeline hosted remotely so the dashboard is
reachable outside a local machine. Written with **Render** as the likely first
target, but most items apply to any platform. Nothing here has been done yet —
this is the to-do list, not a record of work completed.

---

## 1. Repo prep (do first, applies to any platform)

- [ ] `git add` + first commit — nothing is committed yet, and Render (like most
      PaaS) deploys from a git repo/branch.
- [ ] Double-check `.gitignore` excludes `*.db`, `.env`, `__pycache__/` before
      that first commit (already set up correctly — just confirm nothing slipped
      through, e.g. a local `exchange_events.db` sitting at repo root).
- [ ] Add a production WSGI server dependency — none is currently installed.
      `gunicorn` is the standard choice (`pip install gunicorn`, add to
      `pyproject.toml` dependencies). The `serve` CLI command currently calls
      Flask's own dev server directly (`main.py::cmd_serve` →
      `flask_app.run(...)`), which is fine for local demos but explicitly not
      meant for production (Flask prints its own warning about this).
- [ ] Add a small `wsgi.py` (or similar) at the repo root that builds the same
      `Flask` app `cmd_serve` builds, so gunicorn has something to import:
      ```python
      from exchange_events.config.loader import load_config
      from exchange_events.wiring import build_application
      from exchange_events.api.app import create_app
      from exchange_events.dashboard.server import bp as dashboard_bp

      app_state = build_application(load_config())
      app = create_app(
          repository=app_state.repository,
          alert_log=app_state.alert_log,
          ingestion_engine=app_state.ingestion_engine,
          clock=app_state.clock,
          iv_provider=app_state.iv_provider,
          default_range_days=app_state.config.ingestion.default_range_days,
      )
      app.register_blueprint(dashboard_bp)
      ```
      This mirrors `main.py::cmd_serve` exactly — no new logic, just exposing the
      same `app` object at module level the way gunicorn expects.

## 2. Storage decision

- [ ] **Pick one:** SQLite-on-a-persistent-disk (simplest, fine for a demo/low
      traffic) **or** Render's managed Postgres (recommended if this needs to
      survive redeploys/restarts reliably — the repository layer already fully
      supports both, this is a config choice, not a code change).
- [ ] If SQLite: make sure `database.sqlite_path` in the config points at a path
      on Render's **persistent disk** (a plain container filesystem gets wiped
      on every redeploy — the default relative `exchange_events.db` will not
      survive that).
- [ ] If Postgres: create the Render Postgres instance, set
      `EXCHANGE_EVENTS_PG_DSN` to its connection string, set
      `database.backend = "postgres"` in the config TOML.

## 3. Render service setup

- [ ] **Web service** — build command installs the package (`pip install -e .`
      or `pip install -e ".[postgres]"` if using Postgres), start command runs
      gunicorn against the new `wsgi.py` (e.g. `gunicorn wsgi:app`).
- [ ] Set the **health check path** to `/api/v1/exchanges` — cheap, no DB
      round-trip needed, already known-good from local testing.
- [ ] **Scheduled jobs** for ingestion + alerting — the pipeline is deliberately
      not its own scheduler (README's "Scheduling" section already documents
      this). Two options, reuse the cadence already written down in the README:
      - Render **Cron Jobs** running `exchange-events ingest --incremental`
        (every 6h) and `exchange-events alert` (every 15min) directly, or
      - a scheduled job that just `curl -X POST` the already-built
        `/api/v1/ingest/trigger` endpoint instead, if running the CLI directly
        isn't convenient on the chosen job type.

## 4. Environment variables (set in Render's dashboard, never committed)

Mirror `.env.example` exactly:

- [ ] `FRED_API_KEY` — tier 1 of the economic-release waterfall, get a free key
- [ ] `BLS_API_KEY` — tier 2, optional (works unkeyed at a lower rate limit)
- [ ] `BEA_API_KEY` — tier 3
- [ ] `ISM_API_KEY` / `ISM_URL` — only if an ISM aggregator has been chosen
- [ ] `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` /
      `SMTP_FROM_ADDRESS` — only if the Email channel should be live
- [ ] `TEAMS_WEBHOOK_URL` — only if the Teams channel should be live
- [ ] `ALERT_RECIPIENT_EMAIL` / `ALERT_RECIPIENT_NAME` — overrides the placeholder
      address in `config/defaults.toml`'s `team_trading` recipient group; without
      it, CRITICAL alerts route to `placeholder@example.com` (harmless, just
      undelivered)
- [ ] `EXCHANGE_EVENTS_PG_DSN` — only if using Postgres (§2)

## 5. Domain / TLS

- [ ] Nothing to do for a first pass — Render provides a `*.onrender.com`
      subdomain with HTTPS automatically. A custom domain can be added later
      (Render handles the certificate) once there's an actual domain to point.

## 6. Post-deploy verification

- [ ] Hit the Render URL root (`/`) — dashboard loads.
- [ ] Hit `/api/v1/exchanges` — returns the exchange list (same health-check
      endpoint from §3).
- [ ] Trigger one ingest manually (`exchange-events ingest --source iana_tz
      --from ... --to ...` via Render shell, or `POST /api/v1/ingest/trigger`)
      and confirm rows land — proves the deployed app can actually write to
      whichever storage was chosen in §2.
- [ ] Confirm the scheduled ingest/alert jobs from §3 actually ran on their
      first scheduled tick (check Render's job logs).
- [ ] If Email/Teams are configured, confirm a real alert dispatches — check
      recipient inbox / Teams channel, not just the app logs.

## 7. Known caveats to check once live

- [x] ~~CME's live adapter is blocked by IP-reputation~~ — **resolved**: CME now
      uses its own free, OAuth-authenticated Reference Data API v3
      (`refdata.api.cmegroup.com`), separate infrastructure from the blocked
      public website, live-validated from this sandbox (see DECISIONS.md "CME
      Reference Data API"). Needs `CME_API_ID`/`CME_API_SECRET` in the deployed
      environment's secrets — same free CME Group Customer Center account used
      here.
- [ ] **BSE's endpoint and MarketWatch remain unresolved** (BSE needs a real
      URL captured from devtools; MarketWatch is DataDome-CAPTCHA-blocked).
      Whether Render's egress IPs fare differently for either is unknown until
      tested from the deployed instance — neither blocks current scope: BSE
      isn't required, and the economic-release waterfall (FRED/BLS/BEA/ISM)
      covers all *required* data without MarketWatch. Every adapter's failure
      is isolated per-source by the ingestion engine regardless.
- [ ] **Real Email (Gmail SMTP) + Teams (Incoming Webhook) delivery is now
      live-verified** from this sandbox (see DECISIONS.md "Proximity-based
      alert severity" + the notification-content follow-ups) — carries over
      directly to a deployed environment once the same `.env` values are set
      there; no code changes needed, just re-set the secrets.
