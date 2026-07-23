"""Source adapters (design doc §5.1) — one per external data source.

Priority order (per DECISIONS.md): CME live (production priority) > NSE live >
BSE live > KRX (deferred stub). IANA is fully live/offline.

Economic releases (actuals) use a waterfall of official sources, highest
reliability first: FRED > BLS > BEA (official/free, no anti-bot walls) > ISM
(best-effort, ISM Manufacturing PMI only, no free official source exists).
MarketWatch (econ) would supply forecasts, but is blocked by a DataDome CAPTCHA
wall from this environment; see its module docstring and DECISIONS.md
"Economic-release waterfall" — the current required scope is *released* data
only, which the waterfall covers without needing MarketWatch at all.

Forward scheduling (§ DECISIONS.md "Release-schedule adapter"): FREDAdapter's
``fred/release/dates`` covers NFP/CPI/PPI/PCE/JOLTS; FOMCScheduleAdapter reads
the Fed's own meeting calendar directly, since FOMC's FRED series updates daily
and isn't tied to specific meeting dates.
"""

from __future__ import annotations

from .base import HttpSourceAdapter
from .bea import BEAAdapter
from .bls import BLSAdapter
from .bse import BSEAdapter
from .cme import CMEAdapter
from .config import AdapterConfig
from .econ import EconCalendarAdapter
from .fomc import FOMCScheduleAdapter
from .fred import FREDAdapter
from .iana import IANATimezoneAdapter
from .ism import ISMAdapter
from .krx import KRXAdapter
from .nse import NSEAdapter

__all__ = [
    "AdapterConfig",
    "HttpSourceAdapter",
    "CMEAdapter",
    "NSEAdapter",
    "BSEAdapter",
    "KRXAdapter",
    "FREDAdapter",
    "BLSAdapter",
    "BEAAdapter",
    "ISMAdapter",
    "FOMCScheduleAdapter",
    "IANATimezoneAdapter",
    "EconCalendarAdapter",
]
