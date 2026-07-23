# CLAUDE.md — Exchange Events Pipeline

> **Living project guide.** Loaded every session. Always reflects the true current state.
> If you are a new session picking this up: read **§ Resume Here** first, then the
> current phase in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md), then
> the latest entry in [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md).

---

## Resume Here 👈

**PROJECT COMPLETE — all 15 planned phases delivered, plus fifteen post-delivery rounds.**
453 tests pass (unit + integration + e2e, fully offline), 19 skip cleanly without
Postgres, 6 live-network contract tests are opt-in (`pytest -m contract`). `ruff` and
`mypy --strict` are clean across all 100 source files. See [README.md](README.md) for
the user-facing install/run/test/deploy guide (this file stays the internal
continuity/build-history guide).

**Post-delivery update 1 (2026-07-21):** dashboard restructured into exchange-specific
tabs (dynamically built from `/api/v1/exchanges`) + a "Consolidated View" tab holding
the original layout. Driving the real app this way surfaced and fixed a genuine
pre-existing concurrency bug: `Flask.run()` defaults to `threaded=True`, but the SQL
repository/alert-log held one shared connection with no locking →
`sqlite3.InterfaceError` under concurrent load. Fixed with a `threading.Lock`; see
DECISIONS.md's "Post-delivery: dashboard restructure..." entry and the regression test
(`tests/integration/test_repository_concurrency.py`).

**Post-delivery update 2 (2026-07-22):** economic-release data now comes from a
**4-source waterfall** — FRED (tier 1, 6/7 releases) → BLS (tier 2, official backstop
for NFP/CPI/PPI/JOLTS) → BEA (tier 3, official backstop for PCE) → ISM (best-effort,
PMI only, no free official source exists). All four are official/free APIs with no
anti-bot wall — replacing a plan to scrape MarketWatch, which turned out to be
CAPTCHA-blocked (DataDome) *and* unnecessary, since the requirement only calls for
*released* (actual) data, never forecasts. New `domain/reconciliation.py` merges
same-`(release_code, date)` events across sources at read time (API + alert engine),
fixing both duplicate dashboard rows and a latent bug where `EconomicSurpriseRule`
could never fire under real multi-source ingestion. Full detail in DECISIONS.md's
"Economic-release waterfall" entry.

**Post-delivery update 3 (2026-07-22):** `EconomicReleaseEvent` gained a `country`
field (defaults to `"US"` — every current source is US-only), and each exchange in
`api/routes/calendar.py`'s `EXCHANGES` now carries a `"country"` code. Each exchange
tab shows an "Economic Releases (‹country›)" card filtered to that country (US
releases now show under CME), and the exchange-tab Alerts filter includes
economic-release alerts matching the country too. A future US exchange gets this
automatically — no dashboard code change (P4). Full detail in DECISIONS.md's
"Economic-release `country` tagging" entry.

**Post-delivery update 4 (2026-07-22):** the pipeline can now warn about economic
releases **before they happen**, not just show what already occurred — the actual
gap behind "know about upcoming releases... take trading decisions in advance."
Previously, FRED/BLS/BEA's APIs were confirmed backward-looking only (they never
return a not-yet-published date), so `UpcomingHighPriorityReleaseRule` could never
fire in live operation. Fixed via `FREDAdapter` calling FRED's own
`fred/release/dates` (covers NFP/CPI/PPI/PCE/JOLTS) plus a new
`FOMCScheduleAdapter` parsing the Fed's own FOMC calendar page directly (FOMC's
FRED series updates daily, unrelated to specific meeting dates — needed its own
source). Both verified against real reachability/page-structure checks, not
assumed — BLS's own schedule page is blocked here (403, same as CME) and ISM's
redirects to a paid login. Also fixed the dashboard's release-time display: it
was silently rendering in the *viewer's* browser-local timezone with no label;
now shows each release in its own market's timezone with a hardcoded "ET" label
(browser `Intl` timezone-name rendering proved inconsistent — confirmed live).
Full detail in DECISIONS.md's "Release-schedule adapter" entry. **Forecasts
remain explicitly out of scope** (separate, harder problem — no verified free
source), per the user's own scope choice.

**Post-delivery update 5 (2026-07-22):** user asked directly whether the running
demo dashboard showed real data — it didn't; every number came from a hand-written
`seed_demo.py` script that never touched an adapter. Ran real `exchange-events ingest`
against a fresh database for every source needing zero configuration, which surfaced
a genuine bug: `BLSAdapter` built one GET request with all series ids comma-joined in
the URL path, which BLS's live v2 API rejects for 2+ series (`REQUEST_FAILED`,
`Results: null`) — invisible in unit tests because every one of them narrowed to a
single series. Fixed by switching to POST with a JSON `seriesid` array (BLS's
documented multi-series method, confirmed live to also work for one series), plus a
new explicit check on the response's own `status` field. Also fixed
`EconomicReleaseEvent.surprise` leaking float-subtraction artifacts
(`0.2999999999999998`) into the dashboard — now rounded to 6 decimals. Verified live:
`iana_tz`, `nse_circular`, `fomc_schedule`, and post-fix `bls_api` all returned
genuinely real 2026 data end-to-end into a fresh SQLite db, screenshotted via
Playwright. Full detail in DECISIONS.md's "BLS multi-series bug found via real live
ingestion, not a demo" entry.

**Post-delivery update 6 (2026-07-22):** dashboard-only change, no backend logic
touched. The Economic Releases table (Consolidated View + every exchange tab)
now has two independent toggles instead of one flat list: **Upcoming/All dates**
(filters by date, defaults to upcoming-only) and **Latest/All** (collapses each
release code to the single row closest to today — fixes a real flood problem
once FRED's daily-updating series, e.g. FOMC's `DFEDTARU` and the bonus
`FEDFUNDS`, are ingested: hundreds of daily rows under one code instead of one
current value). GDP/Unemployment Rate/Fed Funds Effective Rate — extra series
FRED happens to carry beyond the 7 releases actually asked for — moved to a
separate, collapsed-by-default "Additional Indicators" card with the same two
toggles, per the user's explicit choice to keep them rather than remove them.

**Post-delivery update 7 (2026-07-22):** CME is no longer blocked. User asked
directly what it would take to fix the XCME tab showing "None scheduled" for
both next holiday and next expiry, and — rather than assuming a paid
data-vendor relationship was the only option — found CME has its own genuinely
free, officially documented **Reference Data API v3**
(`refdata.api.cmegroup.com`), separate infrastructure from the blocked public
website, confirmed reachable from this sandbox. The user created a CME Group
Customer Center account and OAuth API ID themselves (needed only for that
account-creation step); `adapters/cme.py` was fully rewritten against the real
API — expiries via `/products` → paginated `/instruments` (real contract
symbols, e.g. "ESU6"), holidays via **gap analysis** of `/tradingSchedules`
(CME's API has no holiday flag; a closure is derived as a calendar date being
entirely absent from the schedule — verified against real Labor Day 2026-09-07
data before trusting the approach). Verified live end-to-end: all 9 real 2026
US market holidays derived correctly with zero hardcoded holiday list, plus 4
real upcoming ES/NQ quarterly expiries; dashboard screenshot confirms the XCME
tab now shows real dates instead of "None scheduled". Full detail in
DECISIONS.md's "CME Reference Data API — replacing the blocked CmeWS/mvc
endpoints" entry.

**Post-delivery update 8 (2026-07-22):** dashboard gained a "Next Timezone Shift"
block — CME's DST transitions (`America/Chicago`) matter for any strategy whose
session-time parameters depend on the exchange's own clock, not the viewer's.
Confirmed `America/Chicago` was already tracked by the existing `iana_tz`
source, no new adapter needed. Each exchange's IANA zone is now in
`api/routes/exchanges` metadata; the dashboard shows the next shift with named
abbreviations (e.g. "CDT → CST") instead of raw UTC offsets, which are easy to
misread for direction, in its own visually distinct amber-bordered block —
not just another line in an existing card, per the user's explicit ask.

**Post-delivery update 9 (2026-07-22):** with CME's Reference Data API live,
expanded expiry coverage from ES/NQ to 11 products (adding YM, RTY, ZN, ZB, CL,
NG, GC, SI, 6E) — confirmed each product's *real* underlying venue live before
hardcoding anything (CME Group spans four real exchanges: CME/CBOT/NYMEX/COMEX
— e.g. YM actually trades on CBOT, not CME itself). Per the user's explicit
choice, all of it still shows under the single existing "XCME"/"CME Group" tab
rather than splitting into per-venue tabs. Also: "Next Holiday" got its own
block (was folded into a generic "Status" card) with a "Show all" toggle; a new
"Expiry Lookup" block lets the user pick any underlying (built dynamically from
whatever's actually in the ingested data, so a config change alone surfaces a
new product) and shows its real contract symbol (e.g. "GCN6") plus a full list
toggle; and the per-exchange calendar was fixed — it was silently showing only
holidays because its filter matched `exchange` directly, and economic-release
events only ever carry a `country` (the same non-obvious gap already hit once
for the Releases card, missed here since the calendar predated that fix).
Calendar badges now also carry hover tooltips describing the actual event.
Full detail in DECISIONS.md's "CME dashboard expansion" entry.

**Post-delivery update 10 (2026-07-22):** per-exchange tab cleaned up around one
idea — the calendar should be a one-look "do I even need to look at the rest of
this today" summary. Removed the redundant "Upcoming (next 14 days)" card
(alerts already cover this), moved the calendar to the top of the tab, and
narrowed its content to holidays, this exchange's own DST shifts (a real gap
fix — `dst_change` events were never shown on any calendar before, since they
carry an `iana_zone` not an `exchange`), ES/NQ expiries only (not all 11 now-
configured products), and the 7 core economic releases. Added the calendar's
own Upcoming/All-dates toggle (defaults to Upcoming), fixed hover tooltips that
weren't visibly working (native `title` attribute's ~1s delay replaced with an
instant CSS tooltip), and flipped both "Latest/All" release toggles to default
to Latest. Full detail in DECISIONS.md's "Per-exchange tab: calendar as the
one-look summary" entry.

**Post-delivery update 11 (2026-07-22):** Alerts box gained a "Show next N
days" numeric input (default 1), Consolidated View + every per-exchange tab —
a client-side display filter over the already-fetched alert list
(`today <= event.date <= today + N`), same fetch-once/cache/re-render pattern
as the calendar/releases toggles. No backend change.

**Post-delivery update 12 (2026-07-22):** the alert engine's severity model
was rebuilt from scratch, at the user's direction, before wiring real Email/
Teams delivery (since severity decides notification content). Surfaced a real
finding first: `RevisedExpiryRule` (the old `is_revised`-based CRITICAL
trigger) can **never fire for CME** — CME's Reference Data API has no
"this date was revised" flag, unlike NSE/BSE's raw circulars — so the user
chose to drop it, along with `EconomicSurpriseRule` (which also never fires
live — no forecast data is ingested from any source), rather than keep dead
rules. Replaced with a **pure proximity classifier per event category**,
specified directly by the user: holiday is always INFO; DST shift and
economic release are INFO / WARNING (within 2 days) / CRITICAL (within 1
day); expiry is INFO / WARNING (within 2 days), no CRITICAL tier. Teams gets
WARNING+CRITICAL, email gets CRITICAL only (unchanged).

The bigger structural change: **one alert record per event, escalating in
place over time**, instead of a fresh alert on every pipeline run. This
required dropping `trigger_date` from `alert_id` (`domain/ids.py`) so the
same (rule, event) pair maps to a stable id forever; `AlertLog.has_fired`/
`record` became `get`/`upsert` (real `ON CONFLICT DO UPDATE`); `AlertEngine.
evaluate()` now only returns an alert for notification when its severity
*escalates* past a previously stored value — re-evaluating an unchanged or
still-INFO event refreshes its row (so displayed countdown text never goes
stale) without ever re-notifying. Four new rule classes
(`HolidayProximityRule`, `DstShiftProximityRule`, `ExpiryProximityRule`,
`EconomicReleaseProximityRule` — the last scoped to the existing
`CORE_RELEASE_CODES`, deliberately excluding FRED's daily-updating extra
series like `FEDFUNDS` which would otherwise sit permanently at WARNING/
CRITICAL) replace the old four. `AlertingConfig`'s `lookahead_days` widened
7 → 30 so far-out events get an INFO row before needing to escalate; routing
simplified to severity-only (no more per-event-type carve-out).

**Verified live:** cleared stale in-session test rows from the dev SQLite
alert log, ran the real wired app's `AlertEngine.evaluate()` twice against
real CME/FRED/BLS/NSE/IANA data — first run: 13 real INFO alerts, 0 escalated
(correct for 2026-07-22, nothing due within 1-2 days); second run: identical
13 rows, 0 newly escalated, confirming idempotent re-evaluation with no
duplicate rows or re-notification. Full detail in DECISIONS.md's
"Proximity-based alert severity" entry.

**Post-delivery update 13 (2026-07-22):** real Email + Teams notification
delivery wired and verified live — the original ask for this session, picked
back up once the severity redesign above was in place. Gmail SMTP (app
password) + a real Teams Incoming Webhook are both in `.env`; the real
recipient email replaced the placeholder in `config/defaults.toml`'s
`recipient_groups.team_trading`. Sent multiple real forced-CRITICAL test
alerts (one per event category) through both channels and confirmed receipt
in the actual inbox and Teams channel.

**Post-delivery update 14 (2026-07-22):** notification *content* redesign, at
the user's direction, to remove redundancy and confusion. Every rule's
title/body used to repeat the same facts; redesigned so title carries the
complete "what + when + identifying attribute" in one line, body adds only
genuinely new supplementary detail (omitted entirely when there's nothing to
add). Added an explicit "Type" fact (Teams) / `[Type]` tag (email subject) —
without it, a reader had no reliable way to tell what kind of alert they were
looking at. Added the identifying attribute per category, systematically:
holiday and DST shift are **exchange**-specific, expiry is
**underlying + exchange**-specific (CME Group spans 4 real venues —
XCME/XCBT/XNYM/XCEC — so underlying alone doesn't uniquely identify the
venue), economic release is **country**-specific. `TeamsChannel` also
dropped the internal `rule_id` fact (meaningless to a reader) and reformats
the timestamp as `YYYY-MM-DD HH:MM UTC`, relabeled "Triggered" → "Updated".

**Post-delivery update 15 (2026-07-22):** DST alerts now show named zone
abbreviations ("CDT -> CST") instead of raw UTC offsets, matching the
dashboard's own "Next Timezone Shift" block (new `ZONE_ABBR` map +
`dst_transition_label()` in `domain/exchange_zones.py`). **Real bug found
while wiring this up:** `AlertEngine.evaluate()`'s internal event query never
set `include_metadata=True` — `EventQuery.include_metadata` defaults to
`False` as a lean-JSON knob for the *public API*, but the alert engine was
inheriting that default too, silently stripping every event's `metadata`
dict (including `DSTChangeEvent.metadata["transition"]`) before any rule saw
it. This has been true since Phase 4, just invisible until a rule finally
needed to read metadata for something real. Fixed with one line + a
regression test. Full detail in DECISIONS.md's "DST alert content: named
abbreviations + a real metadata-stripping bug found" entry.

**Post-delivery update 16 (2026-07-23):** first move toward actual deployment
(not just the checklist — a real discussion of redeploy mechanics, since this
pipeline is going onto a host that already runs another, unrelated dashboard).
First git commit made (nothing was committed before this). Recipient email
moved out of committed config into `ALERT_RECIPIENT_EMAIL`/`ALERT_RECIPIENT_
NAME` env vars before that config file entered git history. Added a
reproducible-install lockfile (`requirements.lock.txt`, pip-tools), `gunicorn`
+ root `wsgi.py` (verified live under real gunicorn), and a full self-managed-
server deployment path: `deploy/systemd/` unit files (web service + ingest/
alert timers) and a gated `scripts/redeploy.sh`/`scripts/rollback.sh` pair.
Key design decision: the ingest/alert cron jobs never pull code themselves —
only a deliberate `redeploy.sh` run (fetch → install from lockfile → full
test+lint+typecheck gate → revert-and-abort on any failure → restart →
health-check → auto-rollback) changes what's installed; this keeps "deploy"
and "run the scheduled pipeline" fully decoupled, so a bad push can never
sneak untested code onto disk between deploys. Full detail in DECISIONS.md's
"Deployment scaffolding" entry.

If picking this up for further work: **still open** — pushing to a GitHub
remote (needs the user's own account/org; no `gh` CLI in this environment),
the storage backend decision (SQLite vs. Postgres, including whether to share
a *database* the other on-host system might already run), and whether the
test gate lives primarily in CI (GitHub Actions, recommended) or only in
`redeploy.sh`. Beyond that: live-source validation from a real deployment
host, confirming BEA's table/line mapping, choosing an ISM aggregator or
forecast source, KRX going live — all additive (P4), not rework.

**Quick start (CLI):**
```bash
pip install -e ".[dev,postgres]"
cp .env.example .env   # fill in secrets as needed; app runs fine with none set
exchange-events init-db
exchange-events ingest --source iana_tz --from 2026-01-01 --to 2026-12-31   # offline, real data
exchange-events alert
exchange-events serve --host 0.0.0.0 --port 8080   # dashboard at http://localhost:8080/
```

**Quick start (programmatic):**
```python
from exchange_events.config.loader import load_config
from exchange_events.wiring import build_application
app = build_application(load_config())   # zero-config: sqlite + dashboard channel only
```

**Raw-record schemas:** documented in each `normalizers/<src>.py` (or `exchange.py`) module docstring — adapters must emit exactly these dict shapes.

**⚠️ Live source status (Phase 6 findings, confirmed again in Phase 13's live-network contract test — full detail in DECISIONS.md "Source adapter findings" and "Economic-release waterfall"):**
| Source | Status | Note |
|---|---|---|
| NSE | ✅ live-validated from this sandbox | session-warm-up design works; real run: 64 holiday/circular records |
| **CME** | ✅ live-validated from this sandbox (2026-07-22) | needs `CME_API_ID`/`CME_API_SECRET` (free CME Group Customer Center account + OAuth API ID — see DECISIONS.md "CME Reference Data API"); the old `cmegroup.com` AJAX endpoints remain domain-wide blocked, replaced entirely by CME's own Reference Data API v3 on separate, unblocked infrastructure; covers 11 products (ES/NQ/RTY/6E on CME, YM/ZN/ZB on CBOT, CL/NG on NYMEX, GC/SI on COMEX — all shown under the one XCME tab, per the user's choice); real run: 19 correctly-derived 2026-2027 holidays + 123 real expiries |
| BSE | ❌ wrong/stale endpoint — confirmed live: HTTP 200 with a non-JSON body | needs real URL captured from devtools |
| **FRED** (econ, tier 1) | needs `FRED_API_KEY` | covers 6/7 releases (NFP/CPI/PPI/PCE/JOLTS/FOMC); no anti-bot wall, expected to work everywhere once keyed |
| **BLS** (econ, tier 2) | ✅ live-validated unkeyed | official backstop for NFP/CPI/PPI/JOLTS; `BLS_API_KEY` optional; real run: 23 records Jan–Jun 2026. **Requires POST with a JSON `seriesid` array** — a comma-joined multi-series GET (the old behavior) is rejected by BLS's live API (`REQUEST_FAILED`); fixed 2026-07-22, see DECISIONS.md |
| **BEA** (econ, tier 3) | needs `BEA_API_KEY`, **not live-tested here** | official backstop for PCE; default table/line believed correct, flagged for confirmation before go-live |
| **ISM** (econ, best-effort) | not configured by default | ISM Manufacturing PMI has no free official source (FRED dropped it in 2016); provider-agnostic, needs a chosen aggregator's URL + field map |
| MarketWatch (econ) | ❌ DataDome **CAPTCHA** (not just a JS challenge) | left wired but not load-bearing — the waterfall above covers all required *actual* data without it; would only add forecasts if ever unblocked |
| **FRED release/dates** (schedule, NFP/CPI/PPI/PCE/JOLTS) | needs `FRED_API_KEY` (same key) | genuinely forward-looking (not just realized data) — verified via FRED's own docs; same reachability as the actuals endpoint |
| **FOMC calendar** (schedule) | ✅ live-validated from this sandbox | reads `federalreserve.gov` directly, no API key; real run: all 8 real 2026 meeting dates |
| BLS's own schedule page | ❌ blocked here (403, IP-reputation) | not used — FRED's release/dates covers the same releases without needing it |
| ISM's schedule/calendar page | ❌ redirects to a paid member login | confirmed directly; consistent with ISM's data also being paywalled |
| IANA (DST) | ✅ fully offline | stdlib `zoneinfo`, no network, verified against real 2026 transition dates |
| KRX | deferred by design | stub only, not live |

---

## Project Overview

A production-grade, **contract-first** Python pipeline that fetches market-moving events
— exchange **holidays**, **DST changes**, derivative **expiries**, and US **economic releases**
— from multiple sources, normalizes them into a canonical model, stores them idempotently,
and exposes them via a thin REST API + dashboard + alert/notification system.

- **Design doc (source of truth for architecture):** [exchange_events_dashboard_design_doc.md](exchange_events_dashboard_design_doc.md)
- **Implementation plan (phases + tests):** [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)
- **Decisions log:** [docs/DECISIONS.md](docs/DECISIONS.md)
- **Progress journal:** [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md)

## Guiding Principles (from design doc §1 — do not violate)

- **P1 Contract-first** — components depend on ABCs, wired via constructor injection. Only `wiring.py` instantiates concretes.
- **P2 Single responsibility** — fetch ≠ normalize ≠ store ≠ alert ≠ deliver.
- **P3 Testable without infra** — every component unit-testable with in-memory fakes.
- **P4 Additive extension** — new source/rule/channel = new class + registration, never modify existing.
- **P5 UTC-canonical, display-local** — store/compare in UTC; convert only at presentation.
- **P6 Idempotent ingestion** — deterministic `event_id`, upsert semantics.
- **P7 Designed for later integration** — API is the public boundary; dashboard is just one consumer.

## Architecture Map

```
Source Adapters ─┬─▶ Ingestion Engine ─▶ Repository ─┬─▶ API (Flask) ─▶ Dashboard
   Normalizers ──┘                                   └─▶ Alert Engine ─▶ Dispatcher ─▶ Channels (Email/Teams)
```
Dependencies point inward. `contracts/` (ABCs) + `domain/` (data types) are imported everywhere;
concrete packages never import each other; `wiring.py` is the only composition root.

## Package Layout (src layout)

```
src/exchange_events/
  domain/        # canonical data types (Event subclasses, Alert, EventQuery, ids, errors)
  contracts/     # ABCs only (SourceAdapter, EventNormalizer, EventRepository, AlertRule, ...)
  infra/         # production concretes for infra ABCs (SystemClock, RealHttpClient, StdLogger)
  adapters/      # SourceAdapter implementations (cme, nse, bse, krx, fred, iana, econ)
  normalizers/   # EventNormalizer implementations (one per adapter)
  storage/       # EventRepository impls (sqlite, postgres) + schema/migrations
  ingestion/     # IngestionEngine, NormalizerRegistry, RetryPolicy
  alerting/      # AlertEngine, NotificationDispatcher, rules/, AlertLog
  notifications/ # NotificationChannel impls (email, teams, dashboard)
  api/           # Flask app + routes + serializers
  dashboard/     # static HTML/JS (thin consumer of the API)
  config/        # AppConfig schema + TOML/env loader
  wiring.py      # build_application() — composition root
  main.py        # CLI entry point (init-db, ingest, alert, serve)
tests/{unit,integration,contract,e2e,fakes,fixtures}
```

## Key Decisions (see docs/DECISIONS.md for full rationale)

| Area | Choice |
|---|---|
| Storage | **Both** SQLite (default, stdlib) + Postgres (`psycopg` 3, gated on `EXCHANGE_EVENTS_PG_DSN`) |
| Live sources | **CME first (production)**, then NSE, BSE live; KRX deferred (stub); IANA live; economic releases = **FRED → BLS → BEA → ISM waterfall** (all official/free, no scraping) |
| API | Flask 3.1 |
| Notifications | Email (SMTP) + Microsoft Teams (webhook) + console/in-memory Dashboard channel |
| Config | TOML (`tomllib`) + env secrets (`pydantic-settings`) |
| Time | UTC everywhere; `Clock` ABC + `FakeClock` in tests (no wall-clock in tests) |

## How to Run / Test

See [README.md](README.md) for the full user-facing guide. Quick reference:

```bash
pip install -e ".[dev,postgres]"

# Tests (default: unit + integration + e2e, all offline; contract excluded)
pytest                          # 453 passed, 19 skipped (no PG), 6 deselected (contract)
pytest -m unit                  # units only
pytest -m integration           # SQLite integration (+ Postgres if EXCHANGE_EVENTS_PG_DSN set)
pytest -m e2e                   # the one full ingest→store→API→alert→dispatch test
pytest -m contract              # live external sources (network) — opt-in, see live-source table above
pytest --cov=exchange_events --cov-report=term-missing   # coverage (96% overall, 99-100% on core logic)
ruff check src tests && mypy src/exchange_events           # lint + strict type-check

# CLI (installed console script, or `python -m exchange_events.main`)
exchange-events init-db
exchange-events ingest --source cme_calendar --from 2026-01-01 --to 2026-12-31
exchange-events alert
exchange-events serve --host 0.0.0.0 --port 8080
```

## Conventions

- Every ABC in `contracts/` has (a) a production concrete and (b) a fake under `tests/fakes/`.
- Normalizer tests use realistic inline raw dicts (matching each adapter's documented schema) rather than on-disk fixture files — kept the suite simpler with no loss of coverage (100% on `normalizers/`); `tests/fixtures/` exists but is currently unused.
- Adapters never parse in tests against the network — they use `FakeHttpClient` + realistic canned responses. Live checks are `@pytest.mark.contract`.
- All timestamps stored/compared in UTC. `datetime` values are timezone-aware.
- No component reads config/files/env directly except `config/loader.py`; everything else receives config via constructor.

## Status Checklist

- ✅ Phase 0 — Scaffolding & continuity docs
- ✅ Phase 1 — Domain model
- ✅ Phase 2 — Contracts
- ✅ Phase 3 — Test fakes + infra
- ✅ Phase 4 — Storage (SQLite + Postgres)
- ✅ Phase 5 — Normalizers
- ✅ Phase 6 — Source Adapters (CME first)
- ✅ Phase 7 — Ingestion Engine
- ✅ Phase 8 — Alert Engine + Rules
- ✅ Phase 9 — Notification (Email + Teams)
- ✅ Phase 10 — Config + Wiring
- ✅ Phase 11 — API (Flask)
- ✅ Phase 12 — Dashboard
- ✅ Phase 13 — CLI entry point
- ✅ Phase 14 — E2E, hardening, docs (FINAL) — **ALL PHASES COMPLETE**

## Known Issues / Watch-outs

- ~~CME is blocked by IP-reputation from this sandbox~~ — **fixed 2026-07-22**: the old `cmegroup.com` AJAX endpoints are still blocked domain-wide, but `adapters/cme.py` now uses CME's own free, OAuth-authenticated Reference Data API v3 on separate, unblocked infrastructure — live-validated, see DECISIONS.md "CME Reference Data API".
- **BSE's guessed endpoint needs real-URL discovery**; **MarketWatch is behind a DataDome CAPTCHA** (confirmed via a real headless-browser test, not just a JS challenge — see DECISIONS.md "Economic-release waterfall"). Neither blocks the rest of the system — every adapter is unit-tested offline, the ingestion engine isolates per-source failures, and economic releases no longer depend on MarketWatch at all (the FRED/BLS/BEA/ISM waterfall covers the required *actual* data).
- **BEA's table/line mapping (`T20806`, line 1) is unverified live** — no API key available in this environment; confirm against BEA's own NIPA table docs before relying on it in production.
- **ISM Manufacturing PMI has no configured default source** — it's the one release with no free official API (FRED dropped it in 2016 over licensing); `adapters/ism.py` is ready to wire up whichever aggregator gets evaluated/chosen (candidates noted in its docstring: Trading Economics, Finnhub, Nasdaq Data Link, FMP — none verified).
- ~~FRED needs `FRED_API_KEY` (untested live)~~ — **live-validated 2026-07-22** once a free key was obtained: real run returned 577 records across all 6 FRED-covered releases plus actuals and forward schedule.
- **No local Postgres server / Docker** in this environment — Postgres code paths share 100% of their logic with the passing SQLite tests, but have never been run against a live PG server here. Set `EXCHANGE_EVENTS_PG_DSN` to unskip `pytest -m integration`'s Postgres-parametrized tests.
- **No IV provider ships in v1** — `IVThresholdProvider` is a fully-specified contract with every consumer (alert rule, API endpoint) degrading gracefully in its absence; wiring one in later is additive (`wiring._build_iv_provider`).
- **KRX adapter is a structural stub** — wired end-to-end (normalizer, registry entry, tests) but `fetch()` intentionally returns no records; going live is future work, not a redesign.
- ~~Nothing has been committed to git yet~~ — **fixed 2026-07-23**: first commit made. Not yet pushed to a remote (needs a GitHub repo created by the user first — no `gh` CLI available in this environment).
- ~~SQL repository/alert-log connection was not thread-safe under Flask's default threaded dev server~~ — **fixed 2026-07-21** (see post-delivery entry above); a `threading.Lock` now guards every connection access in both classes, with a dedicated stress-test regression test.
- The dashboard (`dashboard/static/index.html`) now has exchange-specific tabs built dynamically from `/api/v1/exchanges` — if you add a 5th exchange to `api/routes/calendar.py`'s `EXCHANGES` list, it gets a tab automatically, no dashboard code change needed.
