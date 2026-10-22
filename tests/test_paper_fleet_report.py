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
    render,
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
    assert "FOMC calendar runs out" not in text  # the built-in calendar runs to 2027-12-08 since plan row R7 (it ended 2026-12-09)


def test_report_warns_60_days_before_the_fomc_calendar_runs_out(tmp_path):
    paths = _fleet(tmp_path, "2027-11-01T00:00:00Z", "2027-11-03T00:05:00Z")
    text = write_week(paths, datetime(2027, 11, 3, 0, 30, tzinfo=timezone.utc)).read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if "FOMC calendar runs out" in l)
    assert "last built-in FOMC date is 2027-12-08" in line and "tests/fixtures/fomc_calendar/README.md" in line and "R7" not in line


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


# -- plan row R5b: the allocator section -----------------------------------------------------------------------------

SLEEVES = {"S1/BTC/6H": {"candidate": "S1"}, "S1/ETH/6H": {"candidate": "S1"}}
V2_CFG = {"corr_lookback_days": 60, "corr_min_days": 20, "corr_threshold": 0.7, "group_cap": 0.5, "loss_window_days": 7, "loss_limit": 0.05,
          "cooldown_days": 7}


def _pf_day(day: pd.Timestamp, idx: float, ret: float, *, v2: bool, ref_idx: float = 1.0, ref_ret: float = 0.0, cap: bool = False,
            trip: bool = False, cool: int = 0, in_cool: bool = False, seq: int = 1):
    rec = {"type": "portfolio_day", "day": day.strftime("%Y-%m-%d"), "equity_index": idx, "portfolio_return": ret, "equity": 10_000 * idx,
           "gross_exposure_end_of_day": 0.2, "vol_scale": 1.0, "ladder_multiplier": 1.0, "seq": seq}
    if v2:
        brakes = (["correlation cap"] if cap else []) + (["cooldown"] if in_cool else [])
        rec.update({"allocator": "v2", "brakes": brakes, "invested_share": 0.5 if cap else 0.2, "invested_share_reference": 0.8 if cap else 0.2,
                    "invested_before_cap": {"S1/BTC/6H+S1/ETH/6H": 0.8 if cap else 0.2}, "groups": [["S1/BTC/6H", "S1/ETH/6H"]],
                    "loss_limit_tripped": trip, "loss_window_return": -0.061 if trip else -0.01, "loss_multiplier": 0.0 if in_cool else 1.0,
                    "cooldown_days_left": cool, "ladder_level_after": 0, "correlations": {"BTC-USDT/ETH-USDT": 0.83},
                    "reference_v1": {"return": ref_ret, "equity_index": ref_idx, "ladder_multiplier": 1.0}})
    return rec


def _fleet_with_portfolios(tmp_path, *, created="2026-11-02T00:00:00Z", last_cycle="2026-12-15T00:05:00Z", days=40):
    paths = FleetPaths(tmp_path)
    paths.ensure()
    v2_exp = {"walk_forward": {"cagr": 0.1047, "ann_vol": 0.124, "sharpe": 0.86, "max_drawdown": 0.1229, "trades_per_year": 152.0},
              "reference_v1": {"walk_forward": {"cagr": 0.1093, "ann_vol": 0.1387, "sharpe": 0.82, "max_drawdown": 0.1318}},
              "brakes": {"correlation_cap_days_share": 0.0548, "loss_limit_trips_per_year": 0.23},
              "holdout": {"total_return": -0.0928, "ann_vol": 0.083, "max_drawdown": 0.1444, "bars": 366, "confirmed": False}}
    accounts = [
        {"account_id": "pf-s1s2s4-btceth-vt15", "role": "portfolio", "kind": "portfolio", "label": "v1", "instrument": None, "timeframe": None,
         "portfolio": {"sleeves": SLEEVES}, "expectations": {"walk_forward": {"cagr": 0.1093, "ann_vol": 0.1387, "sharpe": 0.82, "max_drawdown": 0.1318}}},
        {"account_id": "pf-s1s2s4-btceth-vt15-alloc2", "role": "portfolio", "kind": "portfolio", "label": "allocator v2", "instrument": None,
         "timeframe": None, "portfolio": {"sleeves": SLEEVES, "allocator": V2_CFG}, "expectations": v2_exp},
    ]
    state = {"version": 2, "created_at": created, "last_cycle": last_cycle, "cycles": 10, "fingerprint": "f", "positioning_source": "okx",
             "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {}, "fits": {}, "portfolios": {},
             "health": {"stale": False, "newest_candle": {"BTC-USDT": last_cycle}}}
    write_state(paths.state_file, state)
    t0 = pd.Timestamp(created) + pd.Timedelta(days=1)
    v1 = [{"type": "start", "seq": 1}, {"type": "portfolio_warmup", "forward_start_day": t0.strftime("%Y-%m-%d"), "seq": 2}]
    v2 = [{"type": "start", "seq": 1}, {"type": "portfolio_warmup", "forward_start_day": t0.strftime("%Y-%m-%d"), "seq": 2}]
    e1 = e2 = 1.0
    for i in range(days):
        day = t0 + pd.Timedelta(days=i)
        r1 = -0.004 if i % 3 == 0 else 0.002
        # As allocator v2 books it: tripped at the close of day 20, in cash on days 21-27, re-armed from day 28.
        trip, in_cool, cap = i == 20, 21 <= i <= 27, i in (5, 6, 30)
        cool = 7 if trip else (27 - i if in_cool else 0)
        r2 = 0.0 if in_cool else (r1 * 0.6 if cap else r1)
        e1 *= 1 + r1
        e2 *= 1 + r2
        v1.append(_pf_day(day, e1, r1, v2=False, seq=i + 3))
        v2.append(_pf_day(day, e2, r2, v2=True, ref_idx=e1, ref_ret=r1, cap=cap, trip=trip, cool=cool, in_cool=in_cool, seq=i + 3))
    Journal(paths.journal("pf-s1s2s4-btceth-vt15")).append(v1)
    Journal(paths.journal("pf-s1s2s4-btceth-vt15-alloc2")).append(v2)
    return paths


def test_the_allocator_section_compares_v2_with_v1_on_the_same_sleeves_and_lists_every_brake(tmp_path):
    paths = _fleet_with_portfolios(tmp_path)
    data = build_report_data(paths, datetime(2026, 12, 15, 1, 0, tzinfo=timezone.utc))
    row = next(r for r in data["rows"] if r["account"]["account_id"].endswith("alloc2"))
    act, ref = row["allocator"]["since_start"], row["allocator"]["reference"]
    assert act["days"] == 40 and act["cap_days"] == 3 and act["cooldown_days"] == 7 and act["trips"] == [("2026-11-23", -0.061)]
    assert act["cap_average_cut"] == pytest.approx(1 - 0.5 / 0.8) and ref.days == 40
    twin = next(r for r in data["rows"] if r["account"]["account_id"] == "pf-s1s2s4-btceth-vt15")
    assert ref.total_return == pytest.approx(twin["metrics"].total_return)  # the reference IS the v1 account here (same start, same sleeves)
    text = render(data)
    section = text[text.index("## Allocator v2"):text.index("## This week")]
    assert text.index("## Ranking") < text.index("## Allocator v2") < text.index("## This week")
    assert "| v1 on the same sleeves (in its journal) | 40 |" in section and "| v1 account (`pf-s1s2s4-btceth-vt15`) | 40 |" in section
    assert "correlation cap on 3 days" in section and "tripped once (2026-11-23 after -6.10% in a week)" in section
    assert "7 days in cash for the cooldown" in section and "coins count as one bet" in section
    assert "not confirmed" in section and "+10.47% a year" in section and "brakes' own effect so far" in section
    assert "its allocator-v2 twin" in text and "SIMULATION ONLY" in text


def test_the_allocator_section_names_the_holdout_span_and_survives_a_retired_v1_account(tmp_path):
    paths = _fleet_with_portfolios(tmp_path)
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    alloc = state["manifest"]["accounts"][1]
    alloc["expectations"]["holdout"].update(first_day="2025-10-21", last_day="2026-10-19", reference_v1_total_return=-0.15)
    state["manifest"]["accounts"] = [alloc]  # the v1 portfolio account retired: only the allocator-v2 account is left
    write_state(paths.state_file, state)
    text = render(build_report_data(paths, datetime(2026, 12, 15, 1, 0, tzinfo=timezone.utc)))
    assert "1 paper accounts: 0 shortlisted configurations, the allocator-v2 portfolio and 0 controls" in text
    section = text[text.index("## Allocator v2"):text.index("## This week")]
    assert "(2025-10-21 to 2026-10-19)" in section and "v1 on the same sleeves -15.00%" in section and "not confirmed" in section
    assert "v1 account (`" not in section and "| v1 on the same sleeves (in its journal) |" in section
    assert "multiplier between 0 and 1 on v2's own sizing" in section and "count from the next close" in section


def test_no_allocator_section_without_an_allocator_account(tmp_path):
    paths = _fleet(tmp_path, "2026-11-02T00:00:00Z", "2026-11-04T00:05:00Z")
    text = write_week(paths, datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc)).read_text(encoding="utf-8")
    assert "## Allocator v2" not in text and "allocator-v2 twin" not in text
