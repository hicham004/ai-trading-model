"""The daily news-shadow report: built from logs only, and its safety checks catch every violation."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.news.report import build_report_data, generate_daily_report, render_report, write_daily_report
from tests.news_fixtures import NOW, event

DAY = NOW.date()
EXIT_CHECK = "decision without a journaled LONG signal or entry decision (exits are never evaluated)"
JOURNAL_CHECK = "allowed baseline without a runtime 'entry allowed' in the journal"


def _write(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _decision(**over: Any) -> Dict[str, Any]:
    """A consistent decision row; an effect comes from event ``evt_a`` unless overridden."""
    action = over.get("action", "NO_EFFECT")
    base = {
        "ts": (NOW + timedelta(minutes=5)).isoformat(),
        "kind": "shadow_entry_overlay",
        "instrument": "BTC-USDT",
        "candidate_key": "BTC-USDT|" + (NOW - timedelta(hours=1)).isoformat(),
        "decision_time": NOW.isoformat(),
        "candle_close": NOW.isoformat(),
        "signal_action": "long",
        "journal_signal_action": "long",
        "journal_decision_intent": "entry",
        "action": action,
        "size_multiplier": {"NO_EFFECT": "1", "REDUCE_SIZE": "0.75", "BLOCK_NEW_LONGS": "0"}[action],
        "effective_severity": {"NO_EFFECT": 0.0, "REDUCE_SIZE": 0.4, "BLOCK_NEW_LONGS": 0.8}[action],
        "baseline_allowed": True,
        "baseline_reason": "ok",
        "baseline": {"source": "runtime"},
        "would_have_blocked_here": action == "BLOCK_NEW_LONGS",
        "would_have_reduced_here": action == "REDUCE_SIZE",
        "news_healthy": True,
        "event_id": None if action == "NO_EFFECT" else "evt_a",
    }
    base.update(over)
    if "events_at_decision" not in over:
        base["events_at_decision"] = (
            []
            if base["event_id"] is None
            else [
                {
                    "event_id": base["event_id"],
                    "action": base["action"],
                    "effective_severity": base["effective_severity"],
                    "size_multiplier": base["size_multiplier"],
                }
            ]
        )
    return base


def test_no_logs_means_the_shadow_did_not_run(tmp_path: Path):
    text = generate_daily_report(tmp_path, None, DAY)
    assert "did not run on this day" in text and "Safety checks: all passed" in text
    assert "Phase 6a journal directory not found" in text and "not checked (no Phase 6a journal)" in text


def test_a_clean_day_passes_every_check(tmp_path: Path):
    rows = [_decision(), _decision(action="REDUCE_SIZE"), _decision(action="BLOCK_NEW_LONGS")]
    _write(tmp_path / f"decisions-{DAY.isoformat()}.jsonl", rows)
    data = build_report_data(tmp_path, None, DAY)
    assert data["headline"]["invariants_ok"], data["invariants"]


def test_every_safety_check_catches_its_violation(tmp_path: Path):
    ev = event(first_seen=NOW - timedelta(hours=1), ttl_minutes=30)  # expired at NOW - 30 min
    _write(
        tmp_path / f"events-{DAY.isoformat()}.jsonl",
        [
            {"ts": NOW.isoformat(), "kind": "event_candidate_created", "event": ev.model_dump(mode="json"), "known_at": (NOW - timedelta(hours=1)).isoformat()},
            # an unconfirmed event with an effect
            {"ts": NOW.isoformat(), "kind": "effective_signal", "scope": "event", "event_id": "evt_x", "action": "REDUCE_SIZE",
             "size_multiplier": "0.75", "effective_severity": 0.4, "status": "SINGLE_SOURCE", "at": NOW.isoformat(),
             "expires_at": (NOW + timedelta(hours=1)).isoformat()},
            # an effect after expiry
            {"ts": NOW.isoformat(), "kind": "effective_signal", "scope": "event", "event_id": "evt_y", "action": "BLOCK_NEW_LONGS",
             "size_multiplier": "0", "effective_severity": 0.8, "status": "INDEPENDENT_SOURCE_CONFIRMED", "at": NOW.isoformat(),
             "expires_at": (NOW - timedelta(minutes=1)).isoformat()},
        ],
    )
    summed = [
        {"event_id": ev.event_id, "action": "BLOCK_NEW_LONGS", "effective_severity": 0.45, "size_multiplier": "0"},
        {"event_id": "evt_b", "action": "BLOCK_NEW_LONGS", "effective_severity": 0.45, "size_multiplier": "0"},
    ]
    compounded = [{"event_id": "evt_a", "action": "REDUCE_SIZE", "effective_severity": 0.4, "size_multiplier": "0.75"}]
    _write(
        tmp_path / f"decisions-{DAY.isoformat()}.jsonl",
        [
            _decision(journal_signal_action="flat", journal_decision_intent=None),  # an exit signal evaluated
            _decision(size_multiplier="1.5"),  # a size increase
            _decision(action="BLOCK_NEW_LONGS", effective_severity=0.9, event_id=ev.event_id, events_at_decision=summed),
            _decision(action="REDUCE_SIZE", size_multiplier="0.5625", events_at_decision=compounded),  # 0.75 x 0.75
            _decision(action="BLOCK_NEW_LONGS", news_healthy=False),  # effect while unhealthy
            _decision(action="BLOCK_NEW_LONGS", baseline_allowed=False),  # a blocked baseline counted as prevented
        ],
    )
    data = build_report_data(tmp_path, None, DAY)
    counts = {i["check"]: i["count"] for i in data["invariants"]}
    assert counts["single-source or unconfirmed event with an effect"] == 1
    assert counts["expired event with an effect"] == 2  # the logged signal and the decision on the expired event
    assert counts[EXIT_CHECK] == 1
    assert counts["size multiplier above 1"] == 1
    assert counts["severity double counted or reductions compounded"] == 2
    assert counts["effect while the news state was unhealthy"] == 1
    assert counts["baseline-blocked entry counted as prevented"] == 1
    assert counts[JOURNAL_CHECK] is None  # cannot be checked without the journal
    assert not data["headline"]["invariants_ok"]
    text = render_report(data)
    assert "**FAILED**" in text and text.count("**FAIL**") >= 7


def _journal_lines(journal_dir: Path) -> None:
    h = NOW - timedelta(hours=1)
    blocked = json.dumps({"intent": "entry", "allowed": False, "reason": "disarmed", "instrument": "BTC-USDT"})
    rows = [
        {"ts": NOW.isoformat(), "kind": "signal", "source": "shadow_eval", "instrument": "BTC-USDT", "candle_ts": str(h),
         "action": "long", "confidence": 0.7, "cleared": True},
        {"ts": NOW.isoformat(), "kind": "ledger_event", "event_time": str(NOW + timedelta(seconds=4)), "event_type": "risk_decision",
         "message": "entry blocked: disarmed", "payload": blocked},
        {"ts": NOW.isoformat(), "kind": "signal", "source": "shadow_eval", "instrument": "BTC-USDT",
         "candle_ts": str(h - timedelta(hours=1)), "action": "flat", "confidence": 0.6, "cleared": False},
    ]
    _write(journal_dir / f"journal-{DAY.isoformat()}.jsonl", rows)


def test_decisions_are_checked_against_the_journal_itself(tmp_path: Path):
    journal_dir = tmp_path / "journal"
    _journal_lines(journal_dir)
    flat_key = "BTC-USDT|" + (NOW - timedelta(hours=2)).isoformat()
    _write(
        tmp_path / "logs" / f"decisions-{DAY.isoformat()}.jsonl",
        [
            _decision(action="BLOCK_NEW_LONGS"),  # the journal says the runtime BLOCKED this entry
            _decision(candidate_key=flat_key),  # the journal has only a FLAT signal for this candle
        ],
    )
    data = build_report_data(tmp_path / "logs", journal_dir, DAY)
    counts = {i["check"]: i["count"] for i in data["invariants"]}
    assert counts[JOURNAL_CHECK] == 2
    assert counts[EXIT_CHECK] == 1
    assert not data["headline"]["invariants_ok"]


def test_a_report_never_lands_in_the_phase6a_journal_directory(tmp_path: Path):
    _journal_lines(tmp_path)
    with pytest.raises(ValueError):
        write_daily_report(tmp_path, tmp_path, DAY)
    assert not list(tmp_path.glob("report-*.md"))


def test_a_line_cut_inside_a_multibyte_character_is_skipped(tmp_path: Path):
    good = json.dumps({"kind": "cycle_summary", "finished_at": NOW.isoformat(), "healthy": True, "title": "Café €"}, ensure_ascii=False)
    cut = json.dumps({"kind": "source_item_observed", "title": "price €"}, ensure_ascii=False).encode("utf-8")
    cut = cut[: cut.index("€".encode("utf-8")) + 1]  # cut inside the euro sign, no newline: a crash or a full disk
    (tmp_path / f"events-{DAY.isoformat()}.jsonl").write_bytes(good.encode("utf-8") + b"\n" + cut)
    data = build_report_data(tmp_path, None, DAY)
    assert data["runner"]["cycles"] == 1 and data["runner"]["unparseable_lines"] == 1
    generate_daily_report(tmp_path, None, DAY)  # renders, never raises


def test_an_event_live_at_midnight_keeps_its_effect_in_the_next_report(tmp_path: Path):
    from app.news.schema import SourceTier

    late = NOW.replace(hour=23, minute=0)
    ev = event(first_seen=late, ttl_minutes=120, confidence=0.95, impact=0.95, tier=SourceTier.OFFICIAL)
    _write(
        tmp_path / f"events-{DAY.isoformat()}.jsonl",
        [
            {"ts": late.isoformat(), "kind": "event_candidate_created", "event": ev.model_dump(mode="json"), "known_at": late.isoformat()},
            {"ts": late.isoformat(), "kind": "effective_signal", "scope": "event", "event_id": ev.event_id, "action": "BLOCK_NEW_LONGS",
             "size_multiplier": "0", "effective_severity": 0.9, "status": "INDEPENDENT_SOURCE_CONFIRMED", "at": late.isoformat(),
             "expires_at": ev.expires_at.isoformat()},
        ],
    )
    next_day = DAY + timedelta(days=1)
    after = late + timedelta(hours=2)
    _write(tmp_path / f"events-{next_day.isoformat()}.jsonl", [{"ts": after.isoformat(), "kind": "cycle_summary", "finished_at": after.isoformat(), "healthy": True}])
    rows = {r["event_id"]: r for r in build_report_data(tmp_path, None, next_day)["events"]["rows"]}
    # Live at 00:00 with no new signal record that day: at midnight it is half-way through its
    # 2-hour life, decayed from block to reduce (0.9025 x 0.5 = 0.45), and that is what it did that day.
    assert rows[ev.event_id]["strongest_effect"] == "REDUCE_SIZE" and rows[ev.event_id]["max_severity"] == pytest.approx(0.451, abs=1e-3)


def test_unparseable_lines_are_skipped_and_reported(tmp_path: Path):
    path = tmp_path / f"events-{DAY.isoformat()}.jsonl"
    path.write_text('{"kind": "cycle_summary", "finished_at": "2026-10-20T12:00:00+00:00", "healthy": true}\nnot json\n', encoding="utf-8")
    data = build_report_data(tmp_path, None, DAY)
    assert data["runner"]["unparseable_lines"] == 1 and data["runner"]["cycles"] == 1
    assert any("unparseable" in a for a in data["anomalies"])


def test_unhealthy_minutes_and_outages_come_from_the_logs(tmp_path: Path):
    rows = []
    t = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    for i in range(13):  # one cycle every 5 minutes for an hour; the middle 20 minutes unhealthy
        rows.append({"ts": (t + timedelta(minutes=5 * i)).isoformat(), "kind": "cycle_summary",
                     "finished_at": (t + timedelta(minutes=5 * i)).isoformat(), "healthy": not 4 <= i < 8})
        rows.append({"ts": (t + timedelta(minutes=5 * i)).isoformat(), "kind": "source_fetch", "source_id": "gdelt_doc",
                     "status": "ok" if i < 6 else "network_error", "fetched_at": (t + timedelta(minutes=5 * i)).isoformat(),
                     "items": 3, "error": "" if i < 6 else "ConnectionError: refused"})
    _write(tmp_path / f"events-{DAY.isoformat()}.jsonl", rows)
    data = build_report_data(tmp_path, None, DAY)
    assert data["runner"]["observed_minutes"] == 60.0
    # Last healthy cycle at minute 15, next at 40: stale only from minute 31 to 39 (beyond the 15-minute window).
    assert data["runner"]["unhealthy_minutes"] == 9.0
    assert data["sources"]["gdelt_doc"]["failed"] == 7 and data["sources"]["gdelt_doc"]["outage_minutes"] == 35.0
    assert "ConnectionError" in data["sources"]["gdelt_doc"]["last_error"]


def test_write_is_atomic_and_overwrites(tmp_path: Path):
    first = write_daily_report(tmp_path, None, DAY)
    second = write_daily_report(tmp_path, None, DAY)
    assert first == second and first.name == f"report-{DAY.isoformat()}.md"
    assert not list(tmp_path.glob("*.tmp"))
