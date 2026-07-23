# Exchange Events Dashboard — Design Document

**Status:** v1 Draft
**Author:** Samaraha (CloudCraftz)
**Date:** 2026-07-20
**Companion doc:** `exchange_events_dashboard_plan.md` (requirements/scope)

---

## 0. How to Read This Document

This document defines the architecture for a pipeline that fetches market-moving event data from multiple sources, normalizes it into a canonical model, stores it, and exposes it through a dashboard and notification system. It is written for a Python codebase, though the structural principles are language-agnostic.

Every component is defined by a **contract** (an abstract interface) before any mention of implementation. If a component can be swapped, extended, or tested in isolation without touching anything else, the design is working. If it can't, the design has a bug.

The document proceeds top-down: principles → architecture → domain model → contracts → component details → data flow → configuration → testing → extension points → package layout.

---

## 1. Guiding Principles

These are not aspirational. They are constraints that every design decision in this document was tested against, and that every implementation decision should be tested against.

**P1 — Contract-first.** Every component exposes an abstract interface (Python ABC). Concrete classes implement that interface. No component ever imports or instantiates another concrete class directly — it receives its dependencies through its constructor. This is dependency injection at its simplest: if `A` needs `B`, `A`'s constructor takes `B`'s interface type, and the wiring layer (§8) decides which concrete `B` to inject.

**P2 — Single Responsibility per component.** Each class or module does exactly one thing. The source adapter fetches raw data. The normalizer transforms it. The repository stores it. The alert evaluator decides if something is alert-worthy. The notification channel delivers it. No component does two of these. If you find yourself writing a class that fetches *and* normalizes, split it.

**P3 — Testability without infrastructure.** Every component must be unit-testable with only in-memory fakes — no database, no network, no filesystem required. This falls out of P1 naturally: if dependencies are injected via interfaces, tests inject fakes. But it's worth stating explicitly because it rules out hidden coupling (e.g., a component that quietly reads a config file instead of receiving config through its constructor).

**P4 — Additive extension, not modification.** Adding a new exchange, a new economic release, a new notification channel, or a new alert rule should require writing a *new* class that implements an existing interface, and registering it in the wiring layer. It should never require modifying an existing class. This is the open-closed principle stated concretely for this project.

**P5 — UTC-canonical, display-local.** All timestamps are stored and compared in UTC. Conversion to IST, ET, KST, or any other display timezone happens exclusively at the presentation boundary. No business logic ever touches a local timestamp.

**P6 — Idempotent ingestion.** Running the same fetch twice for the same source and time range must not create duplicate events or corrupt state. Every event has a natural key (source + event type + date + exchange), and upsert semantics are the default. This matters because fetch jobs will fail, retry, overlap, and sometimes run concurrently — the storage layer must absorb all of that without help from the caller.

**P7 — Designed for later integration.** The dashboard is the v1 consumer, but the pipeline's output boundary is an API, not a UI. A future live monitoring system, a backtest engine, or an AGH-style pipeline should be able to consume the same data through the same API without the pipeline knowing or caring who's asking.

---

## 2. High-Level Architecture

The system is organized into five layers. Data flows left to right. Dependencies point inward (presentation depends on services, services depend on domain, nothing depends on presentation).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CONFIGURATION / DI WIRING                        │
│           (assembles all components, owns the dependency graph)              │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │ injects into
    ┌────────────┐   ┌───────────┐   │   ┌──────────────┐   ┌──────────────┐
    │   SOURCE   │──▶│ INGESTION │───┼──▶│   STORAGE    │──▶│ PRESENTATION │
    │  ADAPTERS  │   │  ENGINE   │   │   │  (Repository)│   │  (API + UI)  │
    └────────────┘   └─────┬─────┘   │   └──────┬───────┘   └──────────────┘
                           │         │          │
                     ┌─────▼─────┐   │   ┌──────▼───────┐
                     │NORMALIZERS│   │   │  ALERT       │──▶ NOTIFICATION
                     │           │   │   │  ENGINE      │    CHANNELS
                     └───────────┘   │   └──────────────┘
                                     │
```

**Source Adapters** — fetch raw data from external APIs, scraped pages, or static files. One adapter per data source (not per exchange — a single adapter might serve multiple exchanges if the API does).

**Ingestion Engine** — orchestrates the fetch cycle: which adapters to call, when, with what parameters. Handles scheduling, retries, and error isolation. Calls normalizers to transform raw data before handing it to storage.

**Normalizers** — transform source-specific raw data into the canonical domain model (§3). Stateless, pure functions. One normalizer per source adapter, since each source has its own raw schema.

**Storage (Repository)** — persists canonical events. Exposes a query interface. The only component that touches the database. Everything else talks to the repository interface.

**Alert Engine** — evaluates stored events against alert rules. Produces alert payloads. Does not deliver them — hands them to notification channels.

**Notification Channels** — deliver alert payloads to recipients via Slack, email, dashboard push, or whatever else is wired up. One channel class per delivery mechanism.

**Presentation (API + UI)** — a thin REST/HTTP layer over the repository + a dashboard frontend. The API is the system's public boundary. The dashboard is one consumer of that API; a future live monitoring system would be another.

---

## 3. Domain Model — Canonical Event Types

This is the single shared vocabulary of the entire system. Every component upstream (adapters, normalizers) produces instances of these types. Every component downstream (repository, alert engine, API) consumes them. No raw/source-specific data structures leak past the normalizer.

### 3.1 Base Event

All events share a common shape. Specific event categories extend it.

```python
@dataclass(frozen=True)
class Event:
    event_id: str               # Deterministic, derived from natural key (see §3.4)
    event_type: EventType       # Enum: HOLIDAY, DST_CHANGE, EXPIRY, ECONOMIC_RELEASE
    exchange: str | None        # ISO MIC code (XNSE, XBOM, XKRX, XCME) — None for non-exchange events like DST
    date: datetime.date         # The calendar date the event falls on
    timestamp_utc: datetime.datetime | None  # Exact time in UTC, if applicable (e.g., release time)
    source: str                 # Which adapter produced this (e.g., "nse_circular", "fred_api")
    source_raw_id: str | None   # Original ID from the source, if any, for traceability
    ingested_at: datetime.datetime  # When we first stored this event (set by repository)
    updated_at: datetime.datetime   # Last modification time (set by repository)
    metadata: dict              # Escape hatch for source-specific fields not in the canonical model
```

### 3.2 Category-Specific Extensions

```python
@dataclass(frozen=True)
class HolidayEvent(Event):
    holiday_name: str           # "Republic Day", "Chuseok", "Independence Day"
    session_type: SessionType   # Enum: FULL_CLOSE, HALF_DAY, SPECIAL_SESSION (e.g., Muhurat)
    affected_segments: list[str]  # ["EQ", "FO", "CD"] — not all segments close on every holiday

@dataclass(frozen=True)
class DSTChangeEvent(Event):
    region: str                 # IANA region (e.g., "US", "Europe")
    old_utc_offset: str         # e.g., "UTC-5"
    new_utc_offset: str         # e.g., "UTC-4"
    iana_zone: str              # e.g., "America/New_York"

@dataclass(frozen=True)
class ExpiryEvent(Event):
    instrument_type: str        # "options", "futures"
    underlying: str             # "NIFTY", "BANKNIFTY", "KOSPI200", "ES"
    series: str                 # "weekly", "monthly", "quarterly"
    expiry_date: datetime.date  # The actual expiry date
    rollover_to: datetime.date | None  # Next series' expiry, if known
    is_revised: bool            # True if this expiry was moved from its originally scheduled date

@dataclass(frozen=True)
class EconomicReleaseEvent(Event):
    release_name: str           # "CPI", "NFP", "FOMC Rate Decision"
    release_code: str           # Canonical short code: "CPI", "NFP", "PPI", "PCE", "ISM_PMI", "JOLTS", "FOMC"
    agency: str                 # "BLS", "BEA", "ISM", "Federal Reserve"
    period: str                 # The period this data covers: "June 2026", "Q2 2026"
    forecast: float | None      # Consensus estimate (pre-release)
    previous: float | None      # Prior period's value
    actual: float | None        # Released value (None until released)
    revision: float | None      # Revision to previous period's figure, if any
    unit: str                   # "%", "thousands", "index", "bps"
    surprise: float | None      # actual - forecast (computed, not stored raw)
```

### 3.3 EventType Enum

```python
class EventType(str, Enum):
    HOLIDAY = "holiday"
    DST_CHANGE = "dst_change"
    EXPIRY = "expiry"
    ECONOMIC_RELEASE = "economic_release"
```

### 3.4 Event ID Generation

Event IDs are deterministic, derived from the natural key. This is what makes ingestion idempotent (P6): re-fetching the same event from the same source produces the same ID, which triggers an upsert rather than a duplicate insert.

```
event_id = sha256(f"{source}:{event_type}:{exchange}:{date}:{discriminator}")
```

Where `discriminator` is category-specific: `holiday_name` for holidays, `underlying:series` for expiries, `release_code` for economic releases, `iana_zone` for DST changes.

---

## 4. Component Contracts

Every contract is a Python ABC. Implementations follow in §5 (component details). The contracts alone are enough to understand the system's wiring — if you only read one section, read this one.

### 4.1 Source Adapter

```python
class SourceAdapter(ABC):
    """Fetches raw data from a single external source.
    
    One adapter per data source. An adapter may serve multiple exchanges
    or event types if the underlying source does (e.g., a single API
    that covers both NSE and BSE holidays).
    
    Raw data is returned as dicts — no canonical types here. Normalization
    is the normalizer's job.
    """
    
    @abstractmethod
    def fetch(self, params: FetchParams) -> list[dict]:
        """Fetch raw event data for the given parameters.
        
        Args:
            params: Contains date_range, exchange filter, event_type filter.
        
        Returns:
            List of raw dicts, source-specific structure.
        
        Raises:
            SourceUnavailableError: If the source is down or unreachable.
            SourceRateLimitError: If we've hit the source's rate limit.
        """
        ...
    
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source (e.g., 'nse_circular', 'fred_api')."""
        ...
    
    @abstractmethod
    def supported_event_types(self) -> list[EventType]:
        """Which event types this adapter can produce."""
        ...
    
    @abstractmethod
    def supported_exchanges(self) -> list[str] | None:
        """Which exchanges this adapter covers. None = not exchange-specific (e.g., DST)."""
        ...
```

### 4.2 Normalizer

```python
class EventNormalizer(ABC):
    """Transforms raw source-specific dicts into canonical Event objects.
    
    Stateless. Pure function. One normalizer per source adapter — each source
    has its own raw schema, so each needs its own transformation logic.
    """
    
    @abstractmethod
    def normalize(self, raw_records: list[dict], source_name: str) -> list[Event]:
        """Transform raw records into canonical events.
        
        Args:
            raw_records: Raw dicts from the source adapter.
            source_name: Which adapter produced these (for event_id generation).
        
        Returns:
            List of canonical Event instances (or subclasses).
        
        Raises:
            NormalizationError: If a record can't be transformed (with details
                about which record and why). Partial success is allowed — valid
                records are returned, invalid ones are logged and skipped.
        """
        ...
    
    @abstractmethod
    def target_source(self) -> str:
        """Which source adapter's output this normalizer handles."""
        ...
```

### 4.3 Event Repository

```python
class EventRepository(ABC):
    """Persistence layer for canonical events.
    
    Supports upsert (for idempotent ingestion) and query (for the API/dashboard).
    The only component that touches the database.
    """
    
    @abstractmethod
    def upsert(self, events: list[Event]) -> UpsertResult:
        """Insert or update events. Matching is by event_id.
        
        Returns:
            UpsertResult with counts: inserted, updated, unchanged.
        """
        ...
    
    @abstractmethod
    def query(self, filters: EventQuery) -> list[Event]:
        """Query events by type, exchange, date range, etc.
        
        Args:
            filters: Composite filter object (see §4.3.1).
        
        Returns:
            Events matching all filters, ordered by date ascending.
        """
        ...
    
    @abstractmethod
    def get_by_id(self, event_id: str) -> Event | None:
        """Retrieve a single event by its canonical ID."""
        ...
    
    @abstractmethod
    def get_latest_ingest_time(self, source: str) -> datetime.datetime | None:
        """When was the last successful ingest from this source?
        
        Used by the ingestion engine to determine fetch windows
        for incremental ingestion.
        """
        ...
```

**§4.3.1 — EventQuery** (the filter object passed to `query`):

```python
@dataclass
class EventQuery:
    event_types: list[EventType] | None = None      # Filter by type(s)
    exchanges: list[str] | None = None               # Filter by exchange(s)
    date_from: datetime.date | None = None            # Inclusive lower bound
    date_to: datetime.date | None = None              # Inclusive upper bound
    release_codes: list[str] | None = None            # For economic releases only
    include_metadata: bool = False                    # Whether to populate the metadata dict
    limit: int | None = None
    offset: int = 0
```

### 4.4 Alert Rule

```python
class AlertRule(ABC):
    """Evaluates whether a set of events should trigger a notification.
    
    Each rule encodes one alerting condition (e.g., "high-priority release
    happening tomorrow", "IV above threshold near an event", "expiry date
    was revised"). Rules are stateless evaluators — they don't know or care
    how notifications get delivered.
    """
    
    @abstractmethod
    def evaluate(self, events: list[Event], context: AlertContext) -> list[Alert]:
        """Check events against this rule's condition.
        
        Args:
            events: Candidate events to evaluate.
            context: Contextual data the rule might need (current time,
                     IV snapshot if available, previous alert history).
        
        Returns:
            List of Alert payloads for events that triggered. Empty if none triggered.
        """
        ...
    
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule (for dedup and audit)."""
        ...
```

**Alert payload:**

```python
@dataclass(frozen=True)
class Alert:
    alert_id: str               # Deterministic: sha256(rule_id + event_id + trigger_date)
    rule_id: str                # Which rule produced this
    event: Event                # The event that triggered it
    severity: AlertSeverity     # Enum: INFO, WARNING, CRITICAL
    title: str                  # Human-readable one-liner
    body: str                   # Detailed message
    triggered_at: datetime.datetime  # UTC
```

### 4.5 Notification Channel

```python
class NotificationChannel(ABC):
    """Delivers alert payloads to recipients through a specific medium.
    
    One implementation per delivery mechanism (Slack, email, in-dashboard, etc.).
    Does not decide what to alert on — only how to deliver.
    """
    
    @abstractmethod
    def send(self, alert: Alert, recipients: list[Recipient]) -> DeliveryResult:
        """Deliver an alert to the given recipients.
        
        Returns:
            DeliveryResult indicating success/failure per recipient.
        
        Raises:
            ChannelUnavailableError: If the channel itself is down.
        """
        ...
    
    @abstractmethod
    def channel_name(self) -> str:
        """Identifier for this channel (e.g., 'slack', 'email')."""
        ...
```

### 4.6 IV Threshold Provider (optional dependency)

```python
class IVThresholdProvider(ABC):
    """Supplies implied volatility data for overlay and alerting.
    
    This is an optional dependency — the system works without it.
    When present, it feeds both the dashboard (observational overlay)
    and the alert engine (threshold-based rules).
    """
    
    @abstractmethod
    def get_iv_snapshot(
        self, exchange: str, underlying: str, date: datetime.date
    ) -> IVSnapshot | None:
        """Get IV data for a given underlying on a given date."""
        ...
    
    @abstractmethod
    def get_iv_series(
        self, exchange: str, underlying: str, 
        date_from: datetime.date, date_to: datetime.date
    ) -> list[IVSnapshot]:
        """Get IV time series for overlay display."""
        ...
```

### 4.7 Clock (yes, really)

```python
class Clock(ABC):
    """Abstracts the system clock. Exists solely for testability.
    
    Every component that needs "now" receives a Clock, not datetime.utcnow().
    Tests inject a FakeClock set to whatever time the test scenario requires.
    """
    
    @abstractmethod
    def now_utc(self) -> datetime.datetime:
        ...
    
    @abstractmethod
    def today_utc(self) -> datetime.date:
        ...
```

---

## 5. Component Details

### 5.1 Source Adapters — One Per Data Source

Each adapter is a leaf node with no dependencies on other components (except config and an HTTP client, both injected). They return raw dicts, not canonical types.

**Planned v1 adapters:**

| Adapter class | Source | Event types | Exchanges |
|---|---|---|---|
| `NSECircularAdapter` | NSE circulars / website | HOLIDAY, EXPIRY | XNSE |
| `BSECircularAdapter` | BSE circulars / website | HOLIDAY, EXPIRY | XBOM |
| `KRXCalendarAdapter` | KRX published calendar | HOLIDAY, EXPIRY | XKRX |
| `CMECalendarAdapter` | CME Group calendar | HOLIDAY, EXPIRY | XCME |
| `EconCalendarAdapter` | MarketWatch / chosen API (pending source eval) | ECONOMIC_RELEASE | None |
| `FREDAdapter` | FRED API (St. Louis Fed) | ECONOMIC_RELEASE (actuals backfill) | None |
| `IANATimezoneAdapter` | `zoneinfo` stdlib | DST_CHANGE | None |

**Constructor signature pattern** (all adapters follow this):

```python
class NSECircularAdapter(SourceAdapter):
    def __init__(
        self,
        http_client: HttpClient,   # Injected — testable with a fake
        config: NSEAdapterConfig,  # Source-specific config (base URL, rate limits, etc.)
        logger: Logger,            # Injected
    ):
        ...
```

**Key design note on the economic calendar adapter:** the requirements list 7 specific US macro releases. The adapter should not hardcode these 7 — it should accept a list of release codes as config, so adding "Retail Sales" or "GDP" later is a config change, not a code change. The normalizer handles mapping source-specific field names to canonical `EconomicReleaseEvent` fields.

### 5.2 Normalizers — One Per Adapter

Normalizers are stateless and side-effect-free. They take raw dicts, return canonical `Event` subclasses. Their only job is structural transformation and validation.

**Error handling contract:** a normalizer never throws on a single bad record. It transforms what it can, collects errors for what it can't, and returns both:

```python
@dataclass
class NormalizationResult:
    events: list[Event]
    errors: list[NormalizationError]  # Each error references the raw record that failed
```

This means a partially broken fetch (e.g., 48 of 50 records parse fine) still yields 48 usable events rather than zero.

### 5.3 Ingestion Engine

The orchestrator. It owns the fetch lifecycle but does not contain any source-specific or normalization logic.

```python
class IngestionEngine:
    def __init__(
        self,
        adapters: list[SourceAdapter],
        normalizer_registry: NormalizerRegistry,  # Maps source_name → normalizer
        repository: EventRepository,
        clock: Clock,
        logger: Logger,
        retry_policy: RetryPolicy,
    ):
        ...
    
    def run_full_ingest(self, date_range: DateRange) -> IngestionReport:
        """Run all adapters for the given date range, normalize, store.
        
        For each adapter:
          1. Determine fetch window (date_range, narrowed by last ingest time if incremental)
          2. Call adapter.fetch()
          3. Look up the matching normalizer
          4. Call normalizer.normalize()
          5. Call repository.upsert()
          6. Record success/failure in the report
        
        Adapter failures are isolated — one failing adapter does not block others.
        """
        ...
    
    def run_single_source(self, source_name: str, date_range: DateRange) -> IngestionReport:
        """Run a single adapter. Useful for retries and debugging."""
        ...
```

**Scheduling:** the ingestion engine itself is not a scheduler — it's a callable. A thin scheduling wrapper (cron job, APScheduler, or whatever the deployment environment uses) calls `run_full_ingest()` on the desired cadence. This keeps the engine testable without involving any scheduling infrastructure.

**Retry policy** is injected, not hardcoded:

```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    retryable_exceptions: tuple[type[Exception], ...] = (SourceUnavailableError, SourceRateLimitError)
```

### 5.4 Alert Engine

Evaluates alert rules against recent events. Separated from notification delivery.

```python
class AlertEngine:
    def __init__(
        self,
        rules: list[AlertRule],
        repository: EventRepository,
        alert_log: AlertLog,          # Tracks which alerts have already fired (for dedup)
        clock: Clock,
        iv_provider: IVThresholdProvider | None,  # Optional — rules that need IV skip if absent
        logger: Logger,
    ):
        ...
    
    def evaluate(self) -> list[Alert]:
        """Run all rules against upcoming/recent events.
        
        1. Query repository for events in the alerting window
           (configurable, e.g., next 7 days)
        2. Build AlertContext (current time, IV snapshot if available,
           already-fired alert IDs from alert_log)
        3. Pass events + context to each rule
        4. Collect alerts, deduplicate against alert_log
        5. Record newly fired alerts in alert_log
        6. Return deduplicated alerts
        """
        ...
```

**AlertLog** is a small persistence interface for deduplication:

```python
class AlertLog(ABC):
    @abstractmethod
    def has_fired(self, alert_id: str) -> bool: ...
    
    @abstractmethod
    def record(self, alert: Alert) -> None: ...
```

### 5.5 Notification Dispatcher

Sits between the alert engine and the notification channels. Routes alerts to the right channels and recipients.

```python
class NotificationDispatcher:
    def __init__(
        self,
        channels: list[NotificationChannel],
        routing_config: RoutingConfig,  # Maps alert severity / event type → channels + recipients
        logger: Logger,
    ):
        ...
    
    def dispatch(self, alerts: list[Alert]) -> list[DeliveryResult]:
        """Route each alert to the appropriate channel(s) and recipient(s).
        
        Routing logic:
          1. Look up routing_config for this alert's severity and event type
          2. Determine which channels and recipients apply
          3. Call channel.send() for each
          4. Collect and return delivery results
        
        Channel failures are isolated — one down channel does not block others.
        """
        ...
```

**RoutingConfig example** (expressed as data, not code):

```yaml
routes:
  - match:
      severity: CRITICAL
      event_types: [economic_release, expiry]
    channels: [slack, email]
    recipients: [team_trading]
  
  - match:
      severity: WARNING
    channels: [slack]
    recipients: [team_trading]
  
  - match:
      severity: INFO
    channels: [dashboard]
    recipients: [all]
```

### 5.6 API Layer

A thin HTTP layer over the repository and alert engine. No business logic here — just request parsing, auth (if needed), and response serialization.

```python
# Conceptual — exact framework (FastAPI, Flask, etc.) is an implementation choice

GET  /api/v1/events                  → EventRepository.query(filters_from_query_params)
GET  /api/v1/events/{event_id}       → EventRepository.get_by_id(event_id)
GET  /api/v1/events/upcoming         → EventRepository.query(date_from=today, date_to=today+N)
GET  /api/v1/alerts                  → AlertLog.recent()
GET  /api/v1/iv/{exchange}/{underlying}  → IVThresholdProvider.get_iv_series(...)
POST /api/v1/ingest/trigger          → IngestionEngine.run_full_ingest()  # Manual trigger

# Dashboard-specific convenience endpoints
GET  /api/v1/calendar/{year}/{month} → Aggregated calendar view (events grouped by date)
GET  /api/v1/exchanges               → Static list of configured exchanges with metadata
```

The API is the system's public boundary. The dashboard consumes it. A future live monitoring integration consumes the same API. This is P7 in practice.

### 5.7 Dashboard (Presentation)

The dashboard is a consumer of the API, not a part of the pipeline. It can be a separate frontend application (React, plain HTML, whatever suits the team) that calls the API endpoints above.

**Conceptual views:**

| View | What it shows | API source |
|---|---|---|
| Calendar view | All events for a month, color-coded by type | `/api/v1/calendar/{year}/{month}` |
| Upcoming events | Next 7–14 days, prioritized by severity | `/api/v1/events/upcoming` |
| Economic releases | Tabular: release, date, forecast, previous, actual, surprise | `/api/v1/events?event_types=economic_release` |
| Exchange status | Per-exchange: next holiday, next expiry, current timezone offset | Composite of multiple queries |
| IV overlay | IV time series with event markers on the x-axis | `/api/v1/iv/...` + `/api/v1/events` |
| Alert feed | Recent alerts with severity and timestamp | `/api/v1/alerts` |

**Design note:** the dashboard is deliberately the thinnest layer. It does no data transformation, no alerting logic, no fetching from external sources. If the dashboard were deleted, the rest of the system would continue functioning — ingesting, storing, alerting. This is what "designed for later integration" (P7) looks like: the dashboard is one skin over the API, and a future live monitoring system is another skin over the same API.

---

## 6. Data Flow — End to End

### 6.1 Ingestion Flow (Scheduled / Manual Trigger)

```
┌──────────┐     ┌──────────────┐     ┌────────────┐     ┌────────────┐
│ Scheduler│────▶│  Ingestion   │────▶│  Source     │────▶│  External  │
│ (cron)   │     │  Engine      │     │  Adapter    │     │  API/Site  │
└──────────┘     └──────┬───────┘     └────────────┘     └────────────┘
                        │ raw dicts
                        ▼
                 ┌──────────────┐
                 │  Normalizer  │
                 └──────┬───────┘
                        │ canonical Events
                        ▼
                 ┌──────────────┐
                 │  Repository  │──── (upsert) ──── Database
                 └──────────────┘
```

### 6.2 Alert Flow (Scheduled, After Ingestion)

```
┌──────────┐     ┌──────────────┐     ┌────────────┐     ┌────────────────┐
│ Scheduler│────▶│   Alert      │────▶│  Alert     │────▶│  Notification  │
│ (cron)   │     │   Engine     │     │  Rules     │     │  Dispatcher    │
└──────────┘     └──────┬───────┘     └────────────┘     └───────┬────────┘
                        │                                        │
                        ▼                                        ▼
                 ┌──────────────┐                        ┌───────────────┐
                 │  Repository  │                        │  Channels     │
                 │  (query)     │                        │  (Slack/Email) │
                 └──────────────┘                        └───────────────┘
```

### 6.3 Dashboard Flow (On-Demand)

```
┌──────────┐     ┌──────────────┐     ┌────────────┐
│ Dashboard│────▶│   API Layer  │────▶│ Repository │──── Database
│ (browser)│     │   (HTTP)     │     │ (query)    │
└──────────┘     └──────────────┘     └────────────┘
```

### 6.4 Future Live Monitoring Integration

```
┌──────────────────┐     ┌──────────────┐     ┌────────────┐
│ Existing Live    │────▶│   API Layer  │────▶│ Repository │
│ Monitoring System│     │   (same API) │     │            │
└──────────────────┘     └──────────────┘     └────────────┘
```

The API doesn't change. The consumer changes. This is the architectural payoff of P7.

---

## 7. Error Handling Strategy

Errors are categorized by where they occur and how they're handled. The guiding rule: **fail locally, report globally, never cascade.**

| Error origin | Example | Handling |
|---|---|---|
| Source adapter | API timeout, rate limit, HTML structure change | Adapter raises typed exception → ingestion engine catches, logs, retries per policy, moves to next adapter. Other adapters are unaffected. |
| Normalizer | Unparseable date, missing required field | Normalizer skips the bad record, includes it in `NormalizationError` list → ingestion engine logs, continues with valid records. |
| Repository | DB connection failure, constraint violation | Repository raises → ingestion engine catches, marks source as failed in report. Partial writes are acceptable (upsert is idempotent, so re-running is safe). |
| Alert rule | Rule logic exception | Alert engine catches per-rule, logs, continues evaluating other rules. |
| Notification channel | Slack API down, email bounce | Dispatcher catches per-channel, logs, tries fallback channels if configured. |

**Observable health:** the `IngestionReport` returned by every ingest run should contain, per adapter: records fetched, records normalized, records upserted, errors encountered, duration. This is the system's primary health signal — if an adapter starts returning zero records or high error rates, that shows up in the report before it becomes a data gap.

---

## 8. Configuration & Dependency Injection

### 8.1 Config Structure

All configuration lives in a structured config object loaded from a YAML/TOML file (or environment variables for secrets). No component reads config files directly — config is injected.

```python
@dataclass
class AppConfig:
    database: DatabaseConfig
    adapters: dict[str, AdapterConfig]   # Keyed by source_name
    ingestion: IngestionConfig           # Schedule, retry policy, date range defaults
    alerting: AlertingConfig             # Evaluation window, enabled rules
    notification: NotificationConfig     # Channels, routing
    iv: IVConfig | None                  # Optional — IV provider settings
    api: APIConfig                       # Host, port, auth
```

### 8.2 DI Container / Wiring

A single top-level function (or class) assembles the entire dependency graph. This is the only place where concrete classes are instantiated. Every other module imports only ABCs.

```python
def build_application(config: AppConfig) -> Application:
    """The one place where concrete meets abstract.
    
    This function is the composition root. It instantiates every concrete
    class, wires them together, and returns the assembled application.
    """
    
    # Infrastructure
    clock = SystemClock()
    logger = build_logger(config)
    http_client = build_http_client(config)
    db = build_database(config.database)
    
    # Repository
    repository = PostgresEventRepository(db, logger)  # or SqliteEventRepository for dev
    alert_log = PostgresAlertLog(db, logger)
    
    # Source adapters
    adapters = [
        NSECircularAdapter(http_client, config.adapters["nse"], logger),
        BSECircularAdapter(http_client, config.adapters["bse"], logger),
        KRXCalendarAdapter(http_client, config.adapters["krx"], logger),
        CMECalendarAdapter(http_client, config.adapters["cme"], logger),
        EconCalendarAdapter(http_client, config.adapters["econ_calendar"], logger),
        FREDAdapter(http_client, config.adapters["fred"], logger),
        IANATimezoneAdapter(config.adapters["iana_tz"], logger),
    ]
    
    # Normalizers
    normalizer_registry = NormalizerRegistry({
        "nse_circular": NSENormalizer(),
        "bse_circular": BSENormalizer(),
        "krx_calendar": KRXNormalizer(),
        "cme_calendar": CMENormalizer(),
        "econ_calendar": EconCalendarNormalizer(),
        "fred_api": FREDNormalizer(),
        "iana_tz": IANATZNormalizer(),
    })
    
    # Ingestion
    ingestion_engine = IngestionEngine(
        adapters=adapters,
        normalizer_registry=normalizer_registry,
        repository=repository,
        clock=clock,
        logger=logger,
        retry_policy=config.ingestion.retry_policy,
    )
    
    # IV (optional)
    iv_provider = build_iv_provider(config.iv) if config.iv else None
    
    # Alert rules
    rules = [
        UpcomingHighPriorityReleaseRule(lookahead_days=1),
        ExpiryDayRule(lookahead_days=1),
        RevisedExpiryRule(),
        EconomicSurpriseRule(threshold_pct=1.0),
        # IVThresholdRule(thresholds=config.iv.thresholds) — only if iv_provider exists
    ]
    
    # Alert engine
    alert_engine = AlertEngine(
        rules=rules,
        repository=repository,
        alert_log=alert_log,
        clock=clock,
        iv_provider=iv_provider,
        logger=logger,
    )
    
    # Notification
    channels = build_notification_channels(config.notification, logger)
    dispatcher = NotificationDispatcher(channels, config.notification.routing, logger)
    
    # API
    api = build_api(repository, alert_engine, alert_log, iv_provider, config.api)
    
    return Application(
        ingestion_engine=ingestion_engine,
        alert_engine=alert_engine,
        dispatcher=dispatcher,
        api=api,
    )
```

**Why this matters:** if you want to swap Postgres for SQLite during development, you change one line in this function. If you want to add a new exchange, you add one adapter and one normalizer to the lists. Nothing else changes.

---

## 9. Testing Strategy

### 9.1 Test Pyramid

| Level | What it tests | Infrastructure needed | Count |
|---|---|---|---|
| Unit | Single component with faked dependencies | None | Majority of tests |
| Integration | Component + real dependency (e.g., repository + SQLite) | SQLite in-memory | Moderate |
| Contract | Source adapter against real external source (fragile, run sparingly) | Network | Few, run on schedule |
| End-to-end | Full pipeline: ingest → store → query → alert | Test DB | Few |

### 9.2 Unit Test Patterns

Every contract from §4 gets a fake implementation for testing:

```python
class FakeEventRepository(EventRepository):
    """In-memory repository for unit tests."""
    def __init__(self):
        self._events: dict[str, Event] = {}
    
    def upsert(self, events: list[Event]) -> UpsertResult: ...
    def query(self, filters: EventQuery) -> list[Event]: ...
    # etc.

class FakeClock(Clock):
    """Clock fixed at a given time. Tests set it to whatever they need."""
    def __init__(self, fixed_time: datetime.datetime): ...

class FakeHttpClient(HttpClient):
    """Returns canned responses. Tests load fixtures (raw JSON/HTML)."""
    def __init__(self, responses: dict[str, Response]): ...
```

**Example unit test — alert rule:**

```python
def test_upcoming_release_rule_fires_one_day_before():
    clock = FakeClock(fixed_time=datetime.datetime(2026, 8, 6, 12, 0, tzinfo=UTC))
    
    nfp_event = EconomicReleaseEvent(
        event_id="...",
        event_type=EventType.ECONOMIC_RELEASE,
        date=datetime.date(2026, 8, 7),  # Tomorrow relative to clock
        release_name="Nonfarm Payrolls",
        release_code="NFP",
        # ... other fields ...
    )
    
    rule = UpcomingHighPriorityReleaseRule(lookahead_days=1)
    alerts = rule.evaluate(events=[nfp_event], context=AlertContext(clock=clock))
    
    assert len(alerts) == 1
    assert alerts[0].severity == AlertSeverity.WARNING
```

No database, no network, no scheduler. The rule is tested in isolation against known inputs. This is what P3 looks like in practice.

### 9.3 Adapter Contract Tests

Source adapters talk to external systems that change without notice. Contract tests are integration tests that verify an adapter still works against the real source:

```python
@pytest.mark.contract
def test_nse_adapter_returns_holidays():
    """Verify NSE adapter can still fetch holidays from the real source.
    Run weekly, not on every commit.
    """
    adapter = NSECircularAdapter(
        http_client=RealHttpClient(),
        config=NSEAdapterConfig.from_env(),
        logger=NullLogger(),
    )
    results = adapter.fetch(FetchParams(
        date_range=DateRange(date(2026, 1, 1), date(2026, 12, 31)),
        event_types=[EventType.HOLIDAY],
    ))
    assert len(results) > 0  # NSE has holidays every year
```

These are fragile by nature (they depend on external systems), so they're marked separately and run on a schedule, not in the main CI pipeline. When they fail, it means the source's API or page structure has changed and the adapter needs updating — which is expected maintenance, not a bug.

### 9.4 Normalizer Fixture Tests

Normalizers are tested against saved snapshots of raw adapter output:

```
tests/
  fixtures/
    nse_circular/
      holidays_2026_raw.json      # Captured real output
      holidays_2026_expected.json  # Expected canonical events
    fred_api/
      cpi_2026_raw.json
      cpi_2026_expected.json
```

This decouples normalizer testing from adapter testing and from the real external source.

---

## 10. Extension Points — How to Add Things

This section is a checklist for the most common changes. If any of these require modifying an existing class, the design has regressed.

### 10.1 Adding a New Exchange

1. Write a new `SourceAdapter` subclass (e.g., `LSECalendarAdapter`)
2. Write a matching `EventNormalizer` subclass (e.g., `LSENormalizer`)
3. Add adapter config to `AppConfig.adapters`
4. Register both in the composition root (§8.2)
5. No changes to: repository, alert engine, API, dashboard, notification system

### 10.2 Adding a New Economic Release

1. Add the release code to the economic calendar adapter's config
2. If the release comes from a new source, write a new adapter + normalizer (as in 10.1)
3. If it comes from an existing source (e.g., same MarketWatch calendar), no code changes at all — just config

### 10.3 Adding a New Alert Rule

1. Write a new `AlertRule` subclass
2. Register it in the composition root's `rules` list
3. No changes to: alert engine, notification dispatcher, channels

### 10.4 Adding a New Notification Channel

1. Write a new `NotificationChannel` subclass (e.g., `TeamsChannel`)
2. Add routing config to `NotificationConfig.routing`
3. Register in the composition root
4. No changes to: alert engine, alert rules, other channels

### 10.5 Integrating Into a Live Monitoring System

1. Point the monitoring system at the existing API endpoints (§5.6)
2. Add a WebSocket or SSE endpoint to the API if the monitoring system needs push rather than poll
3. No changes to: ingestion, storage, alerting, notification

---

## 11. Package Layout

```
exchange_events/
├── domain/                         # §3 — Pure data types, no dependencies
│   ├── events.py                   # Event, HolidayEvent, ExpiryEvent, etc.
│   ├── alerts.py                   # Alert, AlertSeverity, AlertContext
│   ├── enums.py                    # EventType, SessionType
│   └── query.py                    # EventQuery, DateRange, FetchParams
│
├── contracts/                      # §4 — ABCs only, no implementations
│   ├── source_adapter.py
│   ├── normalizer.py
│   ├── repository.py
│   ├── alert_rule.py
│   ├── notification_channel.py
│   ├── iv_provider.py
│   ├── alert_log.py
│   └── clock.py
│
├── adapters/                       # §5.1 — Source adapter implementations
│   ├── nse_circular.py
│   ├── bse_circular.py
│   ├── krx_calendar.py
│   ├── cme_calendar.py
│   ├── econ_calendar.py
│   ├── fred_api.py
│   └── iana_timezone.py
│
├── normalizers/                    # §5.2 — Normalizer implementations
│   ├── nse_normalizer.py
│   ├── bse_normalizer.py
│   ├── krx_normalizer.py
│   ├── cme_normalizer.py
│   ├── econ_normalizer.py
│   ├── fred_normalizer.py
│   └── tz_normalizer.py
│
├── storage/                        # §5.3 — Repository implementations
│   ├── postgres_repository.py
│   ├── sqlite_repository.py        # Dev/test convenience
│   └── migrations/
│
├── ingestion/                      # §5.3 — Ingestion engine
│   ├── engine.py
│   ├── normalizer_registry.py
│   └── retry.py
│
├── alerting/                       # §5.4, §5.5 — Alert engine + rules
│   ├── engine.py
│   ├── dispatcher.py
│   ├── rules/
│   │   ├── upcoming_release.py
│   │   ├── expiry_day.py
│   │   ├── revised_expiry.py
│   │   ├── economic_surprise.py
│   │   └── iv_threshold.py
│   └── log.py                      # AlertLog implementations
│
├── notifications/                  # §4.5 — Channel implementations
│   ├── slack_channel.py
│   ├── email_channel.py
│   └── dashboard_channel.py
│
├── api/                            # §5.6 — HTTP layer
│   ├── app.py
│   ├── routes/
│   │   ├── events.py
│   │   ├── alerts.py
│   │   ├── calendar.py
│   │   └── iv.py
│   └── serializers.py
│
├── dashboard/                      # §5.7 — Frontend (separate build)
│   └── ...
│
├── config/                         # §8 — Configuration
│   ├── schema.py                   # AppConfig dataclass
│   ├── loader.py                   # YAML/env reader
│   └── defaults.yaml
│
├── wiring.py                       # §8.2 — Composition root (build_application)
├── main.py                         # Entry point
│
└── tests/
    ├── unit/
    │   ├── test_normalizers/
    │   ├── test_rules/
    │   ├── test_engine/
    │   └── test_dispatcher/
    ├── integration/
    │   └── test_repository/
    ├── contract/
    │   └── test_adapters/
    ├── e2e/
    ├── fakes/                      # Fake implementations of all contracts
    │   ├── fake_repository.py
    │   ├── fake_clock.py
    │   ├── fake_http_client.py
    │   └── fake_channel.py
    └── fixtures/
        ├── nse_circular/
        ├── fred_api/
        └── ...
```

**Import rule:** code in `adapters/` imports from `contracts/` and `domain/`. Code in `alerting/` imports from `contracts/` and `domain/`. Code in `api/` imports from `contracts/` and `domain/`. No package imports from a sibling concrete package. Only `wiring.py` imports from everywhere — it's the one file allowed to know about all concrete classes.

---

## 12. v1 Delivery Scope

Based on the requirements doc, v1 should deliver:

1. **Four exchange adapters** (NSE, BSE, KRX, CME) for holidays and expiries
2. **One economic calendar adapter** + FRED backfill adapter for the 7 listed releases
3. **IANA timezone adapter** for DST changes
4. **Normalizers** for all of the above
5. **Repository** (Postgres or SQLite — decision deferred to implementation)
6. **Ingestion engine** with retry and idempotent upsert
7. **API layer** with the endpoints listed in §5.6
8. **Dashboard** — calendar view, upcoming events, economic releases table
9. **Alert engine** with at least: upcoming-release rule, expiry-day rule
10. **One notification channel** (Slack or email — whichever is easier to wire into existing infrastructure)

**Deferred to v2:** IV threshold integration, advanced alert rules (economic surprise, revised expiry), additional notification channels, per-user subscription routing, historical IV overlay on dashboard.

---

## 13. Decisions Still Needed Before Implementation

| Decision | Impact | Who decides |
|---|---|---|
| Primary economic calendar data source (API vs. scraping, which provider) | Adapter design, ToS compliance, update latency | Source evaluation spike — §5 of requirements doc |
| Database choice (Postgres vs. SQLite for v1) | Repository implementation, deployment | Dev/infra |
| Notification channel for v1 (Slack vs. email) | Channel implementation | Team preference |
| IV data source and integration timeline | Whether IVThresholdProvider gets built in v1 | Scope call |
| Dashboard technology (React, plain HTML, etc.) | Frontend build process | Dev preference |
| Hosting/deployment model (bare metal, Docker, cloud) | Config, CI/CD, monitoring | Infra |
