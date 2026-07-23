"""In-memory IVThresholdProvider for tests (design doc §4.6)."""

from __future__ import annotations

import datetime

from exchange_events.contracts.iv_provider import IVThresholdProvider
from exchange_events.domain.iv import IVSnapshot


class FakeIVProvider(IVThresholdProvider):
    def __init__(self, snapshots: dict[tuple[str, str, datetime.date], IVSnapshot] | None = None):
        self._snapshots = dict(snapshots or {})

    def set(self, exchange: str, underlying: str, date: datetime.date, iv: float) -> None:
        self._snapshots[(exchange, underlying, date)] = IVSnapshot(
            exchange=exchange, underlying=underlying, date=date, iv=iv
        )

    def get_iv_snapshot(
        self, exchange: str, underlying: str, date: datetime.date
    ) -> IVSnapshot | None:
        return self._snapshots.get((exchange, underlying, date))

    def get_iv_series(
        self,
        exchange: str,
        underlying: str,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> list[IVSnapshot]:
        return [
            snap
            for (exch, und, day), snap in self._snapshots.items()
            if exch == exchange and und == underlying and date_from <= day <= date_to
        ]
