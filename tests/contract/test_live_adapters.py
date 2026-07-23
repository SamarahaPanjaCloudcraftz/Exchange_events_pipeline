"""Contract tests — adapters against real external sources (design doc §9.3).

Excluded from the default test run (`addopts = "-m 'not contract'"` in
pyproject.toml); run explicitly with ``pytest -m contract``. These are expected to
be fragile and are meant to run on a schedule against a production-like host, not
on every commit — a failure here means the source changed or is blocking us, which
is expected maintenance, not necessarily a code bug (§9.3).

**Environment findings (2026-07-21, recorded in DECISIONS.md), per source:**

* **NSE — passes live from this sandbox.** The session-warm-up + browser-header
  design successfully reaches the real holiday endpoint.
* **CME — passes live from this sandbox (2026-07-22), given ``CME_API_ID`` /
  ``CME_API_SECRET``.** The old ``cmegroup.com/CmeWS/mvc/`` AJAX endpoints are
  blocked domain-wide (confirmed even plain static pages 403); replaced with
  CME's own free, OAuth-authenticated Reference Data API v3
  (``refdata.api.cmegroup.com``), which is genuinely reachable here — see
  ``adapters/cme.py`` module docstring and DECISIONS.md "CME Reference Data API".
* **BSE — xfails: HTTP 200 with a soft-404 HTML body** (classic-ASP 404 page),
  i.e. the guessed endpoint path is stale/wrong — a URL-discovery task, not a
  bot block. See ``adapters/bse.py`` module docstring.
* **MarketWatch (econ_calendar) — xfails: HTTP 401 behind a DataDome
  JavaScript challenge.** Cannot be solved by header/session tuning; needs a
  headless-browser fetch layer or an unblocking proxy before it can run live.
* **FRED — expected to pass everywhere**, given a valid ``FRED_API_KEY``; it is
  a plain keyed API with no anti-bot layer.

Before production go-live: (1) capture BSE's real endpoint URLs and update
``adapters/bse.py``; (2) decide on a DataDome-capable fetch path for
MarketWatch, or accept FRED/CME-only actuals coverage in the interim.
"""

from __future__ import annotations

import datetime
import os

import pytest

from exchange_events.adapters.bse import BSEAdapter
from exchange_events.adapters.cme import CMEAdapter
from exchange_events.adapters.config import AdapterConfig
from exchange_events.adapters.econ import EconCalendarAdapter
from exchange_events.adapters.fred import FREDAdapter
from exchange_events.adapters.nse import NSEAdapter
from exchange_events.domain.enums import EventType
from exchange_events.domain.errors import SourceUnavailableError
from exchange_events.domain.query import DateRange, FetchParams
from exchange_events.infra.http import RealHttpClient

pytestmark = pytest.mark.contract

_THIS_YEAR = FetchParams(
    date_range=DateRange(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)),
    event_types=[EventType.HOLIDAY],
)


@pytest.mark.skipif(
    not (os.environ.get("CME_API_ID") and os.environ.get("CME_API_SECRET")),
    reason="CME_API_ID/CME_API_SECRET not set",
)
def test_cme_adapter_reaches_live_endpoint():
    """CME Reference Data API v3 — passes live given real OAuth credentials
    (see module docstring; this is a different, unblocked host from the old
    cmegroup.com AJAX endpoints)."""
    ad = CMEAdapter(
        RealHttpClient(),
        AdapterConfig(
            api_key=os.environ["CME_API_ID"],
            options={"api_secret": os.environ["CME_API_SECRET"]},
        ),
    )
    records = ad.fetch(_THIS_YEAR)
    assert len(records) > 0


def test_nse_adapter_reaches_live_endpoint():
    """NSE holiday endpoint. Known-blocked from this sandbox (see module docstring)."""
    ad = NSEAdapter(RealHttpClient())
    try:
        records = ad.fetch(_THIS_YEAR)
    except SourceUnavailableError as exc:
        pytest.xfail(f"NSE endpoint unreachable from this environment: {exc}")
    else:
        assert len(records) > 0


def test_bse_adapter_reaches_live_endpoint():
    ad = BSEAdapter(RealHttpClient())
    try:
        records = ad.fetch(_THIS_YEAR)
    except SourceUnavailableError as exc:
        pytest.xfail(f"BSE endpoint unreachable from this environment: {exc}")
    else:
        assert len(records) > 0


def test_econ_calendar_adapter_reaches_live_page():
    """MarketWatch calendar page. Known-blocked by DataDome (see module docstring)."""
    ad = EconCalendarAdapter(RealHttpClient())
    try:
        records = ad.fetch(_THIS_YEAR)
    except SourceUnavailableError as exc:
        pytest.xfail(f"MarketWatch page unreachable from this environment: {exc}")
    else:
        assert len(records) > 0


@pytest.mark.skipif(not os.environ.get("FRED_API_KEY"), reason="FRED_API_KEY not set")
def test_fred_adapter_reaches_live_api():
    ad = FREDAdapter(RealHttpClient(), AdapterConfig(api_key=os.environ["FRED_API_KEY"]))
    records = ad.fetch(_THIS_YEAR)
    assert len(records) > 0


def test_cli_full_ingest_touches_every_adapter_over_real_network(tmp_path, capsys):
    """The CLI's `ingest` with no --source runs every adapter over the real
    network (wiring.py always injects RealHttpClient — there is no offline
    mode for a full run). Documents the expected mixed outcome from this
    sandbox: iana_tz (fully offline) succeeds; CME/BSE/MarketWatch are
    expected to fail per the module-docstring findings; NSE may pass; FRED
    fails without a key; KRX is a deliberate no-op stub. The CLI must still
    print one line per adapter and exit non-zero when any source fails, so an
    operator/cron sees the failure.
    """
    from exchange_events.main import main

    cfg = tmp_path / "config.toml"
    db = tmp_path / "ee.db"
    cfg.write_text(
        f'[database]\nbackend = "sqlite"\nsqlite_path = "{db}"\n', encoding="utf-8"
    )
    code = main([
        "--config", str(cfg), "ingest", "--from", "2026-01-01", "--to", "2026-01-31",
    ])
    out = capsys.readouterr().out
    for source in (
        "cme_calendar", "nse_circular", "bse_circular", "krx_calendar",
        "fred_api", "iana_tz", "econ_calendar",
    ):
        assert f"[{source}]" in out
    assert "[iana_tz] fetched=" in out and "(OK)" in out
    assert code == 1  # at least one live source is expected to fail from this sandbox
