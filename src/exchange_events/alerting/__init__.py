"""Alert engine, rules, and notification dispatcher (design doc §5.4, §5.5)."""

from __future__ import annotations

from .dispatcher import NotificationDispatcher
from .engine import AlertEngine
from .routing import RouteRule, RoutingConfig

__all__ = ["AlertEngine", "NotificationDispatcher", "RoutingConfig", "RouteRule"]
