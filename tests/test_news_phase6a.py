"""Read-only Phase 6a journal snapshots: candidates, baselines, and what never becomes a candidate."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.news.phase6a import (
    Phase6aJournal,
    candidate_key,
    journal_dir_from_env,
    parse_time,
    timeframe_interval,
)

DAY = date(2026, 10, 19)
H10 = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def candle(open_time: datetime, close: float = 100.0, tf: str = "1H") -> dict:
    return {
        "ts": _ts(open_time + timedelta(hours=1, seconds=2)),
        "kind": "candle",
        "instrument": "BTC-USDT",
        "timeframe": tf,
        "candle_ts": str(open_time),  # the journal writes str(datetime): "2026-10-19 10:00:00+00:00"
        "open": "100.0",
        "high": str(close + 5),
        "low": str(close - 5),
        "close": str(close),
        "volume": "12.5",
    }


def signal(open_time: datetime, action: str = "long", *, cleared=True, confidence=0.7, veto=None) -> dict:
    return {
        "ts": _ts(open_time + timedelta(hours=1, seconds=2)),
        "kind": "signal",
        "source": "shadow_eval",
        "instrument": "BTC-USDT",
        "candle_ts": str(open_time),
        "action": action,
        "confidence": confidence,
        "reason": "test",
        "stop_loss": "90.0",
        "cleared": cleared,
        "veto_reason": veto,
    }


def decision(at: datetime, allowed: bool, reason: str, *, payload_as_string: bool = True, message: bool = True) -> dict:
    payload = {"intent": "entry", "allowed": allowed, "reason": reason, "instrument": "BTC-USDT"}
    return {
        "ts": _ts(at + timedelta(seconds=18)),
        "kind": "ledger_event",
        "row_id": 1,
        "event_time": str(at),
        "event_type": "risk_decision",
        "severity": "info" if allowed else "warning",
        "message": f"entry {'allowed' if allowed else 'blocked'}: {reason}" if message else "",
        "payload": json.dumps(payload) if payload_as_string else payload,
    }


def intent(open_time: datetime, size: str = "0.0001", price: str = "100000.0") -> dict:
    return {
        "ts": _ts(open_time + timedelta(hours=1, seconds=20)),
        "kind": "ledger_intent",
        "signal_id": f"BTC-USDT|1H|{open_time.isoformat()}",
        "instrument": "BTC-USDT",
        "side": "buy",
        "intent": "entry",
        "price": price,
        "size": size,
        "status": "submitted",
    }


def write(path: Path, records, *, partial: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
        fh.write(partial)


def journal(tmp_path: Path, records, **kw) -> Phase6aJournal:
    write(tmp_path / f"journal-{DAY.isoformat()}.jsonl", records)
    j = Phase6aJournal(tmp_path, **kw)
    j.refresh([DAY])
    return j


def test_helpers():
    assert timeframe_interval("1H") == timedelta(hours=1)
    assert timeframe_interval("5m") == timedelta(minutes=5)
    assert timeframe_interval("1Dutc") == timedelta(days=1)
    assert timeframe_interval("weird") == timedelta(hours=1)
    assert parse_time("2026-10-19 10:00:00+00:00") == H10
    assert parse_time("2026-10-19T10:00:00Z") == H10
    assert parse_time("2026-10-19 10:00:00") == H10  # naive is UTC
    assert parse_time("not a time") is None and parse_time(None) is None
    assert journal_dir_from_env({"PHASE6A_JOURNAL_DIR": "/x/y"}) == Path("/x/y")
    assert journal_dir_from_env({}) == Path("logs/shadow")


def test_allowed_and_blocked_runtime_decisions_become_baselines(tmp_path: Path):
    h11 = H10 + timedelta(hours=1)
    j = journal(
        tmp_path,
        [
            candle(H10),
            signal(H10),
            decision(h11 + timedelta(seconds=4), True, "ok"),
            intent(H10, size="0.0002", price="50000"),
            candle(h11),
            signal(h11),
            decision(h11 + timedelta(hours=1, seconds=3), False, "disarmed", payload_as_string=False),
        ],
    )
    first, second = j.candidates(h11 + timedelta(hours=2))
    assert first.key == candidate_key("BTC-USDT", H10) and first.signal_source == "shadow_eval"
    assert first.baseline.allowed and first.baseline.source == "runtime" and first.baseline.reason == "ok"
    assert first.decision_time == h11 + timedelta(seconds=4) and first.close_time == h11
    assert first.signal_id == "BTC-USDT|1H|2026-10-19T10:00:00+00:00"
    assert first.baseline_notional == Decimal("10.0000") and first.confidence == 0.7
    assert not second.baseline.allowed and second.baseline.reason == "disarmed" and second.baseline_notional is None


def test_message_is_the_fallback_for_missing_payload_fields(tmp_path: Path):
    rec = decision(H10 + timedelta(hours=1, seconds=3), False, "stale_quote")
    rec["payload"] = json.dumps({"instrument": "BTC-USDT"})  # intent, allowed and reason only in the message
    (c,) = journal(tmp_path, [candle(H10), signal(H10), rec]).candidates(H10 + timedelta(hours=3))
    assert not c.baseline.allowed and c.baseline.reason == "stale_quote" and c.baseline.source == "runtime"


def test_an_unreadable_payload_is_never_guessed_into_an_allowed_baseline(tmp_path: Path):
    rec = decision(H10 + timedelta(hours=1, seconds=3), True, "ok")
    rec["payload"] = "{not json"  # no instrument: the decision cannot be attributed
    (c,) = journal(tmp_path, [candle(H10), signal(H10), rec]).candidates(H10 + timedelta(hours=3))
    assert not c.baseline.allowed and c.baseline.source == "not_observed"


def test_pending_until_settled_then_not_observed_or_confidence_veto(tmp_path: Path):
    j = journal(
        tmp_path,
        [signal(H10), signal(H10 + timedelta(hours=1), cleared=False, confidence=0.4, veto="confidence_too_low")],
        settle=timedelta(minutes=15),
    )
    close = H10 + timedelta(hours=1)
    early = j.candidates(close + timedelta(minutes=5))
    assert [c.settled for c in early] == [False, False]
    later = {c.candle_ts: c for c in j.candidates(close + timedelta(hours=1, minutes=20))}
    assert later[H10].baseline.source == "not_observed" and not later[H10].baseline.allowed
    assert later[H10].decision_time == close  # no runtime decision: the candle close
    veto = later[H10 + timedelta(hours=1)].baseline
    assert veto.source == "shadow_eval" and veto.reason == "confidence_too_low" and not veto.allowed


def test_only_long_signals_and_entry_decisions_are_candidates(tmp_path: Path):
    exit_decision = decision(H10 + timedelta(hours=3, seconds=3), True, "ok")
    exit_decision["payload"] = json.dumps({"intent": "exit", "allowed": True, "reason": "ok", "instrument": "BTC-USDT"})
    records = [
        signal(H10, "flat", cleared=False),
        signal(H10 + timedelta(hours=1), "hold", cleared=False),
        {"ts": _ts(H10), "kind": "stop_eval", "instrument": "BTC-USDT", "candle_ts": str(H10), "breached": True},
        {"ts": _ts(H10), "kind": "ledger_fill", "instrument": "BTC-USDT", "side": "sell"},
        exit_decision,
        {"ts": _ts(H10), "kind": "ledger_intent", "signal_id": f"stop|BTC-USDT|{H10.isoformat()}", "intent": "exit"},
    ]
    j = journal(tmp_path, records)
    assert j.candidates(H10 + timedelta(days=1)) == []
    assert dict(j.signal_actions()) == {"flat": 1, "hold": 1}


def test_a_runtime_entry_decision_without_a_signal_line_is_still_a_candidate(tmp_path: Path):
    (c,) = journal(tmp_path, [candle(H10), decision(H10 + timedelta(hours=1, seconds=5), True, "ok")]).candidates(H10 + timedelta(hours=2))
    assert c.signal_source == "runtime_only" and c.candle_ts == H10 and c.baseline.allowed and c.confidence is None


def test_each_decision_belongs_to_one_candle_even_when_stamped_early(tmp_path: Path):
    h11, h12 = H10 + timedelta(hours=1), H10 + timedelta(hours=2)
    j = journal(
        tmp_path,
        [signal(H10), signal(h11), decision(h12 - timedelta(seconds=20), False, "already_open")],  # the 11:00 candle's decision, stamped at 11:59:40
        settle=timedelta(minutes=15),
    )
    by_ts = {c.candle_ts: c for c in j.candidates(h12 + timedelta(hours=1))}
    assert by_ts[H10].baseline.source == "not_observed"  # never borrows the next candle's decision
    assert by_ts[h11].baseline.reason == "already_open"


def test_first_signal_line_per_candle_wins(tmp_path: Path):
    again = signal(H10, confidence=0.9)
    (c,) = journal(tmp_path, [signal(H10, confidence=0.65), again]).candidates(H10 + timedelta(hours=3))
    assert c.confidence == 0.65


def test_incremental_reads_skip_partial_and_unparseable_lines(tmp_path: Path):
    path = tmp_path / f"journal-{DAY.isoformat()}.jsonl"
    write(path, [signal(H10)], partial='{"kind": "signal", "instrum')
    j = Phase6aJournal(tmp_path)
    assert j.refresh([DAY]) == 1
    with path.open("a", encoding="utf-8") as fh:  # the writer finishes the line, then a broken one
        fh.write('ent": "BTC-USDT"}\nnot json at all\n')
    assert j.refresh([DAY]) == 1 and j.unparseable == 1
    assert j.refresh([DAY]) == 0  # nothing new
    write(path, [decision(H10 + timedelta(hours=1, seconds=3), True, "ok")])
    j.refresh([DAY])
    (c,) = j.candidates(H10 + timedelta(hours=2))
    assert c.baseline.allowed


def test_a_replaced_file_is_read_again_without_duplicates(tmp_path: Path):
    path = tmp_path / f"journal-{DAY.isoformat()}.jsonl"
    write(path, [signal(H10), decision(H10 + timedelta(hours=1, seconds=3), True, "ok"), candle(H10)])
    j = Phase6aJournal(tmp_path)
    j.refresh([DAY])
    path.write_text(json.dumps(signal(H10)) + "\n", encoding="utf-8")  # shorter: replaced
    j.refresh([DAY])
    assert len(j.candidates(H10 + timedelta(hours=2))) == 1


def test_missing_directory_and_files_are_harmless(tmp_path: Path):
    j = Phase6aJournal(tmp_path / "absent")
    assert not j.exists and j.refresh([DAY]) == 0 and j.candidates(H10) == []


def test_journal_candles_and_prune(tmp_path: Path):
    j = journal(tmp_path, [candle(H10, 100), candle(H10 + timedelta(hours=1), 101), signal(H10)])
    series = j.candles("BTC-USDT")
    assert [c.close for c in series] == [100.0, 101.0] and series[0].interval == timedelta(hours=1)
    j.prune(H10 + timedelta(hours=1))
    assert [c.close for c in j.candles("BTC-USDT")] == [101.0] and j.candidates(H10 + timedelta(days=1)) == []


def test_the_reader_never_writes(tmp_path: Path):
    path = tmp_path / f"journal-{DAY.isoformat()}.jsonl"
    write(path, [signal(H10), candle(H10)])
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    j = Phase6aJournal(tmp_path)
    j.refresh([DAY, DAY + timedelta(days=1)])
    j.candidates(H10 + timedelta(days=1))
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_settle_must_be_positive(tmp_path: Path):
    with pytest.raises(ValueError):
        Phase6aJournal(tmp_path, settle=timedelta(0))
