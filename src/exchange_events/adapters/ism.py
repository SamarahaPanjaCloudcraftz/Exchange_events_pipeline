"""ISM adapter (design doc §5.1) — best-effort ISM Manufacturing PMI only.

**Not part of the official-statistics waterfall tiers.** ISM's Manufacturing PMI
is licensed/proprietary data — FRED discontinued carrying it in 2016, and no
free/official government source publishes it (see DECISIONS.md "Economic-release
waterfall"). This adapter is scoped to exactly that one release and is
deliberately **provider-agnostic**: no default endpoint ships, because no specific
aggregator's free-tier access has been verified live in this environment (Trading
Economics, Finnhub, Nasdaq Data Link, and Financial Modeling Prep were all
identified as candidates worth evaluating for pricing/ToS/field coverage — none
confirmed). Both the URL and the response field names are config-driven so
wiring in whichever provider is actually chosen is a config change, not a code
change (P4) — see ``config.options`` below.

Without a configured URL, ``fetch()`` raises :class:`SourceUnavailableError`
cleanly — the ingestion engine isolates this per-source failure exactly like any
other adapter outage, so ISM being unconfigured never blocks the other six
releases (§7 "fail locally, report globally, never cascade").

Required config once a provider is chosen:
    config.urls["ism"]                       — the provider's endpoint
    config.api_key                           — the provider's API key, if any
    config.options["field_map"]              — maps our field names to the
                                                provider's JSON field names, e.g.
                                                {"date": "releaseDate", "actual": "actual"}
    config.options["indicator_match"]        — {field_name: expected_value} used
                                                to pick ISM Manufacturing PMI out of
                                                a mixed-indicator response, e.g.
                                                {"event": "ISM Manufacturing PMI"}

Emits the raw schema documented in ``normalizers/government_release.py``.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import EventType
from ..domain.errors import SourceUnavailableError
from ..domain.query import FetchParams
from .base import HttpSourceAdapter

RELEASE_CODE = "ISM_PMI"
RELEASE_NAME = "ISM Manufacturing PMI"

_DEFAULT_FIELD_MAP = {"date": "date", "actual": "value"}


class ISMAdapter(HttpSourceAdapter):
    def source_name(self) -> str:
        return "ism_pmi"

    def supported_event_types(self) -> list[EventType]:
        return [EventType.ECONOMIC_RELEASE]

    def supported_exchanges(self) -> list[str] | None:
        return None

    def fetch(self, params: FetchParams) -> list[dict[str, Any]]:
        url = self._config.url("ism", "")
        if not url:
            raise SourceUnavailableError(
                "ism_pmi: no provider configured (best-effort source — see "
                "adapters/ism.py docstring for candidate providers to evaluate)"
            )
        field_map = self._config.option("field_map") or _DEFAULT_FIELD_MAP
        indicator_match = self._config.option("indicator_match") or {}
        query = dict(self._config.params)
        if self._config.api_key:
            query.setdefault("apikey", self._config.api_key)
        payload = self._get_json(url, query)
        items = payload if isinstance(payload, list) else payload.get("data", [])
        return self._parse(items, field_map, indicator_match, params)

    @staticmethod
    def _parse(
        items: list[dict[str, Any]],
        field_map: dict[str, str],
        indicator_match: dict[str, Any],
        params: FetchParams,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        previous: Any = None
        for item in items:
            if any(item.get(k) != v for k, v in indicator_match.items()):
                continue
            date_val = item.get(field_map.get("date", "date"))
            actual_val = item.get(field_map.get("actual", "value"))
            if not date_val:
                continue
            out.append(
                {
                    "release_code": RELEASE_CODE,
                    "release_name": RELEASE_NAME,
                    "date": str(date_val),
                    "actual": actual_val,
                    "previous": previous,
                    "unit": "index",
                    "agency": "ISM",
                    "id": f"ism:{date_val}",
                }
            )
            previous = actual_val
        return out
