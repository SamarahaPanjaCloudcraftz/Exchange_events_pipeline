"""In-memory fake implementations of the contracts, for unit tests (§9.2)."""

from __future__ import annotations

from .alert_log import FakeAlertLog
from .channel import FakeChannel
from .clock import FakeClock
from .http import FakeHttpClient, RecordedCall
from .iv_provider import FakeIVProvider
from .normalizer import FakeNormalizer
from .repository import FakeEventRepository
from .smtp_transport import FakeSmtpTransport
from .source_adapter import FakeSourceAdapter

__all__ = [
    "FakeAlertLog",
    "FakeChannel",
    "FakeClock",
    "FakeHttpClient",
    "RecordedCall",
    "FakeEventRepository",
    "FakeSourceAdapter",
    "FakeNormalizer",
    "FakeIVProvider",
    "FakeSmtpTransport",
]
