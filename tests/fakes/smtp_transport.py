"""In-memory SmtpTransport for tests (design doc §9.2)."""

from __future__ import annotations

from email.message import EmailMessage

from exchange_events.notifications.smtp_transport import SmtpTransport


class FakeSmtpTransport(SmtpTransport):
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        """``fail_for``: a set of recipient addresses that raise on send (simulating
        a per-message SMTP failure, e.g. an invalid mailbox)."""
        self._fail_for = fail_for or set()
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        if message["To"] in self._fail_for:
            raise RuntimeError(f"SMTP rejected recipient: {message['To']}")
        self.sent.append(message)
