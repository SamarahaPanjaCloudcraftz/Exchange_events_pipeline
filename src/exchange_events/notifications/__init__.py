"""Notification channel implementations (design doc §4.5) — Email, Teams, Dashboard."""

from __future__ import annotations

from .dashboard_channel import DashboardChannel
from .email_channel import EmailChannel
from .smtp_transport import SmtplibTransport, SmtpTransport
from .teams_channel import TeamsChannel

__all__ = [
    "EmailChannel",
    "SmtpTransport",
    "SmtplibTransport",
    "TeamsChannel",
    "DashboardChannel",
]
