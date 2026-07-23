"""Production loggers (implement contracts.Logger)."""

from __future__ import annotations

import logging
from typing import Any

from ..contracts.logger import Logger


class NullLogger(Logger):
    """Discards everything. Default for tests and contract-test adapters."""

    def debug(self, message: str, **fields: Any) -> None: ...
    def info(self, message: str, **fields: Any) -> None: ...
    def warning(self, message: str, **fields: Any) -> None: ...
    def error(self, message: str, **fields: Any) -> None: ...


class StdLogger(Logger):
    """Wraps the stdlib ``logging`` module, appending structured key=value fields."""

    def __init__(self, name: str = "exchange_events", level: int = logging.INFO) -> None:
        self._log = logging.getLogger(name)
        self._log.setLevel(level)

    @staticmethod
    def _format(message: str, fields: dict[str, Any]) -> str:
        if not fields:
            return message
        extra = " ".join(f"{k}={v!r}" for k, v in fields.items())
        return f"{message} | {extra}"

    def debug(self, message: str, **fields: Any) -> None:
        self._log.debug(self._format(message, fields))

    def info(self, message: str, **fields: Any) -> None:
        self._log.info(self._format(message, fields))

    def warning(self, message: str, **fields: Any) -> None:
        self._log.warning(self._format(message, fields))

    def error(self, message: str, **fields: Any) -> None:
        self._log.error(self._format(message, fields))
