# Exchange Events Pipeline — Implementation Plan

> **Status:** Approved 2026-07-20. Persistent copy of the approved implementation plan,
> kept in-repo so work can resume after any session interruption.
> Source design: `../exchange_events_dashboard_design_doc.md`.

## Context

`exchange_events_dashboard_design_doc.md` (v1 Draft, 1125 lines) specifies a **production-grade, contract-first Python pipeline** that fetches market-moving events (holidays, DST changes, derivative expiries, US economic releases) from multiple exchange/data sources, normalizes them into a canonical model, stores them idempotently, and exposes them via a thin REST API + dashboard + alert/notification system.

The design is complete at the architecture level (7 guiding principles, 5 layers, 8 ABC contracts, full package layout). **No code exists yet** — this is a greenfield build. This plan turns the doc into an executable, phased, test-first implementation, and — per the user's explicit requirement — establishes a **session-continuity protocol** (living `CLAUDE.md` + append-only progress log) so work can resume cleanly if the context window is exhausted.

The goal of this pass: build the full v1 scope (§12) with **exhaustive tests at every layer**, with **CME as the first production-grade live adapter** (immediate production requirement).

---

## Locked Decisions (from user + environment probe)

| Decision | Choice | Notes |
|---|---|---|
| **Storage** | **Both SQLite + Postgres** repositories | SQLite (`sqlite3` stdlib, raw SQL) is the dev/test default and always-testable. Postgres (`psycopg` 3) built too; its integration tests are **gated** behind a `EXCHANGE_EVENTS_PG_DSN` env var (no local Postgres server / no Docker detected). Shared SQL-dialect layer. |
| **Data-source realism** | Mixed, priority-ordered | **CME = live, production-grade (highest priority)**, then **NSE live**, **BSE live**. **KRX deferred** (build structural stub + normalizer, no live fetch). **FRED live** (public API, needs key). **IANA live** (stdlib `zoneinfo`). **Econ-calendar source = MarketWatch** (`https://www.marketwatch.com/economy-politics/calendar`, user-chosen — resolves §13) for upcoming releases; **FRED backfills actuals**. All adapters sit behind the `HttpClient` ABC so unit tests run offline against fixtures; live sources add `@pytest.mark.contract` tests. |
| **API framework** | **Flask 3.1** (installed) | Thin read-mostly boundary; pydantic serializers for typed responses. |
| **Notification channels** | **Email (SMTP) + Microsoft Teams (webhook)** | Plus an in-memory/console `DashboardChannel` for local dev + tests. (Not Slack.) |
| **Config format** | **TOML** (`tomllib` stdlib) + env for secrets | Avoids a `pyyaml` dependency; `pydantic-settings` loads/validates. |
| **Package layout** | `src/` layout | `src/exchange_events/...` + top-level `tests/`. Cleaner import isolation than the doc's flat layout (documented deviation). |

**Environment probe findings (2026-07-20):** egress works. `cmegroup.com` and `nseindia.com` return **HTTP 403 to naive requests** (anti-bot WAF) — adapters need browser-realistic headers/session and likely CME's JSON `/CmeWS/mvc/` service endpoints. `marketwatch.com/economy-politics/calendar` returns **HTTP 401** (Dow Jones subscription/session or bot protection) — the econ-calendar adapter needs session/cookie handling; **FRED remains the reliable actuals source**. `api.stlouisfed.org` reachable (301→HTTPS), needs `FRED_API_KEY`.

**Pre-installed:** Python 3.13.11, Flask 3.1, pydantic 2.12 + pydantic-settings, pytest 9.0, requests 2.32, lxml 6.0, stdlib `sqlite3`/`tomllib`/`zoneinfo`.
**To install (network permitting; degrade gracefully if not):** `psycopg[binary]` (Postgres), `pytest-cov` (coverage), `ruff` + `mypy` (lint/type — production polish, optional). The doc's own `Clock`/`HttpClient` seams remove any need for `freezegun`/`responses`.

---

## Session-Continuity Protocol (maintained every phase)

Three living documents, updated at the **end of every phase** (this is a first-class deliverable, not an afterthought):

1. **`CLAUDE.md`** (project root) — the living project guide loaded each session. Sections: project overview, architecture map, **current status (phase checklist with ✅/🚧/⬜)**, "resume here" pointer, how to install/run/test, conventions, key decisions, known issues. **Always reflects the true current state.**
2. **`docs/PROGRESS_LOG.md`** — append-only chronological journal. Each entry: date, phase, what was built, files touched, test results (pass counts), decisions made, next step.
3. **`docs/DECISIONS.md`** — the locked decisions above + resolutions to the doc's §13 open questions + any new decisions, with rationale.

Every phase ends with: **run the phase's tests → append to PROGRESS_LOG → update CLAUDE.md status checklist → (if a decision was made) update DECISIONS.md.**

---

## Architecture (from design doc, unchanged)

Dependencies point inward. Only `wiring.py` (composition root) touches concrete classes; every other module imports only from `contracts/` + `domain/`. Build order follows the dependency graph inward→outward.

```
Source Adapters → Ingestion Engine → Repository → API/Dashboard
       ↓ Normalizers        ↓                ↓ Alert Engine → Notification Channels
```

---

## Phased Implementation (test-first at every step)

### Phase 0 — Scaffolding & continuity docs
- `git init`; `pyproject.toml` (package `exchange_events`, src layout, pytest config with markers: `unit`, `integration`, `contract`, `e2e`); `.gitignore`; `.env.example`.
- Directory skeleton per §11 (adapted to `src/`).
- **Create `CLAUDE.md`, `docs/PROGRESS_LOG.md`, `docs/DECISIONS.md`.**
- Install deps (attempt `psycopg`, `pytest-cov`, `ruff`, `mypy`; record what succeeded).
- **Verify:** `pytest` collects 0 tests cleanly; package imports.

### Phase 1 — Domain model (§3)
- `domain/enums.py` (EventType, SessionType, AlertSeverity), `domain/events.py` (Event + Holiday/DSTChange/Expiry/EconomicRelease), `domain/alerts.py` (Alert, AlertContext), `domain/query.py` (EventQuery, DateRange, FetchParams), `domain/ids.py` (deterministic `event_id`/`alert_id` — §3.4), `domain/errors.py` (typed exception hierarchy).
- **Tests (unit, exhaustive):** `event_id` determinism + collision behavior across all 4 categories & discriminators; frozen/immutability; `surprise = actual − forecast` computation incl. `None` cases; enum value contracts; EventQuery defaults.

### Phase 2 — Contracts (§4)
- All ABCs: `source_adapter`, `normalizer`, `repository`, `alert_rule`, `notification_channel`, `iv_provider`, `alert_log`, `clock`, plus infra ABCs `http_client`, `logger`.
- Contract value types: UpsertResult, NormalizationResult/Error, DeliveryResult, Recipient, IVSnapshot, RetryPolicy, IngestionReport, Response (HttpClient).
- **Tests (unit):** ABCs cannot be instantiated; required abstract methods enforced; value-type invariants.

### Phase 3 — Test fakes + infra (§9.2)
- `SystemClock` + `FakeClock`; `RealHttpClient` (wraps `requests`, browser headers, retry/backoff) + `FakeHttpClient` (canned fixtures); `NullLogger` + `StdLogger`; `FakeEventRepository`, `FakeAlertLog`, `FakeChannel`.
- **Tests:** the fakes themselves (they're test-critical): FakeClock time control, FakeHttpClient routing/404, FakeEventRepository upsert/query parity with the real one's contract.

### Phase 4 — Storage / Repository (§4.3) — **SQLite + Postgres**
- `storage/schema.sql` (events table keyed by `event_id`, category columns via typed JSON or per-type tables — decide: single-table + `metadata`/typed-JSON for simplicity & query flexibility), indexes on (event_type, exchange, date).
- `storage/sqlite_repository.py` (raw SQL, `INSERT ... ON CONFLICT(event_id) DO UPDATE` for idempotent upsert — P6), `storage/postgres_repository.py` (psycopg 3, same logic, dialect diffs isolated), `storage/migrations/`, `alerting/log.py` AlertLog impls (SQLite+Postgres).
- **Tests (integration, in-memory SQLite always; Postgres gated):** upsert idempotency (run twice → inserted then unchanged/updated, no dupes); every `EventQuery` filter (types, exchanges, date range, release_codes, limit/offset, include_metadata); `get_by_id`; `get_latest_ingest_time`; ordering (date asc); round-trip fidelity of all 4 event subclasses; concurrent upsert safety.

### Phase 5 — Normalizers (§5.2) — one per adapter
- Shared parsing utils (UTC-canonical date/time parsing — P5). Concrete: `cme_`, `nse_`, `bse_`, `krx_` (structural), `econ_`, `fred_`, `tz_` normalizers. Partial-failure contract: return `NormalizationResult(events, errors)`, never throw on one bad record (§5.2).
- **Tests (fixture-based, §9.4):** `raw.json → expected canonical` golden files per normalizer; malformed-record skip + error capture; timezone→UTC correctness; discriminator/event_id wiring.

### Phase 6 — Source Adapters (§5.1) — **CME first & hardest**
- **6a — CME (production milestone):** spike the reachable endpoint (JSON `/CmeWS/mvc/` product-calendar/holiday services vs. downloadable calendar) with browser-realistic headers behind `RealHttpClient`; build robust fetch + parse + retry/rate-limit handling. **Milestone: a real `run_single_source("cme_calendar")` lands CME holidays/expiries in SQLite end-to-end.**
- **6b — NSE, 6c — BSE:** live adapters (holiday/expiry circulars/calendar), same anti-bot header handling.
- **6d — KRX:** structural stub (raises `SourceUnavailableError`/returns empty; wired but not live — deferred per decision).
- **6e — FRED:** live API (key via env), actuals backfill. **6f — IANA:** `zoneinfo`-driven DST transitions (stdlib, fully offline). **6g — EconCalendar (MarketWatch):** scrape `marketwatch.com/economy-politics/calendar` (lxml) for upcoming releases, config-driven release codes (§5.1 note); handle the 401 via session/cookie + browser headers in `RealHttpClient`; correctness anchored to captured fixtures; FRED backfills actuals.
- **Tests:** unit for every adapter via `FakeHttpClient` + captured fixtures (always run); `@pytest.mark.contract` live tests for CME/NSE/BSE/FRED (network-gated, run on schedule, skipped in normal CI). Capture real CME/NSE/BSE responses as fixtures during the spike.

### Phase 7 — Ingestion Engine (§5.3)
- `ingestion/normalizer_registry.py`, `ingestion/retry.py` (RetryPolicy + backoff), `ingestion/engine.py`: `run_full_ingest` / `run_single_source`, per-adapter error isolation, incremental windows via `get_latest_ingest_time`, `IngestionReport` (fetched/normalized/upserted/errors/duration per adapter — §7).
- **Tests (unit, fakes):** one failing adapter doesn't block others; retry/backoff honored for retryable exceptions only; idempotent re-run (P6); partial-normalization pass-through; report accuracy.

### Phase 8 — Alert Engine + Rules (§5.4)
- `alerting/engine.py` (query window, build AlertContext, per-rule exception isolation, dedup via AlertLog), rules: `UpcomingHighPriorityReleaseRule`, `ExpiryDayRule` (v1 required §12), plus `RevisedExpiryRule` + `EconomicSurpriseRule` (pure, low-cost — include now), `IVThresholdRule` (gated on optional `iv_provider`).
- **Tests (unit, FakeClock — mirrors doc §9.2 example):** each rule's fire/no-fire boundaries; severity assignment; dedup across runs; per-rule failure isolation; IV rule skips gracefully when provider absent.

### Phase 9 — Notification (§5.5) — **Email + Teams**
- `alerting/dispatcher.py` (RoutingConfig match by severity/event_type → channels+recipients, per-channel failure isolation), `notifications/email_channel.py` (SMTP via injected transport for testability), `notifications/teams_channel.py` (Incoming Webhook MessageCard/Adaptive Card via HttpClient), `notifications/dashboard_channel.py` (in-memory).
- **Tests (unit):** routing table resolution; channel-failure isolation; DeliveryResult per recipient; Email via fake SMTP transport; Teams via FakeHttpClient (payload shape asserted).

### Phase 10 — Config + Wiring (§8)
- `config/schema.py` (AppConfig pydantic), `config/loader.py` (TOML + env secrets), `config/defaults.toml`, `wiring.py` `build_application()` (the one composition root — §8.2).
- **Tests:** config load/validation (missing/invalid → clear errors); `build_application(test_config)` smoke test yields a working `Application` over SQLite + fake channels.

### Phase 11 — API layer (§5.6) — Flask
- `api/app.py`, `api/routes/` (events, events/{id}, upcoming, alerts, iv, calendar/{y}/{m}, exchanges, ingest/trigger), `api/serializers.py` (pydantic), consistent error envelopes.
- **Tests (integration, Flask test client):** each endpoint against a seeded SQLite repo; query-param → EventQuery mapping; 404s; calendar aggregation; serialization of all event subclasses.

### Phase 12 — Dashboard (§5.7) — minimal static (no build step)
- Thin static HTML/JS (vanilla) served by Flask: calendar view, upcoming events, economic-releases table, alert feed. Consumes API only; zero business logic (§5.7). (React deferred — node present but a build toolchain is unnecessary for the thinnest layer.)
- **Tests:** smoke test that pages render and issue API calls.

### Phase 13 — Entry point + CLI
- `main.py` CLI: `init-db`, `ingest [--source] [--from --to]`, `alert`, `serve`. Scheduling stays external (cron examples in README — §5.3 note; no in-process scheduler).
- **Tests:** CLI arg parsing + command smoke tests.

### Phase 14 — E2E, hardening, docs
- `tests/e2e/`: full pipeline over fixtures — ingest → SQLite → API query → alert eval → dispatch to fake channels — asserted end-to-end.
- Coverage report (target ≥90% on domain/normalizers/engine/rules); `ruff`/`mypy` clean if installed; `README.md`; **final `CLAUDE.md` + PROGRESS_LOG update**.

---

## Exhaustive Testing Strategy (§9)

- **Markers:** `unit` (no infra, majority — run every commit), `integration` (SQLite in-memory; Postgres gated on `EXCHANGE_EVENTS_PG_DSN`), `contract` (live external sources, network-gated, scheduled), `e2e` (full pipeline over fixtures).
- **Every ABC gets a fake** (Phase 3); every normalizer gets golden `raw→expected` fixtures (Phase 5); every adapter gets fixture unit tests + optional live contract tests (Phase 6).
- **Determinism:** `FakeClock` for all time-dependent logic (alerts, ingestion windows); no wall-clock in tests.
- **Idempotency (P6)** and **error-isolation (§7)** get dedicated test cases at repository, ingestion, alert, and dispatch layers.
- **Fixtures** captured from real CME/NSE/BSE/FRED responses during Phase 6 spike, committed under `tests/fixtures/<source>/`.

---

## Dependencies to add (best-effort, graceful degradation)

`psycopg[binary]` (Postgres repo), `pytest-cov` (coverage), `ruff` + `mypy` (lint/type). If any install fails (no network), the affected work degrades: Postgres tests skip, lint is optional — SQLite path and all unit/integration tests remain fully functional.

---

## Verification (end-to-end)

1. `pytest -m "unit or integration"` — full offline suite green.
2. `python -m exchange_events.main init-db && python -m exchange_events.main ingest --source cme_calendar --from 2026-01-01 --to 2026-12-31` — **live CME ingest lands rows in SQLite** (the production milestone).
3. `python -m exchange_events.main serve` → hit `GET /api/v1/events?event_types=holiday&exchanges=XCME` and `GET /api/v1/calendar/2026/07` → real CME data returned; open the static dashboard.
4. `python -m exchange_events.main alert` → upcoming-expiry/release alerts dispatched to fake/console channel; verify Email+Teams payloads via their unit tests.
5. `pytest -m contract` (network) — CME/NSE/BSE/FRED adapters still parse the live sources.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **CME/NSE anti-bot 403** (top risk) | Browser-realistic headers + session in `RealHttpClient`; prefer CME JSON `/CmeWS/` services; capture fixtures so correctness never depends on live availability; live path isolated to contract tests. |
| **MarketWatch 401** (subscription/session) | Session + cookie + browser headers in `RealHttpClient`; fixture-anchored correctness; **FRED as reliable actuals fallback**; live path gated behind contract tests. If session proves infeasible without a subscription, econ-calendar upcoming-release data degrades to FRED release-date metadata (adapter swap is additive — P4). |
| No local Postgres | SQLite is the default; Postgres tests gated + skipped cleanly. |
| Session/context exhaustion | Continuity protocol (CLAUDE.md + PROGRESS_LOG + DECISIONS) updated every phase → clean resume. |
| Network unavailable for installs | Core stack already present; optional deps degrade gracefully. |

## Out of scope / deferred (per §12)
KRX live fetch, IV threshold integration (built as optional/gated), per-user subscription routing, React dashboard, historical IV overlay. All are additive extensions (P4) — no rework required.
