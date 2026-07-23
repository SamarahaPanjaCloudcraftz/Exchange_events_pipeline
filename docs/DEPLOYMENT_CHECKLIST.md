# Deployment Checklist

Practical checklist for getting this pipeline hosted remotely so the dashboard is
reachable outside a local machine. Covers both a **self-managed server**
(systemd, likely alongside another existing system) and **Render** (PaaS) — the
former is now the primary path (§3a), the latter kept as an alternative (§3b).

---

## 1. Repo prep

- [x] First git commit made (2026-07-23). `.gitignore` confirmed clean —
      nothing sensitive (`.db`, `.env`, `__pycache__/`) was ever staged.
- [x] `gunicorn` added as an optional dependency group (`pip install -e ".[deploy]"`,
      see `pyproject.toml`'s `deploy` extra).
- [x] `wsgi.py` added at the repo root — mirrors `main.py::cmd_serve` exactly,
      exposes `app` for a WSGI server to import (`gunicorn wsgi:app`). Verified
      live under real gunicorn (2 workers) against the real database.
- [x] **Lockfile** added — `requirements.lock.txt` (via `pip-tools`, includes the
      `postgres` + `deploy` extras). `pyproject.toml`'s own deps stay as loose
      floors for anyone installing this as a library; the lockfile is what
      `scripts/redeploy.sh` and any server install actually use, for
      reproducible installs. Regenerate after any dependency change:
      `pip-compile --extra=postgres --extra=deploy --output-file=requirements.lock.txt pyproject.toml`.
      Verified: a completely fresh venv installed from the lockfile alone still
      passes all 453 tests.
- [ ] **Push to GitHub.** Needs a repo created on your account/org first (no
      `gh` CLI available in this environment to do it programmatically) — once
      it exists, `git remote add origin <url> && git push -u origin main`.

## 2. Storage decision — still open

- [ ] **Pick one:** SQLite on a persistent path **or** Postgres (Render's managed
      instance, or one already running on the self-managed server) — the
      repository layer already fully supports both, this is a config choice,
      not a code change.
- [ ] If SQLite: make sure `database.sqlite_path` points at a path that survives
      redeploys — on a self-managed server that's any normal persistent disk
      path (e.g. `/opt/exchange-events/exchange_events.db`, outside the git
      checkout so `git checkout` in `redeploy.sh` never touches it); on Render
      specifically, a plain container filesystem gets wiped on every redeploy,
      so it must be on Render's persistent disk add-on.
- [ ] If Postgres: set `EXCHANGE_EVENTS_PG_DSN` to its connection string, set
      `database.backend = "postgres"` in the config TOML. Worth checking
      whether the other existing system on the host already runs a Postgres
      instance this could share a *database* on (never a schema/table) rather
      than standing up a second server.

## 3a. Self-managed server (systemd) — primary path

Everything below is now built and ready under `deploy/systemd/` and `scripts/`;
what's left is copying it onto the actual server and filling in real paths.

- [x] `deploy/systemd/exchange-events-web.service` — gunicorn running `wsgi:app`,
      its own dedicated `exchange-events` user, own working directory
      (`/opt/exchange-events` — adjust if different), own log files. `Restart=
      on-failure` so a crash recovers on its own without affecting anything
      else on the host.
- [x] `deploy/systemd/exchange-events-ingest.{service,timer}` +
      `exchange-events-alert.{service,timer}` — one-shot units on systemd
      timers, same 6h/15min cadence already documented in README.md's
      "Scheduling" section (a plain crontab works identically if you prefer
      that over timers — both are just "run the CLI on a schedule").
- [x] `scripts/redeploy.sh` — the gated redeploy flow: fetch → checkout →
      install from the lockfile → **run the full test suite + ruff + mypy,
      abort before touching the live service if anything fails** → `init-db`
      (idempotent) → restart `exchange-events-web` → curl the health endpoint
      → auto-rollback to the previous commit if the health check fails.
      Never leaves the on-disk working tree pointed at untested code, since
      the ingest/alert cron jobs run whatever is on disk regardless of whether
      the web service was restarted.
- [x] `scripts/rollback.sh` — checks out a specific SHA (or `.last_good_deploy`
      by default, written by `redeploy.sh` on success), reinstalls, restarts,
      re-verifies. Does not re-run tests (that SHA already passed them).
- [ ] Copy the systemd unit files to `/etc/systemd/system/` on the real
      server, adjust `WorkingDirectory`/`User`/paths to match, `daemon-reload`,
      `enable --now` each unit.
- [ ] Create the `exchange-events` system user + `/opt/exchange-events`
      checkout + venv on the real server (first-time setup only).
- [ ] Decide where CI fits: recommended is GitHub Actions running
      `pytest`/`ruff`/`mypy` on every push to `main` as the **primary** gate
      (bad code never reaches the branch the server pulls), with
      `redeploy.sh`'s own test run as a secondary safety net right before
      restart. Not yet set up — needs the GitHub repo to exist first (§1).

## 3b. Render (PaaS) — alternative, if not self-hosting

- [ ] **Web service** — build command installs from the lockfile
      (`pip install -r requirements.lock.txt && pip install --no-deps -e .`),
      start command runs gunicorn against `wsgi.py` (`gunicorn wsgi:app`).
- [ ] Set the **health check path** to `/api/v1/exchanges` — cheap, no DB
      round-trip needed, already known-good from local testing.
- [ ] **Scheduled jobs** for ingestion + alerting — the pipeline is deliberately
      not its own scheduler. Two options, reuse the cadence already written
      down in the README:
      - Render **Cron Jobs** running `exchange-events ingest --incremental`
        (every 6h) and `exchange-events alert` (every 15min) directly, or
      - a scheduled job that just `curl -X POST` the already-built
        `/api/v1/ingest/trigger` endpoint instead, if running the CLI directly
        isn't convenient on the chosen job type.
- [ ] Render's own git-triggered deploy replaces `scripts/redeploy.sh`'s
      pull/restart mechanics, but you'd still want the test suite gating the
      deploy — either via a Render "pre-deploy command" or, better, CI on the
      GitHub side before Render ever sees the push.

## 4. Environment variables (server's `.env` / Render's dashboard — never committed)

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

- [ ] **Self-managed:** if this needs to be reachable outside the host, put it
      behind whatever reverse proxy (nginx/Caddy) is already fronting the other
      system on the same box — a distinct path prefix or subdomain, TLS
      terminated there, never a second TLS setup for this app alone.
- [ ] **Render:** nothing to do for a first pass — Render provides a
      `*.onrender.com` subdomain with HTTPS automatically.

## 6. Post-deploy verification

- [ ] Hit the deployed URL root (`/`) — dashboard loads.
- [ ] Hit `/api/v1/exchanges` — returns the exchange list (same health-check
      endpoint from §3a/3b).
- [ ] Trigger one ingest manually (`exchange-events ingest --source iana_tz
      --from ... --to ...`, or `POST /api/v1/ingest/trigger`) and confirm rows
      land — proves the deployed app can actually write to whichever storage
      was chosen in §2.
- [ ] Confirm the scheduled ingest/alert jobs actually ran on their first
      scheduled tick (`systemctl status exchange-events-ingest.timer` /
      `journalctl -u exchange-events-ingest` on self-managed, or Render's job
      logs).
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
