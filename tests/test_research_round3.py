"""Research round 3 (plan row R19): the S7 / S8 fixed rules, the fixed-rule protocol variant through the unchanged Sprint 2c runner, the
pre-registered readings, the bar-size table, the pre-registration file, the ledger, the shortlist rows (applied / recorded only), the fleet
loader's acceptance of a fixed-rule candidate row, the report and the command line. Everything runs offline on synthetic candles."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.datalake.layout import LakeLayout
from research import round3 as r3
from research.brakes import TRADER_BRAKES
from research.data import bars_per_year
from research.report_round3 import executive_summary, failure_analysis, render_report
from research.sizing import SIZING_TIERS
from research.strategies import ALL_KEYS, CANDIDATES, FIXED_RULES, ROUND3_BASES, VARIANT_OF, get_candidate
from research.strategies.base import FeatureContext
from research.strategies.round3 import SlowBreakout, TrendPullback, pullback_state
from research.sweep import build_frames, param_grid, perturbed_params
from tests.test_research_round2 import _write

ROOT = Path(__file__).resolve().parents[1]


# -- synthetic candles -----------------------------------------------------------------------------------------

def _hourly(seed: int, n: int = 28_000, start: str = "2021-01-01") -> pd.DataFrame:
    """Hourly bars with trends lasting a few months around a rising mean, so the slow rules arm, enter and exit."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="h", tz="UTC", name="open_time")
    regime = np.sign(np.sin(np.arange(n) / 700.0)) * 0.00035 + 0.00005
    close = 100 * np.exp(np.cumsum(regime + rng.normal(0, 0.006, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    volume = rng.lognormal(3, 0.5, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _ctx(timeframe: str = "6H") -> FeatureContext:
    return FeatureContext(timeframe=timeframe, periods_per_year=bars_per_year(timeframe))


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


@pytest.fixture(scope="module")
def study_lake(tmp_path_factory):
    layout = LakeLayout(tmp_path_factory.mktemp("r19_lake") / "lake")
    _write(layout, "BTC-USDT", _hourly(1), bar="1H")
    _write(layout, "XRP-USDT", _hourly(2), bar="1H")
    return layout


@pytest.fixture(scope="module")
def stored():
    v1c = json.loads(r3.V1C_RESULTS.read_text(encoding="utf-8"))
    r12 = json.loads(r3.R12_RESULTS.read_text(encoding="utf-8"))
    r18 = json.loads(r3.R18_RESULTS.read_text(encoding="utf-8"))
    return r3.stored_results(v1c, r12, r18)


# -- the rules ---------------------------------------------------------------------------------------------------

def test_round3_candidates_are_registered_fixed_rules_with_one_parameter_set():
    for key in r3.FIXED_CANDIDATES:
        assert key in CANDIDATES and key in ALL_KEYS and key in FIXED_RULES and ROUND3_BASES[key] == "hold"
        cand = get_candidate(key)
        combos = param_grid(cand.grid, base=cand.default_params)
        assert len(combos) == 1 and all(isinstance(v, (int, float)) for v in combos[0].values()), key
    assert VARIANT_OF == {"S7e": "S7", "S7w": "S7", "S7t": "S7", "S8g": "S8"}
    s7, s7e, s7w, s7t, s8, s8g = (get_candidate(k) for k in ("S7", "S7e", "S7w", "S7t", "S8", "S8g"))
    assert isinstance(s7, TrendPullback) and s7.pullback_kind == "sma" and s7.default_params["pullback_days"] == 20 and s7.default_params["atr_floor_mult"] == 2.0
    assert s7e.pullback_kind == "ema" and s7e.default_params["pullback_days"] == 10 and s7w.default_params["atr_floor_mult"] == 3.0
    assert s7.fixed_bracket == "none" and s7t.fixed_bracket == "trail3" and s7t.default_params == s7.default_params
    assert isinstance(s8, SlowBreakout) and s8.default_params == {"entry_days": 55, "exit_days": 20, "atr_window": 14, "atr_mult": 5.0}
    assert s8g.default_params["entry_days"] == 90 and s8g.default_params["exit_days"] == 45 and s8g.warmup_days == 90.0 and s8.warmup_days == 55.0
    assert s7.warmup_days == 100.0 and s7.grid == {"trend_fast_days": [50], "trend_slow_days": [100], "pullback_days": [20], "atr_floor_mult": [2.0]}
    assert len(perturbed_params(dict(s7.default_params, bracket="none"), list(s7.grid))) == 10
    assert len(perturbed_params(dict(s8.default_params, bracket="none"), list(s8.grid))) == 8
    # The Sprint 2c runner gives the new keys the none/gate modes; the fixed-rule protocol passes a single bracket.
    v1c = r3.runner()
    for key in r3.FIXED_CANDIDATES:
        assert v1c.modes_for(key, ["none", "gate", "scale"]) == ["none", "gate"] and key in v1c.ALL_KEYS
    assert v1c._brackets_for(argparse.Namespace(quick=False, brackets=["none"]), "S7") == ["none"]
    assert v1c._brackets_for(argparse.Namespace(quick=False, brackets=["trail3"]), "S7t") == ["trail3"]


def test_pullback_state_machine_arms_enters_and_exits_as_pre_registered():
    #            0      1      2      3      4      5      6      7      8      9     10     11
    uptrend = [True, True, True, True, True, True, True, True, False, True, True, True]
    pullback = [False, True, True, False, False, False, False, False, False, True, False, False]
    breakout = [True, False, True, True, False, False, True, False, False, True, True, True]
    exit_ = [False, False, False, False, False, True, False, False, False, False, False, False]
    low = [10.0, 9.0, 8.5, 9.5, 9.8, 9.0, 9.7, 9.9, 9.0, 9.6, 9.4, 9.9]
    desired, pb_low = pullback_state(np.array(uptrend), np.array(pullback), np.array(breakout), np.array(exit_), np.array(low))
    # Bar 0: a breakout without a prior pullback does not enter. Bar 1 arms (low 9.0); bar 2 lowers the pullback low to 8.5 and enters on
    # its breakout (armed on an earlier bar). Long through bar 4 with the low frozen at 8.5; bar 5 exits (close below the fast average) and,
    # being no pullback bar, leaves the rule unarmed; bar 6's breakout therefore does not enter. Bar 8: the uptrend fails -> unarmed.
    # Bar 9 arms again (low 9.6); bar 10 enters (its low 9.4 lowers the pullback low to 9.4).
    assert desired.tolist() == [False, False, True, True, True, False, False, False, False, False, True, True]
    assert np.isnan(pb_low[0]) and pb_low[1] == 9.0 and pb_low[2] == 8.5 and pb_low[3] == 8.5 and pb_low[4] == 8.5
    assert np.isnan(pb_low[5]) and np.isnan(pb_low[6]) and np.isnan(pb_low[8]) and pb_low[9] == 9.6 and pb_low[10] == 9.4 and pb_low[11] == 9.4
    # An exit bar that is itself a pullback bar arms a fresh episode at once.
    d2, p2 = pullback_state(np.array([True] * 4), np.array([True, False, True, False]), np.array([False, True, False, True]), np.array([False, False, True, False]),
                            np.array([5.0, 6.0, 4.0, 6.5]))
    assert d2.tolist() == [False, True, False, True] and p2[2] == 4.0 and p2[3] == 4.0


def test_trend_pullback_frames_stop_floor_and_the_variants():
    df = _resample(_hourly(3), "6h")
    ctx = _ctx("6H")
    s7, s7e, s7w, s7t = (get_candidate(k) for k in ("S7", "S7e", "S7w", "S7t"))
    f7 = s7.build(df, s7.default_params, ctx)
    assert f7.desired.any() and not f7.desired.iloc[:399].any(), "no 100-day average before 400 bars at 6H"
    assert f7.stop_distance.notna().iloc[20:].all() and (f7.stop_distance.dropna() > 0).all()
    assert f7.target_distance is None and f7.time_stop_bars is None and f7.trail_r is None
    # The stop is max(close - pullback low, 2 x ATR): recompute the floor and check the bound on every bar.
    from research import features

    atr = features.atr(df["high"], df["low"], df["close"], 14)
    floor = (2.0 * atr).to_numpy()
    sd = f7.stop_distance.to_numpy()
    ok = np.isfinite(floor)
    assert np.all(sd[ok] >= floor[ok] - 1e-12)
    # Where the rule is long with a pullback low below the close, the stop reaches under that low.
    fw = s7w.build(df, s7w.default_params, ctx)
    assert fw.desired.equals(f7.desired) and np.all(fw.stop_distance.to_numpy()[ok] >= sd[ok] - 1e-12) and (fw.stop_distance.to_numpy()[ok] > sd[ok] + 1e-12).any()
    fe = s7e.build(df, s7e.default_params, ctx)
    assert fe.desired.any() and not fe.desired.equals(f7.desired), "the EMA-10 pullback arms on other bars"
    ft = s7t.build(df, s7t.default_params, ctx)
    assert ft.desired.equals(f7.desired) and ft.stop_distance.equals(f7.stop_distance) and ft.trail_r is None, "the trail lives in the bracket, not the frame"
    # The runner layers the trail3 bracket on S7t: activation +1 R, trail 3 R; bracket none leaves S7 untouched.
    frames_t = build_frames(s7t, df, [dict(s7t.default_params, bracket="trail3")], ctx, no_trade=None)
    frames_7 = build_frames(s7, df, [dict(s7.default_params, bracket="none")], ctx, no_trade=None)
    assert frames_t.trail_activate is not None and frames_t.trail_activate[0] == 1.0 and frames_t.trail_dist[0] == 3.0 and frames_7.trail_dist is None
    np.testing.assert_array_equal(frames_t.desired, frames_7.desired)
    # A market that only falls never has an uptrend: no entry, ever.
    down = df.copy()
    down["close"] = np.linspace(400, 100, len(down))
    down["open"], down["high"], down["low"] = down["close"].shift(1).fillna(400), down["close"].shift(1).fillna(400) * 1.001, down["close"] * 0.999
    assert not s7.build(down, s7.default_params, ctx).desired.any()


def test_slow_breakout_frames_and_garners_channels():
    df = _resample(_hourly(4), "6h")
    ctx = _ctx("6H")
    s8, s8g = get_candidate("S8"), get_candidate("S8g")
    f8 = s8.build(df, s8.default_params, ctx)
    from research import features

    dh = features.donchian_high(df["high"], 220)  # 55 days at 6H
    dl = features.donchian_low(df["low"], 80)  # 20 days
    entries = (df["close"] > dh).fillna(False)
    exits = (df["close"] < dl).fillna(False)
    assert f8.desired.any() and not f8.desired.iloc[:219].any()
    starts = f8.desired & ~f8.desired.shift(fill_value=False)
    assert entries[starts].all(), "every run starts on a breakout bar"
    ends = ~f8.desired & f8.desired.shift(fill_value=False)
    assert exits[ends].all(), "every run ends on a channel exit"
    atr = features.atr(df["high"], df["low"], df["close"], 14)
    pd.testing.assert_series_equal(f8.stop_distance, (atr * 5.0).where(np.isfinite(atr)), check_names=False)
    assert f8.target_distance is None and f8.time_stop_bars is None and f8.trail_r is None
    fg = s8g.build(df, s8g.default_params, ctx)
    assert fg.desired.any() and int((fg.desired & ~fg.desired.shift(fill_value=False)).sum()) <= int(starts.sum())
    assert not fg.desired.iloc[:359].any()


def test_the_fleet_can_build_and_decide_for_the_round3_rules():
    """S7 / S8 use only the market's own candles and carry no own exits; the S7 trail variant's exit is the trail3 bracket the fleet applies."""
    from research.paper_fleet.config import OWN_EXIT_CANDIDATES, SleeveSpec
    from research.paper_fleet.signals import decide_sleeve, engine_config, frame_decisions
    from research.engine import Costs

    assert not set(r3.FIXED_CANDIDATES) & OWN_EXIT_CANDIDATES
    df = _resample(_hourly(6, n=16_000), "6h")  # ~660 days: the fleet's 400-day decision window plus the 100-day warm-up
    ctx = _ctx("6H")
    for key, bracket in (("S7", "none"), ("S7t", "trail3"), ("S8", "none"), ("S8g", "none")):
        cand = get_candidate(key)
        spec = SleeveSpec(key, "BTC-USDT", "6H", dict(cand.default_params, bracket=bracket), sizing=SIZING_TIERS["trader"], rebalance_threshold=0.25, brakes=TRADER_BRAKES)
        info = decide_sleeve(spec, df, ctx)
        assert isinstance(info.decision.desired, bool) and info.signal["action"] in ("long", "flat") and info.diagnostics["window_bars"] > 0
        decisions = frame_decisions(spec, df, ctx, start=df.index[-400])
        assert len(decisions) == 400 and any(d.desired for d in decisions), key
        assert all(np.isfinite(d.stop_distance) and d.stop_distance > 0 for d in decisions if d.desired), "a long decision carries the rule's stop"
        cfg = engine_config(spec, costs=Costs(), init_cash=10_000.0)
        assert (cfg.trail_r, cfg.trail_activate_r) == ((3.0, 1.0) if bracket == "trail3" else (None, None)) and cfg.brakes is not None


# -- configuration, jobs, protocol --------------------------------------------------------------------------------

def test_config_jobs_arguments_and_the_protocol_checks(study_lake):
    cfg = r3.Round3Config(lake_dir=str(study_lake.root))
    assert cfg.candidates == ["S7", "S7e", "S7w", "S7t", "S8", "S8g"] and cfg.all_markets == list(r3.ALL_MARKETS) and len(cfg.cell_objects) == 2
    jobs = r3.plan_jobs(cfg, evaluate_holdout=True)
    kinds = {k: sum(1 for j in jobs if j["kind"] == k) for k in r3.JOB_KINDS}
    assert kinds == {"control": 40, "fixed": 36, "fixed_trail": 36, "barsize": 12} and len(jobs) == 124
    # The judged cell opens the holdout for the hypotheses' series only; the 4H controls serve the bar-size table (no holdout, their months are in R18's ledger).
    assert all(j["evaluate_holdout"] == (j["cell"]["key"] == r3.JUDGED_CELL.key and j["kind"] != "barsize" and j["timeframe"] in r3.FIXED_TIMEFRAMES) for j in jobs)
    assert all(j["strategies"] == ["S7t"] for j in jobs if j["kind"] == "fixed_trail") and all(j["strategies"] == ["S7", "S7e", "S7w", "S8", "S8g"] for j in jobs if j["kind"] == "fixed")
    assert {(j["instrument"], j["timeframe"]) for j in jobs if j["kind"] == "barsize"} == {(m, tf) for m in r3.PRIMARY_MARKETS for tf in r3.BARSIZE_TIMEFRAMES}
    assert {j["timeframe"] for j in jobs if j["kind"] == "control"} == {"1D", "6H", "4H"}  # the 4H controls serve the bar-size table
    narrowed = r3.Round3Config(hypotheses=("H8",), markets=("XRP-USDT",), timeframes=("6H",), regime_modes=("none",), cells=(r3.JUDGED_CELL.key,), barsize=False)
    small = r3.plan_jobs(narrowed, evaluate_holdout=False)
    assert [(j["kind"], j["strategies"]) for j in small] == [("control", ["hold"]), ("fixed", ["S8", "S8g"])] and narrowed.all_markets == ["XRP-USDT"]
    # The arguments of a job: the tier, the brakes, the fixed-rule protocol, the cost replays.
    args = r3.job_args(dict(small[1], cfg=narrowed.to_dict()))
    assert args["brackets"] == ["none"] and args["min_trades"] == 0 and args["tier"] == "trader" and args["policy_risk_cap"] == 0.02 and args["turtle_ladder"] and args["brakes"]
    assert args["policy_no_ladder"] and args["policy_target_vol"] == 0.2 and args["cost_scenarios"] == ["measured_btc_eth=0.0005:0.0005", "altcoin=0.001:0.0015"]
    trail = r3.job_argv(r3.JUDGED_CELL, "fixed_trail", ["S7t"], "1D", modes=("none",), evaluate_holdout=True, lake_dir=None, quick=False)
    assert "--brackets" in trail and trail[trail.index("--brackets") + 1] == "trail3" and "--evaluate-holdout" in trail
    ref = r3.job_argv(r3.REFERENCE_CELL, "barsize", ["S1"], "4H", modes=("none", "gate"), evaluate_holdout=False, lake_dir=None, quick=False)
    assert "--brackets" not in ref and "--min-trades" not in ref and "--brakes" not in ref and "--policy-target-vol" in ref
    with pytest.raises(ValueError):
        r3.job_argv(r3.JUDGED_CELL, "nope", ["S7"], "6H", modes=("none",), evaluate_holdout=False, lake_dir=None, quick=False)
    # Protocol checks: a job explains exactly its tier, its fixed-rule protocol and its 1D bars; anything else is unexplained.
    meta = json.loads(r3.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    v1c = r3.runner()
    fixed_1d = dict(vars(v1c.parse_args(r3.job_argv(r3.JUDGED_CELL, "fixed", ["S7", "S8"], "1D", modes=("none", "gate"), evaluate_holdout=False, lake_dir=None, quick=False))))
    check = r3.protocol_check_job(fixed_1d, meta, r3.JUDGED_CELL, "fixed", "1D")
    assert set(check["expected_mismatches"]) == {"policy_sizing", "brackets", "min_trades", "timeframes"} and check["unexplained_mismatches"] == {} and check["ok_for_cell"]
    assert check["new_candidates"] == ["S7", "S8"] and check["protocol_variant"] == r3.FIXED_RULE_PROTOCOL and check["r18"]["brakes"] == TRADER_BRAKES.to_dict()
    assert set(check["mismatches"]) == {"policy_sizing", "brackets", "min_trades", "timeframes"}
    control_6h = dict(vars(v1c.parse_args(r3.job_argv(r3.REFERENCE_CELL, "control", ["hold"], "6H", modes=("none",), evaluate_holdout=False, lake_dir=None, quick=False))))
    clean = r3.protocol_check_job(control_6h, meta, r3.REFERENCE_CELL, "control", "6H")
    assert clean["ok"] and clean["mismatches"] == {} and clean["ok_for_cell"] and clean["protocol_variant"] is None and clean["r18"]["brakes"] is None
    quick = dict(vars(v1c.parse_args(r3.job_argv(r3.JUDGED_CELL, "fixed", ["S7"], "6H", modes=("none",), evaluate_holdout=False, lake_dir=None, quick=True))))
    assert "quick" in r3.protocol_check_job(quick, meta, r3.JUDGED_CELL, "fixed", "6H")["unexplained_mismatches"]
    assert r3.full_study_requested(r3.Round3Config())
    for bad in (r3.Round3Config(quick=True), r3.Round3Config(reproduction=False), r3.Round3Config(barsize=False), r3.Round3Config(hypotheses=("H7",)),
                r3.Round3Config(markets=r3.PRIMARY_MARKETS), r3.Round3Config(timeframes=("6H",)), r3.Round3Config(regime_modes=("none",)),
                r3.Round3Config(cells=(r3.JUDGED_CELL.key,))):
        assert not r3.full_study_requested(bad)


def test_stored_results_cover_the_reproduction_targets(stored):
    ref, trader = stored["reference"], stored["trader"]
    assert {s["study_source"] for s in ref} == {"Sprint 2c", "R12 replication"} and {s["study_source"] for s in trader} == {"R18 Trader Policy v1"}
    assert all(s["cell"]["key"] == "trader|brakes|none" for s in trader)
    assert any(s["candidate"] == "S1+S5" and s["instrument"] == "BTC-USDT" and s["timeframe"] == "6H" for s in trader)
    assert sum(1 for s in trader if s["candidate"] == "hold") == 6
    for inst in r3.REPLICATION_MARKETS:
        assert any(s["candidate"] == "hold" and s["instrument"] == inst and s["timeframe"] == "6H" for s in ref), inst


# -- bookkeeping on fabricated results ------------------------------------------------------------------------------

def _res(cand, inst, tf, mode, cell, *, calmar, passed, holdout=None, n_trades=40, trades_per_year=9.0, kind=None, bracket="none", measured_calmar=None):
    acc = {"passed": passed, "failed": [] if passed else ["calmar_gt_0_5", "sharpe_gt_0_7"], "rolling_positive_share": 0.7, "worst_calendar_year_return": -0.05,
           "payoff_ratio": 2.5, "tier": cell.tier}
    r = {"candidate": cand, "instrument": inst, "timeframe": tf, "regime": {"mode": mode, "label": mode}, "cell": cell.to_dict(),
         "kind": kind or ("control" if cand == "hold" else "fixed" if cand in r3.FIXED_CANDIDATES else "barsize"),
         "configuration": r3.configuration_name(cand, inst, tf, mode), "selected_params": {"bracket": bracket},
         "oos": {"calmar": calmar, "cagr": calmar / 10, "max_drawdown": 0.1, "profit_factor": 1.1 + calmar, "sharpe": calmar, "n_trades": n_trades, "total_return": 0.1,
                 "trades_per_year": trades_per_year, "exposure": 0.5, "avg_allocation": 0.2 if cell.tier == "trader" else 0.1, "fees_pct_per_year": 0.01, "win_rate": 0.4,
                 "ann_vol": 0.1, "windows_traded": 9, "windows": 9, "avg_win": 100.0, "avg_loss": -40.0},
         "acceptance_r18": acc, "acceptance": dict(acc), "robustness": {"share_above_threshold": 0.8}, "dsr": {"dsr": 0.1},
         "policy_sizing": SIZING_TIERS[cell.tier].to_dict(), "yearly": {"2022": -0.02, "2023": 0.05},
         "r18": {"tier": cell.tier, "brakes": TRADER_BRAKES.to_dict() if cell.brakes else None, "brake_summary": {},
                 "trades": {"expectancy_r": 0.2, "risk_pct_mean": 0.015, "risk_pct_max": 0.02, "gap_trades": 0, "reentries_within_2_bars_of_stop": 1, "stop_outs": 5, "payoff_ratio": 2.5},
                 "cap": {"cap_binding_share": 0.3}, "cost_scenarios": {"measured_btc_eth": {"calmar": measured_calmar if measured_calmar is not None else calmar + 0.1, "cagr": calmar / 9,
                                                                                            "max_drawdown": 0.09}} if cell.tier == "trader" else {}},
         "montecarlo": {"prob_max_dd_ge_30": 0.01},
         "protocol_check": {"ok": cell.tier == "reference", "ok_for_cell": True, "expected_mismatches": {}, "unexplained_mismatches": {}, "mismatches": {}}}
    if holdout is not None:
        r["holdout"] = {"total_return": holdout, "profit_factor": 1.5 if holdout > 0 else 0.5, "n_trades": 20, "max_drawdown": 0.05}
        r["holdout_confirmed"] = holdout > 0
    else:
        r["holdout_confirmed"] = None
    return r


def _merged(results):
    return {r3.result_key(r["candidate"], r["instrument"], r["timeframe"], r["regime"]["mode"], r["cell"]["key"]): r for r in results}


def _series_info(merged):
    return {f"{r['instrument']} {r['timeframe']}": {"instrument": r["instrument"], "timeframe": r["timeframe"], "holdout_span": "2025-10-20->2026-10-20",
                                                     "span": f"{r['instrument']} {r['timeframe']}: x", "failures": [], "skipped": None} for r in merged.values()}


def test_annotation_verdicts_readings_openings_and_shortlist_rows_follow_the_preregistered_rules(stored):
    J, R = r3.JUDGED_CELL, r3.REFERENCE_CELL
    rows = [
        _res("hold", "BTC-USDT", "6H", "none", J, calmar=0.3, passed=False, holdout=-0.04), _res("hold", "BTC-USDT", "6H", "none", R, calmar=0.25, passed=False),
        _res("hold", "BTC-USDT", "1D", "none", J, calmar=0.3, passed=False, holdout=-0.04), _res("hold", "XRP-USDT", "6H", "none", J, calmar=0.2, passed=False, holdout=-0.1),
        _res("S7", "BTC-USDT", "6H", "none", J, calmar=0.9, passed=True, holdout=0.03), _res("S7", "BTC-USDT", "6H", "none", R, calmar=0.7, passed=True),
        _res("S7", "BTC-USDT", "1D", "none", J, calmar=0.8, passed=True, holdout=0.02, trades_per_year=8.0),
        _res("S7e", "BTC-USDT", "6H", "none", J, calmar=0.95, passed=True, holdout=-0.02, trades_per_year=45.0),  # confirmed? no: contradicted; and above the ceiling
        _res("S7w", "BTC-USDT", "6H", "none", J, calmar=0.5, passed=False), _res("S7t", "BTC-USDT", "6H", "none", J, calmar=0.6, passed=False, bracket="trail3"),
        _res("S7", "XRP-USDT", "6H", "none", J, calmar=0.95, passed=True, holdout=0.05), _res("S8", "BTC-USDT", "6H", "none", J, calmar=0.2, passed=False, n_trades=12, trades_per_year=2.5),
        _res("S8g", "BTC-USDT", "6H", "none", J, calmar=0.1, passed=False, n_trades=8, trades_per_year=1.5),
    ]
    merged = _merged(rows)
    r3.annotate_all(merged)
    s7 = merged[r3.result_key("S7", "BTC-USDT", "6H", "none", J.key)]
    assert s7["role"] == "configuration" and s7["judged"] and s7["primary"] and s7["fixed_rule"] and s7["hypothesis"] == "H7" and s7["variant_of"] is None
    assert s7["comparison"]["available"] and s7["comparison"]["base_configuration"] == "hold BTC-USDT 6H [none]" and s7["comparison"]["delta"]["calmar"] == pytest.approx(0.6)
    assert s7["reference"]["calmar"] == 0.7 and s7["reference"]["exposure_ratio"] == pytest.approx(2.0) and s7["reference"]["passed"]
    assert s7["fleet_eligible"] and s7["fleet_blockers"] == [] and s7["turnover_ok"] and s7["expected_trades"] == "below"  # 9 a year, the plan expected 10-25
    s7_1d = merged[r3.result_key("S7", "BTC-USDT", "1D", "none", J.key)]
    assert not s7_1d["fleet_eligible"] and s7_1d["fleet_blockers"] == ["the fleet runs 4H and 6H bars, not 1D"]
    s7e = merged[r3.result_key("S7e", "BTC-USDT", "6H", "none", J.key)]
    assert s7e["variant_of"] == "S7" and s7e["variant_comparison"]["available"] and s7e["variant_comparison"]["delta"]["calmar"] == pytest.approx(0.05)
    assert not s7e["turnover_ok"] and s7e["expected_trades"] == "above" and not s7e["fleet_eligible"] and s7e["fleet_blockers"] == []  # contradicted: no blocker text
    s7t = merged[r3.result_key("S7t", "BTC-USDT", "6H", "none", J.key)]
    assert s7t["fixed_bracket"] == "trail3" and s7t["variant_comparison"]["base_configuration"] == "S7 BTC-USDT 6H [none]"
    ref_s7 = merged[r3.result_key("S7", "BTC-USDT", "6H", "none", R.key)]
    assert not ref_s7["judged"] and ref_s7["reference"] is None and ref_s7["comparison"]["base_configuration"] == "hold BTC-USDT 6H [none]"
    hold = merged[r3.result_key("hold", "BTC-USDT", "6H", "none", J.key)]
    assert hold["role"] == "control" and not hold["comparison"]["available"] and not hold["judged"]
    xrp = merged[r3.result_key("S7", "XRP-USDT", "6H", "none", J.key)]
    assert xrp["judged"] and not xrp["primary"] and xrp["fleet_eligible"]
    # Verdicts: H7 confirmed on the primary markets (S7 6H and 1D confirmed; S7e contradicted), confirmed on the replication markets; H8 failed.
    cfg = r3.Round3Config()
    verdicts = {v["hypothesis"]: v for v in r3.hypothesis_verdicts(merged, cfg, trades={})}
    h7, h8 = verdicts["H7"], verdicts["H8"]
    assert h7["label"] == "confirmed" and h7["replication_label"] == "confirmed" and h7["n_primary"] == 5 and h7["n_replication"] == 1
    assert h7["confirmed"] == ["S7 BTC-USDT 6H [none]", "S7 BTC-USDT 1D [none]"] and h7["contradicted"] == ["S7e BTC-USDT 6H [none]"]
    assert h7["fleet_eligible"] == ["S7 BTC-USDT 6H [none]", "S7 XRP-USDT 6H [none]"] and h7["recorded_only"][0]["configuration"] == "S7 BTC-USDT 1D [none]"
    assert h7["turnover_flagged"] == ["S7e BTC-USDT 6H [none]"]
    rep = {e["configuration"]: e for e in h7["replication"]}
    assert set(rep) == {"S7 6H [none]", "S7 1D [none]", "S7e 6H [none]"} and rep["S7 6H [none]"]["n_pass"] == 1 and rep["S7 6H [none]"]["needed"] == 4 and not rep["S7 6H [none]"]["replicated"]
    assert rep["S7 6H [none]"]["markets"][0]["instrument"] == "XRP-USDT" and rep["S7 1D [none]"]["n_ran"] == 0
    var = {e["variant"]: e for e in h7["variants"]}
    assert var["S7e"]["directional"]["improved"] == 1 and var["S7w"]["directional"]["improved"] == 0 and var["S7t"]["n"] == 1 and var["S7e"]["median_delta_calmar"] == pytest.approx(0.05)
    assert h7["directional_primary"]["n"] == 5 and h7["directional_primary"]["improved"] == 5 and h7["directional_primary"]["replicates_in_direction"]
    assert h7["directional_replication"]["n"] == 1 and h7["directional_replication"]["threshold"] is None
    assert h8["label"] == "failed walk-forward" and h8["replication_label"] == "not run" and dict(h8["binding_gates"])["calmar_gt_0_5"] == 2
    ff = h8["failure_facts"]
    assert ff["n_compared"] == 2 and ff["calmar_improved"] == 0 and ff["median_trades_per_year"] == 2.0 and ff["expected_trades_per_year"] == [3.0, 6.0] and ff["by_timeframe"]["6H"]["n"] == 2
    assert "pooled" in h8 and h8["pooled"] == [] or all(e["pooled_trades"] == 0 for e in h8.get("pooled") or [])
    overall = r3.overall_summary(list(verdicts.values()), merged)
    assert (overall["n_judged"], overall["n_primary"], overall["n_passed"], overall["n_confirmed"], overall["n_contradicted"]) == (8, 7, 4, 3, 1)
    assert overall["fleet_eligible"] == ["S7 BTC-USDT 6H [none]", "S7 XRP-USDT 6H [none]"] and overall["expected_passes_by_chance"] == pytest.approx(0.3)
    # Openings, earlier looks (the stored hold control of the market at 6H), the ledger and the second-look guard.
    info = _series_info(merged)
    openings = r3.holdout_openings(merged, info)
    assert [(o["configuration"], o["role"], o["confirmed"]) for o in openings][:5] == [
        ("S7 BTC-USDT 1D [none]", "configuration", True), ("S7 BTC-USDT 6H [none]", "configuration", True), ("S7 XRP-USDT 6H [none]", "configuration", True),
        ("S7e BTC-USDT 6H [none]", "configuration", False), ("hold BTC-USDT 1D [none]", "control", None)]
    looks = {l["configuration"]: l for l in r3.earlier_looks(merged, stored)}
    assert looks["S7 BTC-USDT 6H [none]"]["earlier_configuration"] == "hold BTC-USDT 6H [none]" and looks["S7 BTC-USDT 6H [none]"]["earlier_study"] == "Sprint 2c"
    assert looks["S7 BTC-USDT 6H [none]"]["earlier_opened"] and looks["S7 BTC-USDT 6H [none]"]["same_bar_size"]
    assert looks["S7 BTC-USDT 1D [none]"]["earlier_configuration"] == "hold BTC-USDT 6H [none]" and not looks["S7 BTC-USDT 1D [none]"]["same_bar_size"]
    assert looks["S7 XRP-USDT 6H [none]"]["earlier_study"] == "R12 replication" and looks["S7 XRP-USDT 6H [none]"]["earlier_opened"]
    ledger = [{"generated_at": "a", "openings": openings}]
    assert r3.guard_second_look(ledger, openings, evaluate_holdout=True) == ["S7 BTC-USDT 1D [none] @ trader|brakes|none", "S7 BTC-USDT 6H [none] @ trader|brakes|none",
                                                                             "S7 XRP-USDT 6H [none] @ trader|brakes|none", "S7e BTC-USDT 6H [none] @ trader|brakes|none"]
    assert r3.guard_second_look(ledger, openings, evaluate_holdout=False) == []
    applied, recorded = r3.shortlist_additions(merged, source={"study": r3.STUDY_NAME, "results": "r.json"})
    assert [(a["candidate"], a["instrument"], a["timeframe"]) for a in applied] == [("S7", "XRP-USDT", "6H"), ("S7", "BTC-USDT", "6H")]
    src = applied[0]["source"]
    assert src["tier"] == "trader" and src["cell"] == "trader|brakes|none" and src["variant"] == "none" and src["protocol_variant"] == r3.FIXED_RULE_PROTOCOL
    assert src["brakes"] == TRADER_BRAKES.to_dict() and src["role"] == "candidate" and src["hypothesis"] == "H7" and applied[0]["sizing"] == "vt20/30 crash15/90dh cap2 turtle"
    assert applied[0]["sizing_config"] == SIZING_TIERS["trader"].to_dict() and applied[0]["passed"] and applied[0]["holdout_confirmed"]
    assert [(a["candidate"], a["timeframe"], a["reasons"]) for a in recorded] == [("S7", "1D", ["the fleet runs 4H and 6H bars, not 1D"])]


def test_barsize_table_and_its_preregistered_reading():
    J, R = r3.JUDGED_CELL, r3.REFERENCE_CELL
    rows = []
    for cand in ("S1", "S2"):
        for inst in r3.PRIMARY_MARKETS:
            for mode in ("none", "gate"):
                for tf, calmar, meas in (("1D", 0.3, 0.35), ("6H", 0.6, 0.7), ("4H", 0.5, 0.55)):
                    rows.append(_res(cand, inst, tf, mode, J, calmar=calmar, passed=calmar > 0.5, measured_calmar=meas, kind="barsize"))
                    rows.append(_res(cand, inst, tf, mode, R, calmar=calmar - 0.1, passed=False, kind="barsize"))
                    rows.append(_res("hold", inst, tf, "none", J, calmar=0.2, passed=False))
                    rows.append(_res("hold", inst, tf, "none", R, calmar=0.2, passed=False))
    merged = _merged(rows)
    r3.annotate_all(merged)
    bs = r3.barsize_table(merged)
    assert len(bs["rows"]) == 48 and all(x["hold_calmar"] == 0.2 for x in bs["rows"]) and all(x["measured"] is not None for x in bs["rows"] if x["tier"] == "trader")
    assert all(x["measured"] is None for x in bs["rows"] if x["tier"] == "reference") and not any(x["untested"] for x in bs["rows"])
    assert len(bs["best"]) == 8 and all(b["best_at_gate_cost"] == "6H" and b["best_at_measured_cost"] == "6H" and b["best_at_gate_cost_literal"] == "6H" for b in bs["best"])
    assert {b["family"] for b in bs["best"]} == {"S1", "S2"} and all(b["untested_timeframes"] == [] for b in bs["best"])
    reading = bs["reading"]
    assert reading["n_comparisons"] == 8 and reading["six_h_best_at_gate_cost"] == 8 and reading["needed"] == 4 and reading["holds"] and reading["holds_clarified"]
    assert reading["six_h_best_at_gate_cost_clarified"] == 8 and reading["untested"] == [] and reading["families"]["S1"]["best_counts"]["6H"] == {"gate_cost": 4, "measured_cost": 4}
    assert reading["medians_by_timeframe"]["6H"]["calmar_trader"] == 0.6 and reading["medians_by_timeframe"]["6H"]["calmar_trader_measured"] == 0.7 and reading["medians_by_timeframe"]["6H"]["passed_trader"] == 8
    assert r3.rebuild_merged(list(merged.values())).keys() == merged.keys()
    # 4H wins at the measured cost on every comparison: the claim no longer holds.
    for r in merged.values():
        if r["timeframe"] == "4H" and r["cell"]["tier"] == "trader" and r["candidate"] != "hold":
            r["r18"]["cost_scenarios"]["measured_btc_eth"]["calmar"] = 0.9
    assert not r3.barsize_table(merged)["reading"]["holds"]
    # A bar size on which no walk-forward window qualified a rule (0 trades, 0 windows traded) is untested there: the literal reading counts its 0.00,
    # the clarified reading sets it aside and hides its 0.20 % replay (which would be the default parameters), and the family counts say where it happened.
    for r in merged.values():
        if r["candidate"] == "S2" and r["timeframe"] == "1D":
            r["oos"].update({"windows_traded": 0, "n_trades": 0, "calmar": 0.0, "cagr": 0.0})
            if r["cell"]["tier"] == "trader":
                r["r18"]["cost_scenarios"]["measured_btc_eth"]["calmar"] = 5.0  # a replay of the default parameters: must not count
    bs2 = r3.barsize_table(merged)
    s2_1d = [x for x in bs2["rows"] if x["candidate"] == "S2" and x["timeframe"] == "1D"]
    assert all(x["untested"] and x["measured"] is None and x["measured_literal"] is not None for x in s2_1d if x["tier"] == "trader")
    s2_best = [b for b in bs2["best"] if b["candidate"] == "S2"]
    assert all(b["untested_timeframes"] == ["1D"] and b["best_at_measured_cost_literal"] == "1D" and b["best_at_measured_cost"] == "4H" for b in s2_best)
    rd = bs2["reading"]
    assert rd["untested"] == ["S2 BTC-USDT 1D [gate]", "S2 BTC-USDT 1D [none]", "S2 ETH-USDT 1D [gate]", "S2 ETH-USDT 1D [none]"]
    assert rd["families"]["S2"]["untested"] == 4 and rd["families"]["S1"]["untested"] == 0 and rd["six_h_best_at_measured_cost"] == 0
    assert rd["best_counts"]["1D"]["measured_cost"] == 4 and rd["best_counts"]["1D"]["measured_cost_clarified"] == 0 and rd["best_counts"]["4H"]["measured_cost_clarified"] == 8


# -- the runner on the synthetic lake -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_study(study_lake):
    """Both cells on BTC-USDT 6H, mode none: the control, the fixed rules and the trail variant; plus the control and H8 at the judged cell on 1D bars."""
    cfg = r3.Round3Config(hypotheses=("H7", "H8"), markets=("BTC-USDT",), timeframes=("6H",), regime_modes=("none",), barsize=False, reproduction=False, lake_dir=str(study_lake.root))
    jobs = r3.plan_jobs(cfg, evaluate_holdout=False)
    cfg_1d = r3.Round3Config(hypotheses=("H8",), markets=("BTC-USDT",), timeframes=("1D",), regime_modes=("none",), cells=(r3.JUDGED_CELL.key,), barsize=False, reproduction=False,
                             lake_dir=str(study_lake.root))
    jobs += r3.plan_jobs(cfg_1d, evaluate_holdout=False)
    assert [(j["kind"], j["cell"]["key"], j["timeframe"]) for j in jobs] == [
        ("control", "reference|nobrakes|none", "6H"), ("fixed", "reference|nobrakes|none", "6H"), ("fixed_trail", "reference|nobrakes|none", "6H"),
        ("control", "trader|brakes|none", "6H"), ("fixed", "trader|brakes|none", "6H"), ("fixed_trail", "trader|brakes|none", "6H"),
        ("control", "trader|brakes|none", "1D"), ("fixed", "trader|brakes|none", "1D")]
    outputs = [r3.run_job(j) for j in jobs]
    meta = json.loads(r3.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    merged, info = r3.merge_results(outputs, meta)
    r3.annotate_all(merged)
    trades = {}
    for o in outputs:
        for key, t in (o.get("trades") or {}).items():
            cand, mode = key.split("|")
            trades[r3.result_key(cand, o["instrument"], o["timeframe"], mode, o["cell"]["key"])] = t
    return cfg, merged, info, trades


def test_run_job_merge_and_annotate_on_the_synthetic_lake(synthetic_study):
    cfg, merged, info, trades = synthetic_study
    assert set(info) == {"BTC-USDT 6H", "BTC-USDT 1D"} and all(not s["failures"] and not s.get("skipped") for s in info.values()), info
    keys = {(r["candidate"], r["timeframe"], r["cell"]["key"]) for r in merged.values()}
    assert ("S7t", "6H", "trader|brakes|none") in keys and ("S8g", "1D", "trader|brakes|none") in keys and ("hold", "6H", "reference|nobrakes|none") in keys and len(merged) == 17
    for r in merged.values():
        assert r["protocol_check"]["ok_for_cell"], (r["configuration"], r["protocol_check"]["unexplained_mismatches"])
        assert r["acceptance_r18"]["tier"] == r["cell"]["tier"] and r["oos"]["windows"] >= 1
    s7t = merged[r3.result_key("S7t", "BTC-USDT", "6H", "none", r3.JUDGED_CELL.key)]
    assert s7t["selected_params"]["bracket"] == "trail3" and s7t["fixed_bracket"] == "trail3" and s7t["oos"]["n_trades"] > 0 and s7t["robustness"]["n_neighbours"] == 10
    assert s7t["variant_comparison"]["available"] and s7t["variant_comparison"]["base_configuration"] == "S7 BTC-USDT 6H [none]"
    s7 = merged[r3.result_key("S7", "BTC-USDT", "6H", "none", r3.JUDGED_CELL.key)]
    assert s7["judged"] and s7["oos"]["windows_traded"] == s7["oos"]["windows"], "min_trades 0: every window runs the fixed rule"
    assert s7["selected_params"] == dict(get_candidate("S7").default_params, bracket="none") and s7["comparison"]["available"]
    assert s7["reference"] is not None and s7["reference"]["exposure_ratio"] is not None and s7["r18"]["brakes"] == TRADER_BRAKES.to_dict()
    assert s7["r18"]["trades"]["risk_pct_mean"] is not None and s7["r18"]["cost_scenarios"]["measured_btc_eth"]["round_trip"] == pytest.approx(0.002)
    assert s7["r18"]["trades"]["risk_pct_max"] <= 0.021, "the Trader tier's 2 % cap bounds the risk at the initial stop"
    s8_1d = merged[r3.result_key("S8", "BTC-USDT", "1D", "none", r3.JUDGED_CELL.key)]
    assert s8_1d["oos"]["bars"] >= 90 and s8_1d["selected_params"]["atr_mult"] == 5.0 and s8_1d["robustness"]["n_neighbours"] == 8 and s8_1d["trades_per_year"] is not None
    assert all("holdout" not in r for r in merged.values())
    assert trades[r3.result_key("S7", "BTC-USDT", "6H", "none", r3.JUDGED_CELL.key)].shape[0] == s7["oos"]["n_trades"]


def test_a_gated_barsize_job_at_the_trader_cell_runs_the_runners_sensitivity_replay(study_lake):
    """The runner's gate-threshold sensitivity replay sizes the lead gated S1/S2 rule with the policy spec; a per-trade-cap tier needs the rule's
    stop there (the first full run of this study crashed on it). A quick gated S2 bar-size job at the Trader cell must complete."""
    cfg = r3.Round3Config(hypotheses=("H8",), markets=("BTC-USDT",), timeframes=("6H",), regime_modes=("gate",), cells=(r3.JUDGED_CELL.key,), barsize=True,
                          reproduction=False, quick=True, lake_dir=str(study_lake.root))
    job = {"cfg": cfg.to_dict(), "kind": "barsize", "instrument": "BTC-USDT", "timeframe": "6H", "cell": r3.JUDGED_CELL.to_dict(), "strategies": ["S2"], "evaluate_holdout": False}
    out = r3.run_job(job)
    assert not out["failures"] and not out.get("skipped"), out["failures"]
    assert [r["regime"]["mode"] for r in out["results"]] == ["gate"] and out["results"][0]["policy_sizing"]["risk_cap"] == 0.02
    assert out["results"][0]["oos"]["n_trades"] >= 0 and out["results"][0]["acceptance_r18"]["tier"] == "trader"


def test_verdicts_summary_barsize_and_report_on_the_synthetic_lake(synthetic_study, stored):
    cfg, merged, info, trades = synthetic_study
    verdicts = r3.hypothesis_verdicts(merged, cfg, trades)
    assert [v["hypothesis"] for v in verdicts] == ["H7", "H8"]
    h7, h8 = verdicts
    assert h7["n_primary"] == 4 and h7["n_replication"] == 0 and h7["replication_label"] == "not run" and len(h7["variants"]) == 3
    assert h8["n_primary"] == 4 and h8["pooled"] and all(e["n_markets"] == 1 for e in h8["pooled"]) and h8["pooled"][0]["pooled_trades"] > 0
    assert h7["label"] in ("failed walk-forward", "passed walk-forward, holdout not opened") and h7["failure_facts"]["n_compared"] == 4
    overall = r3.overall_summary(verdicts, merged)
    assert overall["n_judged"] == 8 and set(overall["labels"]) == {"H7", "H8"}
    assert r3.holdout_openings(merged, info) == [] and r3.earlier_looks(merged, stored) == [] and r3.shortlist_additions(merged, source={"study": "t"}) == ([], [])
    assert r3.barsize_table(merged)["rows"] == []
    run = {"meta": {"generated_at": "2026-11-05 12:00 UTC", "elapsed_minutes": 0.1, "config": cfg.to_dict(), "preregistration": r3.PREREGISTRATION,
                    "preregistration_sha256": "abc", "preregistration_file": "p.json", "protocol_check": {"ok": True, "checked": ["fee"]},
                    "v1c_meta": {"holdout_span": "2025-10-20->2026-10-20", "policy_sizing": {"label": "p"}, "regime": {"label": "g"}, "fee_rate": 0.001, "slippage_rate": 0.0005,
                                 "data_span_short": "x"}, "evaluate_holdout": False, "data_end": r3.DATA_END, "gates": {"calmar_min": 0.5}, "holdout_ledger": []},
           "reproduction": [], "results": [{k: v for k, v in r.items() if k not in ("trades", "args")} for r in merged.values()], "series_info": info,
           "verdicts": verdicts, "overall": overall, "barsize": r3.barsize_table(merged), "holdout_openings": [], "earlier_looks": [], "shortlist_additions": [],
           "shortlist_recorded_only": []}
    text = render_report(run)
    for heading in ("## Executive summary", "## Fixed before the first run", "### H7 —", "### H8 —", "## Reproduction of the stored studies", "## H7 —", "## H8 —",
                    "Directional reading on the primary markets", "The Trader cell beside the Reference cell", "The variants beside the base rule S7", "Pooled over the nine markets",
                    "**Failure analysis**", "## The bar size after costs", "## The comparison lines", "## The untouched 12 months", "## Paper-fleet shortlist",
                    "## Owner decisions", "## Method notes and caveats", "Parked by the plan", "Trade-count check before the pre-registration"):
        assert heading in text, heading
    assert "S7t BTC-USDT 6H [none]" in text and "S8g BTC-USDT 1D [none]" in text and "skipped the reproduction" in text
    assert "**Nothing here authorizes paper, demo or live trading.**" in text


# -- the pre-registration file ---------------------------------------------------------------------------------------

def test_preregistration_file_is_written_once_and_checked(tmp_path, monkeypatch):
    path = tmp_path / "prereg.json"
    payload = r3.preregister(path, now=datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc))
    assert payload["written_at"] == "2026-11-05T12:00:00+00:00" and payload["preregistration"] == r3.PREREGISTRATION and payload["judged_cell"]["key"] == "trader|brakes|none"
    assert set(payload["candidates"]) == set(r3.FIXED_CANDIDATES) and payload["candidates"]["S7t"]["bracket"] == "trail3" and payload["turnover_ceiling"] == 40.0
    loaded = r3.load_preregistration(path)
    assert loaded["sha256"] == payload["sha256"] and loaded["configuration"]["hypotheses"] == ["H7", "H8"] and loaded["configuration"]["barsize"]
    with pytest.raises(r3.Round3Error, match="already fixed"):
        r3.preregister(path)
    r3.preregister(path, force=True)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["preregistration"]["hypotheses"]["H8"]["rule"] = "a looser rule"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(r3.Round3Error, match="hash mismatch"):
        r3.load_preregistration(path)
    r3.preregister(path, force=True)
    changed = copy.deepcopy(r3.PREREGISTRATION)
    changed["hypotheses"]["H8"]["rule"] = "a looser rule"
    monkeypatch.setattr(r3, "PREREGISTRATION", changed)
    with pytest.raises(r3.Round3Error, match="differs from the registered file"):
        r3.load_preregistration(path)
    monkeypatch.undo()
    # A rule whose numbers changed after the registration is refused too.
    s8 = get_candidate("S8")
    monkeypatch.setattr(s8, "default_params", dict(s8.default_params, atr_mult=4.0))
    with pytest.raises(r3.Round3Error, match="rule S8 differs"):
        r3.load_preregistration(path)
    monkeypatch.undo()
    other = tmp_path / "r12.json"
    other.write_text(json.dumps({"chosen": ["XRP-USDT", "BCH-USDT"]}), encoding="utf-8")
    with pytest.raises(r3.Round3Error, match="differ from the R12 pre-registration"):
        r3.preregister(tmp_path / "p2.json", r12_path=other)
    assert r3.preregistration_hash(r3.Round3Config(), loaded) != r3.preregistration_hash(r3.Round3Config(quick=True), loaded)


def test_the_committed_preregistration_is_intact_and_matches_the_module():
    data = r3.load_preregistration(r3.PREREGISTRATION_PATH)
    assert data["preregistration"] == r3.PREREGISTRATION and data["configuration"] == r3.Round3Config().to_dict()
    assert sorted(data["preregistration"]["hypotheses"]) == ["H7", "H8"] and data["replication_markets"] == json.loads(r3.R12_PREREGISTRATION.read_text(encoding="utf-8"))["chosen"]


# -- the command line --------------------------------------------------------------------------------------------------

def _cli():
    spec = importlib.util.spec_from_file_location("run_research_round_3", ROOT / "scripts" / "run_research_round_3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_cli_opens_the_holdout_only_for_the_full_preregistered_study_and_writes_the_stub(tmp_path, capsys):
    cli = _cli()
    prereg = tmp_path / "prereg.json"
    stub = tmp_path / "stub.md"
    assert cli.main(["--preregister", "--preregistration", str(prereg), "--report", str(stub)]) == 0
    text = stub.read_text(encoding="utf-8")
    assert text.startswith("# Research round 3") and "pre-registered, not yet run" in text and "### H7 —" in text and "Parked by the plan" in text and "## Owner decisions" in text
    common = ["--preregistration", str(prereg), "--lake-dir", str(tmp_path / "lake"), "--study-lake-dir", str(tmp_path / "study"), "--report", "-", "--json", "-"]
    for argv in (["--evaluate-holdout", "--quick"], ["--evaluate-holdout", "--hypotheses", "H7"], ["--evaluate-holdout", "--timeframes", "6H"],
                 ["--evaluate-holdout", "--regime-modes", "none"], ["--evaluate-holdout", "--markets", "BTC-USDT"], ["--evaluate-holdout", "--no-barsize"],
                 ["--evaluate-holdout", "--cells", "trader|brakes|none"], ["--evaluate-holdout", "--skip-reproduction"], ["--evaluate-holdout", "--holdout-ledger", "-"]):
        assert cli.main(argv + common) == 2, argv
    assert cli.main(["--preregister", "--preregistration", str(prereg), "--report", "-"]) == 2  # written once
    assert cli.main(["--quick", "--preregistration", str(tmp_path / "missing.json"), "--report", "-", "--json", "-"]) == 2
    err = capsys.readouterr().err
    assert "full pre-registered study" in err and "needs a holdout ledger" in err and "run --preregister first" in err


def test_the_cli_runs_a_narrowed_study_on_the_synthetic_lake_and_renders_from_json(tmp_path, study_lake):
    cli = _cli()
    prereg = tmp_path / "prereg.json"
    r3.preregister(prereg)
    out_json, out_md, ledger = tmp_path / "results.json", tmp_path / "report.md", tmp_path / "ledger.json"
    argv = ["--preregistration", str(prereg), "--lake-dir", str(study_lake.root), "--study-lake-dir", str(tmp_path / "study"), "--hypotheses", "H8", "--markets", "BTC-USDT",
            "--timeframes", "6H", "--regime-modes", "none", "--cells", "trader|brakes|none", "--no-barsize", "--skip-reproduction", "--report", str(out_md), "--json", str(out_json),
            "--holdout-ledger", str(ledger), "--shortlist", "-"]
    assert cli.main(argv) == 0
    run = json.loads(out_json.read_text(encoding="utf-8"))
    assert run["meta"]["study"] == r3.STUDY_NAME and not run["meta"]["full_study"] and not run["meta"]["evaluate_holdout"] and run["meta"]["reproduction"] is False
    assert {r["candidate"] for r in run["results"]} == {"hold", "S8", "S8g"} and all(r["protocol_check"]["ok_for_cell"] for r in run["results"])
    assert run["verdicts"][0]["hypothesis"] == "H8" and run["shortlist_additions"] == [] and run["holdout_openings"] == [] and not ledger.exists()
    assert "H8 — the slow breakout with wide stops (S8):" in out_md.read_text(encoding="utf-8")
    out2 = tmp_path / "report2.md"
    assert cli.main(["--render-from-json", str(out_json), "--report", str(out2)]) == 0
    assert out2.read_text(encoding="utf-8") == out_md.read_text(encoding="utf-8")


def test_a_shortlist_amendment_the_fleet_cannot_load_is_rolled_back(tmp_path):
    cli = _cli()
    path = tmp_path / "shortlist.json"
    original = (ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json").read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    J = r3.JUDGED_CELL
    merged = _merged([_res("hold", "XRP-USDT", "6H", "none", J, calmar=0.2, passed=False, holdout=-0.1), _res("S8", "XRP-USDT", "6H", "none", J, calmar=0.9, passed=True, holdout=0.03)])
    r3.annotate_all(merged)
    applied, _ = r3.shortlist_additions(merged, source={"study": r3.STUDY_NAME, "results": "docs/research/missing_results.json"})
    assert len(applied) == 1
    note = cli._apply_shortlist_additions(path, applied)
    assert note.startswith("NOT applied") and path.read_text(encoding="utf-8") == original
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"shortlist_additions": applied, "meta": {}, "results": [], "verdicts": [], "overall": {}}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(path), "--report", "-"]) == 1
    assert path.read_text(encoding="utf-8") == original
    results.write_text(json.dumps({"shortlist_additions": []}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(path), "--report", "-"]) == 0


# -- the fleet loader: a fixed-rule candidate row ---------------------------------------------------------------------------

def _fixed_rule_results_file(tmp_path: Path, *, candidate: str = "S7", bracket: str = "none", protocol_variant: str = r3.FIXED_RULE_PROTOCOL, explained=("policy_sizing", "brackets", "min_trades")):
    cand = get_candidate(candidate) if candidate in CANDIDATES else get_candidate("S1")
    J = r3.JUDGED_CELL
    r = _res(candidate, "BTC-USDT", "6H", "none", J, calmar=0.9, passed=True, holdout=0.03, bracket=bracket)
    r["selected_params"] = dict(cand.default_params, bracket=bracket)
    r["yearly_gate"] = {"rolling_positive_share": 0.8, "worst_calendar_year_return": -0.05}
    r["protocol_check"] = {"ok": False, "ok_for_cell": True, "mismatches": {k: {"got": 1, "stored": 2} for k in ("policy_sizing", "brackets", "min_trades")},
                           "expected_mismatches": {k: "why" for k in explained}, "unexplained_mismatches": {}, "protocol_variant": protocol_variant, "r18": {"brakes": TRADER_BRAKES.to_dict()}}
    doc = {"meta": {"protocol_check": {"ok": True, "mismatches": {}}, "rebalance_threshold": 0.25}, "results": [r]}
    path = tmp_path / "round3_results.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path, r


def test_the_fleet_loader_accepts_a_fixed_rule_candidate_row_and_refuses_the_rest(tmp_path):
    from research.paper_fleet.config import DEFAULT_RESULTS, DEFAULT_SHORTLIST, load_manifest
    from research.replication import append_to_shortlist

    results_path, r = _fixed_rule_results_file(tmp_path)
    merged = {r3.result_key("S7", "BTC-USDT", "6H", "none", r3.JUDGED_CELL.key): r}
    r3.annotate_all(merged)
    applied, _ = r3.shortlist_additions(merged, source={"study": r3.STUDY_NAME, "results": str(results_path)})
    assert len(applied) == 1 and applied[0]["source"]["protocol_variant"] == r3.FIXED_RULE_PROTOCOL
    sl = tmp_path / "shortlist.json"
    sl.write_text(DEFAULT_SHORTLIST.read_text(encoding="utf-8"), encoding="utf-8")
    append_to_shortlist(sl, applied, note="test")
    manifest = load_manifest(sl, DEFAULT_RESULTS)
    acc = [a for a in manifest.accounts if a.sleeve is not None and a.sleeve.candidate == "S7"]
    assert len(acc) == 1 and acc[0].account_id.endswith("-s7-btc-6h-none-trader") and acc[0].tier == "trader" and acc[0].sleeve.brakes == TRADER_BRAKES
    assert acc[0].sleeve.sizing.label == "vt20/30 crash15/90dh cap2" and acc[0].expectations["protocol_variant"] == r3.FIXED_RULE_PROTOCOL
    assert acc[0].expectations["gates"] == "section 4.6 at the trader tier" and acc[0].expectations["holdout_confirmed"] is True and acc[0].sleeve.bracket == "none"
    assert len(manifest.accounts) == 32
    # The trail variant: the bracket the row carries is the one the fleet applies.
    results_t, rt = _fixed_rule_results_file(tmp_path / "t", candidate="S7t", bracket="trail3") if (tmp_path / "t").mkdir() is None else (None, None)
    merged_t = {r3.result_key("S7t", "BTC-USDT", "6H", "none", r3.JUDGED_CELL.key): rt}
    r3.annotate_all(merged_t)
    applied_t, _ = r3.shortlist_additions(merged_t, source={"study": r3.STUDY_NAME, "results": str(results_t)})
    sl_t = tmp_path / "shortlist_t.json"
    sl_t.write_text(DEFAULT_SHORTLIST.read_text(encoding="utf-8"), encoding="utf-8")
    append_to_shortlist(sl_t, applied_t, note="test")
    acc_t = next(a for a in load_manifest(sl_t, DEFAULT_RESULTS).accounts if a.sleeve is not None and a.sleeve.candidate == "S7t")
    assert acc_t.sleeve.bracket == "trail3" and acc_t.account_id.endswith("-s7t-btc-6h-none-trader")
    # Refused: a swept rule (S1) under the fixed-rule protocol; a protocol-variant text the study did not record; an explained deviation the study did not flag.
    for kwargs, match in ((dict(candidate="S1"), "only for a registered fixed rule"), (dict(protocol_variant="another protocol"), "study recorded"),
                          (dict(explained=("policy_sizing", "brackets")), "do not match the study's protocol check")):
        sub = tmp_path / f"refuse_{len(match)}"
        sub.mkdir()
        rp, rr = _fixed_rule_results_file(sub, **kwargs)
        if kwargs.get("protocol_variant") and kwargs["protocol_variant"] != r3.FIXED_RULE_PROTOCOL:
            rr["protocol_check"]["protocol_variant"] = "another protocol"
            rp.write_text(json.dumps({"meta": {"protocol_check": {"ok": True, "mismatches": {}}, "rebalance_threshold": 0.25}, "results": [rr]}), encoding="utf-8")
        row = json.loads(json.dumps(applied[0]))
        row["candidate"] = rr["candidate"]
        row["params"] = rr["selected_params"]
        row["source"]["results"] = str(rp)
        sl_r = sub / "shortlist.json"
        sl_r.write_text(DEFAULT_SHORTLIST.read_text(encoding="utf-8"), encoding="utf-8")
        append_to_shortlist(sl_r, [row], note="test")
        with pytest.raises(ValueError, match=match):
            load_manifest(sl_r, DEFAULT_RESULTS)
