"""Append-only JSONL event and decision logs for the news shadow (design 11)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.news.decay import effective_signal
from app.news.overlay import NewLongEntryCandidate, evaluate_new_long_entry
from app.news.store import (
    DECISION_RECORD_KINDS,
    EVENT_RECORD_KINDS,
    REDACTED,
    SHADOW_LOG_VERSION,
    NewsShadowLog,
    redact,
)
from tests.news_fixtures import NOW, event


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def test_event_and_decision_streams_append_and_roll_over_daily(tmp_path: Path):
    clock = Clock(datetime(2026, 10, 20, 23, 59, 30, tzinfo=timezone.utc))
    log = NewsShadowLog(tmp_path / "news_shadow", clock=clock)
    ev = event()
    log.write_event("event_candidate_created", {"event": ev, "reasons": ()})
    log.write_event("effective_signal", effective_signal(ev, NOW).to_dict())
    clock.now += timedelta(minutes=1)  # next UTC day
    decision = evaluate_new_long_entry(
        NewLongEntryCandidate("BTC-USDT", NOW, True, baseline_size_fraction=Decimal("0.04")), [ev]
    )
    log.write_decision(decision.to_log_record())
    day1, day2 = date(2026, 10, 20), date(2026, 10, 21)
    assert log.events_file(day1).name == "events-2026-10-20.jsonl"
    assert log.decisions_file(day2).name == "decisions-2026-10-21.jsonl"
    first = log.read("events", day1)
    assert [r["kind"] for r in first] == ["event_candidate_created", "effective_signal"]
    assert first[0]["event"]["event_id"] == ev.event_id and first[0]["log_version"] == SHADOW_LOG_VERSION
    assert first[0]["ts"].startswith("2026-10-20T23:59:30")
    assert log.read("decisions", day1) == [] and log.read("events", day2) == []
    (d,) = log.read("decisions", day2)
    assert d["kind"] == "shadow_entry_overlay" and d["action"] == "BLOCK_NEW_LONGS" and d["would_have_blocked_here"]
    # Append-only: earlier lines are byte-identical after more writes.
    before = log.events_file(day1).read_bytes()
    clock.now = datetime(2026, 10, 20, 23, 59, 50, tzinfo=timezone.utc)
    log.write_event("daily_summary", counts={"events": 1})
    after = log.events_file(day1).read_bytes()
    assert after.startswith(before) and len(after.splitlines()) == 3


def test_kinds_are_the_design_list():
    assert {
        "source_item_observed", "source_item_sanitized", "event_candidate_created", "event_deduplicated",
        "classifier_output", "classifier_rejected", "corroboration_update", "effective_signal", "daily_summary",
    } <= EVENT_RECORD_KINDS
    assert DECISION_RECORD_KINDS == {"shadow_entry_overlay"}
    log = NewsShadowLog(Path("unused"), clock=lambda: NOW)
    with pytest.raises(ValueError):
        log.write_event("order_placed", {})
    with pytest.raises(ValueError):
        log.write_event("shadow_entry_overlay", {})  # decisions have their own stream
    with pytest.raises(ValueError):
        log.write_decision({"kind": "effective_signal"})
    with pytest.raises(ValueError):
        log.read("orders", NOW.date())


def test_reserved_fields_cannot_be_spoofed(tmp_path: Path):
    log = NewsShadowLog(tmp_path, clock=lambda: NOW)
    record = log.write_event("daily_summary", {"ts": "1999-01-01", "kind": "fake", "log_version": "x", "n": 1})
    assert record["ts"].startswith("2026-10-20T12:00") and record["kind"] == "daily_summary"
    assert record["log_version"] == SHADOW_LOG_VERSION and record["n"] == 1


def test_secrets_are_redacted(tmp_path: Path):
    log = NewsShadowLog(tmp_path, clock=lambda: NOW)
    log.write_event(
        "classifier_unavailable",
        {
            "api_key": "anything",
            "headers": {"Authorization": "Bearer x", "x-api-key": "y"},
            "note": "leaked sk-ant-abcdefghijklmnop0123 here",
            "usage": {"input_tokens": 5, "output_tokens": 7},
            "nested": [{"telegram_bot_token": "z", "NEWSAPI_AI_API_KEY": "w"}],
        },
    )
    text = log.events_file(NOW.date()).read_text(encoding="utf-8")
    for secret in ("anything", "Bearer x", '"y"', "abcdefghijklmnop0123", '"z"', '"w"'):
        assert secret not in text
    (rec,) = log.read("events", NOW.date())
    assert rec["api_key"] == REDACTED and rec["headers"]["Authorization"] == REDACTED
    assert rec["usage"] == {"input_tokens": 5, "output_tokens": 7}  # token counts are not secrets
    assert redact({"a": {"b", "c"}}) == {"a": ["b", "c"]}


def test_from_env_and_clock_checks(tmp_path: Path):
    log = NewsShadowLog.from_env({"NEWS_SHADOW_LOG_DIR": str(tmp_path / "x")}, clock=lambda: NOW)
    assert log.root == tmp_path / "x"
    assert NewsShadowLog.from_env({}).root == Path("logs/news_shadow")
    naive = NewsShadowLog(tmp_path, clock=lambda: datetime(2026, 10, 20, 12))
    with pytest.raises(ValueError):
        naive.write_event("daily_summary", {})
    with pytest.raises(TypeError):
        NewsShadowLog(tmp_path, clock=lambda: NOW).write_event("daily_summary", {"bad": object()})


def test_daily_logs_are_reproducible(tmp_path: Path):
    """The same inputs produce byte-identical logs (reports can be rebuilt from them)."""

    def run(root: Path) -> bytes:
        log = NewsShadowLog(root, clock=lambda: NOW)
        ev = event()
        for minutes in (0, 60, 120, 240):
            log.write_event("effective_signal", effective_signal(ev, NOW + timedelta(minutes=minutes)).to_dict())
        return log.events_file(NOW.date()).read_bytes()

    assert run(tmp_path / "a") == run(tmp_path / "b")
    lines = [json.loads(line) for line in run(tmp_path / "c").splitlines()]
    # Severity 0.729 at weight 1, 0.75, 0.5 -> 0.729, 0.547, 0.365; zero at expiry (240 min).
    assert [line["action"] for line in lines] == ["BLOCK_NEW_LONGS", "REDUCE_SIZE", "REDUCE_SIZE", "NO_EFFECT"]
    assert [line["size_multiplier"] for line in lines] == ["0", "0.75", "0.75", "1"]
    assert lines[-1]["reason"] == "expired"
