"""BaseNormalizer — encodes the partial-success contract once (design doc §5.2).

Concrete normalizers implement ``_normalize_one`` (raw dict -> Event / list /
None) and ``target_source``. The base loop turns any per-record failure into a
captured :class:`NormalizationError` and keeps going, so one bad record never
sinks a whole batch.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from ..contracts.normalizer import EventNormalizer, NormalizationResult
from ..domain.errors import NormalizationError
from ..domain.events import Event


class BaseNormalizer(EventNormalizer):
    def normalize(
        self, raw_records: list[dict[str, Any]], source_name: str
    ) -> NormalizationResult:
        events: list[Event] = []
        errors: list[NormalizationError] = []
        for record in raw_records:
            try:
                produced = self._normalize_one(record, source_name)
            except NormalizationError as err:
                if err.raw_record is None:
                    err.raw_record = record
                if err.source is None:
                    err.source = source_name
                errors.append(err)
                continue
            except Exception as exc:  # noqa: BLE001 - any parse bug becomes a captured error
                errors.append(
                    NormalizationError(str(exc), raw_record=record, source=source_name)
                )
                continue
            if produced is None:
                continue
            if isinstance(produced, list):
                events.extend(produced)
            else:
                events.append(produced)
        return NormalizationResult(events=events, errors=errors)

    @abstractmethod
    def _normalize_one(
        self, record: dict[str, Any], source_name: str
    ) -> Event | list[Event] | None:
        """Transform one raw record. Return an event, a list, or None to skip."""
        ...
