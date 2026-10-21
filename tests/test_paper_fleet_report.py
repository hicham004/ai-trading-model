"""Paper-fleet weekly report: metrics from journals, pre-declared bands and verdicts, controls first, plain words."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from research.paper_fleet.report import (
    BAND_Z,
    MIN_DAYS_FOR_VERDICT,
    ForwardMetrics,
    ReportScheduler,
    build_report_data,
    count_band,
    return_band,
    sharpe_band,
    sleeve_metrics,
    verdicts,
    week_label,
    write_week,
)
from research.paper_fleet.store import FleetPaths, Journal, write_state


def _bar(t: pd.Timestamp, equity: float, *, events=(), in_position=False, allocation=0.0, anchor=False, seq=1):
    return {"type": "bar", "bar": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "close_time": (t + pd.Timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "equity": equity, "in_position": in_position, "allocation": allocation, "anchor": anchor, "events": list(events), "seq": seq}


def test_sleeve_metrics_from_bar_records():
    t0 = pd.Timestamp("2026-11-02 00:00", tz="UTC")
    recs = [_bar(t0, 10_000, anchor=True)]
    eq = [10_000, 10_100, 9_900, 10_200, 10_200]
    for k, e in enumerate(eq[1:], start=1):
        ev = []
        if k == 1:
            ev = [{"kind": "entry", "fee": 1.0}]
        if k == 3:
            ev = [{"kind": "exit", "fee": 1.5, "pnl": 200.0}]
        recs.append(_bar(t0 + pd.Timedelta(hours=4 * k), e, events=ev, in_position=k in (1, 2), allocation=0.5 if k in (1, 2) else 0.0))
    m = sleeve_metrics(recs, "4H", 10_000.0)
    assert m.total_return == pytest.approx(0.02) and m.max_drawdown == pytest.approx(200 / 10_100)
    assert (m.entries, m.closed_trades, m.wins, m.fees) == (1, 1, 1, 2.5) and m.profit_factor == float("inf")
    assert m.exposure == pytest.approx(0.5) and m.avg_allocation == pytest.approx(0.25) and m.days == pytest.approx(16 / 24)
    assert sleeve_metrics(recs, "4H", 10_000.0, until=t0 + pd.Timedelta(hours=8)).equity == 10_100


def test_bands_are_the_pre_declared_formulas():
    exp, lo, hi = return_band(0.10, 0.20, 365.25)
    assert exp == pytest.approx(0.10) and hi - exp == pytest.approx(BAND_Z * 0.20) and exp - lo == pytest.approx(BAND_Z * 0.20)
    exp, lo, hi = return_band(0.10, 0.20, 91.3125)
    assert exp == pytest.approx(1.10 ** 0.25 - 1) and hi - exp == pytest.approx(BAND_Z * 0.20 * 0.5)
    sr, lo, hi = sharpe_band(0.8, 365.25, 365.25)  # daily returns, one year: SE = sqrt(1 + 0.64 / 730.5)
    assert hi - sr == pytest.approx(BAND_Z * math.sqrt(1 + 0.64 / 730.5))
    sr4, lo4, hi4 = sharpe_band(0.8, 4 * 365.25, 2191.5)  # 4H bars, four years: about +-1 Sharpe point
    assert hi4 - sr4 == pytest.approx(BAND_Z * math.sqrt((1 + 0.64 / 4383.0) / 4.0))
    lam, lo, hi = count_band(36.525, 100.0)
    assert lam == pytest.approx(10.0) and lo == pytest.approx(10 - 2 * math.sqrt(10)) and hi == pytest.approx(10 + 2 * math.sqrt(10))
    assert return_band(None, 0.2, 10) is None and count_band(5.0, 0) is None


def _m(days, ret, dd=0.01, sharpe=0.5, entries=3):
    return ForwardMetrics(days, None, None, 10_000 * (1 + ret), ret, 0.1, sharpe, dd, entries, entries, 1, 1.2, 1.0, 0.5, 0.2, False, 0.0, 10)


ACCOUNT = {"account_id": "c01-x", "kind": "sleeve", "role": "candidate", "timeframe": "6H", "sleeve": {"candidate": "S1+S5"},
           "expectations": {"walk_forward": {"cagr": 0.05, "ann_vol": 0.06, "sharpe": 0.86, "max_drawdown": 0.088, "trades_per_year": 32.0},
                            "holdout": {"total_return": 0.023, "ann_vol": 0.047, "bars": 1461}}}


def test_verdicts_wait_thirty_days_then_judge_against_the_bands():
    assert verdicts(ACCOUNT, _m(MIN_DAYS_FOR_VERDICT - 1, -0.5))["status"] == "too early"
    v = verdicts(ACCOUNT, _m(120, 0.015, entries=10))
    assert (v["return"], v["entries"], v["status"], v["drawdown"]) == ("within", "within", "consistent with backtest", "ok")
    assert verdicts(ACCOUNT, _m(120, -0.08))["status"] == "worse than backtest"
    assert verdicts(ACCOUNT, _m(120, 0.12))["status"] == "better than backtest"
    assert verdicts(ACCOUNT, _m(120, 0.01, dd=0.10))["drawdown"] == "above backtest worst"
    alarm = verdicts(ACCOUNT, _m(120, 0.01, dd=0.14))
    assert alarm["drawdown"] == "ALARM" and alarm["status"] == "worse than backtest"
    assert verdicts(ACCOUNT, _m(120, 0.01, entries=0))["entries"] == "fewer"
    assert verdicts(ACCOUNT, _m(60, 0.01))["sharpe"] == "too early" and verdicts(ACCOUNT, _m(120, 0.01))["sharpe"] in ("within", "below", "above")
    assert verdicts(ACCOUNT, _m(120, 0.01))["holdout"] in ("within", "below", "above")
    bh = {"account_id": "ctl-bh", "kind": "buy_and_hold", "role": "control", "timeframe": "4H",
          "expectations": {"walk_forward": {"cagr": 0.26, "max_drawdown": 0.77}, "holdout": None, "benchmark": True}}
    v = verdicts(bh, _m(120, -0.3, dd=0.3))
    assert v["status"] == "benchmark" and v["entries"] == "n/a (always long)"


def _fleet(tmp_path, created: str, last_cycle: str):
    paths = FleetPaths(tmp_path)
    paths.ensure()
    accounts = [
        {"account_id": "ctl-hold-btc-4h", "role": "control", "kind": "sleeve", "label": "control: always long, policy sizing — BTC-USDT 4H",
         "instrument": "BTC-USDT", "timeframe": "4H", "sleeve": {"candidate": "hold"}, "shortlist_rank": None,
         "expectations": {"walk_forward": {"cagr": 0.032, "ann_vol": 0.056, "sharpe": 0.59, "max_drawdown": 0.072, "trades_per_year": 2.07}, "holdout": None}},
        {"account_id": "c01-s1s5-btc-4h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 4H (no regime gate)",
         "instrument": "BTC-USDT", "timeframe": "4H", "sleeve": {"candidate": "S1+S5"}, "shortlist_rank": 1, "expectations": ACCOUNT["expectations"]},
    ]
    state = {"version": 1, "created_at": created, "last_cycle": last_cycle, "cycles": 10, "fingerprint": "f", "positioning_source": "okx",
             "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {"BTC-USDT 4H": {"anchor": created, "last_bar": None, "bars": 3, "gaps": 0}},
             "fits": {}, "health": {"stale": False, "newest_candle": {"BTC-USDT": last_cycle}}}
    write_state(paths.state_file, state)
    t0 = pd.Timestamp(created)
    for k, acc in enumerate(accounts):
        recs = [{"type": "start", "seq": 1}]
        e = 10_000.0
        for i in range(12):
            e *= 1.001 if k == 0 else 0.999
            recs.append(_bar(t0 + pd.Timedelta(hours=4 * i), 10_000.0 if i == 0 else e, anchor=i == 0, seq=i + 2,
                             in_position=i > 0, allocation=0.3 if i > 0 else 0.0,
                             events=[{"kind": "entry", "fee": 1.0}] if i == 1 else []))
            recs[-1]["decision"] = {"signal": {"action": "long"}, "diagnostics": {"desired": k == 0}}
        Journal(paths.journal(acc["account_id"])).append(recs)
    return paths


def test_report_puts_the_controls_first_and_speaks_plainly(tmp_path):
    paths = _fleet(tmp_path, "2026-11-02T00:00:00Z", "2026-11-04T00:05:00Z")
    out = write_week(paths, datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc))
    text = out.read_text(encoding="utf-8")
    assert out.name == "weekly-2026-W45.md" and "week to date" in text.splitlines()[0]
    assert "SIMULATION ONLY" in text and "Nothing here is an order" in text
    assert text.index("## Controls (read these first)") < text.index("## Ranking")
    assert "## In short (plain English)" in text and "No ranking yet" in text
    assert "too early" in text and "blocked by a filter" in text
    assert "until 2026-11-04 00:05 UTC" in text.splitlines()[0]  # a report ends at the fleet's last cycle
    assert "FOMC calendar runs out" in text  # the built-in calendar ends 2026-12-09, within 60 days of this report


def test_scheduler_finalizes_the_previous_week_once(tmp_path):
    paths = _fleet(tmp_path, "2026-11-02T00:00:00Z", "2026-11-10T00:05:00Z")
    sched = ReportScheduler(paths, every_minutes=60)
    written = sched(datetime(2026, 11, 10, 0, 10, tzinfo=timezone.utc))
    names = sorted(p.split("weekly-")[-1] for p in written)
    assert names == ["2026-W45.md", "2026-W46.md"]
    first = (paths.reports / "weekly-2026-W45.md").read_text(encoding="utf-8").splitlines()[0]
    assert "final" in first
    assert sched(datetime(2026, 11, 10, 0, 20, tzinfo=timezone.utc)) == []  # rate-limited
    again = ReportScheduler(paths, every_minutes=60)(datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc))
    assert [p.split("weekly-")[-1] for p in again] == ["2026-W46.md"]  # the final week is not rewritten
    assert week_label(2026, 3) == "2026-W03"


def test_report_data_compares_each_configuration_with_its_control(tmp_path):
    paths = _fleet(tmp_path, "2026-11-02T00:00:00Z", "2026-11-04T00:05:00Z")
    data = build_report_data(paths, datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc))
    rows = {r["account"]["account_id"]: r for r in data["rows"]}
    c = rows["c01-s1s5-btc-4h-none"]
    assert c["vs_control"] == pytest.approx(c["metrics"].total_return - rows["ctl-hold-btc-4h"]["metrics"].total_return)
    assert rows["ctl-hold-btc-4h"]["vs_control"] is None
    assert json.dumps({k: v for k, v in c["metrics"].to_dict().items()}, default=str)


def test_a_week_to_date_file_is_finalized_once_the_week_is_over(tmp_path):
    paths = _fleet(tmp_path, "2026-11-02T00:00:00Z", "2026-11-08T23:35:00Z")
    sched = ReportScheduler(paths, every_minutes=60)
    sched(datetime(2026, 11, 8, 23, 40, tzinfo=timezone.utc))  # Sunday evening: W45 week to date
    assert "week to date" in (paths.reports / "weekly-2026-W45.md").read_text(encoding="utf-8").splitlines()[0]
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    state["last_cycle"] = "2026-11-09T00:10:00Z"
    write_state(paths.state_file, state)
    written = ReportScheduler(paths, every_minutes=60)(datetime(2026, 11, 9, 0, 15, tzinfo=timezone.utc))  # Monday
    assert any(p.endswith("weekly-2026-W45.md") for p in written)
    first = (paths.reports / "weekly-2026-W45.md").read_text(encoding="utf-8").splitlines()[0]
    assert "final" in first and "week to date" not in first
