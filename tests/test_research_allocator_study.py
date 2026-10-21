"""Allocator v2 study: the Sprint 2c sleeves rebuilt with positions, the reproduction check, and a holdout opened only after a pass."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import research.allocator_study as study
from research.allocator_study import (
    SleeveHistory,
    StudyError,
    StudySettings,
    end_of_day_positions,
    expectations_from_results,
    render_report,
    replay_full_size,
    sleeve_defs,
)
from research.engine import Costs
from research.gated_walkforward import regimes_for_windows, replay_gated
from research.portfolio import align_sleeves, combine_sized
from research.regime_v2 import RegimeV2Config
from research.sizing import LadderConfig
from research.strategies import get_candidate
from research.strategies.base import FeatureContext, days_to_bars
from research.sweep import build_frames
from research.walkforward import WalkForwardConfig, make_windows
from tests.test_paper_fleet_signals import synthetic_4h

ROOT = Path(__file__).resolve().parents[1]
V1C = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
RESULTS = ROOT / "docs" / "research" / "allocator_v2_results.json"
REPORT = ROOT / "docs" / "research" / "ALLOCATOR_V2_REPORT.md"
NAMES = ["S1/BTC/6H", "S1/ETH/6H", "S2/BTC/4H", "S2/ETH/4H", "S4/BTC/6H", "S4/ETH/6H"]


def test_the_full_size_replay_with_positions_is_the_sprint_2c_replay():
    df = synthetic_4h(2400, seed=21)
    cand = get_candidate("S2")
    params = {"entry_days": 10, "exit_days": 5, "vol_mult": 1.0, "volume_window": 20, "atr_window": 14, "atr_mult": 2.0, "atr_pct_max": 0.9,
              "atr_pct_days": 90, "bracket": "none"}
    ctx = FeatureContext("4H", 2191.5)
    frames = build_frames(cand, df, [params], ctx)
    cfg = WalkForwardConfig(train_bars=days_to_bars(120, "4H"), test_bars=days_to_bars(60, "4H"), purge_bars=days_to_bars(7, "4H"))
    windows = make_windows(len(df), cfg)
    regimes = regimes_for_windows(df, windows, RegimeV2Config(mode="none"), "4H", 2191.5)
    costs = Costs(0.001, 0.0005)
    _, series = replay_gated(df, frames, [0], windows, regimes, costs=costs, periods_per_year=2191.5, size_fraction=None, want_returns=True)
    returns, allocation, trades = replay_full_size(df, frames, windows, costs)
    pd.testing.assert_series_equal(returns, series[0], check_names=False)
    assert set(np.unique(allocation.to_numpy())) <= {0.0, 1.0} and allocation.sum() > 0 and len(trades) > 0
    assert allocation.index.equals(returns.index)


def test_end_of_day_positions_take_the_last_bar_that_opened_that_day():
    idx = pd.date_range("2026-03-01 00:00", periods=8, freq="6h", tz="UTC")
    alloc = pd.Series([0, 1, 1, 0, 0, 0, 1, 1.0], index=idx)
    pos = end_of_day_positions(alloc)
    assert pos.tolist() == [False, True] and list(pos.index.strftime("%Y-%m-%d")) == ["2026-03-01", "2026-03-02"]


def test_sleeves_and_settings_come_from_the_sprint_2c_record(tmp_path):
    doc = json.loads(V1C.read_text(encoding="utf-8"))
    defs = sleeve_defs(doc)
    assert [d.name for d in defs] == NAMES
    assert {d.name: d.params.get("bracket") for d in defs}["S4/BTC/6H"] == "trail1"
    s = StudySettings.from_results(doc)
    assert (s.train_days, s.test_days, s.purge_days, s.holdout_months, s.fee_rate, s.slippage_rate) == (540, 180, 7, 12, 0.001, 0.0005)
    assert (s.ladder.half_dd, s.ladder.flat_dd, s.ladder.recovery_bars) == (0.075, 0.15, 30)
    bad = json.loads(json.dumps(doc))
    for p in bad["portfolios"]:
        if p.get("regime") == "none" and (p.get("sizing") or {}).get("target_vol") == 0.15:
            p["sizing"]["ladder"]["flat_dd"] = 0.2
    with pytest.raises(StudyError, match="sizing differs"):
        StudySettings.from_results(bad)


# -- the study end to end on a synthetic market (the lake is patched out) --------------------


def _bars(name: str, start: str, days: int, rng, *, extra_bars: int = 0) -> SleeveHistory:
    tf = name.split("/")[2]
    hours = int(tf[:-1])
    idx = pd.date_range(start, periods=days * 24 // hours + extra_bars, freq=f"{hours}h", tz="UTC", name="open_time")
    n = len(idx)
    long = np.repeat(rng.random(n // 12 + 1) > 0.45, 12)[:n]
    r = np.where(long, rng.normal(0.0012 if "BTC" in name else 0.0009, 0.012, n), 0.0)
    trades = pd.DataFrame({"pnl": rng.normal(15.0, 60.0, max(3, int(long.sum()) // 12))})
    sd = study.SleeveDef(name, name.split("/")[0], "BTC-USDT" if "BTC" in name else "ETH-USDT", tf, {"bracket": "none"})
    return SleeveHistory(sd, pd.Series(r, index=idx), pd.Series(long.astype(float), index=idx), trades)


def _doc(oos):
    daily = align_sleeves({n: h.returns for n, h in oos.items()})
    v1 = combine_sized(daily, name="x", target_vol=0.15, ladder=LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30))
    entry = {"regime": "none", "weights": {n: 1 / 6 for n in NAMES}, "metrics": {k: float(v) for k, v in v1.metrics.items()}, "days": int(len(daily)),
             "sizing": {"target_vol": 0.15, "vol_lookback_days": 30, "weight_lookback_days": 60,
                        "ladder": {"half_dd": 0.075, "flat_dd": 0.15, "recovery_bars": 30}},
             "pooled_trades": 400, "pooled_profit_factor": 1.4}
    results = [{"candidate": n.split("/")[0], "instrument": "BTC-USDT" if "BTC" in n else "ETH-USDT", "timeframe": n.split("/")[2],
                "regime": {"mode": "none"}, "selected_params": {"bracket": "none"}} for n in NAMES]
    meta = {"train_days": 540, "test_days": 180, "purge_days": 7, "holdout_months": 12, "fee_rate": 0.001, "slippage_rate": 0.0005,
            "positioning_source": "binance"}
    return {"meta": meta, "portfolios": [entry], "results": results}


def _patch_market(monkeypatch, oos, hold, rng):
    days = pd.date_range("2023-11-01", "2025-09-30", freq="D", tz="UTC", name="day")
    common = rng.normal(0.0005, 0.03, len(days))
    closes = pd.DataFrame({"BTC-USDT": 40_000 * np.exp(np.cumsum(common + rng.normal(0, 0.01, len(days)))),
                           "ETH-USDT": 2_000 * np.exp(np.cumsum(1.2 * common + rng.normal(0, 0.02, len(days))))}, index=days)
    calls = []

    def fake_rebuild(layout, defs, settings, *, holdout=False):
        calls.append(holdout)
        return dict(oos), (dict(hold) if holdout else {})

    monkeypatch.setattr(study, "rebuild_sleeves", fake_rebuild)
    monkeypatch.setattr(study, "daily_coin_closes", lambda layout, instruments: closes)
    return _doc(oos), calls


@pytest.fixture()
def synthetic(monkeypatch):
    rng = np.random.default_rng(42)
    oos = {n: _bars(n, "2024-01-01", 500, rng) for n in NAMES}
    hold = {n: _bars(n, "2025-05-15 04:00" if "4H" in n else "2025-05-15 06:00", 120, rng) for n in NAMES}
    return _patch_market(monkeypatch, oos, hold, rng)


def _force(monkeypatch, passed: bool):
    real = study.acceptance_check_v1c

    def forced(oos, yearly, robust):
        out = real(oos, yearly, robust)
        out["passed"] = passed
        out["failed"] = [] if passed else ["sharpe_gt_0_7"]
        return out

    monkeypatch.setattr(study, "acceptance_check_v1c", forced)


def test_the_holdout_stays_closed_when_v2_fails_even_if_asked(synthetic, monkeypatch):
    doc, calls = synthetic
    _force(monkeypatch, passed=False)
    out = study.run_study(None, doc, evaluate_holdout=True)
    assert out["holdout"] == {"evaluated": False, "reason": "allocator v2 did not pass the walk-forward gates: the holdout stays untouched"}
    assert calls == [False]  # the holdout bars were never even built
    assert out["reproduction"]["cagr"]["stored"] == pytest.approx(out["reproduction"]["cagr"]["rebuilt"])
    json.dumps(out, allow_nan=False)


def test_a_pass_opens_the_holdout_only_when_asked_and_books_it_from_its_first_full_day(synthetic, monkeypatch):
    doc, calls = synthetic
    _force(monkeypatch, passed=True)
    closed = study.run_study(None, doc, evaluate_holdout=False)
    assert closed["holdout"]["evaluated"] is False and "not requested" in closed["holdout"]["reason"] and calls == [False]
    out = study.run_study(None, doc, evaluate_holdout=True)
    h = out["holdout"]
    assert h["evaluated"] and calls[-2:] == [False, True]
    # First bars at 04:00 / 06:00 on 05-15 -> booked from 05-16; last bars open 09-12 00:00 (a cut-off day) -> booked to 09-11.
    assert h["first_day"] == "2025-05-16" and h["last_day"] == "2025-09-11" and h["days"] == 119
    assert set(h) >= {"v1", "v2", "pooled_trades", "pooled_profit_factor"} and h["v2"]["daily"] and h["v1"]["daily"]
    assert all(r["brakes"] is not None for r in (h["v1"], h["v2"]))
    exp = expectations_from_results(out)
    assert exp["holdout"]["bars"] == 119 and exp["passed_walk_forward"] is True
    assert exp["holdout"]["first_day"] == "2025-05-16" and exp["holdout"]["reference_v1_total_return"] == pytest.approx(h["v1"]["metrics"]["total_return"])
    json.dumps(out, allow_nan=False)
    assert "## The untouched 12 months (holdout)" in render_report(out)


def test_a_day_that_still_holds_walk_forward_bars_is_not_a_holdout_day(monkeypatch):
    """As on the real lake: the 6H holdout starts at 00:00 while the 4H walk-forward still has that day's 00:00 bar."""
    rng = np.random.default_rng(7)
    oos = {n: _bars(n, "2024-01-01", 500, rng, extra_bars=1 if "4H" in n else 0) for n in NAMES}  # 4H: one more bar, 2025-05-15 00:00
    hold = {n: _bars(n, "2025-05-15 04:00" if "4H" in n else "2025-05-15 00:00", 120, rng) for n in NAMES}
    doc, _ = _patch_market(monkeypatch, oos, hold, rng)
    _force(monkeypatch, passed=True)
    h = study.run_study(None, doc, evaluate_holdout=True)["holdout"]
    assert h["first_day"] == "2025-05-16"  # 05-15 mixes walk-forward and holdout bars of the 4H sleeves
    assert h["holdout_first_bar"]["S1/BTC/6H"] == "2025-05-15T00:00:00+00:00" and h["holdout_first_bar"]["S2/BTC/4H"] == "2025-05-15T04:00:00+00:00"


def test_pooled_profit_factor_is_pooled_as_sprint_2c_pooled_it():
    def hist(pnl):
        sd = study.SleeveDef("S1/BTC/6H", "S1", "BTC-USDT", "6H", {})
        return SleeveHistory(sd, pd.Series(dtype=float), pd.Series(dtype=float), pd.DataFrame({"pnl": pnl}))

    assert study.pooled_trades({"a": hist([10.0, 5.0])}) == (2, 999.0)  # nothing lost
    assert study.pooled_trades({}) == (0, 0.0)
    assert study.pooled_trades({"a": hist([10.0, -5.0]), "b": hist([5.0])}) == (3, 3.0)


def test_sleeves_that_do_not_reproduce_sprint_2c_stop_the_study(synthetic, monkeypatch):
    doc, _ = synthetic
    doc["portfolios"][0]["metrics"]["cagr"] += 0.001
    with pytest.raises(StudyError, match="do not reproduce"):
        study.run_study(None, doc)


# -- the committed results ------------------------------------------------------------------


def test_the_committed_report_is_exactly_what_its_numbers_render_to():
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert result["status"].startswith("SIMULATION ONLY") and result["meta"]["default_configuration"] is True
    assert REPORT.read_text(encoding="utf-8") == render_report(result)
    rep = result["reproduction"]
    assert all(abs(v["stored"] - v["rebuilt"]) <= 2e-6 for k, v in rep.items() if k != "days") and rep["days"]["stored"] == rep["days"]["rebuilt"]
    hold = result["holdout"]
    assert hold["evaluated"] == bool(result["walk_forward"]["v2"]["acceptance"]["passed"]) or "not requested" in hold.get("reason", "")
    exp = expectations_from_results(result)
    for key in ("cagr", "ann_vol", "sharpe", "max_drawdown", "trades_per_year"):
        assert exp["walk_forward"][key] is not None


def _counterfactual(result, *, v2, v1, coins, v2_confirmed=False, v1_confirmed=False):
    out = json.loads(json.dumps(result))
    h = out["holdout"]
    h["v2"]["metrics"]["total_return"], h["v1"]["metrics"]["total_return"] = v2, v1
    h["v2"]["confirmed"], h["v1"]["confirmed"] = v2_confirmed, v1_confirmed
    h["coins_buy_and_hold"] = coins
    return render_report(out)


def test_the_holdout_sentences_follow_the_numbers_not_the_story_of_this_run():
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    up = {"BTC-USDT": 0.30, "ETH-USDT": 0.20}
    good = _counterfactual(result, v2=0.12, v1=0.08, coins=up, v2_confirmed=True, v1_confirmed=True)
    assert "**Both gained.**" in good and "in a rising market" in good and "The brakes added return." in good
    assert "confirms v2's walk-forward result" in good and "**What it means.**" not in good and "Do the gates look wrong" not in good
    assert "Both lost" not in good and "falling market" not in good and "cut the loss" not in good
    # A gain that is not confirmed (profit factor at most 1 or too few trades): no "lost" story, no "worse than the controls".
    weak = _counterfactual(result, v2=0.01, v1=0.03, coins={"BTC-USDT": -0.1, "ETH-USDT": 0.1})
    assert "**Both gained.**" in weak and "in a mixed market" in weak and "The brakes cost return." in weak
    assert "does not confirm v2's walk-forward pass" in weak and "lost with them" not in weak and "more than every always-long control" not in weak
    turned = _counterfactual(result, v2=0.02, v1=-0.05, coins={"BTC-USDT": -0.1, "ETH-USDT": -0.2})
    assert "The brakes turned a loss into a gain." in turned and "Both lost" not in turned and "in a falling market" in turned


def test_what_it_means_reads_as_whole_sentences_in_every_outcome():
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    mixed = {"BTC-USDT": -0.05, "ETH-USDT": 0.04}
    only_v2 = _counterfactual(result, v2=-0.02, v1=0.03, coins=mixed)
    assert "v2 lost on these months while v1 on the same sleeves did not" in only_v2 and "lost with them" not in only_v2
    only_v1 = _counterfactual(result, v2=0.01, v1=-0.03, coins=mixed)
    assert "v1 lost on these months and v2 did not" in only_v1 and "The brakes turned a loss into a gain." in only_v1
    v1_ok = _counterfactual(result, v2=-0.01, v1=0.05, coins=mixed, v1_confirmed=True)
    assert "v1, which its holdout confirms, is the stronger of the two" in v1_ok and "neither is a lead candidate" not in v1_ok
    for text in (only_v2, only_v1, v1_ok):
        line = next(l for l in text.splitlines() if l.startswith("- **What it means.**"))
        assert line.endswith("the forward record decides.") and ",." not in line and " ." not in line
