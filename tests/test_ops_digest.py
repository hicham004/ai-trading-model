"""The daily ops digest (plan row R6): reading the services' files, the attention rules, the text, Telegram — offline."""

from __future__ import annotations

import json
import shutil
import socket
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.notify.telegram import TelegramNotifier
from app.ops import digest as dg

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc)
FLEET_FIXTURE = ROOT / "tests" / "fixtures" / "paper_fleet_r5a"


def _jsonl(path: Path, records, tail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + tail, encoding="utf-8")


def _heartbeat(**overrides):
    hb = {"ts": (NOW - timedelta(seconds=30)).isoformat(), "pid": 1, "state": "running", "armed_until": None, "kill": False,
          "kill_owner": None, "restarts_in_window": 0, "position": "0", "flat_at_lot": True, "entries_today": 0,
          "day_pnl": "0", "last_candle": "2026-10-22 03:00:00+00:00", "market_continuity_ok": True}
    hb.update(overrides)
    return hb


def _journal_day():
    t = "2026-10-21T{}:00:00+00:00"
    return [
        {"ts": t.format("01"), "kind": "supervisor", "event": "start", "instrument": "BTC-USDT", "timeframe": "1H"},
        {"ts": t.format("01"), "kind": "candle", "instrument": "BTC-USDT", "timeframe": "1H", "candle_ts": "2026-10-21 00:00:00+00:00"},
        {"ts": t.format("02"), "kind": "candle", "instrument": "BTC-USDT", "timeframe": "1H", "candle_ts": "2026-10-21 01:00:00+00:00"},
        {"ts": t.format("02"), "kind": "signal", "action": "long", "cleared": True, "confidence": 0.7},
        {"ts": t.format("03"), "kind": "signal", "action": "long", "cleared": False, "confidence": 0.5},
        {"ts": t.format("04"), "kind": "signal", "action": "flat"},
        {"ts": t.format("05"), "kind": "signal", "action": "hold"},
        {"ts": t.format("02"), "kind": "ledger_event", "event_type": "risk_decision", "severity": "info", "message": "entry allowed: ok",
         "payload": json.dumps({"intent": "entry", "allowed": True, "reason": "ok"})},
        {"ts": t.format("03"), "kind": "ledger_event", "event_type": "risk_decision", "severity": "warning",
         "message": "entry blocked: confidence_too_low", "payload": {"intent": "entry", "allowed": False, "reason": "confidence_too_low"}},
        {"ts": t.format("04"), "kind": "ledger_event", "event_type": "risk_decision", "severity": "info", "message": "exit allowed: ok",
         "payload": "not json"},
        {"ts": t.format("05"), "kind": "ledger_event", "event_type": "reconcile_error", "severity": "error", "message": "x"},
        {"ts": t.format("02"), "kind": "ledger_fill", "instrument": "BTC-USDT", "side": "buy", "fill_size": "0.0001",
         "fill_price": "100000", "fee": "-0.0000001", "fee_ccy": "BTC"},
        {"ts": t.format("04"), "kind": "ledger_fill", "instrument": "BTC-USDT", "side": "sell", "fill_size": "0.0000999",
         "fill_price": "101000", "fee": "-0.01", "fee_ccy": "USDT"},
        {"ts": t.format("02"), "kind": "ledger_reconciliation", "consistent": True, "foreign_orders": 0, "unexplained_balances": 0},
        {"ts": t.format("03"), "kind": "ledger_reconciliation", "consistent": False, "foreign_orders": 1, "unexplained_balances": 0},
        {"ts": t.format("02"), "kind": "stop_eval", "breached": False},
        {"ts": t.format("03"), "kind": "stop_eval", "breached": True},
        {"ts": t.format("02"), "kind": "health", "ws_auth": True, "feed_usable": True, "market_continuity_ok": True},
        {"ts": t.format("03"), "kind": "health", "ws_auth": False, "feed_usable": True, "market_continuity_ok": True},
        {"ts": t.format("04"), "kind": "supervisor", "event": "restart", "outcome": "crashed"},
        {"ts": t.format("05"), "kind": "supervisor", "event": "rearm", "renewed": None},
        {"ts": t.format("06"), "kind": "supervisor", "event": "rearm", "renewed": "2026-10-21 07:00:00+00:00"},
    ]


def _shadow(tmp_path: Path, *, heartbeat=None, alert=None, journal=True) -> Path:
    shadow = tmp_path / "shadow"
    shadow.mkdir(parents=True, exist_ok=True)
    if heartbeat is not False:
        (shadow / "heartbeat.json").write_text(json.dumps(heartbeat or _heartbeat()), encoding="utf-8")
    (shadow / "state.json").write_text(json.dumps({"kill_owner": None, "capped_day": None, "alert": alert, "restarts": []}),
                                       encoding="utf-8")
    if alert:
        (shadow / "ALERT").write_text(f"2026-10-22T01:00:00+00:00 SHADOW HALT: {alert}\nOperator action required.\n", encoding="utf-8")
    if journal:
        _jsonl(shadow / f"journal-{DAY.isoformat()}.jsonl", _journal_day(), tail='{"ts": "2026-10-21T23:59:59", "kind": "hea')
    return shadow


def _facts(tmp_path: Path, **kw) -> dict:
    shadow = kw.pop("shadow", None) or _shadow(tmp_path)
    return dg.build_facts(now=NOW, day=DAY, shadow_dir=shadow, news_dir=tmp_path / "news", changelog_dir=tmp_path / "cl",
                          fleet=kw.pop("fleet", {"installed": False}), **kw)


# -- the Phase 6a shadow ------------------------------------------------------------------------


def test_the_shadow_day_is_read_from_the_journal_and_its_ledger_mirror(tmp_path):
    sh = dg.collect_shadow(_shadow(tmp_path), DAY, NOW)
    day = sh["day"]
    assert day["found"] and day["unparseable"] == 1 and day["candles"] == 2
    assert (day["instrument"], day["timeframe"]) == ("BTC-USDT", "1H")
    assert day["signals"] == {"long": 2, "cleared": 1, "below_floor": 1, "flat": 1, "hold": 1}
    assert day["decisions"] == {"entry_allowed": 1, "entry_blocked": 1, "exit_allowed": 1}
    assert day["blocked_reasons"] == {"confidence_too_low": 1}
    fills = day["fills"]
    assert (fills["count"], fills["buys"], fills["sells"], fills["quote"]) == (2, 1, 1, "USDT")
    # sells - buys + quote-currency fees: 0.0000999 * 101000 - 0.0001 * 100000 - 0.01
    assert Decimal(fills["cash_result"]) == Decimal("10.0899") - Decimal("10") - Decimal("0.01")
    assert day["reconciliations"] == {"count": 2, "consistent": 1, "inconsistent": 1, "foreign_orders": 1, "unexplained": 0}
    assert day["stops"] == {"evaluations": 2, "breaches": 1}
    assert day["health"]["ws_auth_pct"] == 50.0 and day["health"]["feed_usable_pct"] == 100.0
    assert day["supervisor"] == {"rearm": 1, "rearm_refused": 1, "restart": 1, "start": 1}
    assert day["runtime_errors"] == {"reconcile_error": 1} and day["runtime_warnings"] == {}  # a blocked entry is no warning here
    assert day["expected_candles"] == 24
    hb = sh["heartbeat"]
    assert hb["found"] and hb["state"] == "running" and hb["age_minutes"] == pytest.approx(0.5)
    # the 03:00 candle closed at 04:00, which is now
    assert hb["last_candle_closed_hours_ago"] == pytest.approx(0.0) and hb["flat_at_lot"] is True
    assert sh["alert"] == {"present": False, "first_line": None, "state_alert": None, "state_error": None}


def test_an_alert_a_stale_heartbeat_and_a_silent_feed_need_action(tmp_path):
    shadow = _shadow(tmp_path, alert="reconcile_inconsistent",
                     heartbeat=_heartbeat(ts=(NOW - timedelta(minutes=45)).isoformat(), state="halted_alert",
                                          last_candle="2026-10-21 22:00:00+00:00"))
    facts = _facts(tmp_path, shadow=shadow)
    actions = [a["text"] for a in facts["attention"] if a["level"] == "ACTION"]
    assert any("halted and waits for you" in t and "reconcile_inconsistent" in t for t in actions)
    assert any("heartbeat is 45 min old" in t for t in actions)
    assert any("1 reconciliation(s) with the exchange were inconsistent" in t for t in actions)
    checks = [a["text"] for a in facts["attention"] if a["level"] == "CHECK"]
    assert any("restarted 1 time" in t for t in checks) and any("reconcile_error x1" in t for t in checks)
    assert any("authenticated only 50.0%" in t for t in checks)
    assert [a["level"] for a in facts["attention"]] == sorted((a["level"] for a in facts["attention"]), key=["ACTION", "CHECK"].index)


def test_a_late_candle_and_the_kill_switch_are_reported(tmp_path):
    # the last candle opened at 00:00 and closed at 01:00: three hours without a new one at 04:00
    facts = _facts(tmp_path, shadow=_shadow(tmp_path, journal=False, heartbeat=_heartbeat(
        last_candle="2026-10-22 00:00:00+00:00", kill=True, kill_owner="entries_per_day", market_continuity_ok=False)))
    texts = {a["text"]: a["level"] for a in facts["attention"]}
    assert any("No new 1H candle has closed for the Phase 6a shadow for 3.0 h" in t and "22 Oct 01:00 UTC" in t
               and lvl == "ACTION" for t, lvl in texts.items())
    assert any("paused for the rest of the UTC day" in t and lvl == "CHECK" for t, lvl in texts.items())
    assert any("market-continuity check is not satisfied" in t and lvl == "CHECK" for t, lvl in texts.items())
    assert any("wrote no journal for yesterday" in t for t in texts)
    operator = _facts(tmp_path / "b", shadow=_shadow(tmp_path / "b", heartbeat=_heartbeat(kill=True, kill_owner=None)))
    assert any("did not engage it itself" in a["text"] for a in operator["attention"])
    on_time = _facts(tmp_path / "c", shadow=_shadow(tmp_path / "c", heartbeat=_heartbeat(last_candle="2026-10-22 01:30:00+00:00")))
    assert not any("candle has closed" in a["text"] for a in on_time["attention"])  # closed 02:30, 1.5 h ago


def _changelog_ok(tmp_path: Path, at: datetime) -> Path:
    from app.ops.okx_changelog import run_check

    page = (ROOT / "tests" / "fixtures" / "okx_changelog" / "changelog_v1.html").read_text(encoding="utf-8")
    run_check(tmp_path / "cl", at, fetch=lambda: page, notify=lambda text: True)
    return tmp_path / "cl"


def test_a_healthy_quiet_day_needs_nothing(tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "heartbeat.json").write_text(json.dumps(_heartbeat()), encoding="utf-8")
    _jsonl(shadow / f"journal-{DAY.isoformat()}.jsonl",
           [{"kind": "candle", "instrument": "BTC-USDT", "timeframe": "1H"}] * 24
           + [{"kind": "health", "ws_auth": True, "feed_usable": True, "market_continuity_ok": True},
              {"kind": "ledger_reconciliation", "consistent": True}])
    _changelog_ok(tmp_path, NOW - timedelta(hours=30))  # flags older than a day stay in the section only
    facts = _facts(tmp_path, shadow=shadow)
    assert facts["attention"] == []
    text = dg.render(facts)
    assert "Nothing needs your attention." in text and "reconciliations 1, all consistent" in text
    assert "24 of 24 candles" in text


def test_downtime_and_notable_runtime_events_are_reported(tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "heartbeat.json").write_text(json.dumps(_heartbeat()), encoding="utf-8")
    _jsonl(shadow / f"journal-{DAY.isoformat()}.jsonl",
           [{"kind": "candle", "instrument": "BTC-USDT", "timeframe": "1H"}] * 10
           + [{"kind": "ledger_event", "event_type": "exit_deferred", "severity": "warning", "message": "deferred"},
              {"kind": "ledger_event", "event_type": "market_candle_backfill_succeeded", "severity": "warning"},
              {"kind": "ledger_event", "event_type": "lock_lost", "severity": "error"}])
    facts = _facts(tmp_path, shadow=shadow)
    texts = [a["text"] for a in facts["attention"]]
    assert any("Only 10 of 24 1H candles" in t and "about 14 h" in t for t in texts)
    assert any("a protective exit was deferred (exit_deferred x1)" in t for t in texts)
    assert any("errors yesterday: lock_lost x1" in t for t in texts)
    assert "runtime warnings: exit_deferred 1, market_candle_backfill_succeeded 1" in dg.render(facts)


def test_a_journal_that_cannot_be_read_is_said_and_never_hides_an_alert(tmp_path, monkeypatch):
    shadow = _shadow(tmp_path, alert="reconcile_inconsistent", heartbeat=_heartbeat(ts=(NOW - timedelta(hours=3)).isoformat()))
    real = dg._jsonl

    def denied(path):
        for i, item in enumerate(real(path)):
            if i == 3:
                raise PermissionError("denied")
            yield item

    monkeypatch.setattr(dg, "_jsonl", denied)
    facts = _facts(tmp_path, shadow=shadow)
    levels = {a["text"]: a["level"] for a in facts["attention"]}
    assert any("halted and waits for you" in t and lvl == "ACTION" for t, lvl in levels.items())
    assert any("heartbeat is 3.0 h old" in t and lvl == "ACTION" for t, lvl in levels.items())
    assert any("could not be read completely (PermissionError)" in t and lvl == "CHECK" for t, lvl in levels.items())
    assert not any("candles reached the shadow" in t or "While it ran" in t for t in levels)  # no verdicts from partial counts
    assert "Yesterday (INCOMPLETE: the journal could not be read completely (PermissionError))" in dg.render(facts)


def test_a_day_that_is_not_over_only_expects_the_hours_that_passed(tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "heartbeat.json").write_text(json.dumps(_heartbeat()), encoding="utf-8")
    today = NOW.date()  # 04:00 UTC: four hourly candles can have closed
    _jsonl(shadow / f"journal-{today.isoformat()}.jsonl", [{"kind": "candle", "instrument": "BTC-USDT", "timeframe": "1H"}] * 4)
    facts = dg.build_facts(now=NOW, day=today, shadow_dir=shadow, news_dir=tmp_path / "n", changelog_dir=tmp_path / "cl", fleet={})
    assert facts["shadow"]["day"]["expected_candles"] == 4 and facts["shadow"]["day"]["partial_day"]
    assert not any("candles reached the shadow" in a["text"] for a in facts["attention"])
    assert "4 of 4 candles so far (the day is not over)" in dg.render(facts)
    _jsonl(shadow / f"journal-{today.isoformat()}.jsonl", [{"kind": "candle", "instrument": "BTC-USDT", "timeframe": "1H"}] * 1)
    facts = dg.build_facts(now=NOW, day=today, shadow_dir=shadow, news_dir=tmp_path / "n", changelog_dir=tmp_path / "cl", fleet={})
    assert any("Only 1 of 4 1H candles reached the shadow so far today" in a["text"] for a in facts["attention"])


def test_no_candle_since_a_restart_is_timed_from_the_restart(tmp_path):
    shadow = _shadow(tmp_path, heartbeat=_heartbeat(last_candle=None))
    _jsonl(shadow / f"journal-{NOW.date().isoformat()}.jsonl",
           [{"ts": "2026-10-22T00:30:00+00:00", "kind": "supervisor", "event": "eval_window_reset"},
            {"ts": "2026-10-22T01:00:00+00:00", "kind": "supervisor", "event": "eval_window_reset"}])
    facts = _facts(tmp_path, shadow=shadow)
    assert any(a["level"] == "ACTION" and "No candle has reached the Phase 6a shadow since it restarted 3.0 h ago" in a["text"]
               for a in facts["attention"])
    recent = _shadow(tmp_path / "b", heartbeat=_heartbeat(last_candle=None))
    _jsonl(recent / f"journal-{NOW.date().isoformat()}.jsonl",
           [{"ts": "2026-10-22T03:00:00+00:00", "kind": "supervisor", "event": "eval_window_reset"}])
    assert not any("since it restarted" in a["text"] for a in _facts(tmp_path / "b", shadow=recent)["attention"])
    # no restart in today's journal nor in the digested day's: it was earlier, and no candle came since
    old = tmp_path / "c" / "shadow"
    old.mkdir(parents=True)
    (old / "heartbeat.json").write_text(json.dumps(_heartbeat(last_candle=None)), encoding="utf-8")
    _jsonl(old / f"journal-{DAY.isoformat()}.jsonl", [{"kind": "health", "ws_auth": True, "feed_usable": False}])
    _jsonl(old / f"journal-{NOW.date().isoformat()}.jsonl", [{"kind": "health", "ws_auth": True, "feed_usable": False}])
    facts = _facts(tmp_path / "c", shadow=old)
    assert any(a["level"] == "ACTION" and "No candle has reached the Phase 6a shadow for at least 28 h" in a["text"]
               for a in facts["attention"])


def test_a_missing_shadow_folder_matters_only_where_the_timer_runs(tmp_path):
    args = dict(now=NOW, day=DAY, shadow_dir=tmp_path / "nowhere", news_dir=tmp_path / "n", changelog_dir=tmp_path / "cl", fleet={})
    assert dg.build_facts(**args)["attention"] == []
    served = dg.build_facts(**args, expect_shadow=True)["attention"]
    assert [a["level"] for a in served] == ["CHECK"] and "PHASE6A_JOURNAL_DIR" in served[0]["text"]


def test_one_odd_record_never_hides_the_rest(tmp_path):
    shadow = _shadow(tmp_path, alert="reconcile_inconsistent", heartbeat=_heartbeat(ts=(NOW - timedelta(hours=3)).isoformat()))
    _jsonl(shadow / f"journal-{DAY.isoformat()}.jsonl",
           [{"kind": "ledger_reconciliation", "consistent": False, "foreign_orders": "n/a", "unexplained_balances": [1]},
            {"kind": "signal", "action": {"odd": "type"}}, {"kind": "candle", "timeframe": "1H"}])
    facts = _facts(tmp_path, shadow=shadow)
    actions = [a["text"] for a in facts["attention"] if a["level"] == "ACTION"]
    assert any("halted and waits for you" in t for t in actions) and any("heartbeat is 3.0 h old" in t for t in actions)
    assert any("1 reconciliation(s) with the exchange were inconsistent" in t for t in actions)
    assert facts["shadow"]["day"]["reconciliations"]["foreign_orders"] == 0


def test_damaged_or_unreadable_state_and_heartbeat_files(tmp_path, monkeypatch):
    shadow = _shadow(tmp_path)
    (shadow / "state.json").write_text("{damaged", encoding="utf-8")
    facts = _facts(tmp_path, shadow=shadow)
    assert any(a["level"] == "ACTION" and "could not read the shadow's state.json (unreadable (not JSON))" in a["text"]
               for a in facts["attention"])
    real = dg._read_json

    def denied(path):
        if path.name == "heartbeat.json":
            return None, "unreadable (PermissionError)"
        return real(path)

    monkeypatch.setattr(dg, "_read_json", denied)
    facts = _facts(tmp_path, shadow=shadow)
    assert any(a["level"] == "ACTION" and "could not read the shadow's heartbeat" in a["text"] for a in facts["attention"])


def test_a_missing_watcher_next_to_a_running_shadow_is_a_check(tmp_path):
    facts = _facts(tmp_path)
    assert any("changelog watcher has not run next to the shadow" in a["text"] for a in facts["attention"])


def test_a_missing_shadow_folder_is_reported_not_alarmed(tmp_path):
    facts = dg.build_facts(now=NOW, day=DAY, shadow_dir=tmp_path / "none", news_dir=tmp_path / "news",
                           changelog_dir=tmp_path / "cl", fleet={"installed": False})
    assert facts["attention"] == []
    text = dg.render(facts)
    for phrase in ("Not found here", "Not installed here yet", "Not running here", "has not run here yet", "Nothing needs your attention."):
        assert phrase in text


def test_a_missing_heartbeat_in_an_existing_folder_needs_action(tmp_path):
    facts = _facts(tmp_path, shadow=_shadow(tmp_path, heartbeat=False))
    assert any(a["level"] == "ACTION" and "no heartbeat file" in a["text"] for a in facts["attention"])


def test_file_names_match_the_services_that_write_them():
    from app.news.shadow import STATE_FILE
    from app.shadow import supervisor

    assert (dg.HEARTBEAT_FILENAME, dg.STATE_FILENAME, dg.ALERT_FILENAME) == (
        supervisor.HEARTBEAT_FILENAME, supervisor.STATE_FILENAME, supervisor.ALERT_FILENAME)
    assert dg.NEWS_STATE_FILE == STATE_FILE


def test_outside_text_is_cleaned_before_it_reaches_the_message(tmp_path):
    shadow = _shadow(tmp_path, alert="reason​ with ‮hidden‬ text\nsecond line")
    facts = _facts(tmp_path, shadow=shadow)
    text = dg.render(facts)
    assert "​" not in text and "‮" not in text and "second line" not in text


# -- the news shadow ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def news_run(tmp_path_factory):
    from app.news.dryrun import DEFAULT_SHADOW_FIXTURES, run_dry

    result = run_dry(DEFAULT_SHADOW_FIXTURES, tmp_path_factory.mktemp("news") / "out")
    assert result.ok
    return result


def test_the_news_section_uses_the_news_reports_own_numbers(news_run):
    from app.news.report import build_report_data

    now = datetime(2026, 10, 19, 13, 25, tzinfo=timezone.utc)
    day = date(2026, 10, 19)
    news = dg.collect_news(news_run.out_dir, news_run.out_dir / "phase6a", day, now, monthly_cap_usd=40.0)
    assert news["installed"] and news["state"]["found"] and news["state"]["age_minutes"] == pytest.approx(5.0)
    assert news["state"]["last_cycle_healthy"] is True and len(news["state"]["live_events"]) == 2
    assert news["day"]["headline"] == build_report_data(news_run.out_dir, news_run.out_dir / "phase6a", day)["headline"]
    assert news["spend"]["spent_usd"] > 0 and news["spend"]["cap_usd"] == 40.0
    later = dg.collect_news(news_run.out_dir, news_run.out_dir / "phase6a", day, now + timedelta(hours=2))
    facts = {"generated_at": (now + timedelta(hours=2)).isoformat(), "news": later}
    assert any(a.level == "ACTION" and "has not saved a cycle" in a.text for a in dg.attention_items(facts))


def test_news_safety_failures_and_spend_are_flagged():
    base = {"installed": True, "state": {"found": True, "age_minutes": 3.0, "last_cycle_healthy": True}}
    failed = {**base, "day": {"headline": {"invariants_ok": False, "healthy_pct": 80.0}},
              "spend": {"spent_usd": 35.0, "cap_usd": 40.0}}
    items = dg.attention_items({"generated_at": NOW.isoformat(), "news": failed})
    assert items[0].level == "ACTION" and "safety check FAILED" in items[0].text
    assert any("healthy only 80.0%" in a.text for a in items) and any("$35.00 of the $40.00" in a.text for a in items)
    unreadable = {**base, "day": {"headline": {"invariants_ok": True}}, "spend": {"error": "unreadable (not JSON)"}}
    assert any("spend record is unreadable" in a.text for a in dg.attention_items({"generated_at": NOW.isoformat(), "news": unreadable}))


def test_on_the_first_of_the_month_yesterday_belongs_to_last_months_spend(tmp_path):
    state = tmp_path / "news" / "_state"
    state.mkdir(parents=True)
    (state / "spend-2026-10.json").write_text(json.dumps({"month": "2026-10", "spent_usd": 39.0,
                                                           "by_day": {"2026-10-31": 1.7}}), encoding="utf-8")
    (state / "spend-2026-11.json").write_text(json.dumps({"month": "2026-11", "spent_usd": 0.05,
                                                           "by_day": {"2026-11-01": 0.05}}), encoding="utf-8")
    now = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    sp = dg.collect_news(tmp_path / "news", None, date(2026, 10, 31), now, monthly_cap_usd=40.0,
                         report_data=lambda *a: {"headline": {}})["spend"]
    assert sp["month"] == "2026-11" and sp["spent_usd"] == pytest.approx(0.05) and sp["yesterday_usd"] == pytest.approx(1.7)
    assert sp["previous_month"] == {"month": "2026-10", "spent_usd": 39.0}
    text = dg.render({"generated_at": now.isoformat(), "day": "2026-10-31", "attention": [],
                      "news": {"installed": True, "state": {}, "spend": sp, "day": {"headline": {}}}})
    assert "AI spend 2026-11: $0.05 of the $40.00 cap; 2026-10 closed at $39.00 (yesterday $1.70)." in text


def test_a_broken_news_log_is_a_line_not_a_crash(tmp_path):
    news = tmp_path / "news"
    (news / "_state").mkdir(parents=True)
    (news / "_state" / "shadow_state.json").write_text("{broken", encoding="utf-8")

    def boom(*args):
        raise ValueError("bad log")

    out = dg.collect_news(news, None, DAY, NOW, report_data=boom)
    assert out["state"]["error"] == "unreadable (not JSON)" and "could not be read" in out["day"]["error"]
    text = dg.render({"generated_at": NOW.isoformat(), "day": DAY.isoformat(), "news": out, "attention": []})
    assert "could not be read" in text


# -- the paper fleet ----------------------------------------------------------------------------


def _fleet_copy(tmp_path: Path, **state_changes) -> Path:
    fleet = tmp_path / "fleet"
    shutil.copytree(FLEET_FIXTURE, fleet)
    path = fleet / "_state" / "fleet_state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(state_changes)
    path.write_text(json.dumps(state), encoding="utf-8")
    return fleet


def test_fleet_facts_come_from_the_fleets_own_state(tmp_path):
    from research.paper_fleet.digest import fleet_facts

    now = datetime(2026, 10, 16, 9, 12, tzinfo=timezone.utc)
    facts = fleet_facts(_fleet_copy(tmp_path), now)
    assert facts["found"] and facts["accounts"] == 2 and facts["too_early"]
    assert facts["last_cycle_age_minutes"] == pytest.approx(2.0) and not facts["data_stale"]
    assert facts["best"]["id"] == facts["worst"]["id"] == "pf-s1s2s4-btceth-vt15"  # the only non-control account
    assert facts["days_running"] == pytest.approx((now - datetime(2026, 10, 15, 10, 20, tzinfo=timezone.utc)).total_seconds() / 86400)
    assert facts["verdicts"] == {"too early": 1} and facts["drawdown_alarms"] == []  # the weekly report's own verdicts
    rendered = dg.render({"generated_at": now.isoformat(), "day": "2026-10-15", "fleet": facts, "attention": []})
    assert "Day 1 of the forward record (too early to judge" in rendered and "2 accounts" in rendered
    late = dg.attention_items({"generated_at": (now + timedelta(hours=3)).isoformat(),
                               "fleet": fleet_facts(_fleet_copy(tmp_path / "b"), now + timedelta(hours=3))})
    assert any(a.level == "ACTION" and "paper fleet's last cycle" in a.text for a in late)


def test_fleet_verdicts_and_drawdown_alarms_reach_the_digest():
    fleet = {"installed": True, "found": True, "last_cycle_age_minutes": 1.0, "too_early": False, "days_running": 40.0,
             "accounts": 20, "in_position": 3, "verdicts": {"consistent with backtest": 9, "worse than backtest": 2},
             "drawdown_alarms": ["c03"]}
    items = dg.attention_items({"generated_at": NOW.isoformat(), "fleet": fleet})
    assert [a.level for a in items] == ["CHECK"] and "drawdown ALARM on c03" in items[0].text
    text = dg.render({"generated_at": NOW.isoformat(), "day": DAY.isoformat(), "attention": [], "fleet": fleet})
    assert "Against the backtest (weekly report): 9 consistent with backtest, 2 worse than backtest." in text


def test_fleet_problems_are_lines_not_crashes(tmp_path):
    from research.paper_fleet.digest import fleet_facts

    assert fleet_facts(tmp_path / "absent", NOW) == {"dir": str(tmp_path / "absent"), "installed": False, "found": False}
    empty = tmp_path / "empty"
    empty.mkdir()
    assert fleet_facts(empty, NOW)["found"] is False
    broken = _fleet_copy(tmp_path)
    (broken / "_state" / "fleet_state.json").write_text("{", encoding="utf-8")
    facts = fleet_facts(broken, NOW)
    assert "could not be read" in facts["error"]
    assert any("Paper fleet:" in a.text for a in dg.attention_items({"generated_at": NOW.isoformat(), "fleet": facts}))


# -- the changelog watcher ------------------------------------------------------------------------


def test_the_changelog_section_and_its_attention_rules(tmp_path):
    from app.ops.okx_changelog import run_check

    page = (ROOT / "tests" / "fixtures" / "okx_changelog" / "changelog_v1.html").read_text(encoding="utf-8")
    run_check(tmp_path / "cl", NOW - timedelta(hours=2), fetch=lambda: page)
    facts = _facts(tmp_path)
    cl = facts["changelog"]
    assert cl["installed"] and cl["entries_known"] == 12 and len(cl["flagged_recent"]) == 3
    assert any("API changelog has 3 new or edited entries" in a["text"] for a in facts["attention"])
    text = dg.render(facts)
    assert "#upcoming-changes-websocket-port-8443-discontinuation" in text
    two_days = dg.build_facts(now=NOW + timedelta(days=3), day=DAY, shadow_dir=tmp_path / "none", news_dir=tmp_path / "news",
                              changelog_dir=tmp_path / "cl", fleet={})
    assert any("has not read the changelog since" in a["text"] for a in two_days["attention"])
    assert not any("API changelog has" in a["text"] for a in two_days["attention"])  # older flags stay in the section only


def test_undelivered_changelog_alerts_stay_on_the_digest_until_sent(tmp_path):
    from app.ops.okx_changelog import run_check

    page = (ROOT / "tests" / "fixtures" / "okx_changelog" / "changelog_v1.html").read_text(encoding="utf-8")
    run_check(tmp_path / "cl", NOW - timedelta(hours=40), fetch=lambda: page, notify=lambda text: False)  # Telegram was down
    facts = dg.build_facts(now=NOW, day=DAY, shadow_dir=tmp_path / "none", news_dir=tmp_path / "news",
                           changelog_dir=tmp_path / "cl", fleet={})
    texts = [a["text"] for a in facts["attention"]]
    assert any("could not deliver 3 alert(s) yet" in t and "WebSocket port 8443 discontinuation" in t for t in texts)
    assert "Not delivered yet (retried with the next checks): 3 alert(s)." in dg.render(facts)


# -- text, numbers, Telegram ----------------------------------------------------------------------


def test_split_message_keeps_order_and_respects_the_limit():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200)) + "\n" + "y" * 450
    pieces = dg.split_message(text, limit=400)
    assert len(pieces) > 1 and all(len(p) <= 400 + 10 for p in pieces)
    assert pieces[0].startswith("(1/") and pieces[-1].startswith(f"({len(pieces)}/{len(pieces)})")
    body = "".join(p.split(") ", 1)[1] for p in pieces)
    assert body.replace("\n", "") == text.replace("\n", "")
    assert dg.split_message("short") == ["short"]


def test_numbers_are_normalized_for_the_ai_check():
    assert dg.numbers_in("2,880 checks at 03:00 UTC, floor 0.60, -1.5%, c01") == ["2880", "3", "0", "0.6", "-1.5", "1"]
    assert dg.numbers_in("best c03 -12.0%, +1.2%, −12%, -0.0") == ["3", "-12", "1.2", "-12", "0"]
    assert dg.numbers_in("on 2026-10-21, S1+S5, BTC-USDT 6H") == ["2026", "10", "21", "1", "5", "6"]  # hyphens are not signs


def test_sending_goes_through_the_existing_notifier(monkeypatch):
    sent = []

    def transport(url, payload):
        sent.append(payload["text"])
        return 200, "{}"

    ok = dg.send_text("a\n" * 10, TelegramNotifier("123:secret-token", "42", transport=transport), limit=100)
    assert ok.status == "sent" and ok.parts == 1 and sent == ["a\n" * 9 + "a"]
    assert dg.send_text("x", TelegramNotifier(None, None)).status == "missing-credentials"
    assert dg.send_text("x", TelegramNotifier("t", "c", dry_run=True, transport=transport)).status == "dry-run" and len(sent) == 1
    failed = dg.send_text("x", TelegramNotifier("123:secret-token", "42", transport=lambda u, p: (401, "bad 123:secret-token")))
    assert failed.status == "failed" and "secret-token" not in failed.error


def test_building_a_digest_reads_files_only(tmp_path, monkeypatch, news_run):
    """No network, and no source file is touched: the digest only writes its own outputs."""
    shadow = _shadow(tmp_path)
    fleet = _fleet_copy(tmp_path)
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for root in (shadow, fleet, news_run.out_dir) for p in root.rglob("*") if p.is_file()}

    def no_network(*args, **kwargs):
        raise AssertionError("the digest must not open a network connection")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    from research.paper_fleet.digest import fleet_facts

    facts = dg.build_facts(now=NOW, day=DAY, shadow_dir=shadow, news_dir=news_run.out_dir, changelog_dir=tmp_path / "cl",
                           fleet=fleet_facts(fleet, NOW))
    md, js = dg.write_outputs(tmp_path / "ops" / "digest", facts, dg.render(facts))
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for root in (shadow, fleet, news_run.out_dir) for p in root.rglob("*") if p.is_file()}
    assert before == after
    assert json.loads(js.read_text(encoding="utf-8"))["day"] == DAY.isoformat() and md.read_text(encoding="utf-8").startswith("AI trading")


# -- the script ---------------------------------------------------------------------------------


def _script():
    import importlib.util
    import sys

    name = "ops_digest_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "ops_digest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # its dataclass looks its module up while the class is built
    spec.loader.exec_module(module)
    return module


def _dirs(tmp_path):
    return ["--shadow-dir", str(_shadow(tmp_path)), "--news-dir", str(tmp_path / "news"), "--fleet-dir", str(tmp_path / "fleet"),
            "--ops-dir", str(tmp_path / "ops")]


def test_the_script_prints_by_default_and_never_sends(tmp_path, capsys):
    script = _script()
    assert script.main(_dirs(tmp_path) + ["--day", DAY.isoformat()], env={"TELEGRAM_BOT_TOKEN": "1:x", "TELEGRAM_CHAT_ID": "2"}) == 0
    out = capsys.readouterr().out
    assert out.startswith("AI trading system - daily digest") and "PHASE 6A SHADOW" in out
    assert not (tmp_path / "ops").exists()  # printing writes nothing


def test_the_script_sends_saves_and_logs(tmp_path, capsys, monkeypatch):
    script = _script()
    assert script.main(_dirs(tmp_path) + ["--send"], env={}) == 2  # no Telegram credentials
    assert script.main(_dirs(tmp_path) + ["--send", "--day", DAY.isoformat()], env={"TELEGRAM_DRY_RUN": "1"}) == 0
    digest = tmp_path / "ops" / "digest"
    assert (digest / f"digest-{DAY.isoformat()}.md").exists() and (digest / f"digest-{DAY.isoformat()}.json").exists()
    run = json.loads((digest / "digest.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert run["send"] == "dry-run" and run["ai"] == "no_key"
    import app.notify.telegram as tg

    monkeypatch.setattr(tg, "_requests_transport", lambda url, payload: (500, "server error"))
    env = {"TELEGRAM_BOT_TOKEN": "123:not-a-real-token", "TELEGRAM_CHAT_ID": "42"}
    assert script.main(_dirs(tmp_path) + ["--send"], env=env) == 1
    err = capsys.readouterr().err
    assert "NOT sent (failed" in err and "not-a-real-token" not in err


def test_the_message_goes_out_even_when_it_cannot_be_saved(tmp_path, capsys, monkeypatch):
    script = _script()

    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(dg, "write_outputs", full_disk)
    assert script.main(_dirs(tmp_path) + ["--send"], env={"TELEGRAM_DRY_RUN": "1"}) == 1
    out = capsys.readouterr()
    assert "dry-run in 1 message(s); NOT saved" in out.out and "could not save" in out.err


def test_the_scripts_dry_run_passes_its_checks(capsys):
    assert _script().main(["--dry-run"], env={}) == 0
    out = capsys.readouterr().out
    assert "DRY RUN on the bundled fixtures" in out and "FAILED" not in out and out.count("check: ") >= 10
