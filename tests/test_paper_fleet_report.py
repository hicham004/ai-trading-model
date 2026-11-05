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


# -- plan row R17: the "S5 running without data" label --------------------------------------------------------------------

S5_NOTE = "S5 running without data: the filter passes (funding missing, open interest missing)"


def _fleet_s5(tmp_path, *, created="2026-11-02T00:00:00Z", last_cycle="2026-11-04T00:05:00Z"):
    """Three sleeve accounts: S1+S5 on BTC with current data, S1+S5 on SOL without any, and plain S1 on SOL (no filter)."""
    paths = FleetPaths(tmp_path)
    paths.ensure()
    exp = ACCOUNT["expectations"]
    accounts = [
        {"account_id": "c01-s1s5-btc-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 6H (no regime gate)",
         "instrument": "BTC-USDT", "timeframe": "6H", "sleeve": {"candidate": "S1+S5"}, "shortlist_rank": 1, "expectations": exp},
        {"account_id": "c11-s1s5-sol-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 SOL-USDT 6H (no regime gate) — from R12 replication",
         "instrument": "SOL-USDT", "timeframe": "6H", "sleeve": {"candidate": "S1+S5"}, "shortlist_rank": 11, "expectations": exp},
        {"account_id": "c12-s1-sol-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1 SOL-USDT 6H (no regime gate) — from R12 replication",
         "instrument": "SOL-USDT", "timeframe": "6H", "sleeve": {"candidate": "S1"}, "shortlist_rank": 12, "expectations": exp},
    ]
    health = {"stale": False, "newest_candle": {"BTC-USDT": last_cycle, "SOL-USDT": last_cycle},
              "positioning": {"source": "okx", "last_refresh": last_cycle, "last_errors": [],
                              "markets": {"BTC-USDT": {"swap": "BTC-USDT-SWAP", "funding_newest": "2026-11-04T00:00:00Z", "open_interest_newest": "2026-11-04T00:00:00Z"},
                                          "SOL-USDT": {"swap": "SOL-USDT-SWAP", "funding_newest": None, "open_interest_newest": None}}}}
    state = {"version": 2, "created_at": created, "last_cycle": last_cycle, "cycles": 10, "fingerprint": "f", "positioning_source": "okx",
             "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {}, "fits": {}, "portfolios": {}, "health": health}
    write_state(paths.state_file, state)
    t0 = pd.Timestamp(created)
    for acc in accounts:
        recs = [{"type": "start", "seq": 1}]
        for i in range(6):
            rec = _bar(t0 + pd.Timedelta(hours=6 * i), 10_000.0, anchor=i == 0, seq=i + 2)
            rec["close_time"] = (t0 + pd.Timedelta(hours=6 * (i + 1))).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec["decision"] = {"signal": {"action": "flat"}, "diagnostics": {"desired": False}}
            if acc["account_id"] == "c01-s1s5-btc-6h-none":
                rec["positioning_age_hours"] = {"funding": 2.0, "open_interest": 0.0}
                rec["positioning_data"] = {"source": "okx", "funding": "current", "open_interest": "current", "complete": True, "note": "S5 data current"}
            elif acc["account_id"] == "c11-s1s5-sol-6h-none":
                rec["positioning_age_hours"] = {"funding": None, "open_interest": None}
                if i >= 3:  # bars written since R17 carry the label; the older ones only the ages (read through the same rule)
                    rec["positioning_data"] = {"source": "okx", "funding": "missing", "open_interest": "missing", "complete": False, "note": S5_NOTE}
            recs.append(rec)
        Journal(paths.journal(acc["account_id"])).append(recs)
    return paths


# -- plan row R18b: the Trader tier beside the Reference tier --------------------------------------------------------------------

from research.paper_fleet.report import tier_activity, tier_pairs  # noqa: E402

RULE = {"candidate": "S1+S5", "params": {"vote": 2, "atr_mult": 3.0, "bracket": "none"}, "regime": {"mode": "none"}}
TIER_EXP = {**ACCOUNT["expectations"], "tier": {"name": "trader", "risk_pct_mean": 0.0173, "risk_pct_max": 0.0204, "cap_binding_share": 0.64,
                                                "expectancy_r": 0.27, "brakes_per_year": {"entry_after_exit": 7.5, "ladder": 0.2, "hard_stop": 0.0}}}


def _fleet_tier(tmp_path, *, created="2026-11-02T00:00:00Z", last_cycle="2026-11-05T00:05:00Z", extra=()):
    """A Trader-tier account, its Reference twin, the three controls of its market and an unrelated gated account (plus ``extra`` accounts,
    plan row R23: an id ending in ``trader`` gets the Trader-style journal with entries, brakes and a tripped limit)."""
    paths = FleetPaths(tmp_path)
    paths.ensure()
    accounts = [
        {"account_id": "c01-s1s5-btc-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 6H (no regime gate)", "instrument": "BTC-USDT",
         "timeframe": "6H", "sleeve": dict(RULE, sizing={"label": "vt10/30 crash15/90dh ladder"}), "shortlist_rank": 1, "expectations": ACCOUNT["expectations"]},
        {"account_id": "c17-s1s5-btc-6h-none-trader", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 6H (no regime gate) — trader tier",
         "instrument": "BTC-USDT", "timeframe": "6H", "sleeve": dict(RULE, sizing={"label": "vt20/30 crash15/90dh cap2"}, brakes={"hard_stop_dd": 0.3}),
         "shortlist_rank": 17, "expectations": TIER_EXP, "tier": "trader"},
        {"account_id": "c13-s1vc-btc-4h-gate", "role": "candidate", "kind": "sleeve", "label": "S1+VC BTC-USDT 4H (gate)", "instrument": "BTC-USDT",
         "timeframe": "4H", "sleeve": {"candidate": "S1+VC", "params": {"vote": 1}, "regime": {"mode": "gate"}}, "shortlist_rank": 13, "expectations": ACCOUNT["expectations"]},
        {"account_id": "ctl-hold-btc-6h", "role": "control", "kind": "sleeve", "label": "control: always long, policy sizing — BTC-USDT 6H", "instrument": "BTC-USDT",
         "timeframe": "6H", "sleeve": {"candidate": "hold"}, "expectations": {"walk_forward": {"cagr": 0.026, "ann_vol": 0.057, "sharpe": 0.49, "max_drawdown": 0.08}}},
        {"account_id": "ctl-bh-btc-6h", "role": "control", "kind": "buy_and_hold", "label": "control: plain buy-and-hold — BTC-USDT 6H", "instrument": "BTC-USDT",
         "timeframe": "6H", "expectations": {"walk_forward": {"cagr": 0.3, "max_drawdown": 0.77}, "holdout": None, "benchmark": True}},
        {"account_id": "ctl-tf-btc-6h", "role": "control", "kind": "sleeve", "label": "control: always long above the 200-day average, policy sizing — BTC-USDT 6H",
         "instrument": "BTC-USDT", "timeframe": "6H", "sleeve": {"candidate": "TF", "params": {"sma_days": 200.0}}, "tier": "reference",
         "expectations": {"walk_forward": {"cagr": 0.037, "ann_vol": 0.061, "sharpe": 0.62, "max_drawdown": 0.076, "trades_per_year": 9.3}, "holdout": None}},
    ]
    accounts += [dict(a) for a in extra]
    state = {"version": 2, "created_at": created, "last_cycle": last_cycle, "cycles": 10, "fingerprint": "f", "positioning_source": "okx",
             "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {}, "fits": {}, "portfolios": {},
             "health": {"stale": False, "newest_candle": {"BTC-USDT": last_cycle}}}
    write_state(paths.state_file, state)
    t0 = pd.Timestamp(created)
    for acc in accounts:
        recs = [{"type": "start", "seq": 1}]
        e = 10_000.0
        for i in range(12):
            e *= 1.002 if acc["account_id"].endswith("trader") else 1.001
            events = []
            if acc["account_id"].endswith("trader"):
                if i == 1:
                    events = [{"kind": "entry", "fee": 1.0, "risk": 180.0, "risk_pct": 0.018, "brake_multiplier": 1.0}]
                elif i == 3:
                    events = [{"kind": "exit", "fee": 1.0, "pnl": -180.0, "reason": "stop_loss"}]
                elif i == 4:
                    events = [{"kind": "brake", "multiplier": 0.0, "cuts": {}, "blocked_by": ["entry_after_exit"]}, {"kind": "entry_skipped", "reason": "brake"}]
                elif i == 5:
                    events = [{"kind": "brake", "multiplier": 0.8, "cuts": {"ladder": 0.8}, "blocked_by": []},
                              {"kind": "entry", "fee": 1.0, "risk": 150.0, "risk_pct": 0.015, "brake_multiplier": 0.8}]
                elif i == 8:
                    events = [{"kind": "brake_trip", "brake": "daily_loss", "loss_24h": -0.031}]
            elif acc["kind"] == "sleeve" and acc["role"] == "candidate" and i == 1:
                events = [{"kind": "entry", "fee": 1.0, "risk": 60.0, "risk_pct": 0.006}]
            rec = _bar(t0 + pd.Timedelta(hours=6 * i), 10_000.0 if i == 0 else e, anchor=i == 0, seq=i + 2, events=events, in_position=i > 0,
                       allocation=0.3 if i > 0 else 0.0)
            rec["close_time"] = (t0 + pd.Timedelta(hours=6 * (i + 1))).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec["decision"] = {"signal": {"action": "long"}, "diagnostics": {"desired": True}}
            if acc["account_id"].endswith("trader"):
                rec["brakes"] = {"turtle_multiplier": 0.8 if i >= 5 else 1.0, "halted": False, "week_blocked": False, "month_blocked": False}
            recs.append(rec)
        Journal(paths.journal(acc["account_id"])).append(recs)
    return paths


def test_the_report_puts_the_trader_tier_beside_its_reference_twin_and_the_controls(tmp_path):
    paths = _fleet_tier(tmp_path)
    data = build_report_data(paths, datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc))
    rows = {r["account"]["account_id"]: r for r in data["rows"]}
    pairs = tier_pairs(data["rows"])
    assert len(pairs) == 1 and pairs[0]["row"]["account"]["account_id"] == "c17-s1s5-btc-6h-none-trader"
    assert pairs[0]["twin"]["account"]["account_id"] == "c01-s1s5-btc-6h-none"  # the same rule, the Reference sizing; c13 is another rule
    assert pairs[0]["hold"]["account"]["account_id"] == "ctl-hold-btc-6h" and pairs[0]["buy_and_hold"]["account"]["account_id"] == "ctl-bh-btc-6h"
    assert pairs[0]["tf"]["account"]["account_id"] == "ctl-tf-btc-6h"
    act = rows["c17-s1s5-btc-6h-none-trader"]["tier_activity"]["since_start"]
    assert act["entries"] == 2 and act["risk_pct_mean"] == pytest.approx(0.0165) and act["risk_pct_max"] == 0.018 and act["risk_pct_last"] == 0.015
    assert act["cuts"] == {"ladder": 1} and act["blocks"] == {"entry_after_exit": 1} and act["blocked_entries"] == 1 and act["trips"] == {"daily_loss": 1}
    assert act["last"]["turtle_multiplier"] == 0.8 and rows["c01-s1s5-btc-6h-none"]["tier_activity"]["since_start"]["risk_pct_mean"] == 0.006
    assert rows["c01-s1s5-btc-6h-none"]["tier_activity"]["since_start"]["cuts"] == {} and "tier_activity" not in rows["ctl-bh-btc-6h"]
    assert tier_activity([])["risk_pct_mean"] is None and tier_activity([])["last"] is None
    text = render(data)
    short = text[text.index("## In short"):text.index("## Controls")]
    assert "long only above the 200-day average (policy sizing) made" in short and "(BTC-USDT 6H)" in short
    assert "Trader tier (plan row R18): 1 account run" in short and "`c17-s1s5-btc-6h-none-trader`" in short and "against `c01-s1s5-btc-6h-none`" in short
    section = text[text.index("## Trader tier beside the Reference tier"):text.index("## This week")]
    assert section.index("| S1+S5 BTC-USDT 6H | `c17-s1s5-btc-6h-none-trader` | trader |") < section.index("| Reference twin | `c01-s1s5-btc-6h-none` | reference |")
    assert "| always long, policy sizing | `ctl-hold-btc-6h` |" in section and "| plain buy-and-hold | `ctl-bh-btc-6h` | all in |" in section
    assert "| long above the 200-day average, policy sizing | `ctl-tf-btc-6h` |" in section
    trader_line = next(l for l in section.splitlines() if "`c17-s1s5-btc-6h-none-trader` | trader |" in l)
    assert "| 1.65% / 1.80% | Turtle ladder cut once; no-entry-after-an-exit blocked once |" in trader_line
    twin_line = next(l for l in section.splitlines() if "`c01-s1s5-btc-6h-none` | reference |" in l)
    assert "| 0.60% / 0.60% | - |" in twin_line
    assert "the 24-hour loss limit once" in section and "Turtle multiplier 0.80" in section
    assert "Backtest expectation (walk-forward at this tier): risk per trade 1.73% on average, 2.04% at most; the 2 % cap was the binding limit on 64.00% of entries" in section
    assert "no-entry-after-an-exit blocked 7.5 a year" in section and "hard stop" not in section.split("Backtest expectation")[1].split("\n")[0]
    assert "earns its place only if, forward, it beats its Reference twin" in section and "owner decides the budget at plan row G7" in section
    assert text.index("## Controls (read these first)") < text.index("## Trader tier beside the Reference tier") < text.index("## This week")
    controls = text[text.index("## Controls"):text.index("## Ranking")]
    assert "`ctl-tf-btc-6h`" in controls
    # Without a tier account there is no section and no line.
    plain = _fleet(tmp_path / "plain", "2026-11-02T00:00:00Z", "2026-11-04T00:05:00Z")
    plain_text = write_week(plain, datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc)).read_text(encoding="utf-8")
    assert "## Trader tier beside" not in plain_text and "Trader tier (plan row R18)" not in plain_text


def test_the_report_says_plainly_when_an_s5_account_runs_without_positioning_data(tmp_path):
    paths = _fleet_s5(tmp_path)
    data = build_report_data(paths, datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc))
    rows = {r["account"]["account_id"]: r for r in data["rows"]}
    sol = rows["c11-s1s5-sol-6h-none"]["s5_data"]
    assert sol["bars"] == 6 and sol["incomplete"] == 6 and sol["incomplete_week"] == 6 and sol["last"]["complete"] is False
    assert sol["first_incomplete"] == "2026-11-02T00:00:00Z" and sol["last_incomplete"] == "2026-11-03T06:00:00Z" and sol["last"]["note"] == S5_NOTE
    btc = rows["c01-s1s5-btc-6h-none"]["s5_data"]
    assert btc["bars"] == 6 and btc["incomplete"] == 0 and btc["last"]["complete"] is True
    assert "s5_data" not in rows["c12-s1-sol-6h-none"]  # plain S1 has no positioning filter: nothing to label
    text = render(data)
    short = text[text.index("## In short"):text.index("## Controls")]
    assert f"**S5 running without data**: `c11-s1s5-sol-6h-none` ({S5_NOTE} at its last bar, 6 of 6 bars since its start)" in short
    assert "trades as its base rule" in short and "c01-s1s5-btc-6h-none" not in short.split("S5 running without data")[1].split("\n")[0]
    week = text[text.index("## This week"):text.index("## Data and health")]
    sol_line = next(line for line in week.splitlines() if "`c11-s1s5-sol-6h-none`" in line)
    btc_line = next(line for line in week.splitlines() if "`c01-s1s5-btc-6h-none`" in line)
    assert sol_line.endswith("| flat | flat — S5 without data |") and btc_line.endswith("| flat | flat |")
    health = text[text.index("## Data and health"):text.index("## How to read")]
    assert ("- S5 data for `c11-s1s5-sol-6h-none`: 6 of 6 bars since its start ran without complete funding / open-interest data (6 this week; "
            "first 2026-11-02T00:00:00Z, last 2026-11-03T06:00:00Z); the filter passes on a missing series and uses the last known value on a "
            f"stale one. Last bar 2026-11-03T06:00:00Z: {S5_NOTE}.") in health
    assert "- S5 data for `c01-s1s5-btc-6h-none`: current funding and open-interest data at every one of its 6 bars." in health
    assert ("Newest stored values: BTC-USDT-SWAP funding 2026-11-04T00:00:00Z / open interest 2026-11-04T00:00:00Z; SOL-USDT-SWAP funding missing / "
            "open interest missing.") in health
    assert "S5 data for `c12-s1-sol-6h-none`" not in health
    # A state from before R17 (no feed summary in health) still renders, and the older journals are read through the same rule.
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    state["health"].pop("positioning")
    write_state(paths.state_file, state)
    text2 = render(build_report_data(paths, datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc)))
    assert "Newest stored values" not in text2 and "**S5 running without data**: `c11-s1s5-sol-6h-none`" in text2


# -- plan row R23: an account without a Reference twin, and a forward control at the Trader tier ----------------------------------------

R23_EXTRA = [
    {"account_id": "c20-s1-btc-6h-none-trader", "role": "candidate", "kind": "sleeve",
     "label": "S1 BTC-USDT 6H (no regime gate) — trader tier (vt20/30 crash15/90dh cap2, brakes on) — from R20 breadth v1",
     "instrument": "BTC-USDT", "timeframe": "6H", "shortlist_rank": 20, "tier": "trader",
     "sleeve": {"candidate": "S1", "params": {"vote": 2, "atr_mult": 3.0, "bracket": "none"}, "regime": {"mode": "none"},
                "sizing": {"label": "vt20/30 crash15/90dh cap2"}, "brakes": {"hard_stop_dd": 0.3}},
     "expectations": {**TIER_EXP, "holdout": {"total_return": 0.038, "ann_vol": 0.077, "bars": 1461}}},
    {"account_id": "ctl-s8-btc-6h-trader", "role": "control", "kind": "sleeve", "tier": "trader",
     "label": "control: slow breakout S8 (Turtle System 2: 55-day high entry, 20-day low exit, 5 x ATR stop, forward control) — BTC-USDT 6H "
              "— trader tier (vt20/30 crash15/90dh cap2, brakes on) — from R19 research round 3",
     "instrument": "BTC-USDT", "timeframe": "6H",
     "sleeve": {"candidate": "S8", "params": {"entry_days": 55, "exit_days": 20, "atr_mult": 5.0, "bracket": "none"}, "regime": {"mode": "none"},
                "sizing": {"label": "vt20/30 crash15/90dh cap2"}, "brakes": {"hard_stop_dd": 0.3}},
     "expectations": {"walk_forward": {"cagr": 0.039, "ann_vol": 0.051, "sharpe": 0.78, "max_drawdown": 0.088, "trades_per_year": 3.9}, "holdout": None,
                      "gates": "section 4.6 at the trader tier", "passed_walk_forward": False, "failed_gates": ["calmar_gt_0_5", "enough_trades"],
                      "tier": {"name": "trader", "risk_pct_mean": 0.0198, "risk_pct_max": 0.0202, "cap_binding_share": 0.94, "expectancy_r": 0.54,
                               "brakes_per_year": {"entry_after_exit": 0.7}}}},
]
S8_WORDS = "slow breakout S8 (Turtle System 2: 55-day high entry, 20-day low exit, 5 x ATR stop, forward control)"


def test_the_report_lists_an_account_without_a_twin_beside_its_market_and_a_trader_tier_control_with_the_controls(tmp_path):
    """Plan row R23: `c20` (S1 at the Trader tier) has no Reference twin, so the tier section lists it beside the other BTC-USDT 6H accounts
    and the controls; the S8 forward control at the Trader tier is in the controls table (its backtest checks as information) and under
    each Trader-tier BTC-USDT 6H account with its brakes, never in the ranking."""
    paths = _fleet_tier(tmp_path, extra=R23_EXTRA)
    data = build_report_data(paths, datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc))
    pairs = {p["row"]["account"]["account_id"]: p for p in tier_pairs(data["rows"])}
    assert set(pairs) == {"c17-s1s5-btc-6h-none-trader", "c20-s1-btc-6h-none-trader"}
    c20, c17 = pairs["c20-s1-btc-6h-none-trader"], pairs["c17-s1s5-btc-6h-none-trader"]
    assert c20["twin"] is None and [q["account"]["account_id"] for q in c20["peers"]] == ["c01-s1s5-btc-6h-none", "c17-s1s5-btc-6h-none-trader"]
    assert [c["account"]["account_id"] for c in c20["fixed_controls"]] == ["ctl-s8-btc-6h-trader"] and c20["tf"]["account"]["account_id"] == "ctl-tf-btc-6h"
    assert c17["twin"]["account"]["account_id"] == "c01-s1s5-btc-6h-none" and c17["peers"] == []
    assert [c["account"]["account_id"] for c in c17["fixed_controls"]] == ["ctl-s8-btc-6h-trader"]
    rows = {r["account"]["account_id"]: r for r in data["rows"]}
    s8 = rows["ctl-s8-btc-6h-trader"]
    assert s8["vs_control"] is None and s8["vs_buy_and_hold"] is None and s8["verdicts"]["status"] == "too early"
    assert s8["tier_activity"]["since_start"]["entries"] == 2 and s8["tier_activity"]["since_start"]["trips"] == {"daily_loss": 1}
    assert rows["c20-s1-btc-6h-none-trader"]["vs_control"] is not None
    text = render(data)
    short = text[text.index("## In short"):text.index("## Controls")]
    assert f"; {S8_WORDS} (trader tier, brakes on) made " in short and "(BTC-USDT 6H)" in short
    assert "Trader tier (plan row R18): 2 accounts run" in short
    assert "`c20-s1-btc-6h-none-trader` " in short and "(no Reference twin: its rule never passed at the Reference tier)" in short
    assert "`c17-s1s5-btc-6h-none-trader`" in short and "against `c01-s1s5-btc-6h-none`" in short
    controls = text[text.index("## Controls"):text.index("## Ranking")]
    assert "| `ctl-s8-btc-6h-trader` | BTC-USDT 6H |" in controls and "| too early |" in controls
    ranking = text[text.index("## Ranking"):text.index("## Trader tier beside")]
    assert "`ctl-s8-btc-6h-trader`" not in ranking and "`c20-s1-btc-6h-none-trader`" in ranking
    section = text[text.index("## Trader tier beside the Reference tier"):text.index("## This week")]
    assert "Plan row R23: an account without a Reference twin" in section
    lines = section.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("| S1 BTC-USDT 6H | `c20-s1-btc-6h-none-trader` | trader |"))
    assert lines[i + 1].startswith("| no Reference twin (the rule never passed at the Reference tier) | - | - |")
    assert lines[i + 2].startswith("| same market: S1+S5 BTC-USDT 6H | `c01-s1s5-btc-6h-none` | reference |")
    assert lines[i + 3].startswith("| same market: S1+S5 BTC-USDT 6H | `c17-s1s5-btc-6h-none-trader` | trader |")
    assert lines[i + 4].startswith("| always long, policy sizing | `ctl-hold-btc-6h` | reference |")
    s8_lines = [l for l in lines if l.startswith(f"| {S8_WORDS} | `ctl-s8-btc-6h-trader` | trader |")]
    assert len(s8_lines) == 2 and all("| 1.65% / 1.80% | Turtle ladder cut once; no-entry-after-an-exit blocked once |" in l for l in s8_lines)
    assert section.count("**`ctl-s8-btc-6h-trader`** (forward control, never judged) since its start (12 bars, 2 entries)") == 1
    assert "the 2 % cap was the binding limit on 94.00% of entries" in section and "no-entry-after-an-exit blocked 0.7 a year" in section
    assert section.index("**`c17-s1s5-btc-6h-none-trader`**") < section.index("**`c20-s1-btc-6h-none-trader`**") < section.index("**`ctl-s8-btc-6h-trader`**")
    # Without the R23 accounts the section reads exactly as before: no R23 sentence, no peer or control lines.
    plain = render(build_report_data(_fleet_tier(tmp_path / "plain"), datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc)))
    assert "Plan row R23" not in plain and "same market:" not in plain and "no Reference twin" not in plain and S8_WORDS not in plain
