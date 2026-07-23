# Progress Log

Append-only chronological journal. Newest entries at the bottom. Each entry records what was
built, files touched, test results, and the next step — so any session can resume cleanly.

---

## 2026-07-20 — Phase 0: Scaffolding & continuity docs ✅

**Built**
- `git init` (branch `main`); `src/` package layout skeleton per design-doc §11 (adapted).
- `pyproject.toml`: package `exchange-events` (src layout), deps (flask, pydantic, pydantic-settings, requests, lxml), optional groups `postgres` / `dev`, `exchange-events` console script, pytest config (`pythonpath=["src"]`, markers `unit`/`integration`/`contract`/`e2e`, default `-m 'not contract'`), ruff + mypy config.
- `.gitignore`, `.env.example` (secrets: FRED key, SMTP, Teams webhook, optional PG DSN).
- Continuity docs: `CLAUDE.md` (living guide + Resume-Here), `docs/DECISIONS.md` (§13 resolutions + rationale), `docs/PROGRESS_LOG.md` (this file). Plan persisted at `docs/IMPLEMENTATION_PLAN.md`.

**Files touched**
- `pyproject.toml`, `.gitignore`, `.env.example`, `CLAUDE.md`, `docs/DECISIONS.md`, `docs/PROGRESS_LOG.md`
- `src/exchange_events/**/__init__.py` (package skeleton), `tests/**/__init__.py`

**Deps installed (all succeeded)**
- `psycopg[binary]` 3.3.4, `pytest-cov` 7.1.0 (+ coverage 7.15.2), `ruff` 0.15.22, `mypy` 2.3.0.
- `pip install -e .` succeeded; `import exchange_events` OK.

**Tests / verification**
- `pytest --co -q` → "no tests collected" (clean, as expected for scaffolding).
- `pytest --markers` → all 4 markers registered, no unknown-mark warnings.

**Decisions made**
- None new (all captured pre-execution in `docs/DECISIONS.md`).

**Next step**
- Phase 1 — Domain model (§3): `domain/enums.py`, `events.py`, `alerts.py`, `query.py`, `ids.py`, `errors.py` + exhaustive unit tests (event_id determinism, immutability, surprise computation, enum contracts).

**Notes**
- Not committing to git per-phase unless asked; on-disk files are the persistence. Can enable per-phase commits on request.

---

## 2026-07-21 — Phase 1: Domain model (§3) ✅

**Built** — pure-data domain layer, no dependencies on any other package.
- `domain/enums.py` — `EventType`, `SessionType` (both `StrEnum`).
- `domain/ids.py` — `make_event_id` (§3.4 natural-key sha256), `make_alert_id`.
- `domain/errors.py` — typed exception hierarchy (`ExchangeEventsError` root; source/normalization/repository/channel/config).
- `domain/iv.py` — `IVSnapshot` (kept in domain so contracts + AlertContext can reference it without domain importing upward).
- `domain/events.py` — `Event` base + `HolidayEvent`/`DSTChangeEvent`/`ExpiryEvent`/`EconomicReleaseEvent`.
- `domain/alerts.py` — `AlertSeverity`, `Alert`, `AlertContext`.
- `domain/query.py` — `DateRange`, `FetchParams`, `EventQuery`.
- `domain/__init__.py` — re-exports.

**Design refinements (recorded in DECISIONS.md)**
- `kw_only=True` frozen dataclasses → clean inheritance, keyword construction.
- **`event_id` auto-derived** in `Event.__post_init__` from the natural key (centralizes P6 idempotency); each subclass supplies `discriminator()`. Explicit ids preserved.
- **UTC enforced at the domain boundary** (P5): naive datetimes raise; aware ones normalized to UTC. Same for `Alert.triggered_at` / `AlertContext.now_utc`.
- `EconomicReleaseEvent.surprise` is a computed **property**, never a stored field (§3.2).
- `AlertContext` carries resolved `now_utc`/`today_utc` (not a `Clock`) to keep domain free of `contracts/`.

**Tests / verification**
- `tests/unit/{test_ids,test_events,test_alerts,test_query}.py` — **53 passed**.
- Coverage of: id determinism + every key-component change, enum/str parity, None-exchange collapse; per-subclass event_type defaults, discriminator wiring, immutability, metadata isolation, UTC normalization/rejection; surprise (present/negative/None cases); DateRange validation/iteration; EventQuery/FetchParams defaults.
- `ruff check src tests` clean; `mypy src/exchange_events/domain` clean.

**Decisions made** — StrEnum over `(str, Enum)`; domain stays import-free of contracts (AlertContext resolved-time design). Both logged in DECISIONS.md.

**Next step** — Phase 2: Contracts (§4). All ABCs (`SourceAdapter`, `EventNormalizer`, `EventRepository`, `AlertRule`, `NotificationChannel`, `IVThresholdProvider`, `AlertLog`, `Clock`) + infra ABCs (`HttpClient`, `Logger`) + contract value types (`UpsertResult`, `NormalizationResult`, `DeliveryResult`, `Recipient`, `RetryPolicy`, `IngestionReport`, `Response`).

---

## 2026-07-21 — Phase 2: Contracts (§4) ✅

**Built** — `contracts/` package, ABCs only, importing solely from `domain/` (P1).
- Infra ABCs: `clock.py` (`Clock`), `http_client.py` (`HttpClient` + `Response` value type + `HttpError`), `logger.py` (`Logger`).
- Pipeline ABCs: `source_adapter.py` (`SourceAdapter`), `normalizer.py` (`EventNormalizer` + `NormalizationResult`), `repository.py` (`EventRepository` + `UpsertResult`).
- Alerting/notification ABCs: `alert_rule.py` (`AlertRule`), `alert_log.py` (`AlertLog` incl. `recent`), `notification_channel.py` (`NotificationChannel` + `Recipient` + `DeliveryResult` + `DeliveryStatus`), `iv_provider.py` (`IVThresholdProvider`).
- `contracts/__init__.py` re-exports.

**Decisions made** (all in DECISIONS.md → "Contract-level decisions")
- `normalize` returns `NormalizationResult`; `send` returns `list[DeliveryResult]`; `AlertLog.recent` added; `HttpClient`/`Logger` ABCs in `contracts/`; `RetryPolicy`/`IngestionReport` deferred to `ingestion/` (Phase 7).

**Tests / verification**
- `tests/unit/test_contracts.py` — ABC-not-instantiable (all 10 ABCs, parametrized), partial-impl rejected, complete-impl OK; value-type invariants (`UpsertResult.total`, `NormalizationResult` counts, `Response.ok/text/json/raise_for_status` + `HttpError`, `Recipient` defaults, `DeliveryResult.succeeded`, `DeliveryStatus` values).
- **Total 75 passed** (53 domain + 22 contracts). `ruff` clean; `mypy src/exchange_events/{domain,contracts}` clean (19 files).

**Next step** — Phase 3: Test fakes + production infra concretes. `infra/` → `SystemClock`, `RealHttpClient` (requests + browser headers + retry/backoff), `StdLogger`/`NullLogger`. `tests/fakes/` → `FakeClock`, `FakeHttpClient`, `FakeEventRepository`, `FakeAlertLog`, `FakeChannel`. Tests for the fakes themselves.

---

## 2026-07-21 — Phase 3: Test fakes + infra (§9.2) ✅

**Built**
- Production infra (`src/exchange_events/infra/`):
  - `clock.py` → `SystemClock` (aware UTC).
  - `http.py` → `RealHttpClient` wrapping a `requests`-style session with **browser-realistic default headers** (for the anti-bot CME/NSE/MarketWatch adapters) and **retry+exponential backoff** on network errors / 429 / 5xx. Session and `sleep` are injectable → fully unit-testable offline.
  - `logging.py` → `NullLogger`, `StdLogger` (structured `key=value` fields over stdlib logging).
- Test fakes (`tests/fakes/`): `FakeClock` (advanceable), `FakeHttpClient` (register json/text/bytes by url, records calls, base-url match), `FakeEventRepository` (**reference semantics** for the repo contract — idempotent upsert accounting, all EventQuery filters, metadata strip, ingested/updated_at), `FakeAlertLog`, `FakeChannel` (fail / unavailable modes).

**Tests / verification**
- `tests/unit/test_fakes.py` + `tests/unit/test_infra.py`. **Total 108 passed** (75 → 108).
- RealHttpClient tested with injected fake session + no-op sleep: response mapping, retry-then-succeed, retries-exhausted-returns-last, connection-error → `SourceUnavailableError`, recovery-after-error, backoff cap, header injection, POST json passthrough.
- `ruff` clean; `mypy src/exchange_events` clean (34 files). Added `types-requests` to dev deps.

**Decisions made** — `RealHttpClient` maps exhausted network failures to `SourceUnavailableError` (infra may import domain errors); low-level HTTP retry is complementary to the Phase-7 ingestion `RetryPolicy`.

**Next step** — Phase 4: Storage. `storage/schema.sql`, `SqliteEventRepository` (raw SQL, `ON CONFLICT` upsert), `PostgresEventRepository` (psycopg 3, gated on `EXCHANGE_EVENTS_PG_DSN`), `AlertLog` impls; integration tests holding both repos to the FakeEventRepository reference semantics.

---

## 2026-07-21 — Phase 4: Storage / Repository (§4.3) ✅

**Built**
- `domain/serialization.py` — `serialize_event`/`deserialize_event` (round-trippable JSON form, shared) + ISO datetime helpers.
- `storage/schema.py` — one TEXT-column DDL for both backends (events + alerts tables, indexes).
- `storage/_sql.py` — dialect helpers (`adapt` `?`→`%s`, `exec_ddl`, `placeholders`, DB-API Protocol).
- `storage/sql_repository.py` — `BaseSqlEventRepository` (per-event idempotent upsert w/ content_hash; query with all EventQuery filters, ordering, pagination, metadata strip; get_by_id; get_latest_ingest_time) + `content_hash()`.
- `storage/sqlite_repository.py` (`SqliteEventRepository`, LIMIT/OFFSET quirk handled), `storage/postgres_repository.py` (`PostgresEventRepository`, lazy psycopg).
- `storage/alert_log.py` — `BaseSqlAlertLog` + `SqliteAlertLog` / `PostgresAlertLog`.
- `storage/__init__.py` — exports SQLite eagerly, PG via lazy `__getattr__`.

**Tests / verification**
- `tests/unit/test_serialization.py` — round-trip + type preservation for all 4 subclasses, JSON-safety, None-optionals.
- `tests/integration/{conftest,test_repository,test_alert_log}.py` — **parametrized over fake + SQLite + Postgres** (PG gated on `EXCHANGE_EVENTS_PG_DSN`). Covers: insert/unchanged/updated accounting, re-ingest idempotency (no dups), ingested_at-stable/updated_at-bumps, round-trip of all subclasses through the DB, every query filter, pagination incl. offset-without-limit, metadata strip, get_latest_ingest_time.
- **Total 150 passed, 18 skipped** (PG). `ruff` clean; `mypy src/exchange_events` clean (41 files). Smoke-tested lazy PG import + SQLite defaults.

**Decisions made** — see DECISIONS.md "Storage decisions": one TEXT schema for both backends; per-event upsert; serialization in domain; SQL AlertLog in `storage/` (not `alerting/`); lazy psycopg. **PG not yet run against a live server here.**

**Next step** — Phase 5: Normalizers (§5.2). Shared parsing utils (UTC-canonical) + one normalizer per adapter (cme, nse, bse, krx, fred, iana/tz, econ), partial-failure `NormalizationResult`, golden `raw→expected` fixture tests.

---

## 2026-07-21 — Phase 5: Normalizers (§5.2) ✅

**Built** — `normalizers/` package. Each normalizer's **raw-record schema is documented in its module docstring** (this is the contract Phase-6 adapters must emit).
- `util.py` — `parse_date` (ISO + strptime fallbacks), `parse_float` (tolerant), `local_time_to_utc` (ET→UTC via zoneinfo, P5), `require`/`first`, `to_session_type`.
- `base.py` — `BaseNormalizer` encoding partial-success once (per-record errors captured into `NormalizationResult`, never fatal).
- `exchange.py` — `ExchangeCalendarNormalizer` shared base (holiday+expiry `record_type` dispatch) for the four exchanges.
- `cme.py`/`nse.py`/`bse.py`/`krx.py` — thin subclasses declaring exchange MIC + date formats (CME ISO/"04 Jul 2026", NSE "26-Jan-2026", BSE "26/01/2026", KRX "20260101").
- `fred.py` — `EconomicReleaseEvent` actuals (forecast=None). `tz.py` — `DSTChangeEvent`. `econ.py` — MarketWatch upcoming releases (forecast/previous + ET→UTC time).

**Tests / verification**
- `tests/unit/test_normalizers.py`: per-normalizer happy paths (all event types, date formats, session mapping, ET→UTC in winter EST *and* summer EDT, surprise), event_id determinism, and the partial-failure contract (good kept / bad captured, unknown record_type, missing-required, empty batch), target_source names.
- **Total 168 passed, 18 skipped.** `ruff` clean; `mypy` clean (51 files).

**Decisions made** — Normalizer tests use **inline raw dicts** (the documented adapter schema) rather than JSON `raw.json` files; captured real-source fixtures belong to the Phase-6 adapter tests. The 4 exchange normalizers share `ExchangeCalendarNormalizer` (still one class per source — P2/P4).

**Next step** — Phase 6: Source Adapters. CME first & hardest (spike reachable endpoint w/ browser headers; land data in SQLite end-to-end), then NSE/BSE live, KRX stub, FRED (keyed API), IANA (zoneinfo, offline), MarketWatch econ. Unit tests via FakeHttpClient + captured fixtures; `@pytest.mark.contract` live tests.

---

## 2026-07-21 — Phase 6: Source Adapters (§5.1) ✅

**Built** — `adapters/` package: `config.py` (`AdapterConfig`), `base.py` (`HttpSourceAdapter` — shared HTTP plumbing, typed error mapping, per-call header merging), and one adapter per source:
- `cme.py` (production priority — JSON `/CmeWS/mvc/` services), `nse.py` (session-warm-up pattern), `bse.py`, `krx.py` (deferred stub, fully wired), `fred.py` (keyed observations API, 7 default series), `iana.py` (stdlib `zoneinfo`, fully offline DST-transition scanner), `econ.py` (MarketWatch, lxml HTML table parsing, config-driven release codes per §5.1 design note).

**Live spike findings (real network probes, both curl and adapters) — full table in DECISIONS.md:**
- **NSE: passes live** from this sandbox — validates the session-warm-up design. 🎉
- **CME: HTTP 403, explicit IP-reputation block** (Akamai-style "IP blocked for suspected scraping") — needs the real deployment host's egress to validate; not a code defect.
- **BSE: HTTP 200 soft-404** — the guessed endpoint path is stale/wrong; a URL-discovery task, not a bot block.
- **MarketWatch: HTTP 401 behind DataDome JS-challenge** — cannot be solved by headers alone; needs a headless-browser fetch layer or unblocking proxy. FRED remains the reliable actuals fallback.
- **IANA: validated correct** against real 2026 DST dates (US 03-08/11-01, UK 03-29/10-25) — fully offline, deterministic.

**Robustness fixes made from these findings:**
- `HttpSourceAdapter._get_json` now wraps any JSON-parse failure (e.g. BSE's soft-404 HTML body) in `SourceUnavailableError` — previously an unhandled `JSONDecodeError` could crash the ingestion path.
- `_get`/`_get_json`/`_get_text` accept per-call `headers` merged with config; fixed a latent NSE bug where bot-relevant headers were defined but never applied to the actual data-fetch calls (only the session warm-up).
- CME/NSE/BSE/Econ all now route every response through these hardened helpers (no adapter calls `resp.json()` directly anymore).
- Fixed real bugs found via testing: `Europe/Frankfurt` is not a valid IANA zone key (→ `Europe/Berlin`); econ normalizer needed MarketWatch's `m/d/yy` date format and 12-hour `8:30am`-style times; `parse_float` needed `K`/`M`/`B` magnitude-suffix support (MarketWatch displays NFP as "170K").

**Tests / verification**
- `tests/unit/test_adapters.py` — all 7 adapters via `FakeHttpClient` + realistic fixtures: happy paths end-to-end through their normalizers, event-type filtering, 403→`SourceUnavailableError`, 429→`SourceRateLimitError`, 401 handling, KRX stub, FRED api-key requirement + observation chaining, IANA 2026 DST dates, MarketWatch HTML parsing + date-range filtering + unknown-label skip.
- `tests/unit/test_normalizer_util.py` — dedicated coverage of `parse_float` (incl. suffixes), `local_time_to_utc` (24h + 12h variants), `parse_date`.
- `tests/contract/test_live_adapters.py` — **real network**, `@pytest.mark.contract` (excluded from default run): NSE passes, CME/BSE/MarketWatch `xfail` with documented reasons, FRED skips without a key.
- **Default suite: 216 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (60 files).

**Decisions made** — full per-source table + robustness-fix notes in DECISIONS.md "Source adapter findings".

**Next step** — Phase 7: Ingestion Engine (§5.3). `NormalizerRegistry`, `RetryPolicy` (backoff, retryable-exception allowlist), `IngestionEngine.run_full_ingest`/`run_single_source` (per-adapter error isolation, incremental windows via `get_latest_ingest_time`, `IngestionReport`). Tests: one failing adapter doesn't block others; retry honored only for retryable exceptions; idempotent re-run; partial-normalization pass-through; report accuracy.

---

## 2026-07-21 — Phase 7: Ingestion Engine (§5.3) ✅

**Built** — `ingestion/` package:
- `retry.py` — `RetryPolicy` (max_retries, backoff base/max, retryable_exceptions tuple) + `backoff_for(attempt)`.
- `normalizer_registry.py` — `NormalizerRegistry` (dict keyed by `source_name`, `.from_list()` convenience).
- `report.py` — `SourceIngestResult` (fetched/normalized/upserted breakdown/errors/duration/succeeded) + `IngestionReport` (aggregate helpers: `total_upserted`, `any_source_failed`, `total_normalization_errors`, `for_source`).
- `engine.py` — `IngestionEngine.run_full_ingest`/`run_single_source`: per-adapter try/except isolation (§7 — one failure never blocks another), retry-with-backoff restricted to `retry_policy.retryable_exceptions` (injectable `sleep`, no real delays in tests), incremental fetch-window narrowing via `repository.get_latest_ingest_time`, structured logging of normalization errors and per-adapter completion/failure.
- Reusable test doubles added to `tests/fakes/`: `FakeSourceAdapter` (scriptable return-value/exception sequence, records calls) and `FakeNormalizer` (pluggable transform) — kept in `tests/fakes/` (not test-local) since Phase 14's E2E suite will need them too.

**Tests / verification**
- `tests/unit/test_ingestion.py` (15 tests): happy-path report accuracy; **error isolation** for a failing adapter, a missing normalizer, and a repository exception (each in turn, others unaffected); **retry policy** — retryable exception retried then succeeds (with sleep-call count asserted), retries-exhausted still isolated, non-retryable exception fails immediately with zero retries; **idempotent re-ingest** (P6 — second run reports `unchanged`, not a duplicate insert); **partial-normalization pass-through** (§5.2 — bad records counted but good ones still upserted, and this does *not* count as an adapter failure); `run_single_source` returns one result and leaves other adapters untouched, raises `ValueError` for an unknown source; **incremental window narrowing** (start moves to last-ingest date; falls back to full range with no prior ingest; non-incremental always uses the full range); adapter-declared `event_types`/`exchanges` flow into `FetchParams`.
- **Total 231 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (64 files).

**Decisions made** — None new; `RetryPolicy`/`IngestionReport` confirmed to live in `ingestion/` (not `contracts/`), per the Phase-2 decision log.

**Next step** — Phase 8: Alert Engine + Rules (§5.4). `AlertEngine.evaluate` (query window, build `AlertContext` from `Clock`, per-rule exception isolation, dedup via `AlertLog`). Rules: `UpcomingHighPriorityReleaseRule`, `ExpiryDayRule` (v1-required, §12), plus `RevisedExpiryRule` + `EconomicSurpriseRule` (promoted from v2 — pure/cheap), `IVThresholdRule` (gated on optional `iv_provider`). Tests mirror doc §9.2's `FakeClock`-based example: fire/no-fire boundaries, severity, dedup across runs, per-rule failure isolation, graceful IV-absent skip.

---

## 2026-07-21 — Phase 8: Alert Engine + Rules (§5.4) ✅

**Built** — `alerting/` package:
- `engine.py` — `AlertEngine.evaluate()`: queries `[today-lookback, today+lookahead]` window (defaults 1/7 days), builds `AlertContext` (resolves IV snapshots for `ExpiryEvent`s only, deduped by `(exchange, underlying)`, only when `iv_provider` is set), runs every rule with **per-rule exception isolation** (§7), then applies **dedup at the engine level** — checks `alert_log.has_fired()` per candidate alert and records only newly-fired ones.
- `rules/upcoming_release.py` — `UpcomingHighPriorityReleaseRule` (fires exactly N days before a high-priority release; default codes = the 7 named in the requirements doc, overridable).
- `rules/expiry_day.py` — `ExpiryDayRule` (fires exactly N days before an expiry; deliberately proximity-only, revision status is a separate rule — P2).
- `rules/revised_expiry.py` — `RevisedExpiryRule` (fires on `is_revised`, any proximity, CRITICAL).
- `rules/economic_surprise.py` — `EconomicSurpriseRule` (percent-surprise threshold, absolute-value fallback when forecast is 0, CRITICAL).
- `rules/iv_threshold.py` — `IVThresholdRule` (per-underlying or default threshold; skips gracefully with zero snapshot present — degrades to no-op with no IV provider wired, §12).
- **Domain fix during this phase:** `AlertContext.today_utc` was typed `date | None`, causing mypy errors in both rules (`context.today_utc + timedelta` on a nullable). Simplified to a derived-only, non-Optional field (`field(init=False)`, always computed from `now_utc`) — no code anywhere constructed it with an explicit override, confirmed by grep before changing. See DECISIONS.md "Alerting decisions".
- Reusable test doubles added: `tests/fakes/iv_provider.py` (`FakeIVProvider`).

**Tests / verification**
- `tests/unit/test_alert_rules.py` (24 tests) — each rule's exact fire/no-fire day boundary, severity, non-matching-event-type no-op, config overrides (custom high-priority codes, per-underlying IV threshold), surprise direction + zero-forecast fallback, IV graceful-skip with no snapshot.
- `tests/unit/test_alert_engine.py` (10 tests) — window query correctness (lookback/lookahead inclusive/exclusive boundaries), dedup across two `evaluate()` calls, a broken rule isolated from a working one (and all-broken → empty, no crash), multiple rules produce distinct-id alerts, IV-snapshot context building with/without a provider, empty-rules-list safety.
- **Total 260 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (70 files).

**Decisions made** — `AlertContext.today_utc` derived-only (not independently settable); dedup is engine-side not rule-side; IV-snapshot population is engine-side and expiry-scoped. Full rationale in DECISIONS.md.

**Next step** — Phase 9: Notification (§5.5). `alerting/dispatcher.py` (`NotificationDispatcher` — routing by severity/event_type → channels+recipients, per-channel failure isolation), `notifications/email_channel.py` (SMTP via injected transport), `notifications/teams_channel.py` (Incoming Webhook via `HttpClient`), `notifications/dashboard_channel.py` (in-memory). Tests: routing resolution, channel-failure isolation, DeliveryResult per recipient, Email via fake SMTP transport, Teams payload shape via FakeHttpClient.

---

## 2026-07-21 — Phase 9: Notification (§5.5) ✅

**Built**
- `alerting/routing.py` — `RouteRule` (severity/event_type match, `None` = wildcard), `RoutingConfig` (ordered routes, first-match-wins; `recipient_groups` name→`Recipient` list; `resolve_recipients` dedupes by id).
- `alerting/dispatcher.py` — `NotificationDispatcher.dispatch()`: match route → resolve recipients → send per channel; catches `ChannelUnavailableError` per channel and synthesizes `FAILED` results for that channel's recipients (§7 isolation) without blocking other channels/alerts.
- `notifications/smtp_transport.py` — `SmtpTransport` ABC (channel-local, not a top-level contract) + `SmtplibTransport` (stdlib `smtplib`/STARTTLS).
- `notifications/email_channel.py` — `EmailChannel`: one email per recipient, per-recipient try/except, `[SEVERITY]`-prefixed subject.
- `notifications/teams_channel.py` — `TeamsChannel`: single MessageCard POST via `HttpClient` (severity-colored), one `DeliveryResult` per named recipient sharing that one outcome; non-2xx or transport exception → `ChannelUnavailableError`.
- `notifications/dashboard_channel.py` — `DashboardChannel`: never fails, logs + records in-memory; the safe default/catch-all channel.
- Reusable fake added: `tests/fakes/smtp_transport.py` (`FakeSmtpTransport`, with per-recipient failure injection).

**Tests / verification**
- `tests/unit/test_notification_channels.py` (11 tests) — Email: per-recipient send, subject/body/from correctness, one bad recipient doesn't block the other. Teams: MessageCard shape + severity color, non-2xx → `ChannelUnavailableError`, transport exception → `ChannelUnavailableError`, one POST regardless of recipient count. Dashboard: records + always succeeds.
- `tests/unit/test_notification_dispatcher.py` (11 tests) — routing: first-match-wins across 3 real-shaped routes (mirrors the doc's YAML example), event-type filter correctly falls through to catch-all, recipient dedup across overlapping groups. Dispatcher: routes to the right channel, fans out to multiple channels for one alert, **isolates a down channel while another still delivers**, unknown-channel-in-routing skipped gracefully, no-matching-route skipped, multiple alerts routed independently.
- **Total 279 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (76 files).

**Decisions made** — see DECISIONS.md "Notification decisions": SMTP transport is channel-local not a top-level contract; email is per-recipient, Teams is single-webhook/shared-outcome; DashboardChannel never fails and is distinct from `AlertLog.recent()` (the actual API feed); routing is first-match-wins.

**Next step** — Phase 10: Config + Wiring (§8). `config/schema.py` (`AppConfig` pydantic — database/adapters/ingestion/alerting/notification/iv/api sub-configs), `config/loader.py` (TOML + env secrets via `pydantic-settings`), `config/defaults.toml`, `wiring.py` `build_application()` (the one composition root — instantiates every concrete class built in Phases 3-9: SQLite/Postgres repo choice, all 7 adapters + normalizers wired via registry, ingestion engine, alert engine + all 5 rules, dispatcher + 3 channels, routing config). Tests: config load/validation errors are clear; `build_application(test_config)` smoke test over SQLite + fake channels yields a working `Application`.

---

## 2026-07-21 — Phase 10: Config + Wiring (§8) ✅ — MAJOR MILESTONE: full app composes end-to-end

**Built**
- `config/schema.py` — pydantic `AppConfig` (`DatabaseConfig`, `AdapterConfigModel`, `IngestionConfig`, `AlertingConfig`, `NotificationConfig` incl. `EmailConfig`/`TeamsConfig`/`RouteRuleModel`/`RecipientModel`, `IVConfig`, `APIConfig`).
- `config/loader.py` — `load_toml`/`load_config` (TOML → `ConfigError` on missing/invalid), `Secrets` (`pydantic_settings.BaseSettings`, field-for-field mirror of `.env.example`), `_merge_secrets` (overlays env secrets onto the TOML-loaded config: PG DSN, FRED key, SMTP fields, Teams webhook).
- `config/defaults.toml` — real, working defaults: sqlite backend, retry/alerting defaults, and the **doc's §5.5 routing example verbatim** (CRITICAL release/expiry → email+teams, WARNING → teams, catch-all → dashboard) with placeholder recipient groups.
- `wiring.py` — `build_application(config) -> Application`: the sole composition root. Builds storage (SQLite default / Postgres if configured, `ConfigError` if postgres selected without a DSN), all 7 adapters + their normalizers via `NormalizerRegistry`, the `IngestionEngine`, the `AlertEngine` with all 4 v1 rules (IV rule omitted — no provider ships in v1), and the `NotificationDispatcher` with channels wired **conditionally on real config being present** (not just "named in enabled_channels").

**Tests / verification**
- `tests/unit/test_config.py` (13 tests) — missing/invalid TOML → `ConfigError`; schema rejects an unknown `database.backend`; bundled `defaults.toml` loads correctly (3 routes, 2 recipient groups, all 7 adapter keys); custom TOML path override; every `_merge_secrets` path (PG DSN, FRED key incl. preserving existing adapter options, SMTP fields, Teams webhook, no-op when nothing set).
- `tests/unit/test_wiring.py` (6 tests) — **full graph wiring** (all 7 adapters, all 4 rule ids, dashboard-only channel with no secrets configured, `iv_provider is None`); every adapter has a matching normalizer; postgres-without-DSN → `ConfigError`; email/teams channels *do* get wired once their config fields are set; **a true smoke test** — `build_application` over a temp SQLite file, then a real `run_single_source("iana_tz", ...)` ingest (fully offline/live), `alert_engine.evaluate()`, and `dispatcher.dispatch()` all run without error.
- **Manually verified via a real run** (not just pytest): `build_application()` against the bundled defaults + a temp SQLite path prints exactly the expected adapters/rules/channels and logs the expected "not configured" warnings for email/teams — confirming the whole system composes correctly end-to-end, independent of the test suite.
- **Total 297 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (79 files).

**Decisions made** — see DECISIONS.md "Config + wiring decisions": pydantic for config (dataclass kept for the adapter-facing `AdapterConfig` to avoid a pydantic dependency in `adapters/`); dedicated `Secrets` class mirroring `.env.example`; bundled `defaults.toml` as the zero-config default; direct submodule imports for lazy Postgres classes (mypy correctness); IV provider never built in v1; channels wired only when their config is actually complete.

**Next step** — Phase 11: API layer (§5.6). Flask app (`api/app.py`) + routes (`events`, `events/{id}`, `events/upcoming`, `alerts`, `iv/{exchange}/{underlying}`, `calendar/{year}/{month}`, `exchanges`, `ingest/trigger`) + pydantic serializers for all 4 event subclasses + consistent error envelopes. Tests: Flask test client against a seeded SQLite repo, per-endpoint query-param → `EventQuery` mapping, 404s, calendar aggregation.

---

## 2026-07-21 — Phase 11: API layer (§5.6) ✅

**Built** — `api/` package, all 8 endpoints from §5.6:
- `serializers.py` — `event_to_dict` (reuses `domain.serialization`, adds computed `surprise` for releases), `alert_to_dict`, `iv_snapshot_to_dict`, `error_envelope`.
- `query_params.py` — `parse_event_query` (query-string → `EventQuery`, raises `QueryParamError` on bad input), `parse_optional_int`.
- `routes/events.py` — `GET /events` (full filter set), `GET /events/upcoming` (`?days=`, default 14), `GET /events/<id>` (404 on miss).
- `routes/alerts.py` — `GET /alerts` (`AlertLog.recent`, `?limit=`).
- `routes/iv.py` — `GET /iv/<exchange>/<underlying>` — **501** (not 404/500) when no `IVThresholdProvider` is wired.
- `routes/calendar.py` — `GET /calendar/<year>/<month>` (events grouped by date, invalid month/year → 400) and `GET /exchanges` (static 4-exchange list).
- `routes/ingest.py` — `POST /ingest/trigger` (optional `source`/`date_from`/`date_to`/`incremental` body; unknown source → 404).
- `app.py` — `create_app(*, repository, alert_log, ingestion_engine, clock, iv_provider=None, default_range_days=365)`: dependencies stashed on `app.config["EE_*"]`, blueprints registered, global error handlers for `QueryParamError`→400, any `ExchangeEventsError`→500, unmatched routes→404 (consistent JSON error envelope everywhere).

**Verification (manual, before writing tests)** — booted a real Flask app (`test_client()`) against a seeded in-memory SQLite repo and hit **every** endpoint by hand: correct JSON for events/upcoming/calendar/exchanges/alerts, `501` for IV with no provider, `404` for an unknown event id — all before the automated suite existed, to catch wiring mistakes fast.

**Tests / verification**
- `tests/integration/test_api.py` (29 tests, Flask test client + seeded SQLite): every filter combination on `/events` (exchange, type, date range, release_codes incl. `surprise` field, invalid enum/date → 400, limit/offset, metadata hidden by default); `/events/<id>` hit + 404; `/events/upcoming` default/custom/invalid window; `/calendar/<y>/<m>` grouping, invalid month, empty month; `/exchanges` static list; `/alerts` empty/populated/limit; `/iv/...` 501-without-provider and 200-with-provider (incl. invalid date → 400); `/ingest/trigger` full run, single-source, unknown-source → 404, empty-body defaults, invalid date → 400.
- **Total 326 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (87 files) — required adding `-> ResponseReturnValue` (Flask's own type) to every route/error-handler function to satisfy strict mode.

**Decisions made** — see DECISIONS.md "API decisions": `create_app` takes explicit contract-typed kwargs (not the `wiring.Application`); IV endpoint uses 501 for "not configured"; static exchange list; shared ingest-trigger default range.

**Next step** — Phase 12: Dashboard (§5.7). Minimal static HTML/JS (no build step) served by Flask: calendar view, upcoming events, economic-releases table, alert feed — consumes the API only, zero business logic (deliberately the thinnest layer — if deleted, ingestion/storage/alerting keep working). Smoke test: pages render and issue the expected API calls.

---

## 2026-07-21 — Phase 12: Dashboard (§5.7) ✅

**Built** — `dashboard/` package (its `__init__.py` was missing since Phase 0's scaffolding loop didn't cover it — created now):
- `dashboard/static/index.html` — single self-contained page (inline CSS/JS, no build step, no CDN). Five tabbed views: **Calendar** (month grid, prev/next nav, color-coded event badges), **Upcoming** (next 14 days table), **Economic Releases** (release/forecast/previous/actual/surprise table), **Exchange status** (composite cards: next holiday + next expiry per exchange, fetched via existing `/events` filters), **Alert feed** (severity-badged table). Light/dark themes wired via `prefers-color-scheme` + a manual toggle (`data-theme`, persisted in `localStorage`). Colors drawn from the `dataviz` skill's validated reference palette (loaded before writing the page): 4 fixed categorical slots for event types, the reserved status palette for alert severity.
- `dashboard/server.py` — `bp` Blueprint, `GET /` serves the static file via `send_from_directory`. **No imports from any other `exchange_events` package** — enforced by a test, not just a docstring claim.
- **`api/app.py` deliberately untouched** — the dashboard is a peer of the API (§5.7), not wired into `create_app`; Phase 13's `serve` command will mount both blueprints on one Flask instance.

**Tests / verification**
- `tests/integration/test_dashboard.py` (4 tests): standalone serve returns the expected HTML; **AST-based static check** that `dashboard/server.py` imports nothing from `exchange_events.*` except itself (mechanical enforcement of "no business logic"); dashboard + a real `create_app()` API mounted together on one Flask app, both `/` and `/api/v1/exchanges` respond correctly; the dashboard's JS only references documented, real API paths (catches a typo'd endpoint before shipping).
- Manual boot check: rendered the page via a real Flask test client, confirmed byte size and key section markers present.
- **Total 330 passed, 18 skipped (PG), 5 deselected (contract).** `ruff` clean; `mypy` clean (89 files).

**Decisions made** — see DECISIONS.md "Dashboard decisions": API/dashboard stay decoupled peers; IV overlay view omitted (no provider in v1, `/iv` already 501s cleanly); AST-based no-business-logic test; palette usage per the dataviz skill.

**Next step** — Phase 13: Entry point + CLI (§5.3). `main.py`: `init-db` (create schema), `ingest [--source] [--from] [--to] [--incremental]` (calls `IngestionEngine`), `alert` (calls `AlertEngine.evaluate()` + `NotificationDispatcher.dispatch()`), `serve` (mounts API + dashboard blueprints, runs Flask). All built on `wiring.build_application()` + `config.load_config()`. Tests: CLI arg parsing, command smoke tests (each command runs end-to-end against a temp SQLite file).

---

## 2026-07-21 — Phase 13: Entry point + CLI (§5.3) ✅

**Built** — `main.py`, four subcommands over stdlib `argparse`, all built on `load_config()` + `build_application()`:
- `init-db` — constructs storage (which runs its own `CREATE TABLE IF NOT EXISTS` DDL), prints backend + path/dsn. Idempotent.
- `ingest [--source] [--from] [--to] [--incremental]` — defaults date range to `today..today+ingestion.default_range_days`; prints one line per source (fetched/normalized/errors/upserted/status) + a total; exits 1 if any source failed (visible to cron/an operator).
- `alert [--no-dispatch]` — evaluates rules, prints fired alerts, dispatches unless suppressed, prints delivery counts.
- `serve [--host] [--port] [--debug]` — mounts **both** the API blueprints and the dashboard blueprint on one `Flask()` instance (this is where the Phase-11/12 API↔dashboard decoupling gets bridged), CLI flags override `config.api.*` defaults; takes an injectable `run_server` seam (defaults to `Flask.run`) so it's testable without binding a socket.

**Manual verification (before writing the automated suite)** — ran the real CLI end-to-end: `init-db` created a real SQLite file; `ingest --source iana_tz --from 2026-01-01 --to 2026-12-31` fetched and stored **8 real 2026 DST transition records**; `alert` ran cleanly; `serve` (via the injectable seam) resolved correct host/port/debug from config. Also reinstalled the package and ran the **installed `exchange-events` console command directly** (not just `python -m`), confirming the `pyproject.toml` script entry actually works.

**Bug found and fixed** — `run_single_source`'s `ValueError` for an unknown `--source` name wasn't caught by `main()`'s top-level handler (which only catches `ExchangeEventsError`), so a typo'd source name crashed the CLI with a raw traceback. Fixed: `cmd_ingest` now catches `ValueError` explicitly and reports it cleanly with exit code 1.

**Tests / verification**
- `tests/unit/test_main_cli.py` (12 tests): `init-db` creates schema + is idempotent; `ingest --source iana_tz` (real offline DST computation) succeeds with correct output format; unknown `--source` → exit 1 cleanly (regression test for the bug above); date-range defaulting; `alert` with no events; `alert --no-dispatch` vs default-dispatch (seeding a real "tomorrow" expiry and confirming `ExpiryDayRule` fires and either does/doesn't dispatch); `serve` builds the full app and invokes the injected runner with correct config-derived and CLI-override host/port/debug; `main()` requires a subcommand / rejects an unknown one.
- `tests/contract/test_live_adapters.py` — added `test_cli_full_ingest_touches_every_adapter_over_real_network` (network-gated): full `ingest` with no `--source` over the real network, documenting the same mixed per-source outcome as the Phase-6 findings.
- **Total 342 passed, 18 skipped (PG), 6 deselected (contract).** `ruff` clean; `mypy` clean (90 files).

**Decisions made** — see DECISIONS.md "CLI decisions": argparse over a framework; full-run-is-live-network is correct but pushed the exhaustive full-run test to `@pytest.mark.contract`; `serve`'s injectable runner seam; the `ValueError` bug fix; console-script verified for real.

**Next step — Phase 14 (final phase): E2E, hardening, coverage, docs.** `tests/e2e/`: full pipeline over fixtures (ingest → SQLite → API query → alert eval → dispatch to fake channels), asserted end-to-end in one test. Coverage report (target ≥90% on domain/normalizers/engine/rules) via `pytest-cov`. Final `ruff`/`mypy` full-repo pass. `README.md` (install/run/test/deploy, including example crontab lines for `ingest`/`alert` per §5.3's "scheduling is external" design, and the CME/BSE/MarketWatch live-source caveats). Final `CLAUDE.md` status update marking all 15 phases complete.

---

## 2026-07-21 — Phase 14: E2E, hardening, coverage, docs ✅ — ALL 15 PHASES COMPLETE

**Built**
- `tests/e2e/test_full_pipeline.py` — the one true end-to-end test: a fake source adapter emitting realistic CME-shaped raw records → real `CMENormalizer` → real `SqliteEventRepository`/`SqliteAlertLog` → real Flask API (`create_app` + test client, querying `/events` and `/calendar`) → real `AlertEngine` + real `ExpiryDayRule`/`UpcomingHighPriorityReleaseRule` (confirms the expiry fires, dedup on re-evaluate, alert visible via `/alerts`) → real `NotificationDispatcher` + `RoutingConfig` → a fake terminal channel (asserts exact delivery). One flow, every real component except the outermost adapter and channel.
- **Coverage measured directly** (`pytest-cov`): domain 100%, normalizers 100%, ingestion 98%, alerting 99%, overall repo 96%. Closed a real gap in `normalizers/base.py` (the `None`-skip / list-expansion / bare-exception-capture branches of `BaseNormalizer` were never exercised by any production normalizer) with a small local `_ContractProbeNormalizer` test double — these are load-bearing shared-base behaviors, not incidental lines.
- **`README.md`** — install/configure/run/test instructions, the scheduling crontab example (ingestion engine is a plain callable per §5.3, not a scheduler), the full live-source-status table (NSE ✅ / CME ⚠️ blocked / BSE ⚠️ wrong endpoint / MarketWatch ⚠️ DataDome / FRED needs a key / IANA ✅ offline / KRX deferred), package layout, and the v1 scope boundaries (no IV provider, KRX stub).

**Final full-repo verification**
- `pytest` (default: unit+integration+e2e, contract excluded) → **347 passed, 18 skipped (Postgres), 6 deselected (contract)**.
- `ruff check src tests` → clean. `mypy src/exchange_events` (strict) → clean, 90 source files.
- Every phase from 0 through 14 has its own dedicated entry above in this log, plus a matching decisions block in `DECISIONS.md` — a new session can reconstruct the full rationale for every non-obvious choice without re-deriving it.

**Project status: COMPLETE.** All 15 planned phases delivered: domain model, contracts, fakes/infra, storage (SQLite + Postgres), normalizers, source adapters (CME live-first per the production priority, NSE live-validated, BSE/MarketWatch flagged with concrete next steps, KRX deferred by design, FRED/IANA live), ingestion engine, alert engine + 4 v1 rules, notification (Email + Teams + Dashboard), config + composition root, Flask API (all 8 §5.6 endpoints), static dashboard (5 views), CLI (`init-db`/`ingest`/`alert`/`serve`), and this final hardening pass. The three continuity documents (this log, DECISIONS.md, CLAUDE.md) are current as of this entry.

---

## 2026-07-21 — Post-delivery: dashboard restructure + concurrency bug fix (driven by actually running the app)

**Context:** after project completion, ran the app for real for the first time — seeded a demo SQLite DB, started `exchange-events serve`, screenshotted the dashboard. User then asked for the dashboard to be restructured: exchange-specific tabs (one per exchange) plus a "Consolidated View" tab holding the original all-exchanges layout.

**Built**
- Restructured `dashboard/static/index.html`: outer nav = Consolidated View + one dynamically-built tab per exchange (from `GET /api/v1/exchanges` — no code change needed if a 5th exchange is added later). Each exchange tab: status card, 14-day upcoming table, its own independent calendar month-nav, alerts table — all filtered to that exchange. Reused 100% of the existing API surface (no backend changes): `?exchanges=` query param for upcoming/status, client-side filtering by `event.exchange`/`alert.event.exchange` for calendar/alerts.

**Real bug found by driving the app (not by code review):** loading the new multi-tab dashboard triggered `sqlite3.InterfaceError: bad parameter or other API misuse` on several endpoints. Root cause: `Flask.run()` defaults to `threaded=True`, but `BaseSqlEventRepository`/`BaseSqlAlertLog` (built in Phase 4) each hold one shared connection with no locking — a **pre-existing bug**, just not concurrent-enough to reliably surface until the new dashboard pushed simultaneous DB access higher.
- **Fixed:** `threading.Lock` added around every connection-touching method in both classes (`src/exchange_events/storage/sql_repository.py`, `src/exchange_events/storage/alert_log.py`).
- **Regression test:** `tests/integration/test_repository_concurrency.py` — 16-thread × 25-round stress test against both classes, asserting zero exceptions + data integrity. Would have caught this before it ever reached a running server.
- **Verified live, twice:** once showing the bug (500s in the server log, "Error: HTTP 500" visible on-screen), once after the fix (zero errors, correct per-exchange filtering confirmed via Playwright driving the system `google-chrome` binary — clicked into the XCME and XNSE tabs and screenshotted real, correctly-isolated data for each).

**Tests / verification**
- New: `tests/integration/test_repository_concurrency.py` (2 tests). Existing `tests/integration/test_dashboard.py` (4 tests) still pass unmodified — the dashboard's "only calls documented API paths" and "no business-logic imports" checks still hold.
- **Full suite: 349 passed** (347 → 349), 18 skipped (PG), 6 deselected (contract). `ruff` clean, `mypy` clean.

**Decisions made** — full detail in DECISIONS.md "Post-delivery: dashboard restructure + a real concurrency bug found by driving the app".

---

## 2026-07-22 — Post-delivery: economic-release waterfall (FRED/BLS/BEA/ISM) + cross-source reconciliation ✅

**Context.** User asked to fetch CME data from MarketWatch's economic calendar; clarified it meant the general econ-calendar feature. Tried headless Chrome (Playwright + system `google-chrome`) against MarketWatch to see if real JS execution could beat the documented DataDome block — it could not: DataDome served an actual interactive CAPTCHA (`geo.captcha-delivery.com` iframe), not a JS puzzle. Did not attempt to script past it. Re-reading the requirement precisely ("add the data that was **released**") showed forecasts were never actually required — only realized/actual data for the 7 releases, which official APIs publish with no anti-bot wall at all. User then asked for a reliability-ranked waterfall (max 4 sources) instead, with ISM PMI (no free official source, per verified web search of FRED's 2016 ISM removal) handled best-effort.

**Built**
- **FRED** (`adapters/fred.py`) — added `JOLTS` (`JTSJOL`) and `FOMC` (`DFEDTARU`, the target-rate decision itself) to `DEFAULT_SERIES`; now covers 6/7 required releases. Series ids verified via web search against BLS/FRED's own docs, not guessed.
- **BLS** (`adapters/bls.py`, `BLSAdapter`) — tier 2, official backstop for NFP/CPI/PPI/JOLTS via the BLS v2 timeseries API; works unkeyed at a lower rate limit.
- **BEA** (`adapters/bea.py`, `BEAAdapter`) — tier 3, official backstop for PCE via the BEA NIPA API; table/line mapping flagged as needing confirmation before go-live (no key available here).
- **ISM** (`adapters/ism.py`, `ISMAdapter`) — best-effort only, fully provider-agnostic (config-driven URL + field-name mapping), degrades to `SourceUnavailableError` cleanly when unconfigured rather than blocking the other six.
- **`normalizers/government_release.py`** — new shared `GovernmentReleaseNormalizer` base (same pattern as `ExchangeCalendarNormalizer`); FRED/BLS/BEA/ISM normalizers are now thin subclasses.
- **`domain/reconciliation.py`** — `reconcile_economic_releases()`, a pure read-time merge of same-`(release_code, date)` events across sources, by priority (`fred_api > bls_api > bea_api > ism_pmi > econ_calendar`). Fixes duplicate dashboard rows *and* a latent bug where `EconomicSurpriseRule` could never fire under real multi-source ingestion. Wired into `api/routes/events.py`, `api/routes/calendar.py`, `alerting/engine.py::evaluate()`.
- Wiring: 3 new adapters/normalizers registered in `wiring.py`; new secrets (`BLS_API_KEY`, `BEA_API_KEY`, `ISM_API_KEY`, `ISM_URL`) in `config/loader.py`/`.env.example`.

**Real bug caught by the new tests before ever running live:** `BEAAdapter._parse_time_period` had an off-by-one length check against BEA's `"YYYYMM"`-style `TimePeriod` (7 chars, e.g. `"2026M06"`, not 6) — every BEA response would have silently produced zero events. Fixed.

**Tests / verification**
- `tests/unit/test_adapters.py` — BLS/BEA/ISM adapter tests + FRED 6/7-coverage check.
- `tests/unit/test_normalizers.py` — BLS/BEA/ISM `target_source()` + shared behavior.
- `tests/unit/test_reconciliation.py` (new, 14 tests) — merge semantics, priority, backfill, passthrough, custom priority, 3-way merge, metadata provenance.
- `tests/unit/test_alert_engine.py` — 2 new tests proving the cross-source surprise-rule bug is fixed and no duplicate alerts result.
- Fixed 2 pre-existing hardcoded adapter-name-set assertions to include the 3 new sources.
- **Total 385 passed** (349 → 385), 18 skipped (PG), 6 deselected (contract). `ruff` clean; `mypy` clean (98 files).

**Decisions made** — full detail in DECISIONS.md "Economic-release waterfall". MarketWatch's adapter is left exactly as built (still wired, still fixture-tested) but is no longer load-bearing for the required scope.

---

## 2026-07-22 — Post-delivery: `country` tagging for economic releases + CME-tab integration ✅

**Context.** User raised two points after seeing the Economic Releases tab: (1) the 7 required releases are all US-specific — other countries' exchanges (NSE/BSE/KRX) could have their own equivalents, so how should that be handled; (2) only 2 of 6 covered releases were visible in the demo (a seed-data gap, not a pipeline gap — confirmed via live API check, `adapters/fred.py`'s `DEFAULT_SERIES` already had all 6). Decision on (1): stay US-only for now (no India/Korea adapters), but associate US releases with the CME tab specifically — "any other exchange in the US will have this as well."

**Built**
- `domain/events.py` — added `country: str | None = None` to `EconomicReleaseEvent`.
- `domain/serialization.py` — serialize/deserialize `country`.
- `normalizers/government_release.py` (FRED/BLS/BEA/ISM shared base) + `normalizers/econ.py` (MarketWatch) — both default `country` to `"US"` (overridable via the raw record), since every current source is US-only.
- `domain/reconciliation.py` — added `country` to `_MERGE_FIELDS` so it survives cross-source merges (backfilled from a lower-priority source if the top-ranked one lacks it).
- `api/routes/calendar.py` — added a `"country"` field to each entry in `EXCHANGES` (XCME→US, XNSE/XBOM→IN, XKRX→KR). Adding a future US exchange here automatically gets the same association — no dashboard code change (P4), directly matching the user's "any other US exchange" framing.
- `dashboard/static/index.html` — each exchange tab now has an **"Economic Releases (‹country›)"** card, populated by fetching the existing `/events?event_types=economic_release` endpoint and filtering client-side by `e.country === ex.country` (no new backend query filter needed — same pattern already used for exchange-tab calendar/alerts). Also extended the exchange tab's Alerts filter to include economic-release alerts matching the exchange's country (previously such alerts could never appear on any exchange tab, since `EconomicReleaseEvent.exchange` is always `None`).
- Reseeded demo data (`seed_demo.py`, scratchpad-only) with all 6 releases (was missing PPI/PCE/JOLTS/FOMC) tagged `country="US"`.

**Tests / verification**
- `tests/unit/test_serialization.py`, `test_normalizers.py`, `test_reconciliation.py` — round-trip, default-to-`"US"` across all 5 economic normalizers, override-via-raw-record, merge preservation/backfill.
- **Total 394 passed** (385 → 394), 18 skipped (PG), 6 deselected (contract). `ruff` clean; `mypy` clean (98 files). `tests/integration/test_dashboard.py` (4 tests) still pass unmodified.
- **Verified live** via Playwright: XCME tab shows all 6 releases under "Economic Releases (United States)" plus the CPI-surprise alert; XNSE tab correctly shows "No releases for this country yet" / "No alerts for this exchange" — no cross-country leakage.

**Known minor cosmetic issue spotted (not fixed, not asked for):** the dashboard's Surprise column displays raw float subtraction artifacts (e.g. `0.2999999999999998` instead of `0.3`) — a pre-existing display-formatting gap, unrelated to this change.

---

## 2026-07-22 — Post-delivery: release-schedule adapter (FRED release/dates + FOMCScheduleAdapter) ✅

**Context.** User asked whether the release time could be added to the dashboard. Added it via a hardcoded `STANDARD_RELEASE_TIMES_ET` fallback — user immediately caught two real problems: (1) the dashboard displayed it in the *viewer's* browser-local timezone with no label (fixed: per-country timezone + hardcoded "ET"/"IST"/"KST" label, since `Intl`'s `timeZoneName: "short"` renders inconsistently — user's own browser showed "GMT-4" instead of "EDT" for verification); (2) more fundamentally, a static hardcoded time can't self-correct if a schedule shifts, and — bigger problem — FRED/BLS/BEA's APIs are backward-looking only, so **no active source could ever warn about an upcoming release before it happened at all**. User confirmed the pipeline's actual purpose ("know about upcoming releases... take trading decisions in advance") and chose to solve scheduling now, defer forecasts (separate, harder problem) to later.

**Research (real probes before any code):** BLS's own schedule page → 403 (blocked, same as CME). ISM's calendar page → redirects to a paid member login (confirmed, not assumed). Fed's FOMC calendar and BEA's schedule page → both reachable. **Key simplifying discovery:** FRED itself exposes `fred/release/dates` (separate from `series/observations`) which, per FRED's own docs, returns scheduled dates *before* data is published when `include_release_dates_with_no_data=true` — meaning NFP/CPI/PPI/PCE/JOLTS's forward schedule could go through the already-working `FREDAdapter`, with zero new anti-bot risk, no need to touch BLS or BEA's pages at all.

**Built**
- `adapters/fred.py` — `fetch()` now also resolves each series's `release_id` (`fred/series/release`) and fetches its forward schedule (`fred/release/dates`), adding schedule-only records for not-yet-published dates (never duplicating a date that already has real data). Best-effort per code (§7 isolation); new `fetch_schedule` config toggle.
- **FOMC deliberately excluded** from this generic path (`skip_schedule=True`): its FRED series (`DFEDTARU`) belongs to a *daily*-updating release, unrelated to the ~8/year meeting dates — would produce wrong, noisy schedule entries.
- `adapters/fomc.py` (new) — `FOMCScheduleAdapter`, parsing the Fed's own FOMC calendar page. Real page structure inspected directly via lxml (not guessed): year panels → meeting-row divs → month + day-range, with an authoritative Statement-link date once a meeting has happened. **Confirmed live that future meetings have no such link at all** — for those, computed the decision date from year + month + last day in the range. Verified against the real captured page: found all 8 real 2026 meetings correctly (4 via link, 4 computed).
- `normalizers/fomc.py` — `FOMCScheduleNormalizer`, thin subclass of the shared `GovernmentReleaseNormalizer` base.
- `domain/reconciliation.py` — added `fomc_schedule` to `DEFAULT_SOURCE_PRIORITY`.
- Wired into `wiring.py`, `config/defaults.toml`; no new secrets needed (FOMC page needs no key).

**Confirmed this actually fixes the real problem:** `UpcomingHighPriorityReleaseRule` only ever needed `release_code` + `date` — never `forecast`/`actual`. Before this, no active source produced a future-dated event at all, so the rule (already built, already wired) could never fire outside hand-seeded demo data. New regression test proves a bare schedule-only event is now sufficient.

**Tests / verification**
- `tests/unit/test_adapters.py`: FRED schedule-fetch (future-date addition, no duplication, best-effort failure isolation, config toggle, FOMC exclusion) + FOMC adapter (past-via-link, future-computed, single-day "notation vote" format, date-range filtering, end-to-end through normalizer).
- `tests/unit/test_alert_engine.py::test_upcoming_release_rule_fires_from_a_schedule_only_event` — the actual proof.
- Fixed 3 pre-existing hardcoded assertions (adapter-name sets in `test_config.py`/`test_wiring.py`, priority tuple in `test_reconciliation.py`) to include the new source.
- **Total 417 passed** (409 → 417), 18 skipped (PG), 6 deselected (contract). `ruff` clean; `mypy` clean (100 files).

**Decisions made** — full detail in DECISIONS.md "Dashboard timestamp_utc display..." and "Release-schedule adapter" entries. Forecasts remain explicitly out of scope for this pass, per the user's own choice.

---

## 2026-07-22 — Post-delivery: real-data verification finds and fixes a genuine BLS bug ✅

**Context.** User asked directly: is the dashboard showing real data or demo data? It was 100% demo — `seed_demo.py` (scratchpad-only) hand-inserts made-up numbers, never touching any adapter. Answered honestly, then ran real `exchange-events ingest` against a fresh SQLite db for every zero-configuration source to actually show real data.

**Real bug found (not a network block):** `bls_api` crashed with `'NoneType' object has no attribute 'get'`. Root cause confirmed via direct `curl` against BLS's live v2 API: comma-joining 2+ series ids in a GET URL path (the adapter's default behavior — it always requests all 4 configured series at once) returns `{"status":"REQUEST_FAILED","Results":null}`, and `_parse`'s `.get("Results", {})` doesn't guard against an explicit `null` value. Existing unit tests never caught this because every one of them narrowed `options={"series": {...}}` down to a single series, never exercising the real multi-series default.

**Fixed:**
- `adapters/bls.py` — switched to POST with a JSON `seriesid` array (BLS's documented way to query multiple series; confirmed live it also works for one), added an explicit check on the response's own `status` field so a real API-side failure raises `SourceUnavailableError` with BLS's message instead of crashing.
- `adapters/base.py` — new `_post_json` helper on `HttpSourceAdapter`, alongside the existing `_get_json`/`_get_text`.
- `domain/events.py::EconomicReleaseEvent.surprise` — rounded to 6 decimals; was leaking float-subtraction artifacts (`0.2999999999999998`) into the dashboard's Surprise column, spotted earlier but not yet fixed.

**Verified live, not fabricated:** fresh db + real ingestion — `iana_tz` (8 DST events), `nse_circular` (64 real holiday records), `fomc_schedule` (all 8 real 2026 FOMC dates), `bls_api` post-fix (23 real CPI/NFP/PPI/JOLTS observations, Jan–Jun 2026, correctly increasing month over month). Confirmed the already-documented failures are still exactly as described: `cme_calendar` 403, `bse_circular` HTTP 200 with non-JSON garbage (real broken endpoint), `fred_api`/`bea_api` correctly refuse without their keys, `ism_pmi` correctly refuses (no provider), `econ_calendar` 401 (DataDome). Screenshotted the served dashboard via Playwright against this real database — XCME tab's calendar and Economic Releases table show the genuine values.

**Tests / verification**
- `tests/unit/test_adapters.py` — 2 new tests (multi-series POST regression, API-failure-status regression) + 4 existing BLS tests updated to the POST contract.
- **Total 419 passed** (417 → 419), 18 skipped (PG), 6 deselected (contract). `ruff` clean; `mypy` clean (100 files).

**Full detail in DECISIONS.md "BLS multi-series bug found via real live ingestion, not a demo".** Remaining real-data gaps unchanged: FRED/BEA need API keys not available in this sandbox, ISM has no configured provider, CME is IP-blocked here, BSE's endpoint needs a real URL from devtools.

---

## 2026-07-22 — Post-delivery: CME unblocked via its real Reference Data API v3 (OAuth) ✅

**Context.** User asked directly what it would take to get CME working, given the dashboard's XCME tab showed "None scheduled" for both next holiday and next expiry — a direct consequence of the already-documented CME IP-reputation block. Investigated whether CME had a free-key option like FRED before assuming a paid vendor relationship was required.

**Found and used a genuine free official path:** CME's **Reference Data API v3** (`refdata.api.cmegroup.com`) — distinct from their paid real-time market-data feeds, confirmed free via CME's own public statements. Access requires a CME Group Customer Center account (with phone-verified MFA) and an OAuth "API ID", both of which the user created themselves; no separate entitlement approval needed for plain Futures & Options data. Confirmed this infrastructure is **not** behind the same anti-scraping WAF as `cmegroup.com` — reachable from this sandbox, real OAuth tokens obtained, real data returned.

**Own debugging note:** early `invalid_client` failures were caused by testing via bash's `source .env`, which silently mangled the secret (contains `$`/`#`, both shell-special characters when unquoted) — not by bad credentials. Fixed by reading `.env` as plain text in Python for testing, never as a sourced shell script.

**Built:**
- `adapters/cme.py` — full rewrite. OAuth client-credentials token fetch; expiries via `/products` (resolve `productGuid`) → paginated `/instruments` (real symbols, `lastTradeDate`, client-side date-range filtering since the API's own date-filter params rejected every format tried); holidays via **gap analysis** of `/tradingSchedules` — CME's API has no holiday flag, so a full closure is derived as a calendar date being entirely absent from the schedule, verified against a real known holiday (Labor Day 2026-09-07) before trusting the approach, and clamped to the schedule's own actual coverage window to avoid false positives outside it.
- `adapters/base.py` — new `_post_form` helper (form-urlencoded POST + optional HTTP Basic auth header, built manually since `HttpClient` has no `auth=` param).
- `config/loader.py` — wired `CME_API_ID`/`CME_API_SECRET` (secret lives in `AdapterConfig.options["api_secret"]`, additive, no schema change).
- `tests/fakes/http.py` — added `register_json_sequence` for queued per-call responses (needed for a real pagination test; the fake routes by URL only, not params).

**Verified live, not fabricated:** a real ingest run derived all 9 real 2026 US market holidays correctly (New Year's, MLK Day, Presidents Day, Memorial Day, Juneteenth, July 4th observed, Labor Day, Thanksgiving, Christmas) purely from schedule gaps, plus 4 real upcoming ES/NQ quarterly expiries (ESU6/NQU6 Sept, ESZ6/NQZ6 Dec). Dashboard screenshot confirms the XCME tab now shows "Next holiday: 2026-09-07" and "Next expiry: 2026-09-18 — ES" instead of "None scheduled".

**Tests / verification**
- `tests/unit/test_adapters.py` — 10 CME tests rewritten for the new OAuth flow (metadata, missing-credentials, Basic-auth request shape, holiday gap-derivation, coverage clamping, expiry pagination + filtering, no-match skip, full normalizer round-trip, 401/429 mapping).
- `tests/contract/test_live_adapters.py` — CME's live test now `skipif`s on missing credentials (matching FRED's pattern) rather than expecting an xfail.
- **Total 424 passed** (419 → 424), 18 skipped (PG), 6 deselected (contract). `ruff` clean; `mypy` clean (100 files).

**Full detail in DECISIONS.md "CME Reference Data API — replacing the blocked CmeWS/mvc endpoints".** Remaining gaps unchanged: BSE's endpoint still needs a real URL from devtools, MarketWatch/econ_calendar remains DataDome-blocked (forecasts only, out of scope), ISM PMI has no configured provider.

---

## 2026-07-22 — Post-delivery: dashboard timezone-shift block, then CME expansion (2 rounds) ✅

**Round 1 — timezone shift, in its own block.** User asked what timezone CME operates in and when the next shift happens, then asked for it added to the dashboard as a clearly-separated, important block (not buried in an existing card). Confirmed `America/Chicago` was already tracked by the existing `iana_tz` source (no new adapter needed) — next real 2026 shift: 2026-11-01, DST ends, UTC-5→UTC-6. Added `timezone` to each exchange's metadata in `api/routes/calendar.py`; built a `nextDstShiftInfo()` dashboard helper mapping known zones to named abbreviations (CST/CDT, EST/EDT, GMT/BST, CET/CEST) instead of raw UTC offsets, since "UTC-5 → UTC-6" is easy to misread which direction is which; added a new amber-bordered "Next Timezone Shift" card (`.tz-card`) to both the per-exchange tab and the Consolidated "Exchanges" grid.

**Round 2 — CME dashboard expansion.** With CME's Reference Data API now live, user asked for three more things: (1) put "Next Holiday" in its own block too, with a full-list toggle; (2) expand expiry coverage beyond ES/NQ, letting the user pick an underlying; (3) fix the CME calendar, which was silently showing only holidays, never economic releases together with them, plus add hover tooltips on calendar events.

Confirmed live, per-product, the real venue each new underlying actually trades on before hardcoding anything: YM/ZN/ZB are CBOT (`XCBT`), CL/NG are NYMEX (`XNYM`), GC/SI are COMEX (`XCEC`) — only ES/NQ/RTY/6E are true CME (`XCME`). Per the user's explicit choice, kept everything under the single existing "XCME"/"CME Group" tab rather than splitting into per-venue tabs — `DEFAULT_PRODUCTS` in `adapters/cme.py` now carries an `exchange_globex` per entry used only to query the correct venue internally.

**Built:**
- "Next Holiday" — its own card (was folded into the old "Status" card), with a "Show all" toggle revealing every holiday in a table.
- "Expiry Lookup" — a dropdown built dynamically from whatever underlyings are actually in the ingested data (not hardcoded — a config change alone surfaces a new product, no dashboard change needed), defaulting to the soonest upcoming expiry, showing the real contract symbol (e.g. "GCN6") and a "Show all" toggle for that underlying's full list.
- Calendar fix — the per-exchange filter matched only `e.exchange === filterMic`, which silently dropped every economic-release event (they only carry a `country`, never an `exchange` — the same non-obvious fact already hit once before for the Releases card/Alerts filter, missed here since the calendar was built earlier). Fixed by also matching `economic_release` events against the exchange's own country.
- Hover tooltips on every calendar badge, via the already-existing `eventDescription()` helper, just never wired to the calendar before.

**Verified live:** re-ingested `cme_calendar` with all 11 products over a 2-year window — 123 real expiry records across all products, 19 real derived holidays. Screenshots confirm: Gold's full expiry list (GCN6 → GCZ7, 18 real contracts); all 19 real 2026–2027 holidays via the "Show all" toggle; the CME calendar now showing Econ. Release + Expiry + Holiday badges together (previously holiday-only); tooltip `title` attributes present, confirmed via direct DOM inspection.

**Tests / verification**
- `tests/unit/test_adapters.py` — added `test_cme_fetch_expiries_queries_each_products_own_real_venue` (regression proving the per-product exchange_globex is actually sent, using YM/XCBT).
- **Total 425 passed** (424 → 425), 18 skipped (PG), 6 deselected (contract). `ruff` clean; `mypy` clean (100 files). Dashboard-only pieces (new blocks, calendar fix, tooltips) need no backend test changes — none of it touches Python.

**Full detail in DECISIONS.md's "CME dashboard expansion" entry.** Remaining gaps unchanged: BSE's endpoint still needs a real URL, MarketWatch/econ_calendar remains DataDome-blocked, ISM PMI has no configured provider.

---

## 2026-07-22 — Post-delivery: per-exchange tab as a one-look summary ✅

Immediately following the CME expansion above, a further cleanup pass, framed by the user around one idea: the calendar should answer "do I even need to look at the rest of the dashboard today" — lean and decision-relevant, not a full data dump, and the first thing seen.

**Removed:** the per-exchange "Upcoming (next 14 days)" card — redundant with alerts, per the user's own reasoning. Scoped to the per-exchange tab only; Consolidated View's separate "Upcoming" nav tab was explicitly kept.

**Moved:** the calendar to the top of the per-exchange tab.

**Narrowed the calendar's content** to exactly: holidays, this exchange's own DST shifts (a genuine gap fix — `dst_change` events were never shown on *any* calendar before, since they carry an `iana_zone` not an `exchange`, same class of miss as the earlier economic-release gap), ES/NQ expiries only (not all 11 products now configured), and the 7 core economic releases (excluding the bonus GDP/Unemployment/Fed-Funds indicators). Added the calendar's own Upcoming/All-dates toggle, defaulting to Upcoming.

**Fixed hover tooltips** that weren't visibly working — the native `title` attribute's ~1s delay and minimal styling made it easy to miss entirely; replaced with an instant CSS-only tooltip.

**Changed defaults:** both "Latest/All" release toggles (Economic Releases + Additional Indicators, both views) now default to Latest instead of All, per explicit request.

**Verified live** via screenshots: Upcoming-only calendar showing just the two remaining core-release dates for the rest of the month; "All dates" revealing full history including a past holiday; tooltip appearing instantly with the real event description; both release tables opening on Latest by default.

**Tests:** dashboard-only (HTML/CSS/JS), no backend touched. All 425 tests still pass, `ruff`/`mypy` clean. Full detail in DECISIONS.md's "Per-exchange tab: calendar as the one-look summary" entry.

## 2026-07-22 — Post-delivery: alerts box "show next N days" filter

Added a numeric "Show next N days" input to the Alerts box (Consolidated View
+ every per-exchange tab), defaulting to 1 — a display-only client-side
filter over the already-fetched alert list (`today <= event.date <= today +
N`), same fetch-once/cache/re-render pattern as the calendar and releases
toggles. Reintroduced `addDaysISO(days)` (deleted earlier alongside the old
"Upcoming (14 days)" card) for this new real use. No backend change; all 425
tests still pass.

## 2026-07-22 — Post-delivery: proximity-based alert severity redesign

Before wiring real Email/Teams notification delivery, the user asked to
finalize the alert engine's severity model, since it determines what actually
gets emailed. Two things came out of that conversation:

1. A real finding: the old `RevisedExpiryRule` (fires on `is_revised`) can
   **never fire for CME** — CME's Reference Data API has no "this date was
   revised" flag, unlike NSE/BSE's raw circulars. User chose to drop it
   entirely (and `EconomicSurpriseRule`, which also never fires in live
   operation — no forecast data is ingested from any live source) rather than
   keep dead rules alongside a new model.
2. A complete replacement taxonomy, specified directly by the user: all 4
   event categories (holiday/DST/expiry/economic release) get a pure
   days-until-event severity classifier (INFO -> WARNING -> CRITICAL), with
   holiday always flat INFO and expiry having no CRITICAL tier. One alert
   *record* per event, escalating in place over time — Teams/email fire only
   on the moment of crossing into WARNING/CRITICAL, never repeatedly.

**Core change enabling "escalates in place":** `alert_id` dropped its
`trigger_date` component (`domain/ids.py`) so the same (rule, event) pair
maps to one stable id forever, not just within a calendar day.
`AlertLog.has_fired`/`record` became `get`/`upsert` (real
`ON CONFLICT DO UPDATE`, not `DO NOTHING`); `AlertEngine.evaluate()` now
compares each candidate's severity against the alert log's stored value and
only returns strict escalations (past INFO) for notification, while always
upserting the freshly classified row so displayed text/severity never goes
stale.

Four new rule classes (`HolidayProximityRule`, `DstShiftProximityRule`,
`ExpiryProximityRule`, `EconomicReleaseProximityRule`) replace the old four.
The economic-release rule stays scoped to the existing `CORE_RELEASE_CODES`
(7 required releases) — including FRED's extra daily-updating series like
`FEDFUNDS` would otherwise sit permanently at WARNING/CRITICAL. Config's
`AlertingConfig` fields replaced accordingly; default `lookahead_days` widened
7 -> 30 so far-out events get an INFO row well before needing to escalate;
notification routing simplified to severity-only (no more per-event-type
carve-out on the CRITICAL route).

**Verified live:** cleared stale in-session test rows from the dev SQLite
alert log, ran `AlertEngine.evaluate()` twice via the real wired app against
real CME/FRED/BLS/NSE/IANA data. First run: 13 real INFO alerts, 0 escalated
(correct — nothing is currently within 1-2 days of anything real). Second
run: same 13 rows, 0 newly escalated — confirms idempotent re-evaluation,
no duplicate rows, no re-notification. Confirmed via the live API that the
dashboard's existing (previously unused) `badge-info` CSS renders correctly.

**Tests:** rewrote `test_alert_rules.py` and `test_alert_engine.py` for the
new classifiers and escalation semantics; updated `test_alert_log.py`,
`test_fakes.py`, `test_wiring.py`, `test_ids.py`, `test_alerts.py`,
`test_api.py`, `test_repository_concurrency.py`, and the e2e test. **434
passed** (425 -> 434), 19 skipped (PG), 6 deselected (contract), `ruff`/
`mypy` clean across 100 source files. Full detail in DECISIONS.md's
"Proximity-based alert severity" entry.

**Not yet done:** real Email/Teams credentials — the original ask for this
session, paused to finish this redesign first. Next: Gmail SMTP app password
+ Teams Incoming Webhook URL into `.env`, then verify one real delivery of
each.

## 2026-07-22 — Post-delivery: expiry alerts scoped to ES/NQ only

`ExpiryProximityRule` gained an `underlyings` allow-list parameter
(`ALERT_EXPIRY_UNDERLYINGS`, defaults to `{"ES", "NQ"}`) — mirrors
`EconomicReleaseProximityRule`'s `CORE_RELEASE_CODES` pattern and the
dashboard's own `CALENDAR_EXPIRY_UNDERLYINGS`, at the user's explicit request
to only alert on ES/NQ rather than all 11 configured CME products. Both
exported from `alerting/rules/__init__.py`. Cleared stale non-ES/NQ expiry
alert rows (CL/NG/GC/SI/6E) from both dev databases that predated this
filter. 437 tests pass (434 -> 437), ruff/mypy clean.

## 2026-07-22 — Post-delivery: notification content cleanup + exchange/country attribution

Two rounds of polish on the alert content itself, at the user's request, once
real Email/Teams delivery was confirmed working:

1. **Removed redundancy between title and body.** Every rule's title/body
   used to repeat the same facts (e.g. holiday name + exchange in both).
   Redesigned so title carries the complete "what + when" in one line, and
   body adds only genuinely new supplementary detail (agency for releases,
   instrument type + real contract symbol for expiries, IANA zone for DST
   shifts, session type + affected segments for holidays) — omitted entirely
   when there's nothing to add. `TeamsChannel._build_card` also dropped the
   internal `rule_id` fact (meaningless plumbing to a reader) and reformatted
   the timestamp from a raw ISO string to `YYYY-MM-DD HH:MM UTC`, relabeled
   "Triggered" -> "Updated".
2. **Added exchange/country attribution per the user's explicit mapping**:
   holiday and DST-shift alerts are exchange-specific, expiry is
   underlying-specific (already present), economic release is
   country-specific. Holiday/expiry already carried this; DST and economic
   release didn't. Economic release's title now includes `event.country`.
   DST is trickier: `DSTChangeEvent` has no `exchange` field at all (only
   `iana_zone`) — new `domain/exchange_zones.py` (`EXCHANGE_TIMEZONES` +
   `exchanges_for_zone()`) resolves a zone back to its configured exchange
   MIC(s) for the title (e.g. "America/Chicago" -> "XCME"), duplicating (not
   importing) `api/routes/calendar.py`'s `EXCHANGES` list since `alerting/`
   must never import from `api/` (dependencies point inward). Falls back to
   the raw zone name for a tracked zone with no configured exchange.

**Verified live:** cleared and re-ran `alert` against both dev databases;
confirmed titles now read e.g. "Producer Price Index (PPI, US) in 22 day(s)
(2026-08-13)" and "Independence Day — XNSE on 2026-08-15" with non-redundant
bodies. Sent a real forced-CRITICAL test alert through both Email and Teams
with the new formatting; user confirmed receipt.

**Tests:** 446 passed (439 -> 446) — new `test_exchange_zones.py`, DST/
release title-content tests, Teams-card omission tests. `ruff`/`mypy` clean
across 101 source files (new `domain/exchange_zones.py`).

## 2026-07-22 — Post-delivery: DST abbreviations, expiry exchange, and a real include_metadata bug

Two content fixes plus one genuine bug found while making them:

1. **Expiry alerts now include the exchange** (`ExpiryProximityRule` title:
   `"ES (XCME) quarterly expiry in N day(s) (date)"`) — underlying alone
   doesn't uniquely identify the venue in general, since CME Group spans 4
   real exchanges.
2. **DST alerts show named abbreviations** ("CDT -> CST") instead of raw UTC
   offsets, matching the dashboard's own "Next Timezone Shift" block — new
   `ZONE_ABBR` map + `dst_transition_label()` in `domain/exchange_zones.py`,
   using the DST event's `metadata["transition"]` to pick direction.
3. **Real bug found in the process:** `AlertEngine.evaluate()`'s internal
   event query never set `include_metadata=True`, so `EventQuery`'s
   lean-JSON-for-the-API default (`include_metadata=False`) was silently
   stripping every event's `metadata` dict before any rule saw it — invisible
   until DstShiftProximityRule finally needed to read
   `metadata["transition"]` for something real. Fixed with one line + a
   regression test proving metadata now survives the engine's query.

**Verified live:** confirmed the real America/Chicago DST event's metadata
was empty before the fix, populated after; sent a corrected test alert
through both Email and Teams reading "XCME timezone shift in 101 day(s): CDT
-> CST (2026-11-01)" and confirmed delivery.

Also: the scratchpad dev database/config used for one of the two live test
servers (port 8766) was wiped by an environment reset mid-session — recreated
the config, re-ingested real CME/FRED/BLS/NSE/IANA data, and re-ran `alert`
to restore it; both dev servers (8099, 8766) now running current code again.

**Tests:** 453 passed (446 -> 453) — new regression test for the metadata
bug, `test_exchange_zones.py` additions, expiry/DST title tests. `ruff`/
`mypy` clean across 102 source files. Full detail in DECISIONS.md's "DST
alert content: named abbreviations + a real metadata-stripping bug found"
entry.
