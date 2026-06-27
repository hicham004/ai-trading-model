"""Tests for the Telegram notifier (offline; mock transport, no network).

Covers message formatting, missing-credentials no-op, secret redaction, and
dedup/rate-limiting. No real token, chat id, or network is ever used.
"""

from __future__ import annotations

import pytest

from app.notify.telegram import (
    EVENT_LABELS,
    NotifyResult,
    TelegramNotifier,
    format_message,
    redact,
)


class RecordingTransport:
    """A mock transport that records calls and returns a canned response."""

    def __init__(self, status: int = 200, body: str = "ok"):
        self.calls: list[tuple[str, dict]] = []
        self._status = status
        self._body = body

    def __call__(self, url: str, payload: dict):
        self.calls.append((url, payload))
        return self._status, self._body


# --- formatting -----------------------------------------------------------

def test_format_message_known_event_includes_label_and_fields():
    msg = format_message("ci_fail", repo="o/r", title="CI failed", url="http://x/pr/1")
    assert "CI passed" not in msg
    assert EVENT_LABELS["ci_fail"] in msg
    assert "o/r" in msg
    assert "CI failed" in msg
    assert "http://x/pr/1" in msg


def test_format_message_unknown_event_falls_back_to_name():
    msg = format_message("totally_new_event", title="hi")
    assert msg.startswith("totally_new_event")
    assert "hi" in msg


def test_format_message_minimal_is_just_label():
    assert format_message("ci_pass") == EVENT_LABELS["ci_pass"]


# --- missing credentials --------------------------------------------------

def test_send_skips_cleanly_without_credentials():
    transport = RecordingTransport()
    n = TelegramNotifier(token=None, chat_id=None, transport=transport)
    result = n.send("hello")
    assert isinstance(result, NotifyResult)
    assert result.ok is False
    assert result.skipped == "missing-credentials"
    assert transport.calls == []  # never hit the network


def test_send_skips_when_only_token_present():
    transport = RecordingTransport()
    n = TelegramNotifier(token="abc", chat_id=None, transport=transport)
    assert n.send("hello").skipped == "missing-credentials"
    assert transport.calls == []


def test_from_env_dry_run_does_not_send():
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c", "TELEGRAM_DRY_RUN": "1"}
    transport = RecordingTransport()
    n = TelegramNotifier.from_env(env, transport=transport)
    result = n.send("hello")
    assert result.ok is True
    assert result.skipped == "dry-run"
    assert transport.calls == []


# --- happy path + redaction ----------------------------------------------

def test_send_calls_transport_with_token_in_url_and_chat_in_payload():
    transport = RecordingTransport(status=200, body="ok")
    n = TelegramNotifier(token="SECRET_TOKEN", chat_id="CHAT_42", transport=transport)
    result = n.send("ping")
    assert result.ok is True
    assert result.status_code == 200
    (url, payload), = transport.calls
    assert "SECRET_TOKEN" in url  # token used in URL only at send time
    assert payload == {"chat_id": "CHAT_42", "text": "ping"}


def test_redact_helper_replaces_all_secrets():
    out = redact("token=SECRET chat=CHAT", "SECRET", "CHAT")
    assert "SECRET" not in out
    assert "CHAT" not in out
    assert out.count("***") == 2


def test_error_body_is_redacted():
    # Telegram echoes the token in error payloads; we must scrub it.
    body = "error for bot SECRET_TOKEN with chat CHAT_42"
    transport = RecordingTransport(status=401, body=body)
    n = TelegramNotifier(token="SECRET_TOKEN", chat_id="CHAT_42", transport=transport)
    result = n.send("ping")
    assert result.ok is False
    assert result.status_code == 401
    assert "SECRET_TOKEN" not in (result.error or "")
    assert "CHAT_42" not in (result.error or "")


def test_transport_exception_is_caught_and_redacted():
    def boom(url, payload):
        raise RuntimeError("connection to bot SECRET_TOKEN failed")

    n = TelegramNotifier(token="SECRET_TOKEN", chat_id="c", transport=boom)
    result = n.send("ping")
    assert result.ok is False
    assert "SECRET_TOKEN" not in (result.error or "")


# --- dedup / rate-limit ---------------------------------------------------

def test_dedup_suppresses_identical_message_within_window():
    clock = {"t": 0.0}
    transport = RecordingTransport()
    n = TelegramNotifier(
        token="t", chat_id="c", transport=transport,
        min_interval_seconds=60.0, clock=lambda: clock["t"],
    )
    first = n.send("same")
    assert first.ok is True and first.skipped is None
    # Same text, 10s later -> deduplicated, no second network call.
    clock["t"] = 10.0
    second = n.send("same")
    assert second.skipped == "deduplicated"
    assert len(transport.calls) == 1


def test_dedup_allows_message_after_window():
    clock = {"t": 0.0}
    transport = RecordingTransport()
    n = TelegramNotifier(
        token="t", chat_id="c", transport=transport,
        min_interval_seconds=60.0, clock=lambda: clock["t"],
    )
    n.send("same")
    clock["t"] = 61.0
    again = n.send("same")
    assert again.ok is True and again.skipped is None
    assert len(transport.calls) == 2


def test_dedup_allows_different_message_immediately():
    transport = RecordingTransport()
    n = TelegramNotifier(
        token="t", chat_id="c", transport=transport,
        min_interval_seconds=60.0, clock=lambda: 0.0,
    )
    n.send("first")
    n.send("second")
    assert len(transport.calls) == 2


def test_no_dedup_by_default():
    transport = RecordingTransport()
    n = TelegramNotifier(token="t", chat_id="c", transport=transport)
    n.send("same")
    n.send("same")
    assert len(transport.calls) == 2


@pytest.mark.parametrize("event", sorted(EVENT_LABELS))
def test_notify_formats_and_sends_every_known_event(event):
    transport = RecordingTransport()
    n = TelegramNotifier(token="t", chat_id="c", transport=transport)
    result = n.notify(event, title="x")
    assert result.ok is True
    assert len(transport.calls) == 1
