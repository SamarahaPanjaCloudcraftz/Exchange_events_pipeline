"""Structured logger contract (infrastructure interface).

Components receive a ``Logger`` and emit structured records (a message plus
arbitrary keyword fields). Tests inject a ``NullLogger``; production wires a
``StdLogger`` (both in ``infra/``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Logger(ABC):
    @abstractmethod
    def debug(self, message: str, **fields: Any) -> None: ...

    @abstractmethod
    def info(self, message: str, **fields: Any) -> None: ...

    @abstractmethod
    def warning(self, message: str, **fields: Any) -> None: ...

    @abstractmethod
    def error(self, message: str, **fields: Any) -> None: ...
