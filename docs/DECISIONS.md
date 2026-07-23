# Decisions Log

Records every non-obvious decision and its rationale. Resolves the design doc's §13 open
questions. Append new decisions at the bottom with a date.

---

## Design-doc §13 resolutions (2026-07-20)

| §13 open question | Resolution | Rationale |
|---|---|---|
| Primary economic calendar data source | **MarketWatch** (`https://www.marketwatch.com/economy-politics/calendar`) for upcoming releases; **FRED** for actuals backfill | User choice. FRED gives a stable keyed API for actuals; MarketWatch covers the forward calendar. |
| Database (Postgres vs SQLite) | **Both** — SQLite is the v1 default, Postgres built alongside | User chose "both". SQLite = zero-infra + always testable; Postgres = prod path, gated on a DSN env var since no local server. |
| Notification channel for v1 | **Email (SMTP) + Microsoft Teams (webhook)** | User choice. Plus an in-memory/console `DashboardChannel` for dev + tests. |
| IV data source & timeline | **Deferred** — `IVThresholdProvider` remains optional/gated; no concrete impl in this pass | Design doc marks it optional (§4.6, §12 deferred). Rules that need IV skip gracefully when absent. |
| Dashboard technology | **Minimal static HTML/JS** served by Flask (no build step) | The dashboard is deliberately the thinnest layer (§5.7). React deferred; node present but a build toolchain is unwarranted. |
| Hosting/deployment model | **Out of scope for this pass** | Scheduling stays external (cron); engine is a plain callable (§5.3). |

## Additional decisions (2026-07-20)

- **Source realism, priority-ordered:** CME = live production-grade (immediate requirement) → NSE live → BSE live → KRX deferred (structural stub). FRED + IANA live. All adapters sit behind the `HttpClient` ABC; unit tests are offline against fixtures; live paths are `@pytest.mark.contract` (network-gated).
  - **Why:** User stated CME is the immediate production requirement; NSE/BSE wanted live; KRX future. Fixture-anchoring keeps the suite deterministic and CI-safe despite fragile external sources.
- **API framework = Flask 3.1.** Already installed; the API layer is intentionally thin/read-mostly; pydantic used for typed serialization.
- **Config = TOML (`tomllib`, stdlib) + env for secrets (`pydantic-settings`).**
  - **Why:** `pyyaml` is not installed; `tomllib` is stdlib in 3.11+. Avoids a dependency. The design doc allowed YAML *or* TOML.
- **Package layout = `src/` layout** (`src/exchange_events/…`, tests top-level).
  - **Why:** Prevents accidental imports of the in-tree package before install and keeps test/prod import paths identical. Documented deviation from the doc's flat layout.
- **Infra concretes live in `infra/`** (`SystemClock`, `RealHttpClient`, `StdLogger`/`NullLogger`); fakes live in `tests/fakes/`.
  - **Why:** The design doc's package layout has no home for infra concretes; `contracts/` is ABC-only.
- **Alert rules promoted from v2 → v1 in this pass:** `RevisedExpiryRule`, `EconomicSurpriseRule` built now (still keeping IV rule gated).
  - **Why:** They are pure, stateless evaluators — cheap to build and test, and additive (P4), so no rework risk.

## Contract-level decisions (2026-07-21, Phase 1–2)

- **StrEnum instead of `(str, Enum)`** for `EventType`/`SessionType`/`AlertSeverity`/`DeliveryStatus`. Cleaner `str()` semantics (`str(member) == value`) and satisfies ruff UP042. `.value` still used explicitly in id generation.
- **`domain/` never imports `contracts/`.** `AlertContext` therefore carries resolved `now_utc`/`today_utc` (read by the engine from its `Clock`) rather than a `Clock` object — a deliberate deviation from the doc's illustrative `AlertContext(clock=clock)`.
- **`event_id`/`alert_id` auto-derived** in `__post_init__` from the natural key; explicit ids still honored. Centralizes P6 so normalizers can't miscompute ids.
- **UTC enforced at the domain boundary** (P5): naive datetimes raise; aware ones normalize to UTC (`Event.timestamp_utc/ingested_at/updated_at`, `Alert.triggered_at`, `AlertContext.now_utc`).
- **`NotificationChannel.send` returns `list[DeliveryResult]`** (one per recipient), not the doc's single `DeliveryResult`, so multi-recipient partial failure is representable.
- **`EventNormalizer.normalize` returns `NormalizationResult`** (events + errors, §5.2) rather than the bare `list[Event]` shown in §4.2 — the richer §5.2 form is authoritative (partial success).
- **`AlertLog.recent(limit)`** added to the contract (needed by API `GET /alerts`, §5.6).
- **`HttpClient` + `Logger` ABCs live in `contracts/`** (all interfaces together); concretes go in `infra/`. `RetryPolicy` + `IngestionReport` are *not* contracts and will live in `ingestion/` (Phase 7).

## Storage decisions (2026-07-21, Phase 4)

- **One TEXT-column schema for both SQLite and Postgres.** Queryable/indexed columns (event_id, event_type, source, exchange, event_date, release_code, ingested_at, updated_at, content_hash) plus the full round-trippable event as JSON in `data`. Datetimes/dates are ISO strings (UTC, fixed-width) which sort correctly lexically, so range filters and `MAX()` work on TEXT. **Why:** maximizes shared code between backends and keeps v1 simple; PG-native DATE/TIMESTAMPTZ/JSONB is a future optimization, not needed for correctness.
- **Idempotent upsert is per-event inside one transaction** (SELECT content_hash → INSERT / skip / UPDATE) rather than a bulk `ON CONFLICT`, so inserted/updated/unchanged counts are exact (P6). `content_hash` excludes `ingested_at`/`updated_at`.
- **Canonical event (de)serialization lives in `domain/serialization.py`** so storage, the alert log, and the future API serializer share one round-trippable form without any concrete package importing another.
- **SQL `AlertLog` lives in `storage/` (not `alerting/`)** — deviation from doc §11 — so `alerting/` (pure engine/rules) never imports the concrete `storage/` package. `record` uses `INSERT … ON CONFLICT (alert_id) DO NOTHING` (works in both SQLite ≥3.24 and PG).
- **Postgres classes import `psycopg` lazily** (module-level `__getattr__` in `storage/__init__.py`) so importing storage never requires psycopg. PG integration tests are gated on `EXCHANGE_EVENTS_PG_DSN` and skip cleanly otherwise. **Not yet run against a live PG in this environment** — logic is shared with SQLite, which passes.

## Source adapter findings (2026-07-21, Phase 6 contract-test spike)

Live reachability probed with both plain `curl` and each adapter via `RealHttpClient` against real endpoints. Per-source outcome (also documented in each adapter's module docstring and in `tests/contract/test_live_adapters.py`):

| Source | Live result from this sandbox | Category | Action before go-live |
|---|---|---|---|
| **NSE** | ✅ **Passes.** Session-warm-up (GET homepage → cookies → GET API) + browser headers works. | — | None — validates the design. |
| **CME** | ❌ HTTP 403, explicit body: *"This IP address is blocked due to suspected web scraping activity..."* | IP-reputation block (Akamai-style), not a header/session problem. | Run from the real deployment host (likely reputable datacenter/cloud egress works where this sandbox doesn't); confirm before relying on it for the production milestone. |
| **BSE** | ❌ HTTP 200 with a soft-404 (classic-ASP 404 HTML body). | **Wrong/stale endpoint URL** — a discovery task, not a block. | Capture BSE's real API calls (browser devtools) and update `DEFAULT_HOLIDAY_URL`/`DEFAULT_EXPIRY_URL` in `adapters/bse.py`. |
| **MarketWatch** (econ_calendar) | ❌ HTTP 401, DataDome JS-challenge page (`var dd={'rt':'i','cid':...}`). | JavaScript bot-wall — cannot be solved by headers/session/cookies alone. | Needs a headless-browser fetch layer (e.g. Playwright) or a DataDome-aware unblocking proxy. Until then, **FRED is the reliable actuals source**; MarketWatch stays fixture-validated only. |
| **FRED** | Not probed live in this pass (no `FRED_API_KEY` configured); expected to pass anywhere — plain keyed REST API, no anti-bot layer. | — | Set `FRED_API_KEY` and run `pytest -m contract -k fred` to confirm. |
| **KRX** | Not probed — live fetch deliberately deferred per the storage/source-priority decision above. | — | Future work. |

**Robustness fix made during this spike:** `HttpSourceAdapter._get_json` (base class used by CME/NSE/BSE) previously let a malformed/non-JSON 200 response raise an unhandled `JSONDecodeError`; discovered via the real BSE soft-404. Fixed to wrap any JSON-parse failure in `SourceUnavailableError` with the HTTP status included. `_get`/`_get_json`/`_get_text` now also accept per-call `headers` (merged with `config.headers`) so adapters no longer need to bypass the base helpers to send bot-relevant headers (Accept/Referer) — this also fixed a latent NSE bug where `_headers()` was defined but never applied to the actual data-fetch calls (only to the session warm-up).

## Alerting decisions (2026-07-21, Phase 8)

- **`AlertContext.today_utc` is not independently settable** — only `now_utc` is a constructor argument; `today_utc` is always derived from it in `__post_init__` and exposed as a non-Optional `datetime.date` field (`field(init=False, ...)`). The design doc's illustrative snippet implied an overridable `today_utc`, but since domain can't import `Clock` (see the Phase-1/2 `AlertContext` decision) and nothing in the codebase needs to desync "today" from "now", making it derived-only removes an `Optional[date]` that would otherwise force every rule to null-check or assert. Simpler and still fully correct for timezone-boundary tests (set `now_utc` to the desired instant).
- **Dedup is engine-side, not rule-side.** Rules always construct their `Alert` (with its deterministic `alert_id`); the `AlertEngine.evaluate()` loop is the single place that calls `alert_log.has_fired()`/`record()`. This keeps every rule a pure, side-effect-free evaluator (P2) and means dedup logic exists in exactly one place.
- **IV snapshot population is engine-side and expiry-scoped**: `AlertEngine._build_context` populates `iv_snapshots` only for `ExpiryEvent`s (deduped by `(exchange, underlying)`) and only when `iv_provider` is set — `IVThresholdRule` and any future IV-aware rule never touch the provider directly, they only read `context.iv_snapshots`, so they degrade to a no-op automatically when IV isn't configured (§12 v2-deferred).

## Notification decisions (2026-07-21, Phase 9)

- **`SmtpTransport` is a channel-local ABC** (`notifications/smtp_transport.py`), not a top-level system contract in `contracts/` — only `EmailChannel` needs it, unlike `HttpClient`/`Clock`/`Logger` which are used everywhere. `SmtplibTransport` (stdlib `smtplib` + STARTTLS) is the production concrete; `FakeSmtpTransport` (records `EmailMessage`s, can simulate per-recipient failure) is the test double.
- **Email sends one message per recipient**, each wrapped in its own try/except, so one bad mailbox doesn't block delivery to the others — mirrors the per-recipient `DeliveryResult` contract exactly.
- **Teams delivers via a single Incoming Webhook POST regardless of recipient count** — a webhook has no per-recipient addressing (everyone in that Teams channel gets it). `recipients` is still accepted (for `NotificationChannel` interface uniformity) and each gets a `DeliveryResult` describing the one shared outcome. Payload is a MessageCard (`@type: MessageCard`) with severity-colored `themeColor`.
- **`DashboardChannel` never fails** (no external dependency) — it logs and keeps an in-memory `delivered` list. It's the safe default/catch-all recipient (§5.5's routing example: `severity: INFO -> channels: [dashboard]`). The durable "recent alerts" feed for the API (§5.6) is `AlertLog.recent()`, not this channel — this channel is purely a routing/delivery target.
- **Routing = first-match-wins**, mirroring the doc's YAML ordering (specific-severity-plus-event-type rules before a catch-all). `RoutingConfig.resolve_recipients` de-dupes by `Recipient.id` across overlapping named groups.
- **Dispatcher isolates channel failures** by catching `ChannelUnavailableError` per channel and synthesizing `FAILED` `DeliveryResult`s for every recipient on that channel, so a down channel never blocks alerts routed to a different one for the same alert.

## Config + wiring decisions (2026-07-21, Phase 10)

- **Config = pydantic `BaseModel` (not dataclasses)** for `AppConfig` and all sub-configs — free validation (rejects e.g. `database.backend="mongodb"`), matches the pre-installed pydantic 2.12, and is the natural fit for TOML→object mapping. `AdapterConfigModel` is a deliberate *separate* pydantic mirror of `adapters.config.AdapterConfig` (a plain dataclass) so the `adapters/` package itself never depends on pydantic — only `wiring.py`/`config/` do.
- **Secrets are a dedicated `pydantic_settings.BaseSettings` class (`Secrets`)** whose field names match `.env.example` exactly (`fred_api_key`, `smtp_host`, ..., `exchange_events_pg_dsn`), loaded independently of the TOML `AppConfig` and merged on top by `loader._merge_secrets`. TOML must never contain a secret value; env always wins if both are somehow set.
- **`load_config()` defaults to the bundled `config/defaults.toml`** (via `DEFAULTS_PATH = Path(__file__).parent / "defaults.toml"`) so the app is runnable with zero external config — a deployment only needs a `.env` for secrets, or a custom TOML path for structural overrides.
- **`build_application()` lazily imports the Postgres storage submodules directly** (`storage.postgres_repository`, `storage.alert_log`), not via `storage`'s dynamic `__getattr__` — this avoids mypy treating them as `object` (the `__getattr__` return type) while still keeping `psycopg` an optional import (it's only imported inside those classes' `__init__`, not at module load).
- **IV provider is never built in v1** (`_build_iv_provider` logs a warning if `iv.enabled=true` and returns `None` regardless) — no concrete `IVThresholdProvider` ships in this pass (§12 v2-deferred), so `IVThresholdRule` is simply never added to the rules list. Flipping this on later is additive: implement a provider, wire it in `_build_iv_provider`, done (P4).
- **Channels are wired conditionally on having real config**, not just on being named in `enabled_channels`: e.g. `"email" in enabled_channels` alone doesn't construct `EmailChannel` unless `smtp_host` *and* `from_address` are actually set (a warning is logged otherwise). This means the bundled `defaults.toml` + no `.env` yields a **working app with only the `dashboard` channel active** — verified by a real `build_application()` smoke run in this environment (all 7 adapters, all 4 v1 rules, SQLite storage, dashboard-only notification).

## API decisions (2026-07-21, Phase 11)

- **`create_app()` takes explicit contract-typed keyword arguments** (`repository`, `alert_log`, `ingestion_engine`, `clock`, `iv_provider`), not the `wiring.Application` dataclass — keeps `api/` decoupled from `wiring.py` (only `main.py`, Phase 13, will know both). Dependencies are stashed on `app.config` under `EE_*` keys and read back inside each route handler; this is the standard Flask pattern for handler-visible app-scoped state without a global.
- **`event_to_dict` adds a `surprise` field** for `EconomicReleaseEvent` on top of `domain.serialization.serialize_event`'s round-trippable form — `surprise` is a computed domain property (never stored), but API consumers (the dashboard's economic-releases table, §5.7) need it directly without recomputing client-side.
- **IV endpoint returns HTTP 501 (not 404/500) when no provider is configured** — this is a "feature not enabled," not "resource not found" or "server error"; a `IVThresholdProvider | None` dependency injected straight into `create_app` (mirrors how the alert engine treats it — §4.6/§12 v2-deferred).
- **`GET /exchanges` is a static, hardcoded list** (4 exchanges: XNSE/XBOM/XKRX/XCME with MIC/name/source) per the doc's "static list of configured exchanges with metadata" — adding a 5th exchange later is a one-line addition to `EXCHANGES` in `routes/calendar.py` (P4), not a schema change.
- **Ingest-trigger defaults its date range to `today..today+ingestion.default_range_days`** when the request body omits `date_from`/`date_to`, using the same config value the CLI (Phase 13) will use — one shared default, not duplicated.
- **Flask route handlers are annotated `-> ResponseReturnValue`** (from `flask.typing`) to satisfy mypy strict mode — Flask views can legitimately return a bare `Response`, a `(body, status)` tuple, or other shapes, and this is Flask's own type for that union.

## Dashboard decisions (2026-07-21, Phase 12)

- **`api/app.py` never imports `dashboard/`, and vice versa** — they are peers, not a dependency of one on the other, matching §5.7's framing exactly ("a consumer of the API... a future live monitoring system is another skin over the same API"). `create_app()` from Phase 11 is untouched. Phase 13's CLI `serve` command is the one place that mounts both blueprints (`api` blueprints + `dashboard.bp`) onto a single `Flask()` instance — verified now in `tests/integration/test_dashboard.py::test_dashboard_mounted_alongside_api_on_one_flask_app`, which mirrors exactly what `serve` will do.
- **One self-contained `index.html`** (inline `<style>`/`<script>`, no build step, no external CDN) — matches "the dashboard is deliberately the thinnest layer" and the design doc's "no build process" framing for a v1 static consumer. All 6 conceptual views from §5.7's table are present except the **IV overlay, which is not built** — no `IVThresholdProvider` ships in v1 (§12 v2-deferred, consistent with the Phase-8/10 IV decisions), so there's nothing for it to display; the `/api/v1/iv/...` endpoint already returns a clean 501 for exactly this reason.
- **A test (`test_dashboard_has_no_business_logic_imports`) statically parses the dashboard module's AST** and asserts it imports nothing from `exchange_events.*` except itself — a durable, mechanical enforcement of "no data transformation, no alerting logic, no fetching from external sources" (§5.7) that will fail loudly if someone later adds a shortcut import instead of going through the API.
- **Color usage follows the `dataviz` skill's validated reference palette** (loaded before building the page): the 4 canonical categorical slots (blue/green/magenta/yellow, fixed order) for event-type badges, and the reserved status palette (info/warning/critical, distinct hues from the categorical set) for alert severity — both light and dark mode are wired via the palette's documented CSS custom-property pattern (`prefers-color-scheme` + a `data-theme` override for a manual toggle).

## CLI decisions (2026-07-21, Phase 13)

- **stdlib `argparse`**, not a third-party CLI framework — four subcommands is well within argparse's comfort zone and it avoids a new dependency for something this small.
- **Every command is built on exactly `load_config()` + `build_application()`** — `main.py` has no logic beyond arg parsing and result formatting, matching §5.3's framing of the ingestion engine as "a plain callable" that an external scheduler (cron/systemd-timer) invokes, not something the app schedules itself.
- **`ingest` with no `--source` runs every adapter over the real network** (wiring always injects `RealHttpClient` — there's no offline mode for a full run). This is correct production behavior but means a "full ingest" CLI test is inherently a live-network test — it was written and gated as `@pytest.mark.contract` in `tests/contract/test_live_adapters.py`, documenting the same mixed per-source outcome as the Phase-6 findings (iana_tz succeeds; CME/BSE/MarketWatch expected-fail from this sandbox; NSE may pass; FRED needs a key). The default unit-test suite instead exercises `--source iana_tz` (fully offline, real 2026 DST data) to cover the CLI's formatting/exit-code logic without touching the network.
- **`serve` takes an injectable `run_server` seam** (defaults to `Flask.run`) purely so it's unit-testable — tests pass a no-op that records the resolved `host`/`port`/`debug` instead of actually binding a socket and blocking forever.
- **Bug found and fixed via testing:** `IngestionEngine.run_single_source` raises a bare `ValueError` for an unknown `source_name` (by design, per its Phase-7 contract test), but `main()`'s top-level handler only caught `ExchangeEventsError` — a typo'd `--source` would have crashed the CLI with a raw traceback instead of a clean exit code. `cmd_ingest` now catches `ValueError` explicitly around both `run_single_source`/`run_full_ingest` calls and reports it the same way as a domain error.
- **`exchange-events` console-script entry point verified for real** (not just via `python -m`): reinstalled the package (`pip install -e .`) and ran the installed command directly — confirms `pyproject.toml`'s `[project.scripts]` wiring actually works, not just the module invocation.

## Final hardening decisions (2026-07-21, Phase 14)

- **Coverage target (≥90% on domain/normalizers/ingestion/alerting) was checked directly with `pytest-cov`, not assumed:** domain 100%, normalizers 100% (after closing a gap — see next point), ingestion 98%+, alerting 99%. Overall repo coverage 96%. The remaining gaps are all expected: `storage/postgres_repository.py` (0%, correctly untestable without a live PG server), `notifications/smtp_transport.py`'s real-`smtplib` call path (only `FakeSmtpTransport` runs in tests), a handful of defensive/edge branches in `main.py`/`api/app.py` error handlers.
- **Closed a real coverage gap in `normalizers/base.py`:** three documented `BaseNormalizer` contract behaviors — `_normalize_one` returning `None` (skip), returning a `list[Event]` (expand), and an *unwrapped* generic exception being captured rather than propagated — were never exercised, because no production normalizer happens to use the `None`/`list` paths and none has an internal bug to trigger the generic-exception branch. Added `_ContractProbeNormalizer` (a small local test double) in `test_normalizers.py` to lock in all three branches directly, since they're load-bearing parts of the shared base every real normalizer depends on, not incidental code.
- **One dedicated E2E test** (`tests/e2e/test_full_pipeline.py`) runs the full chain — fake source adapter → real `CMENormalizer` → real `SqliteEventRepository`/`SqliteAlertLog` → real Flask API (`create_app` + test client) → real `AlertEngine` with the real `ExpiryDayRule` → real `NotificationDispatcher`/`RoutingConfig` → a fake terminal channel — in one flow, per §9.1 ("few" E2E tests; everything else is unit/integration against fakes for its neighbors). It runs in the default suite (no network involved), unlike the network-gated `@pytest.mark.contract` tests.
- **README.md is the external-facing summary**; CLAUDE.md remains the internal living guide. The README's live-source-status table and scheduling/crontab guidance are pulled directly from the DECISIONS.md findings and the design doc's §5.3 "not a scheduler" framing, so there's one source of truth restated in the right place for each audience (operator vs. future-session continuity).

## Post-delivery: dashboard restructure + a real concurrency bug found by driving the app (2026-07-21)

- **Dashboard restructured into exchange-specific tabs + a Consolidated View** (user request, after seeing the running dashboard for the first time). Top-level nav is now "Consolidated View" (exactly the original 5-tab layout: Calendar/Upcoming/Economic Releases/Exchanges/Alerts, unchanged) plus **one tab per exchange, built dynamically from `GET /api/v1/exchanges`** — adding a 5th configured exchange later requires zero dashboard code changes (P4). Each exchange tab shows: a status card (next holiday/next expiry), a 14-day upcoming table, its own independent month-navigable calendar, and an alerts table — all filtered to that exchange, either via the API's existing `?exchanges=` query param (upcoming/status) or client-side filtering on `event.exchange`/`alert.event.exchange` (calendar/alerts, since those two endpoints don't take an exchange filter and didn't need one before). No backend changes were required for this — every new capability reused existing API surface.
- **Real bug found and fixed while driving the app, not by inspection:** the moment the dashboard fired several exchange tabs' worth of concurrent API requests on page load, the server started throwing `sqlite3.InterfaceError: bad parameter or other API misuse`. Root cause: `Flask.run()` defaults to `threaded=True` (confirmed by reading Flask's source), but `BaseSqlEventRepository`/`BaseSqlAlertLog` each hold **one shared DB-API connection for their lifetime with no locking** — `sqlite3`'s `check_same_thread=False` only disables the same-thread *ownership* check, it does not make a connection safe for genuinely concurrent statement execution from multiple threads. This was a **pre-existing bug from Phase 4**, not something introduced by the dashboard change — the original 5-tab dashboard already fired 5 concurrent top-level fetches on load, it just wasn't quite enough concurrency to reliably trigger the race before. The new exchange tabs pushed concurrent DB access over the threshold.
  - **Fix:** added a `threading.Lock` in both `BaseSqlEventRepository.__init__` and `BaseSqlAlertLog.__init__`, held around every method that touches `self._conn` (`upsert`/`query`/`get_by_id`/`get_latest_ingest_time`, `has_fired`/`record`/`recent`). This benefits the Postgres backend too — a shared `psycopg` connection has the same concurrent-use hazard — even though the bug was only observed via SQLite in this environment.
  - **Regression test added:** `tests/integration/test_repository_concurrency.py` — a `ThreadPoolExecutor`-based stress test (16 threads × 25 rounds of interleaved reads/writes) against both `SqliteEventRepository` and `SqliteAlertLog`, asserting zero exceptions and data integrity. This is the kind of test that would have caught the bug before it ever reached a running server.
  - **Verified the fix live**, not just via the test suite: restarted the demo server, re-screenshotted (via headless Chrome + Playwright driving the system-installed `google-chrome` binary, no bundled browser download needed), zero errors in the server log, and confirmed both a specific exchange tab (XCME) and the Consolidated view render correct, correctly-filtered data.

## Economic-release waterfall (2026-07-22) — replaces the MarketWatch-dependency plan

**Context:** attempted to get MarketWatch's economic calendar live using headless Chrome (Playwright driving the system `google-chrome`) to see if real JS execution could get past the DataDome wall documented earlier. It could not — DataDome served an **actual interactive CAPTCHA** (`'t':'fe'`, an iframe to `geo.captcha-delivery.com`), not a computational challenge a browser silently solves. This is almost certainly the same IP-reputation root cause as CME's block, not a fixable header/fingerprint issue. **Did not attempt to script past the CAPTCHA** — deliberately automating past an anti-bot control is a line not worth crossing regardless of technical feasibility.

**This changed the whole approach, for a good reason:** re-reading the original requirement — "economic calendar (add the data that was **released** to it as well)" — confirmed forecasts/consensus were never actually required, only *realized* (actual) values for the 7 releases. FRED and other official statistical APIs publish exactly that, with no anti-bot wall at all. The MarketWatch effort had been solving for forecast data the requirement never asked for.

**New design — a 4-source waterfall, highest reliability first, capped at 4 sources per the user's explicit request:**

| Tier | Source | Adapter | Covers | Why this rank |
|---|---|---|---|---|
| 1 | **FRED** | `adapters/fred.py` | NFP, CPI, PPI, PCE, JOLTS, FOMC (6/7) | Single stable free JSON API, no anti-bot wall, already built pre-this-change. |
| 2 | **BLS** (Bureau of Labor Statistics) | `adapters/bls.py` | NFP, CPI, PPI, JOLTS (4/7) | *Original publisher* of those four — official backstop when FRED is stale/down. Series ids verified via web search against BLS's own docs (not guessed): CPI=`CUUR0000SA0`, NFP=`CES0000000001`, PPI=`WPSFD4`, JOLTS=`JTS000000000000000JOL`. Works unkeyed at a lower rate limit; free key = 500 req/day. |
| 3 | **BEA** (Bureau of Economic Analysis) | `adapters/bea.py` | PCE / Personal Income (1/7) | *Original publisher* of PCE — official backstop. **Not live-verified** (no API key available here): default targets NIPA Table `T20806`, line 1 — believed correct from BEA's own table docs, flagged for confirmation before go-live, same honesty posture as BSE's endpoint. |
| best-effort | **ISM** | `adapters/ism.py` | ISM Manufacturing PMI only | **No free official source exists** — FRED discontinued all ISM series in 2016 over licensing (confirmed via St. Louis Fed's own removal notice). Built fully generic/provider-agnostic (config-driven URL + field-name mapping) since no specific aggregator's free-tier access was verified live; degrades to `SourceUnavailableError` (isolated by the ingestion engine, §7) rather than blocking the other six when unconfigured. |

`FOMC`'s FRED series was deliberately chosen as `DFEDTARU` (Federal Funds Target Range - Upper Limit — the literal outcome of the FOMC's decision) rather than `FEDFUNDS` (the market-determined effective rate) — verified as a real FRED series via search, not guessed. `FEDFUNDS` is kept as a separate bonus entry for anyone who wants the effective-rate series too.

**MarketWatch (`adapters/econ.py`, `EconCalendarAdapter`) is left exactly as built** — still wired into `build_application()`'s adapter list, still fixture-tested, still correctly documented as CAPTCHA-blocked. Nothing forces removing working code; the ingestion engine already isolates its per-run failure like any other adapter outage. It's just no longer load-bearing for the required scope, and would only start contributing forecast data automatically the moment it's reachable from an unblocked host.

**A new problem this surfaced and fixed:** since each source's `event_id` includes `source` (P6, by design — keeps per-source idempotency simple), the *same* real-world release from FRED vs. BLS produces two different event_ids — i.e. two rows, not one merged record. Worse, it silently meant `EconomicSurpriseRule` could never fire under real multi-source ingestion, since no single source's event ever had both `forecast` and `actual` populated at once.
- **Fix:** `domain/reconciliation.py::reconcile_economic_releases()` — a pure, read-time function (no storage/ingestion changes) that groups events by `(release_code, date)` and merges them field-by-field, preferring the highest-priority source's value for each field but backfilling from lower-priority sources when the top source has no value. Wired into the 3 places that consume repository query results: `api/routes/events.py` (`list_events`, `upcoming_events`), `api/routes/calendar.py` (`month_calendar`), and `alerting/engine.py`'s `evaluate()` (right before rules run). Storage/ingestion themselves are untouched — every source's own history stays intact per-source (P6); the merge is purely presentational/evaluative.
- Default priority order: `fred_api > bls_api > bea_api > ism_pmi > econ_calendar` (MarketWatch ranked lowest, in case it's ever revived).
- **Regression test** (`tests/unit/test_alert_engine.py::test_economic_surprise_rule_fires_across_two_sources_...`) proves the exact bug this fixes: a forecast-only event + an actual-only event from two different sources now correctly produce one surprise alert.

**A real bug the new adapter tests caught before it ever ran live:** `BEAAdapter._parse_time_period` had an off-by-one length check (`len(value) != 6`) against BEA's actual `"YYYYMM"`-style `TimePeriod` field, which is 7 characters (e.g. `"2026M06"`), not 6 — every BEA response would have silently parsed to zero events. Fixed to check for the `"M"` separator instead of a fixed length.

## Environment findings feeding decisions (2026-07-20)

- Egress works. `cmegroup.com` & `nseindia.com` → **HTTP 403** to naive requests (anti-bot WAF). `marketwatch.com/economy-politics/calendar` → **HTTP 401** (Dow Jones subscription/session). `api.stlouisfed.org` reachable (301→HTTPS), needs key.
- Pre-installed: Python 3.13.11, Flask 3.1, pydantic 2.12 + pydantic-settings, pytest 9.0, requests 2.32, lxml 6.0; stdlib `sqlite3`/`tomllib`/`zoneinfo`.

## Economic-release `country` tagging (2026-07-22)

- **Decision:** stay US-only for economic releases (no India/Korea adapters built) — user explicitly deferred multi-country expansion — but associate the 6 US releases with the **CME tab** specifically, since "any other exchange in the US will have this as well."
- **Mechanism:** `EconomicReleaseEvent.country` (new field, defaults `"US"`, set by all 5 economic normalizers) + a `"country"` field on each entry in `api/routes/calendar.py`'s `EXCHANGES` list (XCME→US, XNSE/XBOM→IN, XKRX→KR). The dashboard fetches the existing `/events?event_types=economic_release` endpoint once per exchange tab and filters client-side by `e.country === ex.country` — **no new backend query filter was needed**, this mirrors the client-side-filter pattern already used for exchange-tab calendar/alerts.
- **Why country, not a hardcoded "show under CME" rule:** if a second US exchange is ever added to `EXCHANGES`, it gets the same economic-releases section automatically (P4) — matches the user's own framing exactly, and is the same mechanism that would extend cleanly to India/Korea releases later, should that be revisited.
- **Alerts side-effect:** the exchange-tab Alerts filter previously only matched `alert.event.exchange === mic`, which meant economic-release alerts (whose `event.exchange` is always `None`) could never appear on *any* exchange tab. Extended to also match `event.event_type === "economic_release" && event.country === ex.country` — verified live that XCME now shows the CPI-surprise alert while XNSE correctly does not.

## Dashboard `timestamp_utc` display + standard release times (2026-07-22)

- Added `STANDARD_RELEASE_TIMES_ET` (`normalizers/util.py`) — a hardcoded release_code → time-of-day mapping (NFP/CPI/PPI/PCE=8:30am ET, JOLTS/ISM_PMI=10:00am ET, FOMC=2:00pm ET), sourced via web search from each agency's own materials (BLS's own release PDFs, BEA's own embargo notices, ISM's site, Fed convention) — not guessed. Applied as a fallback in `GovernmentReleaseNormalizer`/`EconCalendarNormalizer` when a raw record doesn't supply its own `"time"`, since none of FRED/BLS/BEA's APIs return an intraday time at all.
- **User correctly flagged two real problems with this, in order:**
  1. The dashboard rendered this time via the *viewer's own browser-local timezone* with no label at all — ambiguous, silently wrong-looking to anyone not in US Eastern. Fixed: `dashboard/static/index.html` now renders each release in *its own market's* timezone (`COUNTRY_TIMEZONE` keyed by `country`) with a hardcoded label (`COUNTRY_TZ_LABEL` = "ET"/"IST"/"KST") rather than trusting `Intl`'s `timeZoneName: "short"`, which renders inconsistently across browsers (confirmed live: user's Chrome showed "GMT-4" instead of "EDT" for the exact same instant).
  2. **The bigger issue:** a hardcoded time is static and can't self-correct if an agency revises its schedule, and — more fundamentally — FRED/BLS/BEA's APIs are backward-looking only (`series/observations` never returns a not-yet-published date), so no active source could warn about an upcoming release before it happens at all. Confirmed via `adapters/fred.py::_parse` — it only iterates `payload["observations"]`, which by construction contains only realized data. This directly undermines the pipeline's purpose ("know about upcoming releases... to take trading decisions in advance") and led to the release-schedule adapter work below.

## Release-schedule adapter (2026-07-22)

**Scope decision:** user chose to solve *scheduling* (know about a release before it happens) now, and explicitly deferred *forecasts* (consensus values for trading decisions) as a separate, harder problem — MarketWatch is CAPTCHA-blocked and no other forecast aggregator's free-tier access was ever verified. This entry covers scheduling only.

**Reachability research (real probes, not assumptions):**
| Source | Result |
|---|---|
| BLS's own schedule page (`bls.gov/bls/updated_release_schedule.htm`) | ❌ HTTP 403 from this sandbox — same IP-reputation class of block as CME. |
| ISM's release-date calendar (`ismworld.org/.../rob-report-calendar/`) | ❌ Redirects to `ecommerce.ismworld.org/SSO/Login.aspx` — requires a **paid ISM member login**, confirmed directly, not assumed. |
| Federal Reserve's FOMC calendar (`federalreserve.gov/monetarypolicy/fomccalendars.htm`) | ✅200 OK, 164KB — genuinely reachable. |
| BEA's schedule page (`bea.gov/news/schedule`) | ✅ 200 OK, 80KB — reachable, but **turned out unnecessary** (see below). |

**Key finding that simplified the whole design:** FRED itself exposes `fred/release/dates` (distinct from `fred/series/observations`, which `FREDAdapter` already used) — confirmed via FRED's own docs that setting `include_release_dates_with_no_data=true` plus a future `realtime_end` returns **scheduled dates before the data is published**, i.e. a genuine forward calendar. Verified the actual API endpoint responds (structured "missing api_key" error, not a block) even without a key. This meant NFP/CPI/PPI/PCE/JOLTS's forward schedule could be added to the **already-working, already-unblocked `FREDAdapter`** — no need to touch BLS's blocked page or BEA's page at all.

**What was built:**
- `adapters/fred.py`: `fetch()` now also calls `fred/series/release` (resolve a series's `release_id`) then `fred/release/dates` (with `include_release_dates_with_no_data=true`) per configured code, adding a schedule-only record (`actual`/`previous` both `None`) for any date not already covered by a real observation — never duplicates a date that already has data. New `fetch_schedule` config toggle (default on). Schedule lookup is **best-effort per release code** (§7): a failure is logged and skipped, never raised, so a hiccup doesn't block the actuals fetch or other codes.
- **FOMC excluded from this generic mechanism** (`"skip_schedule": True` in `DEFAULT_SERIES["FOMC"]`): `DFEDTARU` belongs to FRED's H.15 (Selected Interest Rates) release, which updates **daily** — its release-dates schedule is a stream of near-daily entries, not the ~8/year FOMC meeting dates. Using it would be actively wrong, not just noisy.
- `adapters/fomc.py` (new): `FOMCScheduleAdapter` parses the Fed's own FOMC calendar page directly. **Real page structure inspected via lxml before writing any parsing logic** (not guessed): each year is a `div.panel.panel-default`; each meeting is a `row fomc-meeting` / `fomc-meeting--shaded row fomc-meeting` child div with a `fomc-meeting__month` + `fomc-meeting__date` (day-range, e.g. `"17-18*"`, `"22 (notation vote)"`). Once a meeting has happened, its block also has a Statement press-release link (`monetary20260128a.htm`) whose embedded date is authoritative and preferred. **Confirmed directly against the real live page that future meetings have no such link at all** — for those, the decision date is computed from year + month name + the *last* day number in the range (the second/decision day). Verified against the actual captured page: correctly found all 8 real 2026 meetings (4 from statement links, 4 computed).
- `domain/reconciliation.py`: `DEFAULT_SOURCE_PRIORITY` gained `"fomc_schedule"` (ranked right after `fred_api`) — in practice its ranking never matters since `fomc_schedule` never sets `actual`/`forecast`, only the date; it's complementary to `fred_api`'s `DFEDTARU` value, not competing with it.
- `normalizers/fomc.py`: `FOMCScheduleNormalizer`, a thin subclass of `GovernmentReleaseNormalizer` (same pattern as FRED/BLS/BEA/ISM) — `STANDARD_RELEASE_TIMES_ET["FOMC"]` (2:00pm ET) applies automatically via the shared base, no new logic needed.

**What this actually fixes (confirmed with a dedicated regression test):** `UpcomingHighPriorityReleaseRule` only requires `release_code` + `date` on an event — it never needed `forecast`/`actual`. Before this work, no active source ever produced a future-dated `EconomicReleaseEvent` at all (FRED/BLS/BEA are backward-looking only), so this already-built rule could never fire in real operation — only in hand-seeded demo data. `tests/unit/test_alert_engine.py::test_upcoming_release_rule_fires_from_a_schedule_only_event` proves a bare schedule-only event (no forecast, no actual) is now sufficient.

**Tests:** `tests/unit/test_adapters.py` — FRED schedule-fetch (adds future date / no duplicate / best-effort failure isolation / config toggle / FOMC exclusion), FOMC adapter (past-meeting-via-link / future-meeting-computed / single-day "notation vote" format / date-range filtering / end-to-end through the normalizer). **Total 417 passed** (410 → 417 across this + the timestamp/timezone work). `ruff`/`mypy` clean (100 files).

**Still not solved (by design, per user's scope choice):** forecast/consensus values. `fomc_schedule` and FRED's schedule records never set `forecast` — only MarketWatch (blocked) or a licensed aggregator (never evaluated) could supply that.

## BLS multi-series bug found via real live ingestion, not a demo (2026-07-22)

**Context.** User asked directly whether the dashboard's data was real or demo — it was 100% demo (a hand-authored `seed_demo.py` script inserting made-up numbers straight into SQLite, no adapter ever touched). To answer honestly and move toward "actually used," ran real `exchange-events ingest` against every source that needs zero configuration (`iana_tz`, `nse_circular`, `bls_api`, `fomc_schedule`) against a fresh (non-demo) SQLite database.

**Real bug found:** `bls_api` failed with `'NoneType' object has no attribute 'get'` — not a network block. Root cause: `BLSAdapter.fetch()` built one GET request with all series ids comma-joined in the URL path (`.../timeseries/data/CUUR0000SA0,CES0000000001,WPSFD4,JTS...`). Confirmed via direct `curl` against BLS's live API: a **single** series in the path works fine over GET, but **two or more** comma-joined ids return `{"status":"REQUEST_FAILED","Results":null}` — and `_parse`'s `payload.get("Results", {}).get("series", [])` crashes on that `null` because the key is *present* (not missing), so the `{}` default never applies. This was invisible in the existing unit tests because every one of them overrode `options={"series": {...}}` down to a single series — the real multi-series default path was never actually exercised end-to-end until this live run.

**Fix:** BLS's v2 API's documented way to query more than one series is a POST with a JSON `seriesid` array; confirmed live this also works for a single series, so `BLSAdapter.fetch()` now always POSTs one request (`_post_json`, new helper on `HttpSourceAdapter` alongside `_get_json`/`_get_text`) regardless of series count — one code path instead of a GET/POST branch. Also added an explicit check on the response's own `"status"` field, raising `SourceUnavailableError` with BLS's own message on any non-`REQUEST_SUCCEEDED` result, instead of only surfacing an `AttributeError` when the shape happened to break parsing.

**Also fixed while confirming real data end-to-end:** `EconomicReleaseEvent.surprise` (`domain/events.py`) returned raw float-subtraction artifacts (e.g. `3.4 - 3.1 == 0.2999999999999998`, visible in the dashboard's "Surprise" column) — rounded to 6 decimal places, more precision than any real release value in this pipeline carries.

**Verified live (not fabricated):** fresh SQLite db, real ingestion runs — `iana_tz` (8 DST transitions), `nse_circular` (64 real 2026 holiday/circular records), `fomc_schedule` (all 8 real 2026 FOMC meeting dates from the Fed's own calendar page), `bls_api` (23 real CPI/NFP/PPI/JOLTS observations from Jan–Jun 2026, post-fix). Confirmed `cme_calendar` (403, IP-reputation), `bse_circular` (HTTP 200 but non-JSON garbage body — a real broken/wrong endpoint, matches "soft-404" in the live-source table), `fred_api`/`bea_api` (correctly refuse to run without their API keys, which are not set in this environment), `ism_pmi` (correctly refuses — no provider configured), `econ_calendar` (401, DataDome) all fail exactly as previously documented — none of this was fabricated, all captured from real command output. Screenshotted the served dashboard via Playwright against this real database: the XCME tab's "Economic Releases" table and July-2026 calendar show the genuine BLS/FOMC values, not demo numbers.

**Tests:** `tests/unit/test_adapters.py` — `test_bls_requests_multiple_series_in_one_post_body` (regression for the exact bug), `test_bls_raises_source_unavailable_when_api_reports_failure`; updated 4 existing BLS tests to the new POST contract. **Total 419 passed** (417 → 419), 18 skipped (PG), 6 deselected (contract). `ruff`/`mypy` clean (100 files).

**Still real-data gaps, unchanged by this fix:** `FRED_API_KEY`/`BEA_API_KEY` not available in this sandbox (needed for PCE, better rate limits, and redundant cross-source confirmation); ISM has no configured provider; CME is IP-blocked here (untested from a real deploy host); BSE's endpoint needs a real URL captured from devtools, not the current guessed one.

## CME Reference Data API — replacing the blocked CmeWS/mvc endpoints (2026-07-22)

**Context.** User asked directly what it would take to unblock CME (the XCME dashboard tab showed "Next holiday: None scheduled" / "Next expiry: None scheduled" — a direct consequence of `cmegroup.com`'s domain-wide IP-reputation block, confirmed this time to cover even plain static HTML pages, not just the `CmeWS/mvc` JSON calendar service). Investigated whether CME has anything resembling FRED/BLS's free-key model before assuming a paid data-vendor relationship was the only path.

**Finding:** CME does have a genuinely free, officially documented **Reference Data API v3** (`refdata.api.cmegroup.com`) — distinct from CME's paid real-time market-data feeds (Market Data API, DataMine), which are commercial products. Confirmed via CME's own FIA-published announcement quoting their managing director: "we provide completely free access to the API." It covers exactly what this adapter needs: trading-hours/holiday schedules **and** instrument lifecycle dates (first/last trade, notice, delivery, settlement — i.e. expiries).

**Access is heavier than FRED's, but still free and self-service:** requires (1) a CME Group Customer Center account (their own SSO, including phone-verified MFA via their EASE support line — a real, standard identity-verification call, not automatable), (2) an OAuth "API ID" generated in-portal under My Profile → API ID Management. Per CME's own docs, plain Futures & Options reference data needs **no separate entitlement approval** beyond the API ID itself (extra approval is only for BrokerTec/EBS fixed-income/FX data). The user completed this account/credential creation themselves; `CME_API_ID`/`CME_API_SECRET` now live in `.env` (gitignored).

**Confirmed reachable from this sandbox** — unlike `cmegroup.com` itself. `auth.cmegroup.com` (OAuth token endpoint) and `refdata.api.cmegroup.com` (the actual data API) are separate infrastructure from the public marketing/trading website; both returned normal application responses (a clean 401 "api key or token is invalid" from refdata, not a block page) even before authenticating, and a real OAuth token was obtained on the first correctly-formed request. This confirms the earlier hypothesis that purpose-built automated-client infrastructure sits outside the anti-scraping WAF fronting the public site.

**Debugging note (own tooling bug, not CME's):** the first several token requests failed with `invalid_client` even with correct credentials — traced to testing via `bash`'s `source .env`, which silently mangled the secret (it contains `$` and `#`, which bash interprets as variable expansion and a comment marker respectively when unquoted). Confirmed by checking the loaded variable's length (1 character instead of the real ~24). Fixed by reading `.env` as plain text in Python instead of shell-sourcing it — a reminder that `.env` files are not shell scripts and should never be `source`d directly when values might contain shell-special characters.

**API contract, confirmed live (not assumed):**
- OAuth: `POST https://auth.cmegroup.com/as/token.oauth2`, HTTP Basic auth (`client_id:client_secret`), `grant_type=client_credentials` form body — confirmed via the `WWW-Authenticate: basic` response header when the wrong auth method was tried first. Tokens last `expires_in=1799` seconds (~30 min); the adapter fetches a fresh one per `fetch()` call rather than caching, since one ingestion run comfortably fits.
- Expiries: `/refdata/v3/products?exchangeGlobex=XCME&globexProductCode=ES&securityType=FUT` resolves a `productGuid`; `/refdata/v3/instruments?productGuid=...` (HAL-paginated via `_links.next`) returns real per-contract records — confirmed live with genuine symbols (`ESU6`, `ESZ6`, `NQU6`, `NQZ6`, ...), `lastTradeDate`, `finalSettlementDate`, `contractMonth`. The endpoint's date-filter params (`startedAfter` etc.) reject every format tried (400 "Bad request data type in filter") — unresolved; worked around by filtering client-side against `params.date_range` instead, consistent with how other adapters already handle date filtering.
- Holidays: there is no direct holiday-list endpoint. `/refdata/v3/tradingSchedules?globexGroupCode=ES` resolves a `tradingScheduleId`; fetching that schedule's full `marketEventsByDate` gives per-day open/preopen/close timestamps for a rolling ~1-year-forward window (confirmed: the API's own schedule coverage starts at "today", not arbitrary history). **A full holiday closure is not flagged — it's simply absent from the list.** Verified directly against a real, known holiday: Labor Day 2026-09-07 was confirmed completely missing from the schedule, while every surrounding weekday was present; also confirmed present dates are always Monday-Friday (weekends are naturally absent too, never miscounted as holidays). Holidays are therefore *derived* via gap analysis — any weekday within the schedule's own covered range (intersected with the requested range, to avoid false positives from asking about a period the schedule doesn't cover at all) that's missing from the trading-date set. Scoped to the equity-index schedule (`globexGroupCode=ES`) since that's what this adapter's configured products (ES, NQ) actually need — other CME product classes run different session calendars, so this is deliberately not asserted as CME's universal holiday calendar.

**Verified live end-to-end:** a real CLI ingest run derived all 9 real 2026 US market holidays correctly (New Year's Day, MLK Day, Presidents Day, Memorial Day, Juneteenth, Independence Day observed Fri Jul 3, Labor Day, Thanksgiving, Christmas) purely from schedule gaps — no hardcoded holiday list anywhere — plus 4 real upcoming ES/NQ quarterly expiries. Screenshotted the dashboard's XCME tab showing "Next holiday: 2026-09-07" and "Next expiry: 2026-09-18 — ES" in place of the previous "None scheduled".

**Built:** `adapters/cme.py` fully rewritten (OAuth token fetch, `_fetch_holidays` gap-derivation, `_fetch_expiries` via products→instruments with pagination); `adapters/base.py` gained `_post_form` (form-urlencoded POST with optional HTTP Basic auth — `HttpClient` has no `auth=` param, so the Basic-auth header is built manually); `config/loader.py` wired `CME_API_ID`/`CME_API_SECRET` (the secret rides in `AdapterConfig.options["api_secret"]` since there's only one dedicated `api_key` slot, and CME needs both an id and a secret — a generic, additive use of the existing `options` dict, no schema change). `tests/fakes/http.py` gained `register_json_sequence` (queued per-call responses) since the existing fake routes purely by URL and can't distinguish paginated calls to the same path by their query params alone — a small, additive fake enhancement, no existing test behavior changed.

**Tests:** `tests/unit/test_adapters.py` — 10 CME tests replacing the old ones (metadata, missing-credentials error, OAuth Basic-auth request shape, holiday gap-derivation, holiday-derivation coverage clamping, expiry pagination + date-range filtering, expiry skip-on-no-match, full normalizer round-trip, 401/429 mapping). `tests/contract/test_live_adapters.py` updated: CME's live contract test now follows the same `skipif`-on-missing-credentials pattern as FRED's, since it's expected to genuinely pass now rather than xfail. **Total 424 passed** (419 → 424), 18 skipped (PG), 6 deselected (contract). `ruff`/`mypy` clean (100 files).

**Remaining gap, unchanged:** BSE's endpoint still needs a real URL from devtools; MarketWatch/econ_calendar remains DataDome-blocked (only relevant for forecasts, out of scope); ISM PMI still has no configured provider.

## CME dashboard expansion — more underlyings, dedicated blocks, calendar fix (2026-07-22)

**Context.** With CME's Reference Data API now live, the user asked to actually use it: expand expiry coverage past ES/NQ, give "Next Holiday" its own block (matching the timezone-shift treatment) with a full-list toggle, and fix the CME tab's calendar — which was silently showing *only* holidays, never economic releases or expiries together.

**Expanded CME product coverage — confirmed real venues per product, not assumed.** "CME Group" is a holding-company brand covering four distinct exchanges with their own real MIC codes: CME itself (`XCME`), CBOT (`XCBT`), NYMEX (`XNYM`), COMEX (`XCEC`). Queried each new product against the live Reference Data API with no `exchangeGlobex` filter to discover its actual venue before hardcoding anything:

| Code | Product | Real venue |
|---|---|---|
| ES, NQ, RTY, 6E | E-mini S&P/Nasdaq/Russell, Euro FX | `XCME` |
| YM, ZN, ZB | E-mini Dow, 10Y Note, 30Y Bond | `XCBT` |
| CL, NG | Crude Oil, Natural Gas | `XNYM` |
| GC, SI | Gold, Silver | `XCEC` |

**User's explicit call: keep one dashboard tab.** Despite these being four real, distinct exchanges, the dashboard still shows everything under the single existing "XCME"/"CME Group" tab — matching how the design has always treated "CME" as one combined adapter/exchange, and avoiding a much larger restructure (new exchange entries, per-venue holiday calendars, etc.) that wasn't asked for. `DEFAULT_PRODUCTS` in `adapters/cme.py` now carries an `exchange_globex` per entry used only to query the right venue internally — the domain event's `exchange` field stays `"XCME"` for all of them, via the unchanged `CMENormalizer`.

**Dashboard changes:**
- **Next Holiday** — extracted out of the old combined "Status" card into its own dedicated card, with a "Show all" toggle revealing every holiday (not just the next one) in a table — mirrors the "Next Timezone Shift" card's visual treatment and the Economic Releases/Additional Indicators show/hide pattern already established.
- **Expiry Lookup** (new) — a dropdown of every underlying actually present in the ingested data (built dynamically from `/events?event_types=expiry`, not hardcoded — a new product added to config just works, no dashboard change needed, P4), defaulting to whichever underlying has the soonest upcoming expiry. Shows the real contract symbol (e.g. "GCN6") via the already-serialized `source_raw_id` field, plus a "Show all" toggle for that underlying's full expiry list. Deliberately a single selector, not two: every currently configured CME product is a plain future (`instrument_type`/`series` are 1:1 with the underlying), so a second "instrument type" dropdown would only ever have one option — noted as where it would extend if options are ever added, not built speculatively now.
- **Calendar fix** — the per-exchange calendar's client-side filter was `e.exchange === filterMic`, which silently dropped every economic-release event, since those only ever carry a `country`, never an `exchange` (same non-obvious fact already encountered for the Releases card and Alerts filter, missed here because the calendar was built earlier). Fixed by extending the filter to also match `event_type === "economic_release" && e.country === filterCountry`, threaded through via `exchangeCalState[mic].country` (already stored per-exchange).
- **Hover tooltips** — calendar day badges now carry a `title` attribute (reusing the already-existing `eventDescription()` helper, just never wired to the calendar before), so hovering any badge shows what the event actually is instead of just its category color.

**Verified live:** re-ingested `cme_calendar` with all 11 products over a 2-year window — 123 real expiry records (6E: 18, CL: 20, ES: 6, GC: 18, NG: 20, NQ: 6, RTY: 6, SI: 18, YM: 5, ZB: 3, ZN: 3) plus 19 real derived holidays. Dashboard screenshots confirm: Expiry Lookup showing real Gold contract symbols (GCN6 → GCZ7) across an 18-row "all expiries" table; Next Holiday's "Show all" revealing all 19 real 2026–2027 holidays; the CME tab's July 2026 calendar now showing Econ. Release, Expiry, and Holiday badges together (previously holiday-only); tooltip `title` attributes confirmed present via direct DOM inspection.

**Tests:** `tests/unit/test_adapters.py` — added `test_cme_fetch_expiries_queries_each_products_own_real_venue` (regression for the exchange_globex-per-product plumbing, using YM/XCBT as the real example). All 10 prior CME tests pass unchanged. **Total 425 passed** (424 → 425), 18 skipped (PG), 6 deselected (contract). `ruff`/`mypy` clean (100 files). No backend test changes needed for the dashboard-only pieces (calendar fix, new blocks) — none of it touches Python.

**Remaining gap, unchanged:** BSE's endpoint still needs a real URL; MarketWatch/econ_calendar remains DataDome-blocked; ISM PMI has no configured provider.

## Per-exchange tab: calendar as the one-look summary (2026-07-22)

**Context.** Immediately after the CME expansion above, user asked for a further cleanup pass, explicitly framed around the calendar's purpose: "does the user even need to look at the rest of the dashboard" — i.e. it should be a lean, decision-relevant summary, not a full data dump, and it should be the first thing seen.

**Changes:**
- **Removed the per-exchange "Upcoming (next 14 days)" card.** User's own reasoning: alerts already exist for exactly this purpose, so a separate near-term list was redundant. Explicitly scoped to the per-exchange tab only — Consolidated View's own "Upcoming" nav tab was kept as-is (user's explicit choice when asked, since it serves the all-exchanges-combined view differently).
- **Calendar moved to the top of the per-exchange tab.** Now the very first thing shown, above Next Holiday/Next Timezone Shift/Expiry Lookup.
- **Calendar content narrowed** to exactly: holidays, this exchange's own DST shifts (previously never shown on any calendar at all — `dst_change` events carry an `iana_zone`, not an `exchange`, so the earlier per-exchange filter dropped them entirely, the same class of gap already hit once for economic releases), ES/NQ expiries only (not all 11 now-configured products — the Expiry Lookup card below still covers the rest), and the 7 core economic releases (reusing the existing `CORE_RELEASE_CODES` set — the bonus GDP/Unemployment/Fed-Funds indicators are excluded from the calendar, staying only in their own "Additional Indicators" card).
- **Calendar gained its own Upcoming/All-dates toggle**, defaulting to Upcoming (today forward) — consistent with the "one-look, not a data dump" intent. Re-renders from a per-key client-side cache, no refetch, matching the existing Economic Releases toggle pattern.
- **Fixed hover tooltips that weren't visibly working.** The native HTML `title` attribute has a ~1s hover delay and minimal, easy-to-miss styling — switched to an instant CSS-only tooltip (`data-tooltip` attribute + `::after` pseudo-element triggered on `:hover`), confirmed rendering immediately via a live screenshot.
- **Both "Latest/All" release toggles now default to Latest** (previously defaulted to "All") — user's explicit ask, for both the core Economic Releases card and the Additional Indicators card, in both Consolidated View and the per-exchange tab (4 toggle-groups total). The "Upcoming/All dates" toggles were already defaulting to Upcoming and were left unchanged.

**Verified live:** screenshots confirm the per-exchange calendar defaulting to Upcoming-only (showing just the two remaining core-release dates for the rest of the month), "All dates" correctly revealing full-month history including a past holiday, the tooltip appearing instantly on hover with the real event description, and both release tables opening on "Latest" by default.

**Tests:** dashboard-only change (HTML/CSS/JS), no backend touched — all 425 existing tests still pass unchanged, `ruff`/`mypy` clean.

## Alerts box: "show next N days" filter (2026-07-22)

**Context.** Before moving on to alert-engine work, added a display control the
user asked for directly: a numeric "Show next N days" input on the Alerts box
(Consolidated View + every per-exchange tab), defaulting to 1, filtering the
already-fetched alert list client-side to `today <= event.date <= today + N`.
Purely a display filter — mirrors the existing calendar/releases toggle
pattern (fetch once, cache, re-render on input change, no refetch) and does
not touch the alert engine's own server-side lookahead.

**Implementation:** `alertsCache`/`alertsDaysFilter` keyed by `"consolidated"`
or `"ex-<MIC>"`; a shared `renderAlertsTable()` helper; a delegated `input`
listener on `.alerts-days-input` so it works for per-exchange tabs built
dynamically. Reintroduced the `addDaysISO(days)` helper (previously deleted
along with the old "Upcoming (14 days)" card) for real new use here.

## Proximity-based alert severity (2026-07-22)

**Context.** Before wiring real Email/Teams notification delivery, the user
asked to finalize the alert engine's severity model first, since it decides
notification content. Two clarifying rounds preceded this:

1. What counts as CRITICAL vs. WARNING, and what "expiry rollover" means. This
   surfaced a real finding: `RevisedExpiryRule` (the old `is_revised`-based
   CRITICAL trigger) can **never fire for CME** — CME's Reference Data API has
   no equivalent "this date was revised from an earlier announcement" flag,
   and the CME adapter's expiry records never set `is_revised` (defaults
   `False` always). It only ever had real data behind it for NSE (whose raw
   circulars do carry an `isRevised` flag). User chose to drop the rule
   entirely rather than keep dead code for CME.
2. The user then specified a complete replacement taxonomy directly:

   | Event type | INFO | WARNING | CRITICAL |
   |---|---|---|---|
   | Holiday | always | — | — |
   | DST/timezone shift | >2 days out | within 2 days | within 1 day |
   | Expiry | >2 days out | within 2 days | — |
   | Economic release | >2 days out | within 2 days | within 1 day |

   Teams gets WARNING+CRITICAL; email gets CRITICAL only (unchanged from
   before). User's explicit choices on the two open design questions this
   raised: (a) drop the old `EconomicSurpriseRule`/`RevisedExpiryRule`
   entirely rather than keep them alongside the new proximity model — simpler,
   one mental model, and `EconomicSurpriseRule` never fired in live operation
   anyway (no forecast data is ingested from any live source); (b) one alert
   *record* per event that escalates in place over time, rather than a fresh
   alert firing at every pipeline run — Teams/email should only fire the
   moment an event *crosses into* WARNING/CRITICAL, not repeatedly while it
   stays there.

**What changed:**
- **`domain/ids.py::make_alert_id`** dropped its `trigger_date` parameter —
  `alert_id = sha256(f"{rule_id}:{event_id}")`, stable across every
  evaluation of the same (rule, event) pair forever, not just within one
  calendar day. This is the load-bearing change that makes "escalates in
  place" possible.
- **`contracts/alert_log.py`** replaced `has_fired`/`record` with `get`/
  `upsert` — the engine now reads the *previously stored severity* for a
  given alert_id to decide whether this evaluation is an escalation, then
  unconditionally upserts the freshly classified alert (so displayed
  title/severity never goes stale even when unchanged, e.g. an expiry's
  countdown text updating from "in 2 days" to "in 1 day" while staying
  WARNING both days). `storage/alert_log.py` now does a real
  `ON CONFLICT (alert_id) DO UPDATE`, not `DO NOTHING`.
- **`alerting/engine.py::AlertEngine.evaluate()`** rewritten around this:
  for each rule-produced candidate, compare its severity rank against the
  alert log's stored value; only a strict increase past INFO is returned for
  notification dispatch. INFO alerts are always upserted (so the dashboard/
  API always reflects the full picture) but never notify anyone.
- **Four new rule classes** replace the old four, one per event category,
  each a pure days-until-event classifier: `HolidayProximityRule` (flat
  INFO), `DstShiftProximityRule`, `ExpiryProximityRule` (no CRITICAL tier,
  per the user's own table), `EconomicReleaseProximityRule` (scoped to the
  existing `CORE_RELEASE_CODES` — deliberately excludes FRED's daily-updating
  extra series like `FEDFUNDS`/`DFEDTARU`, which would otherwise sit at
  permanent WARNING/CRITICAL and spam every evaluation).
- **`config/schema.py::AlertingConfig`** replaced `upcoming_release_lookahead_days`/
  `expiry_day_lookahead_days`/`economic_surprise_threshold_pct` with
  `dst_warning_days`/`dst_critical_days`/`expiry_warning_days`/
  `economic_release_warning_days`/`economic_release_critical_days`; default
  `lookahead_days` widened from 7 to 30 so a far-out event's INFO row exists
  well before it needs to escalate (previously the window only ever admitted
  events close enough to fire the old fixed-day rules).
- **`config/defaults.toml`** notification routes simplified: severity alone
  now decides the channel, uniformly across all 4 event types (the old
  CRITICAL route's `event_types = ["economic_release", "expiry"]` restriction
  is gone, since holiday/DST alerts now participate in the same severity
  scale too).

**Verified live:** cleared the dev SQLite alert log of stale rows from
in-session testing, then ran `AlertEngine.evaluate()` twice via the real
wired app against real ingested CME/FRED/BLS/NSE/IANA data. First run: 13 real
INFO alerts (6 economic releases, 5 CME expiries, 2 NSE holidays), 0 escalated
(nothing currently within the 1-2 day WARNING/CRITICAL bands) — correct for
2026-07-22's real data. Second run: identical row count (13), 0 newly
escalated — confirms idempotent re-evaluation with no duplicate rows and no
re-notification. Confirmed via the live Flask API (`GET /api/v1/alerts`) that
the dashboard's existing `badge-info` CSS (already present, unused until now)
renders these correctly.

**Tests:** rewrote `test_alert_rules.py` (4 new rule classes, boundary tests
per severity tier) and `test_alert_engine.py` (escalation/de-escalation/
re-evaluation semantics replace the old fixed-day/dedup tests), updated
`test_alert_log.py`, `test_fakes.py`, `test_wiring.py`, `test_ids.py`,
`test_alerts.py`, `test_api.py`, `test_repository_concurrency.py`, and the one
e2e test for the new contract. **434 passed** (425 → 434), 19 skipped (PG), 6
deselected (contract), `ruff`/`mypy` clean across 100 source files.

**Not yet done:** real Email (Gmail SMTP app password) and Teams (Incoming
Webhook) credentials — this was the original ask for this session, paused to
finalize the severity model first since it determines notification content.
Next step once the user has the credentials: wire `SMTP_HOST`/`SMTP_USERNAME`/
`SMTP_PASSWORD`/`SMTP_FROM_ADDRESS`/`TEAMS_WEBHOOK_URL` into `.env` and verify
one real end-to-end delivery of each.

## DST alert content: named abbreviations + a real metadata-stripping bug found (2026-07-22)

**Context.** User asked the DST timezone-shift alert to show named zone
abbreviations ("CDT -> CST") instead of raw UTC offsets, matching the
dashboard's own "Next Timezone Shift" block — plus, separately, flagged that
the expiry alert's title was missing the exchange (only underlying was
shown), even though CME Group spans 4 real venues (XCME/XCBT/XNYM/XCEC), so
underlying alone doesn't uniquely identify the venue in general.

**Expiry fix:** `ExpiryProximityRule`'s title now includes `event.exchange`:
`"{underlying} ({exchange}) {series} expiry in N day(s) (date)"`.

**DST abbreviation:** ported the dashboard's `ZONE_ABBR` map (EST/EDT,
CST/CDT, GMT/BST, CET/CEST) into `domain/exchange_zones.py` as
`ZONE_ABBR` + `dst_transition_label(iana_zone, transition)`, using
`DSTChangeEvent.metadata["transition"]` ("start"/"end", set by
`adapters/iana.py` from whether the UTC offset grew or shrank) to pick the
correct direction — mirrors the dashboard JS's `nextDstShiftInfo()` exactly.
Falls back to raw offsets for a zone/direction with no known abbreviation
pair.

**Real bug found while wiring this up (not by code review):** the DST alert
kept showing raw offsets even after the abbreviation code was in place.
Root cause: `EventQuery.include_metadata` defaults to `False` — a deliberate
knob for the *public API* (`GET /events`) to keep JSON responses lean unless
a client explicitly asks for metadata — but `AlertEngine.evaluate()`'s
internal window query never opted in, so every event's `metadata` dict was
silently stripped to `{}` before reaching any rule. This wasn't a new bug
introduced by the DST-label work — it's been true since Phase 4 — but it was
invisible until a rule finally needed to *read* `event.metadata` for
something real. **Fixed** in `alerting/engine.py`: the internal query now
sets `include_metadata=True` explicitly, with a comment explaining why this
differs from the API's own default.

**Verified live:** confirmed the real America/Chicago DST event's metadata
came back empty before the fix and populated (`{"transition": "end"}`) after;
sent a corrected real test alert through both Email and Teams —
`"XCME timezone shift in 101 day(s): CDT -> CST (2026-11-01)"` — confirmed
delivered.

**Tests:** `test_evaluate_does_not_strip_event_metadata` (regression test for
the metadata bug), `dst_transition_label`/`ZONE_ABBR` tests in
`test_exchange_zones.py`, expiry-exchange and DST-abbreviation title tests in
`test_alert_rules.py`. 453 passed (452 -> 453), ruff/mypy clean across 102
source files.

## Deployment scaffolding: lockfile, WSGI entrypoint, systemd path, gated redeploy (2026-07-23)

**Context:** first real move from "runs on my machine" toward "runs on a server
alongside an existing, unrelated dashboard/system" — a deep discussion (not
just the checklist) about redeploy mechanics, dependency reproducibility, and
keeping this pipeline from ever affecting the other system on the same host.

**First git commit made.** Nothing was committed before this (the working tree
itself was the only persistence layer). `.gitignore` confirmed clean — no
`.db`, `.env`, or `__pycache__` ever staged.

**Recipient email moved out of committed config.** `config/defaults.toml`'s
`team_trading` recipient group previously had a real personal email hardcoded
(added directly per an earlier explicit user request, before git existed).
Now a harmless `placeholder@example.com`; the real address comes from a new
`ALERT_RECIPIENT_EMAIL`/`ALERT_RECIPIENT_NAME` env pair, merged in
`config/loader.py::_merge_secrets` exactly like every other secret. Chosen
over "commit as-is" specifically because this file is about to go into git
history permanently, on whatever remote it ends up pushed to.

**Lockfile added** (`requirements.lock.txt`, via `pip-tools`) — `pyproject.
toml` keeps loose version floors (fine for library use), but a deploy target
needs exact, reproducible installs so "works on my machine" can't silently
diverge from what a redeploy actually installs months later. Verified: a
fresh venv installed from the lockfile alone (no `pyproject.toml` resolution)
still passes all 453 tests.

**`gunicorn` + `wsgi.py` added** — `serve`'s Flask dev server was explicitly
not production-safe. `wsgi.py` mirrors `main.py::cmd_serve` exactly (no new
logic). Verified live: real gunicorn, 2 workers, against the real database,
serving `/` and `/api/v1/exchanges` correctly.

**Redeploy decoupled from pipeline execution — the core mechanical decision.**
The cron/timer-triggered `ingest`/`alert` runs never pull code themselves;
they always execute whatever is currently installed on disk. Only a
deliberate, gated `scripts/redeploy.sh` run changes that: fetch → checkout →
install from the lockfile → run the full test suite + ruff + mypy (**abort
before touching the live service if anything fails, and revert the working
tree to the previous known-good commit** so a failed redeploy can never leave
untested code on disk for the next cron tick to pick up) → `init-db`
(idempotent) → restart the `exchange-events-web` systemd unit → curl the
health endpoint → auto-rollback to the previous commit if the health check
still fails post-restart. `scripts/rollback.sh` handles rolling back to a
specific SHA (or the last-verified one, tracked in `.last_good_deploy`)
without re-running tests, since that SHA already passed them during its own
redeploy.

**Self-managed server (systemd) established as the primary deployment path**,
Render kept as a documented alternative (`docs/DEPLOYMENT_CHECKLIST.md` §3a
vs §3b) — driven by the actual context: this pipeline is going onto a host
that already runs another, unrelated dashboard/system, not a fresh isolated
PaaS app. `deploy/systemd/` has ready-to-copy unit files: `exchange-events-
web.service` (gunicorn, its own dedicated user/working directory/logs,
`Restart=on-failure`), plus `exchange-events-ingest`/`exchange-events-alert`
one-shot services on systemd timers matching the README's existing 6h/15min
cadence. All deliberately isolated per-unit so a crash or restart of this
app's units never touches the other system's.

**Still open:** GitHub repo creation + push (no `gh` CLI available in this
environment; needs the user's own account/org), the storage backend decision
(SQLite vs. Postgres — including whether to share the *database* the other
system might already run, never a schema/table), and whether the test gate
lives primarily in CI (GitHub Actions) or only in `redeploy.sh` — leaning CI-
primary but not yet set up, pending the repo existing.
