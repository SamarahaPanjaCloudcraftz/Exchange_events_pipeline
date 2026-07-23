"""Composition root (design doc §8.2).

The one place where concrete meets abstract. Every other module in this
codebase imports only ``contracts/`` and ``domain/``; this file is the sole
exception — it is allowed to know about every concrete class because its job is
to instantiate and wire them together. Swapping SQLite for Postgres, or adding a
new adapter/rule/channel, means editing exactly this function (plus, for a truly
new component, writing that one new class) — nothing else changes (P4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapters import (
    AdapterConfig,
    BEAAdapter,
    BLSAdapter,
    BSEAdapter,
    CMEAdapter,
    EconCalendarAdapter,
    FOMCScheduleAdapter,
    FREDAdapter,
    IANATimezoneAdapter,
    ISMAdapter,
    KRXAdapter,
    NSEAdapter,
)
from .alerting import AlertEngine, NotificationDispatcher, RouteRule, RoutingConfig
from .alerting.rules import (
    DstShiftProximityRule,
    EconomicReleaseProximityRule,
    ExpiryProximityRule,
    HolidayProximityRule,
    IVThresholdRule,
)
from .config.schema import AdapterConfigModel, AppConfig
from .contracts.alert_log import AlertLog
from .contracts.alert_rule import AlertRule
from .contracts.clock import Clock
from .contracts.http_client import HttpClient
from .contracts.iv_provider import IVThresholdProvider
from .contracts.logger import Logger
from .contracts.notification_channel import NotificationChannel, Recipient
from .contracts.repository import EventRepository
from .contracts.source_adapter import SourceAdapter
from .domain.alerts import AlertSeverity
from .domain.enums import EventType
from .domain.errors import ConfigError
from .infra.clock import SystemClock
from .infra.http import RealHttpClient
from .infra.logging import StdLogger
from .ingestion.engine import IngestionEngine
from .ingestion.normalizer_registry import NormalizerRegistry
from .ingestion.retry import RetryPolicy
from .normalizers import (
    BEANormalizer,
    BLSNormalizer,
    BSENormalizer,
    CMENormalizer,
    EconCalendarNormalizer,
    FOMCScheduleNormalizer,
    FREDNormalizer,
    ISMNormalizer,
    KRXNormalizer,
    NSENormalizer,
    TimezoneNormalizer,
)
from .notifications.dashboard_channel import DashboardChannel
from .notifications.email_channel import EmailChannel
from .notifications.smtp_transport import SmtplibTransport
from .notifications.teams_channel import TeamsChannel


@dataclass
class Application:
    """The fully-wired application, ready to ingest/alert/serve."""

    ingestion_engine: IngestionEngine
    alert_engine: AlertEngine
    dispatcher: NotificationDispatcher
    repository: EventRepository
    alert_log: AlertLog
    config: AppConfig
    clock: Clock
    logger: Logger
    iv_provider: IVThresholdProvider | None = None


def build_application(config: AppConfig) -> Application:
    """Composition root (§8.2) — instantiate every concrete class and wire it up."""
    clock = SystemClock()
    logger = StdLogger()
    http_client = RealHttpClient()

    repository, alert_log = _build_storage(config, clock, logger)
    ingestion_engine = _build_ingestion_engine(config, http_client, repository, clock, logger)
    iv_provider = _build_iv_provider(config, logger)
    alert_engine = _build_alert_engine(config, repository, alert_log, clock, logger, iv_provider)
    dispatcher = _build_dispatcher(config, http_client, logger)

    return Application(
        ingestion_engine=ingestion_engine,
        alert_engine=alert_engine,
        dispatcher=dispatcher,
        repository=repository,
        alert_log=alert_log,
        config=config,
        clock=clock,
        logger=logger,
        iv_provider=iv_provider,
    )


# --- storage -------------------------------------------------------------------------
def _build_storage(
    config: AppConfig, clock: Clock, logger: Logger
) -> tuple[EventRepository, AlertLog]:
    if config.database.backend == "postgres":
        if not config.database.postgres_dsn:
            raise ConfigError(
                "database.backend is 'postgres' but no DSN is configured "
                "(set EXCHANGE_EVENTS_PG_DSN)"
            )
        from .storage.alert_log import PostgresAlertLog
        from .storage.postgres_repository import PostgresEventRepository

        dsn = config.database.postgres_dsn
        return (
            PostgresEventRepository(dsn, clock=clock, logger=logger),
            PostgresAlertLog(dsn, clock=clock, logger=logger),
        )

    from .storage import SqliteAlertLog, SqliteEventRepository

    path = config.database.sqlite_path
    return (
        SqliteEventRepository(path, clock=clock, logger=logger),
        SqliteAlertLog(path, clock=clock, logger=logger),
    )


# --- adapters + normalizers + ingestion -----------------------------------------------
def _adapter_config(config: AppConfig, source_name: str) -> AdapterConfig:
    model = config.adapters.get(source_name) or AdapterConfigModel()
    return AdapterConfig(
        urls=dict(model.urls),
        headers=dict(model.headers),
        params=dict(model.params),
        timeout=model.timeout,
        api_key=model.api_key,
        options=dict(model.options),
    )


def _build_ingestion_engine(
    config: AppConfig,
    http_client: HttpClient,
    repository: EventRepository,
    clock: Clock,
    logger: Logger,
) -> IngestionEngine:
    adapters: list[SourceAdapter] = [
        CMEAdapter(http_client, _adapter_config(config, "cme_calendar"), logger),
        NSEAdapter(http_client, _adapter_config(config, "nse_circular"), logger),
        BSEAdapter(http_client, _adapter_config(config, "bse_circular"), logger),
        KRXAdapter(http_client, _adapter_config(config, "krx_calendar"), logger),
        IANATimezoneAdapter(_adapter_config(config, "iana_tz"), logger),
        # Economic-release waterfall (DECISIONS.md "Economic-release waterfall"),
        # highest reliability first: FRED > BLS > BEA (official, free, no anti-bot
        # walls) > ISM (best-effort, ISM Manufacturing PMI only). Each is a fully
        # independent adapter/source; domain.reconcile_economic_releases merges
        # same-(release_code, date) results at read time (API routes, alert engine)
        # rather than the ingestion engine picking a single "winner" source.
        FREDAdapter(http_client, _adapter_config(config, "fred_api"), logger),
        BLSAdapter(http_client, _adapter_config(config, "bls_api"), logger),
        BEAAdapter(http_client, _adapter_config(config, "bea_api"), logger),
        ISMAdapter(http_client, _adapter_config(config, "ism_pmi"), logger),
        # Forward FOMC meeting calendar — separate from FRED's generic schedule
        # mechanism (DFEDTARU's own FRED release updates daily, unrelated to
        # specific meeting dates; see adapters/fomc.py + skip_schedule in
        # adapters/fred.py). Reads the Fed's own published calendar directly.
        FOMCScheduleAdapter(http_client, _adapter_config(config, "fomc_schedule"), logger),
        # MarketWatch would supply forecasts, but is blocked by a DataDome CAPTCHA
        # wall from this environment (see adapters/econ.py). Left wired — the
        # ingestion engine isolates its per-run failure like any other adapter
        # outage (§7) — so it activates automatically the moment it's reachable.
        EconCalendarAdapter(http_client, _adapter_config(config, "econ_calendar"), logger),
    ]
    normalizer_registry = NormalizerRegistry.from_list([
        CMENormalizer(), NSENormalizer(), BSENormalizer(), KRXNormalizer(),
        TimezoneNormalizer(), FREDNormalizer(), BLSNormalizer(), BEANormalizer(),
        ISMNormalizer(), FOMCScheduleNormalizer(), EconCalendarNormalizer(),
    ])
    retry_policy = RetryPolicy(
        max_retries=config.ingestion.max_retries,
        backoff_base_seconds=config.ingestion.backoff_base_seconds,
        backoff_max_seconds=config.ingestion.backoff_max_seconds,
    )
    return IngestionEngine(
        adapters=adapters,
        normalizer_registry=normalizer_registry,
        repository=repository,
        clock=clock,
        logger=logger,
        retry_policy=retry_policy,
    )


# --- IV provider (optional, v2-scoped — see DECISIONS.md) -----------------------------
def _build_iv_provider(config: AppConfig, logger: Logger) -> IVThresholdProvider | None:
    if config.iv.enabled:
        logger.warning(
            "iv.enabled=true but no concrete IVThresholdProvider ships in this build "
            "(deferred to v2 per DECISIONS.md) — IVThresholdRule will not be registered"
        )
    return None


# --- alert engine + rules --------------------------------------------------------------
def _build_alert_engine(
    config: AppConfig,
    repository: EventRepository,
    alert_log: AlertLog,
    clock: Clock,
    logger: Logger,
    iv_provider: IVThresholdProvider | None,
) -> AlertEngine:
    rules: list[AlertRule] = [
        HolidayProximityRule(),
        DstShiftProximityRule(
            warning_days=config.alerting.dst_warning_days,
            critical_days=config.alerting.dst_critical_days,
        ),
        ExpiryProximityRule(warning_days=config.alerting.expiry_warning_days),
        EconomicReleaseProximityRule(
            warning_days=config.alerting.economic_release_warning_days,
            critical_days=config.alerting.economic_release_critical_days,
        ),
    ]
    if iv_provider is not None:
        rules.append(
            IVThresholdRule(
                thresholds=dict(config.iv.thresholds),
                default_threshold=config.iv.default_threshold,
            )
        )
    return AlertEngine(
        rules=rules,
        repository=repository,
        alert_log=alert_log,
        clock=clock,
        logger=logger,
        iv_provider=iv_provider,
        lookback_days=config.alerting.lookback_days,
        lookahead_days=config.alerting.lookahead_days,
    )


# --- notification dispatcher + channels ------------------------------------------------
def _build_dispatcher(
    config: AppConfig, http_client: HttpClient, logger: Logger
) -> NotificationDispatcher:
    enabled = set(config.notification.enabled_channels)
    channels: list[NotificationChannel] = []

    email_cfg = config.notification.email
    if "email" in enabled and email_cfg.smtp_host and email_cfg.from_address:
        transport = SmtplibTransport(
            email_cfg.smtp_host,
            email_cfg.smtp_port,
            username=email_cfg.smtp_username,
            password=email_cfg.smtp_password,
        )
        channels.append(EmailChannel(transport, email_cfg.from_address, logger))
    elif "email" in enabled:
        logger.warning("email channel enabled but smtp_host/from_address not configured")

    teams_cfg = config.notification.teams
    if "teams" in enabled and teams_cfg.webhook_url:
        channels.append(TeamsChannel(http_client, teams_cfg.webhook_url, logger))
    elif "teams" in enabled:
        logger.warning("teams channel enabled but webhook_url not configured")

    if "dashboard" in enabled:
        channels.append(DashboardChannel(logger))

    routing_config = _build_routing_config(config)
    return NotificationDispatcher(channels=channels, routing_config=routing_config, logger=logger)


def _build_routing_config(config: AppConfig) -> RoutingConfig:
    routes = [
        RouteRule(
            severity=AlertSeverity(r.severity) if r.severity else None,
            event_types=[EventType(t) for t in r.event_types] if r.event_types else None,
            channels=list(r.channels),
            recipients=list(r.recipients),
        )
        for r in config.notification.routes
    ]
    recipient_groups = {
        name: [
            Recipient(id=r.id, address=r.address, display_name=r.display_name) for r in group
        ]
        for name, group in config.notification.recipient_groups.items()
    }
    return RoutingConfig(routes=routes, recipient_groups=recipient_groups)
