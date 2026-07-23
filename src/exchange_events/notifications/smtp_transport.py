"""SMTP transport abstraction used by ``EmailChannel`` (design doc §4.5, §9.2).

A small, channel-local contract (not a top-level system contract like
``HttpClient``/``Clock`` — this abstraction only matters to the email channel).
Injected so ``EmailChannel`` is unit-testable without a real mail server.
"""

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage


class SmtpTransport(ABC):
    @abstractmethod
    def send(self, message: EmailMessage) -> None:
        """Send a fully-formed email message."""
        ...


class SmtplibTransport(SmtpTransport):
    """Production transport: Python stdlib ``smtplib`` over STARTTLS."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        *,
        username: str | None = None,
        password: str | None = None,
        use_starttls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_starttls = use_starttls
        self._timeout = timeout

    def send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            if self._use_starttls:
                smtp.starttls()
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(message)
