"""KRX adapter (design doc §5.1) — XKRX holidays + expiries.

**Structural stub — live fetch deferred** (per DECISIONS.md: KRX is future work,
after CME/NSE/BSE). This class is fully wired (implements the contract, has a
matching normalizer, registerable in the composition root) so KRX support is a
config/endpoint change away, never a redesign (P4) — but ``fetch`` returns no
records rather than calling a live endpoint.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import EventType
from ..domain.query import FetchParams
from .base import HttpSourceAdapter


class KRXAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "krx_calendar"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.HOLIDAY, EventType.EXPIRY]

    def supported_exchanges(self) -> list[str] | None:
        return ["XKRX"]

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        self._logger.info(
            "krx_calendar fetch skipped: live KRX integration is deferred (see DECISIONS.md)"
        )
        return []
