"""Unit tests for production infra concretes (SystemClock, RealHttpClient, loggers).

RealHttpClient is tested with an injected fake session and a no-op sleep, so the
retry/backoff logic and response mapping are exercised with no network and no delay.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import pytest
import requests

from exchange_events.domain.errors import SourceUnavailableError
from exchange_events.infra.clock import SystemClock
from exchange_events.infra.http import RealHttpClient
from exchange_events.infra.logging import NullLogger, StdLogger

pytestmark = pytest.mark.unit


# --- SystemClock -------------------------------------------------------------------
def test_system_clock_is_utc_aware():
    now = SystemClock().now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.timedelta(0)


def test_system_clock_today_matches_now_date():
    clk = SystemClock()
    assert clk.today_utc() == clk.now_utc().date()


# --- RealHttpClient test doubles ---------------------------------------------------
class _RawResp:
    def __init__(self, status_code: int, url: str = "https://x", content: bytes = b"",
                 headers: dict | None = None, encoding: str = "utf-8") -> None:
        self.status_code = status_code
        self.url = url
        self.content = content
        self.headers = headers or {}
        self.encoding = encoding


class _FakeSession:
    def __init__(self, script: list[Any]) -> None:
        self.headers: dict[str, str] = {}
        self._script = list(script)
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append((method, url, kwargs))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(session: _FakeSession, **kw: Any) -> RealHttpClient:
    sleeps: list[float] = []
    kw.setdefault("sleep", sleeps.append)
    client = RealHttpClient(session=session, **kw)
    client._sleeps = sleeps  # type: ignore[attr-defined]
    return client


def test_real_http_get_maps_response():
    sess = _FakeSession([_RawResp(200, url="https://api/x", content=b'{"a": 1}')])
    resp = _client(sess).get("https://api/x")
    assert resp.status_code == 200
    assert resp.url == "https://api/x"
    assert resp.json() == {"a": 1}


def test_real_http_applies_browser_headers():
    sess = _FakeSession([_RawResp(200)])
    _client(sess)
    assert "User-Agent" in sess.headers
    assert "Mozilla" in sess.headers["User-Agent"]


def test_real_http_retries_on_503_then_succeeds():
    sess = _FakeSession([_RawResp(503), _RawResp(503), _RawResp(200, content=b"ok")])
    client = _client(sess, max_retries=3)
    resp = client.get("https://api/x")
    assert resp.status_code == 200
    assert len(sess.calls) == 3
    assert len(client._sleeps) == 2  # type: ignore[attr-defined]


def test_real_http_returns_last_response_when_retries_exhausted():
    sess = _FakeSession([_RawResp(503), _RawResp(503)])
    resp = _client(sess, max_retries=1).get("https://api/x")
    assert resp.status_code == 503
    assert len(sess.calls) == 2


def test_real_http_raises_on_persistent_connection_error():
    err = requests.ConnectionError("refused")
    sess = _FakeSession([err, err])
    with pytest.raises(SourceUnavailableError, match="failed"):
        _client(sess, max_retries=1).get("https://api/x")


def test_real_http_recovers_after_connection_error():
    sess = _FakeSession([requests.ConnectionError("blip"), _RawResp(200, content=b"ok")])
    resp = _client(sess, max_retries=2).get("https://api/x")
    assert resp.status_code == 200


def test_real_http_post_passes_json_through():
    sess = _FakeSession([_RawResp(200, content=b"ok")])
    _client(sess).post("https://hook", json={"msg": "hi"})
    method, url, kwargs = sess.calls[0]
    assert method == "POST"
    assert kwargs["json"] == {"msg": "hi"}


def test_real_http_backoff_is_capped():
    sess = _FakeSession([_RawResp(500), _RawResp(500), _RawResp(500), _RawResp(200)])
    client = _client(sess, max_retries=3, backoff_base=1.0, backoff_max=2.5)
    client.get("https://api/x")
    assert client._sleeps == [1.0, 2.0, 2.5]  # type: ignore[attr-defined]


# --- Loggers -----------------------------------------------------------------------
def test_null_logger_is_silent(caplog):
    with caplog.at_level(logging.DEBUG):
        log = NullLogger()
        log.info("hello", key="value")
        log.error("boom")
    assert caplog.records == []


def test_std_logger_emits_with_fields(caplog):
    log = StdLogger(name="test_std", level=logging.INFO)
    with caplog.at_level(logging.INFO, logger="test_std"):
        log.info("ingested", source="cme", count=42)
    assert len(caplog.records) == 1
    assert "ingested" in caplog.text
    assert "source='cme'" in caplog.text
    assert "count=42" in caplog.text
