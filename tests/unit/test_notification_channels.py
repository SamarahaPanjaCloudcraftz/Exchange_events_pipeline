"""Unit tests for notification channels (§4.5, §5.5) — Email, Teams, Dashboard."""

from __future__ import annotations

import datetime

import pytest

from exchange_events.contracts.notification_channel import DeliveryStatus, Recipient
from exchange_events.domain.alerts import Alert, AlertSeverity
from exchange_events.domain.errors import ChannelUnavailableError
from exchange_events.domain.events import HolidayEvent
from exchange_events.notifications.dashboard_channel import DashboardChannel
from exchange_events.notifications.email_channel import EmailChannel
from exchange_events.notifications.teams_channel import TeamsChannel
from tests.fakes.http import FakeHttpClient
from tests.fakes.smtp_transport import FakeSmtpTransport

pytestmark = pytest.mark.unit

UTC = datetime.UTC


def make_alert(severity: AlertSeverity = AlertSeverity.WARNING) -> Alert:
    event = HolidayEvent(
        source="nse", exchange="XNSE", date=datetime.date(2026, 1, 26), holiday_name="Republic Day"
    )
    return Alert(
        rule_id="expiry_day", event=event, severity=severity,
        title="Republic Day is a holiday", body="XNSE closed on 2026-01-26.",
        triggered_at=datetime.datetime(2026, 1, 25, 12, 0, tzinfo=UTC),
    )


# --- EmailChannel --------------------------------------------------------------------
def test_email_sends_one_message_per_recipient():
    smtp = FakeSmtpTransport()
    channel = EmailChannel(smtp, from_address="alerts@example.com")
    recipients = [Recipient(id="a", address="a@x.com"), Recipient(id="b", address="b@x.com")]
    results = channel.send(make_alert(), recipients)

    assert len(smtp.sent) == 2
    assert {m["To"] for m in smtp.sent} == {"a@x.com", "b@x.com"}
    assert all(r.succeeded for r in results)
    assert channel.channel_name() == "email"


def test_email_subject_includes_severity_prefix_type_tag_and_body():
    smtp = FakeSmtpTransport()
    channel = EmailChannel(smtp, from_address="alerts@example.com")
    channel.send(make_alert(AlertSeverity.CRITICAL), [Recipient(id="a", address="a@x.com")])
    msg = smtp.sent[0]
    assert msg["Subject"].startswith("[CRITICAL]")
    assert "[Holiday]" in msg["Subject"]  # category tag -- so recipients can tell at a glance
    assert "Republic Day is a holiday" in msg["Subject"]
    assert msg.get_content().strip() == "XNSE closed on 2026-01-26."
    assert msg["From"] == "alerts@example.com"


def test_email_per_recipient_failure_does_not_block_others():
    smtp = FakeSmtpTransport(fail_for={"bad@x.com"})
    channel = EmailChannel(smtp, from_address="alerts@example.com")
    recipients = [
        Recipient(id="good", address="good@x.com"),
        Recipient(id="bad", address="bad@x.com"),
    ]
    results = channel.send(make_alert(), recipients)

    by_id = {r.recipient_id: r for r in results}
    assert by_id["good"].status == DeliveryStatus.SUCCESS
    assert by_id["bad"].status == DeliveryStatus.FAILED
    assert len(smtp.sent) == 1  # only the good one actually sent


# --- TeamsChannel ----------------------------------------------------------------------
WEBHOOK = "https://outlook.office.com/webhook/fake"


def test_teams_posts_message_card_with_severity_color():
    http = FakeHttpClient()
    http.register_json(WEBHOOK, {"ok": True})
    channel = TeamsChannel(http, WEBHOOK)
    results = channel.send(make_alert(AlertSeverity.CRITICAL), [Recipient(id="team", address="x")])

    assert len(http.calls) == 1
    call = http.calls[0]
    assert call.method == "POST"
    assert call.json["@type"] == "MessageCard"
    assert call.json["themeColor"] == "D13438"  # critical color
    assert call.json["title"] == "Republic Day is a holiday"
    assert all(r.succeeded for r in results)
    assert channel.channel_name() == "teams"


def test_teams_card_includes_event_type_fact():
    """Without this, a recipient can't tell what kind of alert they're looking
    at (title wording alone doesn't reliably convey it, and rule_id is
    intentionally hidden -- see test_teams_card_omits_internal_rule_id)."""
    http = FakeHttpClient()
    http.register_json(WEBHOOK, {"ok": True})
    channel = TeamsChannel(http, WEBHOOK)
    channel.send(make_alert(), [Recipient(id="team", address="x")])
    facts = http.calls[0].json["sections"][0]["facts"]
    type_fact = next(f for f in facts if f["name"] == "Type")
    assert type_fact["value"] == "Holiday"


def test_teams_card_omits_internal_rule_id():
    """rule_id (e.g. "economic_release_proximity:2:1") is plumbing, not
    reader-facing -- must never appear in the delivered card."""
    http = FakeHttpClient()
    http.register_json(WEBHOOK, {"ok": True})
    channel = TeamsChannel(http, WEBHOOK)
    channel.send(make_alert(), [Recipient(id="team", address="x")])
    facts = http.calls[0].json["sections"][0]["facts"]
    assert not any(f["name"] == "Rule" for f in facts)
    assert not any("expiry_day" in str(f["value"]) for f in facts)


def test_teams_card_omits_text_section_when_body_empty():
    http = FakeHttpClient()
    http.register_json(WEBHOOK, {"ok": True})
    channel = TeamsChannel(http, WEBHOOK)
    alert = make_alert()
    object.__setattr__(alert, "body", "")
    channel.send(alert, [Recipient(id="team", address="x")])
    assert "text" not in http.calls[0].json


def test_teams_webhook_error_response_raises_channel_unavailable():
    http = FakeHttpClient()
    http.register_json(WEBHOOK, {"error": "bad request"}, status_code=400)
    channel = TeamsChannel(http, WEBHOOK)
    with pytest.raises(ChannelUnavailableError):
        channel.send(make_alert(), [Recipient(id="team", address="x")])


def test_teams_network_exception_raises_channel_unavailable():
    class ExplodingHttp(FakeHttpClient):
        def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    channel = TeamsChannel(ExplodingHttp(), WEBHOOK)
    with pytest.raises(ChannelUnavailableError, match="unreachable"):
        channel.send(make_alert(), [Recipient(id="team", address="x")])


def test_teams_returns_one_result_per_recipient():
    http = FakeHttpClient()
    http.register_json(WEBHOOK, {"ok": True})
    channel = TeamsChannel(http, WEBHOOK)
    recipients = [Recipient(id="a", address="x"), Recipient(id="b", address="y")]
    results = channel.send(make_alert(), recipients)
    assert {r.recipient_id for r in results} == {"a", "b"}
    assert len(http.calls) == 1  # single webhook POST regardless of recipient count


# --- DashboardChannel --------------------------------------------------------------------
def test_dashboard_records_and_always_succeeds():
    channel = DashboardChannel()
    recipients = [Recipient(id="all", address="dashboard")]
    results = channel.send(make_alert(), recipients)
    assert len(channel.delivered) == 1
    assert channel.delivered[0][0].title == "Republic Day is a holiday"
    assert all(r.succeeded for r in results)
    assert channel.channel_name() == "dashboard"
