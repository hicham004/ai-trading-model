"""Research round 2 (plan row R16): the slow trend rules, the unchanged Sprint 2c runner on them, the pre-registered readings
(sign test, pattern check, contradicted breakouts, the exposure rule beside its control), the pre-registration file, the ledger with
its earlier looks, the shortlist additions, the report and the command line. Everything runs offline on synthetic candles."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, write_partitioned
from research import round2 as r2
from research.bracket import apply_bracket, get_bracket
from research.data import bars_per_year
from research.report_round2 import executive_summary, failure_analysis, render_report
from research.strategies import ALL_KEYS, CANDIDATES, FIXED_RULES, ROUND2_BASES, get_candidate
from research.strategies.base import FeatureContext
from research.strategies.round2 import TREND_SMA_DAYS, SlowTrendExposure, SlowTrendGated, slow_trend_ok
from research.strategies.s2_breakout import DonchianBreakout
from research.sweep import param_grid, perturbed_params

ROOT = Path(__file__).resolve().parents[1]
N = 7600
PPY_4H = bars_per_year("4H")


# -- synthetic candles -------------------------------------------------------------------------------------

def _frame(seed: int, drift: np.ndarray, *, n: int = N, freq: str = "4h", start: str = "2021-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC", name="open_time")
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.012, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = np.random.default_rng(seed).lognormal(3, 0.5, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _market(seed: int, n: int = N) -> pd.DataFrame:
    """A trend flip about every 9 days (so the Sprint 2c rules qualify) around a flat mean (so the slow average is crossed often)."""
    regime = np.sign(np.sin(np.arange(n) / 60.0))
    return _frame(seed, 0.004 * regime, n=n)


def _ctx(timeframe: str = "4H") -> FeatureContext:
    return FeatureContext(timeframe=timeframe, periods_per_year=bars_per_year(timeframe))


def _write(layout: LakeLayout, inst: str, df: pd.DataFrame, bar: str = "4H") -> None:
    n = len(df)
    table = pa.table({
        "open_time": pa.array([t.to_pydatetime() for t in df.index], type=TS_TYPE), "instrument": pa.array([inst] * n), "timeframe": pa.array([bar] * n),
        "open": pa.array(df["open"].to_numpy()), "high": pa.array(df["high"].to_numpy()), "low": pa.array(df["low"].to_numpy()),
        "close": pa.array(df["close"].to_numpy()), "volume": pa.array(df["volume"].to_numpy()), "confirmed": pa.array([True] * n),
    }, schema=CANDLE_SCHEMA)
    write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file(inst, bar, y))


@pytest.fixture(scope="module")
def study_lake(tmp_path_factory):
    layout = LakeLayout(tmp_path_factory.mktemp("r16_lake") / "lake")
    _write(layout, "BTC-USDT", _market(1))
    _write(layout, "XRP-USDT", _market(2))
    return layout


@pytest.fixture(scope="module")
def stored():
    v1c = json.loads(r2.V1C_RESULTS.read_text(encoding="utf-8"))
    r12 = json.loads(r2.R12_RESULTS.read_text(encoding="utf-8"))
    return r2.stored_results(v1c, r12)


def _entries_only(out: pd.Series, base: pd.Series, ok: pd.Series) -> None:
    """``out`` is the entries-only gate of ``base`` by ``ok``: a subset of base, and every new run starts on an allowed bar."""
    o, b, k = out.to_numpy(dtype=bool), base.to_numpy(dtype=bool), ok.to_numpy(dtype=bool)
    assert not (o & ~b).any()
    starts = o & ~np.concatenate([[False], o[:-1]])
    assert k[starts].all()
    assert ((o[1:] | ~(o[:-1] & b[1:]))).all()


# -- the rules -------------------------------------------------------------------------------------------------

def test_round2_candidates_are_registered_as_fixed_pre_registered_rules():
    for key, base_key in ROUND2_BASES.items():
        assert key in CANDIDATES and key in ALL_KEYS and base_key in ALL_KEYS
    s2tf, tf, s2 = get_candidate("S2+TF"), get_candidate("TF"), get_candidate("S2")
    assert isinstance(s2tf, SlowTrendGated) and s2tf.base.key == "S2" and s2tf.sma_days == 200.0 and s2tf.grid == s2.grid and s2tf.default_params == s2.default_params
    assert isinstance(tf, SlowTrendExposure) and tf.grid == {"sma_days": [200.0]} and tf.default_params == {"sma_days": 200.0}
    assert FIXED_RULES[0] == "TF" and "TF" in FIXED_RULES and TREND_SMA_DAYS == 200.0  # round 3 (plan row R19) adds its fixed rules after TF
    assert s2tf.warmup_days == 200.0 and tf.warmup_days == 200.0 and get_candidate("S2").warmup_days is None
    assert len(param_grid(tf.grid, base=tf.default_params)) == 1
    assert perturbed_params(dict(tf.default_params, bracket="none"), list(tf.grid)) == [{"sma_days": 140.0, "bracket": "none"}, {"sma_days": 260.0, "bracket": "none"}]
    # The Sprint 2c runner gives the new keys the none/gate modes and the full bracket set, like S1 and S2.
    v1c = r2.runner()
    for key in ("S2+TF", "TF", "S1+VC"):
        assert v1c.modes_for(key, ["none", "gate", "scale"]) == ["none", "gate"]
        assert v1c._brackets_for(argparse.Namespace(quick=False, brackets=v1c.DEFAULT_BRACKETS), key) == v1c.DEFAULT_BRACKETS
        assert key in v1c.ALL_KEYS


def test_slow_trend_filter_gates_entries_only_and_has_no_signal_before_its_warm_up():
    df = _market(3)
    ctx = _ctx()
    c = get_candidate("S2+TF")
    out = c.build(df, c.default_params, ctx)
    base = DonchianBreakout().build(df, c.default_params, ctx)
    ok = slow_trend_ok(df, ctx)
    assert ok.any() and not ok.all() and ok.index.equals(df.index)
    assert not ok.iloc[:1199].any(), "no 200-day average before its 1200th bar at 4H, so no entry"
    assert not out.desired.iloc[:1199].any() and out.desired.any()
    _entries_only(out.desired, base.desired, ok)
    assert out.stop_distance.equals(base.stop_distance) and out.strength[~out.desired].isna().all()
    # A market that only rises is always above its average once it exists: the filter then changes nothing after the warm-up.
    up = df.copy()
    up["close"] = np.linspace(100, 400, len(up))
    up["open"], up["high"], up["low"] = up["close"].shift(1).fillna(100), up["close"] * 1.001, up["close"].shift(1).fillna(100) * 0.999
    ok_up = slow_trend_ok(up, ctx)
    assert ok_up.iloc[1200:].all() and not ok_up.iloc[:1199].any()
    # A market that only falls is never above it: no entry, ever.
    down = up.copy()
    down["close"] = np.linspace(400, 100, len(down))
    down["open"], down["high"], down["low"] = down["close"].shift(1).fillna(400), down["close"].shift(1).fillna(400) * 1.001, down["close"] * 0.999
    assert not c.build(down, c.default_params, ctx).desired.any()
    # 6H bars: 800 bars of warm-up.
    df6 = _market(4).resample("6h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    assert not slow_trend_ok(df6, _ctx("6H")).iloc[:799].any() and slow_trend_ok(df6, _ctx("6H")).iloc[799:].any()


def test_slow_trend_exposure_rule_is_long_above_its_average_with_no_stop():
    df = _market(5)
    ctx = _ctx()
    tf = get_candidate("TF")
    frame = tf.build(df, tf.default_params, ctx)
    sma = df["close"].rolling(1200, min_periods=1200).mean()
    expected = (df["close"] > sma).fillna(False)
    assert frame.desired.equals(expected.astype(bool)) and frame.desired.any() and not frame.desired.iloc[:1199].any()
    assert frame.stop_distance.isna().all() and frame.strength[frame.desired].notna().all() and frame.strength[~frame.desired].isna().all()
    assert (frame.strength.dropna() > 0).all()
    # A shorter average (the robustness replay's 140-day neighbour) is a different rule: more bars qualify sooner.
    short = tf.build(df, {"sma_days": 140.0}, ctx)
    assert short.desired.iloc[840:1200].any()
    # Without a stop the take-profit bracket has no target and the trailing bracket nothing to trail: only the time stop binds.
    tp = apply_bracket(frame, get_bracket("tp2"), "4H")
    assert tp.target_distance is not None and tp.target_distance.isna().all() and tp.time_stop_bars is None
    t30 = apply_bracket(frame, get_bracket("time30"), "4H")
    assert t30.time_stop_bars == 180 and t30.target_distance is None


def test_the_fleet_can_build_and_decide_for_the_round2_rules():
    """TF and S2+TF use only the market's own candles, carry no own exits and are known to the fleet's registry, so its decision path runs them."""
    from research.paper_fleet.config import OWN_EXIT_CANDIDATES, SleeveSpec
    from research.paper_fleet.signals import decide_sleeve, frame_decisions

    assert not {"TF", "S2+TF"} & OWN_EXIT_CANDIDATES
    df = _market(6, n=3600)  # 600 days: the fleet's 400-day decision window plus the 200-day average
    ctx = _ctx()
    for key, params in (("TF", {"sma_days": 200.0, "bracket": "time30"}), ("S2+TF", dict(DonchianBreakout.default_params, bracket="none"))):
        spec = SleeveSpec(key, "BTC-USDT", "4H", params)
        info = decide_sleeve(spec, df, ctx)
        assert isinstance(info.decision.desired, bool) and info.signal["action"] in ("long", "flat") and info.diagnostics["window_bars"] > 0
        decisions = frame_decisions(spec, df, ctx, start=df.index[-300])
        assert len(decisions) == 300 and any(d.desired for d in decisions), key
        if key == "TF":
            assert all(not np.isfinite(d.stop_distance) for d in decisions), "no stop: the exit is the cross below the average"


# -- the readings -------------------------------------------------------------------------------------------------

def test_sign_test_thresholds_and_directional_reading():
    assert r2.binomial_tail(19, 28) == pytest.approx(11698223 / 2 ** 28) and r2.binomial_tail(0, 5) == 1.0 and r2.binomial_tail(6, 5) == 0.0
    assert r2.sign_threshold(28) == 19 and r2.sign_threshold(20) == 15 and r2.sign_threshold(7) == 7 and r2.sign_threshold(5) == 5 and r2.sign_threshold(4) is None
    assert r2.binomial_tail(19, 28) <= 0.05 < r2.binomial_tail(18, 28)
    rows = [{"configuration": f"c{i}", "comparison": {"available": True, "delta": {"calmar": 0.1 if i < 19 else -0.1}}} for i in range(28)]
    d = r2.directional_reading(rows)
    assert d["n"] == 28 and d["improved"] == 19 and d["threshold"] == 19 and d["replicates_in_direction"] and d["expected_by_chance"] == 14.0
    assert d["p_value"] == pytest.approx(r2.binomial_tail(19, 28)) and len(d["configurations_improved"]) == 19
    rows[0]["comparison"]["delta"]["calmar"] = 0.0  # a tie is not an improvement
    assert not r2.directional_reading(rows)["replicates_in_direction"]
    assert r2.directional_reading([])["n"] == 0 and r2.directional_reading([{"configuration": "x", "comparison": {"available": False}}])["p_value"] is None


def _res(cand, inst, tf, mode, *, calmar, passed, holdout=None, base=None, n_trades=60, windows=(9, 9)):
    r = {"candidate": cand, "instrument": inst, "timeframe": tf, "regime": {"mode": mode, "label": mode}, "selected_params": {"bracket": "none"},
         "oos": {"calmar": calmar, "cagr": calmar / 10, "max_drawdown": 0.1, "profit_factor": 1.1 + calmar, "sharpe": calmar, "n_trades": n_trades, "total_return": 0.1,
                 "trades_per_year": n_trades / 4.0, "exposure": 0.5, "avg_allocation": 0.06, "fees_pct_per_year": 0.01, "win_rate": 0.4,
                 "windows_traded": windows[0], "windows": windows[1]},
         "acceptance": {"passed": passed, "failed": [] if passed else ["calmar_gt_0_5", "sharpe_gt_0_7"], "rolling_positive_share": 0.7, "worst_calendar_year_return": -0.05},
         "robustness": {"share_above_threshold": 0.8}, "dsr": {"dsr": 0.1}, "policy_sizing": {"label": "p"}, "yearly": {"2022": -0.02, "2023": 0.05}}
    if holdout is not None:
        r["holdout"] = {"total_return": holdout, "profit_factor": 1.5 if holdout > 0 else 0.5, "n_trades": 20, "max_drawdown": 0.05}
    return r2.annotate_result(r, base)


def _merged(results_by_series):
    out = {}
    for (inst, tf), results in results_by_series.items():
        out[(inst, tf)] = {"instrument": inst, "timeframe": tf, "results": results, "failures": [], "benchmark": {}, "span": f"{inst} {tf}", "holdout_span": "2025-10-20->2026-10-20",
                           "positioning": {}, "s0_blocked_share": 0.0, "skipped": None, "sleeves": {}, "trades": {}, "kinds": [], "args": {}}
    return out


def test_pattern_check_contradicted_list_and_exposure_comparisons_follow_the_preregistered_rules(stored):
    # The stored breakout configurations that passed walk-forward and were not confirmed, on the trend-filter markets.
    contradicted = r2.contradicted_base_configurations(stored, "S2", r2.TREND_MARKETS)
    names = [c["configuration"] for c in contradicted]
    assert "S2 BTC-USDT 4H [gate]" in names and "S2 TRX-USDT 4H [none]" in names and "S2 ADA-USDT 6H [gate]" in names and "S2 DOGE-USDT 6H [gate]" in names
    assert all(c["study"] in ("Sprint 2c", "R12 replication") for c in contradicted) and not any("ETH" in n for n in names)
    assert all(c["holdout"]["total_return"] is not None for c in contradicted)
    # Pattern check: the gated 4H rows per market.
    rows = []
    for i, m in enumerate(r2.REPLICATION_MARKETS):
        rows.append({"instrument": m, "timeframe": "4H", "regime": {"mode": "gate"}, "configuration": f"S1+VC {m} 4H [gate]",
                     "comparison": {"available": True, "delta": {"calmar": 0.1 if i < 5 else -0.1}}})
        rows.append({"instrument": m, "timeframe": "6H", "regime": {"mode": "gate"}, "configuration": f"S1+VC {m} 6H [gate]", "comparison": {"available": True, "delta": {"calmar": 0.3}}})
    p = r2.pattern_check(rows)
    assert p["n"] == 7 and p["improved"] == 5 and p["consistent_with_round_1"] and p["markets_improved"] == list(r2.REPLICATION_MARKETS[:5])
    rows[0]["comparison"]["delta"]["calmar"] = -0.1
    assert not r2.pattern_check(rows)["consistent_with_round_1"]
    # The exposure rule beside the control (one mode) and beside the filtered breakout on the same series and mode.
    hold = _res("hold", "BTC-USDT", "4H", "none", calmar=0.3, passed=False, holdout=-0.04)
    s2 = _res("S2", "BTC-USDT", "4H", "gate", calmar=0.8, passed=True, holdout=-0.05)
    tf_none = _res("TF", "BTC-USDT", "4H", "none", calmar=0.45, passed=False, base=hold)
    tf_gate = _res("TF", "BTC-USDT", "4H", "gate", calmar=0.2, passed=False, base=hold)
    s2tf_gate = _res("S2+TF", "BTC-USDT", "4H", "gate", calmar=0.6, passed=True, base=s2)
    merged = _merged({("BTC-USDT", "4H"): [hold, s2, tf_none, tf_gate, s2tf_gate]})
    assert tf_gate["comparison"]["base_configuration"] == "hold BTC-USDT 4H [none]" and tf_none["comparison"]["beats_base_by_0_1"] and not tf_gate["comparison"]["beats_base_by_0_1"]
    assert r2.base_mode("TF", "gate") == "none" and r2.base_mode("S2+TF", "gate") == "gate" and r2.find_base(tf_gate, [hold], []) is hold
    exp = r2.exposure_comparisons(merged, stored)
    assert [(e["mode"], e["beats_hold"], e["breakout_adds"]) for e in exp] == [("gate", False, True), ("none", True, None)]
    assert exp[0]["hold"]["calmar"] == 0.3 and exp[0]["s2tf"]["calmar"] == 0.6 and exp[0]["s2"]["calmar"] == 0.8
    outcomes = r2.contradicted_outcomes(merged, stored)
    btc = next(o for o in outcomes if o["configuration"] == "S2 BTC-USDT 4H [gate]")
    assert btc["ran"] and btc["filtered_passed"] and btc["filtered_calmar"] == 0.6 and btc["filtered_holdout"] is None
    assert all(not o["ran"] for o in outcomes if o["instrument"] != "BTC-USDT")


def test_verdict_labels_failure_facts_openings_earlier_looks_and_shortlist_rows(tmp_path, stored):
    cfg = r2.Round2Config(hypotheses=("H4", "H5", "H6"), timeframes=("4H",), regime_modes=("none",))
    s1_xrp = _res("S1", "XRP-USDT", "4H", "none", calmar=0.3, passed=False)
    s1_sol = _res("S1", "SOL-USDT", "4H", "none", calmar=0.6, passed=False)
    hold_btc = _res("hold", "BTC-USDT", "4H", "none", calmar=0.3, passed=False, holdout=-0.04)
    s2_btc = _res("S2", "BTC-USDT", "4H", "none", calmar=0.4, passed=False)
    merged = _merged({
        ("XRP-USDT", "4H"): [s1_xrp, _res("S1+VC", "XRP-USDT", "4H", "none", calmar=0.9, passed=True, holdout=0.03, base=s1_xrp)],
        ("SOL-USDT", "4H"): [s1_sol, _res("S1+VC", "SOL-USDT", "4H", "none", calmar=0.8, passed=True, holdout=-0.02, base=s1_sol)],
        ("BTC-USDT", "4H"): [hold_btc, s2_btc, _res("S2+TF", "BTC-USDT", "4H", "none", calmar=0.2, passed=False, base=s2_btc),
                             _res("TF", "BTC-USDT", "4H", "none", calmar=0.1, passed=False, base=hold_btc, windows=(3, 9))],
    })
    assert hold_btc["role"] == "control" and s2_btc["role"] == "reproduction" and not s2_btc["judged"]
    verdicts = {v["hypothesis"]: v for v in r2.hypothesis_verdicts(merged, cfg, stored)}
    assert verdicts["H4"]["label"] == "confirmed" and verdicts["H4"]["confirmed"] == ["S1+VC XRP-USDT 4H [none]"] and verdicts["H4"]["contradicted"] == ["S1+VC SOL-USDT 4H [none]"]
    assert verdicts["H5"]["label"] == "failed walk-forward" and verdicts["H6"]["label"] == "failed walk-forward"
    f4 = verdicts["H4"]["failure_facts"]
    assert f4["n_compared"] == 2 and f4["calmar_improved"] == 2 and f4["median_delta_calmar"] == pytest.approx((0.6 + 0.2) / 2) and f4["per_market_improved"]["XRP-USDT"]["n"] == 1
    f6 = verdicts["H6"]["failure_facts"]
    assert f6["base_candidate"] == "hold" and f6["windows_traded_total"] == 3 and f6["windows_total"] == 9 and f6["beats_base_by_0_1"] == 0
    assert verdicts["H4"]["directional"]["n"] == 2 and verdicts["H4"]["directional"]["threshold"] is None and verdicts["H4"]["pattern"]["n"] == 0
    assert len(verdicts["H5"]["contradicted_outcomes"]) >= 4 and len(verdicts["H6"]["exposure"]) == 1
    overall = r2.overall_summary(list(verdicts.values()), merged)
    assert (overall["n_judged"], overall["n_passed"], overall["n_confirmed"], overall["n_contradicted"]) == (4, 2, 1, 1)
    assert overall["binding_gates"][0][0] == "calmar_gt_0_5" and set(overall["directional"]) == {"H4", "H5", "H6"}
    openings = r2.holdout_openings(merged)
    assert [(o["configuration"], o["role"], o["confirmed"]) for o in openings] == [
        ("S1+VC XRP-USDT 4H [none]", "configuration", True), ("S1+VC SOL-USDT 4H [none]", "configuration", False), ("hold BTC-USDT 4H [none]", "control", None)]
    # Earlier looks: the comparison line's stored holdout on the same series (S1 SOL 4H [none] never opened its holdout in R12; XRP neither).
    looks = r2.earlier_looks(merged, stored)
    assert [(l["configuration"], l["earlier_configuration"], l["earlier_study"], l["earlier_opened"]) for l in looks] == [
        ("S1+VC XRP-USDT 4H [none]", "S1 XRP-USDT 4H [none]", "R12 replication", False), ("S1+VC SOL-USDT 4H [none]", "S1 SOL-USDT 4H [none]", "R12 replication", False)]
    fake_stored = [dict(s1_sol, study_source="a study", holdout={"total_return": 0.095, "profit_factor": 5.5, "n_trades": 12})]
    look = r2.earlier_looks({("SOL-USDT", "4H"): merged[("SOL-USDT", "4H")]}, fake_stored)
    assert look[0]["earlier_opened"] and look[0]["earlier_total_return"] == 0.095 and look[0]["earlier_confirmed"] is True
    path = str(tmp_path / "ledger.json")
    r2.write_round2_ledger(path, [{"generated_at": "a", "openings": openings}])
    ledger = r2.load_ledger(path)
    assert len(ledger) == 1 and ledger[0]["openings"][0]["configuration"] == "S1+VC XRP-USDT 4H [none]"
    assert r2.guard_second_look(ledger, openings, evaluate_holdout=True) == ["S1+VC SOL-USDT 4H [none]", "S1+VC XRP-USDT 4H [none]"]
    assert r2.guard_second_look(ledger, openings, evaluate_holdout=False) == []
    additions = r2.shortlist_additions(merged, source={"study": r2.STUDY_NAME, "results": "r.json"})
    assert [(a["candidate"], a["instrument"]) for a in additions] == [("S1+VC", "XRP-USDT")] and additions[0]["source"]["hypothesis"] == "H4"
    assert additions[0]["holdout_confirmed"] is True and additions[0]["passed"] is True
    # A passer whose holdout was not opened: 'holdout not opened'.
    cfg5 = r2.Round2Config(hypotheses=("H5",), timeframes=("4H",), regime_modes=("none",))
    merged2 = _merged({("BTC-USDT", "4H"): [s2_btc, _res("S2+TF", "BTC-USDT", "4H", "none", calmar=0.9, passed=True, base=s2_btc)]})
    assert r2.hypothesis_verdicts(merged2, cfg5, stored)[0]["label"] == "passed walk-forward, holdout not opened"


# -- the runner on the synthetic lake -------------------------------------------------------------------------------

def test_jobs_protocol_and_the_full_study_guard(study_lake):
    cfg = r2.Round2Config(lake_dir=str(study_lake.root))
    assert cfg.markets == list(r2.ALL_MARKETS) and len(cfg.markets) == 9
    assert r2.Round2Config(hypotheses=("H4",)).markets == list(r2.REPLICATION_MARKETS)
    assert sorted(r2.Round2Config(hypotheses=("H6",)).markets) == sorted(r2.TREND_MARKETS)  # the round's fixed order, not the hypothesis's
    jobs = r2.plan_jobs(cfg, evaluate_holdout=False)
    kinds = {k: sum(1 for j in jobs if j["kind"] == k) for k in ("reproduction", "H4", "H5", "H6")}
    assert kinds == {"reproduction": 18, "H4": 14, "H5": 10, "H6": 10} and len(jobs) == 52
    assert all(j["strategies"] == list(r2.REPRODUCTION_STRATEGIES) for j in jobs if j["kind"] == "reproduction")
    assert {j["instrument"] for j in jobs if j["kind"] == "H4"} == set(r2.REPLICATION_MARKETS) and {j["instrument"] for j in jobs if j["kind"] == "H6"} == set(r2.TREND_MARKETS)
    args = r2.round2_args(cfg, list(r2.REPRODUCTION_STRATEGIES) + ["S2+TF", "TF"], evaluate_holdout=True)
    assert args["evaluate_holdout"] and args["lake_dir"] == str(study_lake.root) and "TF" in args["strategies"]
    meta = json.loads(r2.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    check = r2.protocol_check_round2(args, meta)
    assert check["ok"], check["mismatches"]
    assert check["new_candidates"] == ["S2+TF", "TF"]
    quick = r2.protocol_check_round2(r2.round2_args(r2.Round2Config(quick=True), ["S1"], evaluate_holdout=False), meta)
    assert not quick["ok"] and "quick" in quick["mismatches"]
    assert r2.full_study_requested(r2.Round2Config())
    for bad in (r2.Round2Config(quick=True), r2.Round2Config(reproduction=False), r2.Round2Config(hypotheses=("H4", "H5")),
                r2.Round2Config(timeframes=("4H",)), r2.Round2Config(regime_modes=("none",))):
        assert not r2.full_study_requested(bad)
    assert r2.check_replication_markets() == list(r2.REPLICATION_MARKETS)


@pytest.fixture(scope="module")
def synthetic_study(study_lake, stored):
    """H5 and H6 with the full grids on one market (the slow rules need the full bracket set to trade), H4 quick on another."""
    cfg = r2.Round2Config(hypotheses=("H4", "H5", "H6"), timeframes=("4H",), regime_modes=("none",), reproduction=False, quick=False, lake_dir=str(study_lake.root))
    jobs = [j for j in r2.plan_jobs(cfg, evaluate_holdout=False) if (j["instrument"], j["kind"]) in (("BTC-USDT", "H5"), ("BTC-USDT", "H6"))]
    quick_cfg = r2.Round2Config(hypotheses=("H4",), timeframes=("4H",), regime_modes=("none",), reproduction=False, quick=True, lake_dir=str(study_lake.root))
    jobs += [j for j in r2.plan_jobs(quick_cfg, evaluate_holdout=False) if j["instrument"] == "XRP-USDT"]
    assert [(j["instrument"], j["strategies"]) for j in jobs] == [("BTC-USDT", ["S2+TF"]), ("BTC-USDT", ["TF"]), ("XRP-USDT", ["S1+VC"])]
    outputs = [r2.run_job(j) for j in jobs]
    merged = r2.merge_series(outputs)
    r2.annotate_all(merged, stored)
    return cfg, merged


def test_run_job_merge_and_annotate_on_the_synthetic_lake(synthetic_study):
    cfg, merged = synthetic_study
    assert set(merged) == {("BTC-USDT", "4H"), ("XRP-USDT", "4H")}
    for s in merged.values():
        assert not s["failures"], s["failures"]
    btc = merged[("BTC-USDT", "4H")]
    by = {r["candidate"]: r for r in btc["results"]}
    assert set(by) == {"S2+TF", "TF"} and btc["kinds"] == ["H5", "H6"] and set(btc["sleeves"]) == {"S2+TF|none", "TF|none"}
    tf, s2tf = by["TF"], by["S2+TF"]
    assert tf["hypothesis"] == "H6" and tf["role"] == "configuration" and tf["judged"] and tf["fixed_rule"] and tf["base_candidate"] == "hold"
    assert tf["comparison"]["available"] and tf["comparison"]["base_configuration"] == "hold BTC-USDT 4H [none]" and tf["comparison"]["base_study"] == "Sprint 2c"
    assert tf["selected_params"]["sma_days"] == 200.0 and tf["selected_params"]["bracket"] in ("none", "time30") and tf["robustness"]["n_neighbours"] == 2
    assert tf["oos"]["n_trades"] > 0 and tf["oos"]["windows_traded"] >= 1
    assert s2tf["hypothesis"] == "H5" and s2tf["comparison"]["base_configuration"] == "S2 BTC-USDT 4H [none]" and s2tf["oos"]["n_trades"] > 0 and not s2tf["fixed_rule"]
    vc = merged[("XRP-USDT", "4H")]["results"][0]
    assert vc["hypothesis"] == "H4" and vc["comparison"]["base_configuration"] == "S1 XRP-USDT 4H [none]" and vc["comparison"]["base_study"] == "R12 replication"
    assert all("holdout" not in r and r["holdout_confirmed"] is None for s in merged.values() for r in s["results"])


def test_verdicts_summary_and_report_on_the_synthetic_lake(synthetic_study, stored):
    cfg, merged = synthetic_study
    verdicts = r2.hypothesis_verdicts(merged, cfg, stored)
    assert [v["hypothesis"] for v in verdicts] == ["H4", "H5", "H6"]
    h4, h5, h6 = verdicts
    assert h4["n_configurations"] == 1 and h4["label"] in ("failed walk-forward", "passed walk-forward, holdout not opened") and h4["pattern"]["n"] == 0
    assert h5["n_configurations"] == 1 and len(h5["contradicted_outcomes"]) >= 4
    # The stored BTC breakout row that was contradicted ran with the regime gate; this synthetic run had no gate mode, so nothing ran on it.
    assert "S2 BTC-USDT 4H [gate]" in [o["configuration"] for o in h5["contradicted_outcomes"]] and all(not o["ran"] for o in h5["contradicted_outcomes"])
    assert h6["n_configurations"] == 1 and h6["exposure"][0]["breakout_adds"] is not None and h6["exposure"][0]["beats_hold"] is not None
    assert h6["failure_facts"]["windows_total"] > 0 and h6["directional"]["n"] == 1
    overall = r2.overall_summary(verdicts, merged)
    assert overall["n_judged"] == 3 and set(overall["labels"]) == {"H4", "H5", "H6"}
    assert r2.holdout_openings(merged) == [] and r2.earlier_looks(merged, stored) == [] and r2.shortlist_additions(merged, source={"study": "t"}) == []
    run = {"meta": {"generated_at": "2026-11-04 23:00 UTC", "elapsed_minutes": 0.1, "config": cfg.to_dict(), "preregistration": r2.PREREGISTRATION,
                    "preregistration_sha256": "abc", "preregistration_file": "p.json", "protocol_check": {"ok": True, "checked": ["fee"], "new_candidates": ["TF"]},
                    "v1c_meta": {"holdout_span": "2025-10-20->2026-10-20", "policy_sizing": {"label": "p"}, "regime": {"label": "g"}, "fee_rate": 0.001, "slippage_rate": 0.0005,
                                 "data_span_short": "x"}, "evaluate_holdout": False, "data_end": r2.DATA_END, "gates": {"calmar_min": 0.5}, "holdout_ledger": []},
           "reproduction": [], "series": [{k: v for k, v in s.items() if k not in ("sleeves", "trades", "args")} for s in merged.values()],
           "verdicts": verdicts, "overall": overall, "earlier_looks": [], "shortlist_additions": []}
    text = render_report(run)
    for heading in ("## Executive summary", "## Fixed before the first run", "### H4 —", "### H5 —", "### H6 —", "## Reproduction of the stored studies", "## H4 —",
                    "## H5 —", "## H6 —", "Directional reading (pre-registered)", "Breakout configuration (stored)", "TF configuration | TF Calmar", "**Failure analysis**",
                    "## The untouched 12 months", "## Paper-fleet shortlist", "## Owner decisions", "## Method notes and caveats"):
        assert heading in text, heading
    assert "TF BTC-USDT 4H [none]" in text and "S2+TF BTC-USDT 4H [none]" in text and "S1+VC XRP-USDT 4H [none]" in text and "skipped the reproduction" in text
    assert "**Nothing here authorizes paper, demo or live trading.**" in text


# -- the pre-registration file ---------------------------------------------------------------------------------------

def test_preregistration_file_is_written_once_and_checked(tmp_path, monkeypatch):
    path = tmp_path / "prereg.json"
    payload = r2.preregister(path, now=datetime(2026, 11, 4, 23, 0, tzinfo=timezone.utc))
    assert payload["written_at"] == "2026-11-04T23:00:00+00:00" and payload["preregistration"] == r2.PREREGISTRATION and payload["gates"]["calmar_min"] == 0.5
    assert payload["replication_markets"] == list(r2.REPLICATION_MARKETS) and payload["trend_markets"] == list(r2.TREND_MARKETS)
    loaded = r2.load_preregistration(path)
    assert loaded["sha256"] == payload["sha256"] and loaded["configuration"]["hypotheses"] == ["H4", "H5", "H6"]
    with pytest.raises(r2.Round2Error, match="already fixed"):
        r2.preregister(path)
    r2.preregister(path, force=True)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["preregistration"]["hypotheses"]["H5"]["rule"] = "a looser rule"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(r2.Round2Error, match="hash mismatch"):
        r2.load_preregistration(path)
    r2.preregister(path, force=True)
    changed = copy.deepcopy(r2.PREREGISTRATION)
    changed["hypotheses"]["H5"]["rule"] = "a looser rule"
    monkeypatch.setattr(r2, "PREREGISTRATION", changed)
    with pytest.raises(r2.Round2Error, match="differs from the registered file"):
        r2.load_preregistration(path)
    monkeypatch.undo()
    # The replication markets must be the ones the R12 pre-registration fixed.
    other = tmp_path / "r12.json"
    other.write_text(json.dumps({"chosen": ["XRP-USDT", "BCH-USDT"]}), encoding="utf-8")
    with pytest.raises(r2.Round2Error, match="differ from the R12 pre-registration"):
        r2.check_replication_markets(other)
    with pytest.raises(r2.Round2Error, match="differ from the R12 pre-registration"):
        r2.preregister(tmp_path / "p2.json", r12_path=other)
    assert r2.preregistration_hash(r2.Round2Config(), loaded) != r2.preregistration_hash(r2.Round2Config(quick=True), loaded)


def test_the_committed_preregistration_is_intact_and_matches_the_module():
    data = r2.load_preregistration(r2.PREREGISTRATION_PATH)
    assert data["preregistration"] == r2.PREREGISTRATION and data["configuration"] == r2.Round2Config().to_dict()
    assert sorted(data["preregistration"]["hypotheses"]) == ["H4", "H5", "H6"]
    assert data["replication_markets"] == json.loads(r2.R12_PREREGISTRATION.read_text(encoding="utf-8"))["chosen"]


# -- the command line --------------------------------------------------------------------------------------------------

def _cli():
    spec = importlib.util.spec_from_file_location("run_research_round_2", ROOT / "scripts" / "run_research_round_2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_shortlist_amendment_the_fleet_cannot_load_is_rolled_back(tmp_path):
    cli = _cli()
    path = tmp_path / "shortlist.json"
    original = (ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json").read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    s1 = _res("S1", "XRP-USDT", "4H", "none", calmar=0.3, passed=False)
    merged = _merged({("XRP-USDT", "4H"): [s1, _res("S1+VC", "XRP-USDT", "4H", "none", calmar=0.9, passed=True, holdout=0.03, base=s1)]})
    additions = r2.shortlist_additions(merged, source={"study": r2.STUDY_NAME, "results": "docs/research/missing_results.json"})
    note = cli._apply_shortlist_additions(path, additions)
    assert note.startswith("NOT applied") and path.read_text(encoding="utf-8") == original
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"shortlist_additions": additions, "meta": {}, "series": [], "verdicts": [], "overall": {}}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(path), "--report", "-"]) == 1
    assert path.read_text(encoding="utf-8") == original
    results.write_text(json.dumps({"shortlist_additions": []}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(path), "--report", "-"]) == 0


def test_the_cli_opens_the_holdout_only_for_the_full_preregistered_study(tmp_path, capsys):
    cli = _cli()
    prereg = tmp_path / "prereg.json"
    r2.preregister(prereg)
    common = ["--preregistration", str(prereg), "--lake-dir", str(tmp_path / "lake"), "--study-lake-dir", str(tmp_path / "study"), "--report", "-", "--json", "-"]
    for argv in (["--evaluate-holdout", "--quick"], ["--evaluate-holdout", "--hypotheses", "H4"], ["--evaluate-holdout", "--timeframes", "4H"],
                 ["--evaluate-holdout", "--regime-modes", "none"], ["--evaluate-holdout", "--skip-reproduction"], ["--evaluate-holdout", "--holdout-ledger", "-"]):
        assert cli.main(argv + common) == 2, argv
    assert cli.main(["--preregister", "--preregistration", str(prereg)]) == 2  # written once
    assert cli.main(["--quick", "--preregistration", str(tmp_path / "missing.json"), "--report", "-", "--json", "-"]) == 2
    err = capsys.readouterr().err
    assert "full pre-registered study" in err and "needs a holdout ledger" in err and "run --preregister first" in err


def test_render_from_json_rebuilds_the_report(tmp_path, stored):
    cli = _cli()
    cfg = r2.Round2Config(hypotheses=("H6",), timeframes=("4H",), regime_modes=("none",))
    hold = _res("hold", "BTC-USDT", "4H", "none", calmar=0.3, passed=False, holdout=-0.04)
    merged = _merged({("BTC-USDT", "4H"): [hold, _res("TF", "BTC-USDT", "4H", "none", calmar=0.2, passed=False, base=hold)]})
    verdicts = r2.hypothesis_verdicts(merged, cfg, stored)
    run = {"meta": {"generated_at": "2026-11-04 23:00 UTC", "config": cfg.to_dict(), "preregistration": r2.PREREGISTRATION, "preregistration_sha256": "abc",
                    "protocol_check": {"ok": True, "checked": [], "new_candidates": ["TF"]}, "v1c_meta": {}, "evaluate_holdout": True, "gates": {"calmar_min": 0.5},
                    "holdout_ledger": [{"generated_at": "2026-11-04 23:00 UTC", "openings": [{"configuration": "hold BTC-USDT 4H [none]", "role": "control", "total_return": -0.04,
                                                                                               "max_drawdown": 0.05, "profit_factor": 0.0, "n_trades": 1, "confirmed": None}]}],
                    "holdout_ledger_path": "ledger.json"},
           "reproduction": [{"candidate": "S2", "instrument": "ADA-USDT", "timeframe": "6H", "regime": "gate", "ok": True, "max_abs_difference": 0.0, "n_trades": 44,
                             "n_trades_stored": 44, "selected_matches": True, "verdict_matches": True, "reproduced": {"total_return": 0.2}, "stored": {"total_return": 0.2}}],
           "series": [{k: v for k, v in s.items() if k not in ("sleeves", "trades", "args")} for s in merged.values()], "verdicts": verdicts,
           "overall": r2.overall_summary(verdicts, merged), "earlier_looks": [{"configuration": "TF BTC-USDT 4H [none]", "earlier_configuration": "hold BTC-USDT 4H [none]",
                                                                               "earlier_study": "Sprint 2c", "earlier_opened": True, "earlier_total_return": -0.043,
                                                                               "earlier_profit_factor": 0.0, "earlier_n_trades": 1, "earlier_confirmed": None}],
           "shortlist_additions": []}
    src = tmp_path / "results.json"
    src.write_text(json.dumps(run), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cli.main(["--render-from-json", str(src), "--report", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Research round 2") and "1 of 1 reproduced" in text and "### Every opening of the holdout (ledger)" in text
    assert "H6 — the slow trend filter as the exposure rule: **failed walk-forward**" in text and "### Earlier looks at the same months" in text
    assert "| TF BTC-USDT 4H [none] | hold BTC-USDT 4H [none] | Sprint 2c | -4.3% / PF 0.00 / 1 tr |" in text


# -- the report's sentences --------------------------------------------------------------------------------------------

def _verdict(label, facts, *, n_passed=0, gates=(("calmar_gt_0_5", 2),), base="S1"):
    return {"hypothesis": "H4", "title": "t", "label": label, "candidate": "S1+VC", "base_candidate": base, "markets": [], "n_configurations": 2, "n_passed": n_passed,
            "n_confirmed": 0, "n_contradicted": 1 if label.startswith("passed") else 0, "n_unevaluated": 0, "configurations": ["a", "b"], "passed": [], "confirmed": [],
            "contradicted": [], "binding_gates": list(gates), "best": None, "failure_facts": facts,
            "directional": {"n": 2, "improved": 1, "threshold": None, "alpha": 0.05, "p_value": 0.75, "expected_by_chance": 1.0, "replicates_in_direction": False}}


def _facts(delta, *, base_cagr=0.03, var_cagr=0.02, base_dd=0.10, var_dd=0.08, base="S1"):
    return {"n": 2, "n_compared": 2, "base_candidate": base, "calmar_improved": 1, "drawdown_fell": 2, "return_fell": 1, "beats_base_by_0_1": 1, "median_delta_calmar": delta,
            "median_base_calmar": 0.3, "median_variant_calmar": 0.3 + delta, "median_base_cagr": base_cagr, "median_variant_cagr": var_cagr, "median_base_dd": base_dd,
            "median_variant_dd": var_dd, "median_base_rolling": 0.6, "median_variant_rolling": 0.65, "median_trades_removed_share": 0.4, "median_base_trades": 100,
            "median_variant_trades": 60, "median_variant_exposure": 0.45, "median_base_exposure": 1.0, "median_delta_exposure": -0.1, "median_delta_fees": -0.004,
            "median_2022_base": -0.03, "median_2022_variant": -0.01, "windows_traded_total": 15, "windows_total": 18,
            "by_mode": {"none": {"calmar_improved": 1, "n": 1}, "gate": {"calmar_improved": 0, "n": 1}}, "by_timeframe": {"4H": {"calmar_improved": 1, "n": 2}},
            "per_market_improved": {"XRP-USDT": {"calmar_improved": 1, "n": 1}, "SOL-USDT": {"calmar_improved": 0, "n": 1}}}


def test_failure_analysis_readings_follow_the_deltas():
    worse = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(-0.2, base_cagr=0.04, var_cagr=0.01, base_dd=0.10, var_dd=0.09))))
    assert "removed good entries along with bad ones" in worse and "the return fell by 75% of itself" in worse and "By market: SOL-USDT 0 of 1; XRP-USDT 1 of 1" in worse
    same = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(0.01))))
    assert "changed little" in same and "With the HMM regime gate already on" in same and "removed a median 40%" in same
    better = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(0.2))))
    assert "the condition helped" in better and "Calmar above 0.5 (2 of 2)" in better
    contradicted = "\n".join(failure_analysis(_verdict("passed walk-forward, contradicted by the holdout", _facts(0.2), n_passed=1)))
    assert "did not carry into the untouched 12 months" in contradicted
    exposure = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(0.01, base="hold"), base="hold")))
    assert "beside hold + policy sizing" in exposure and "in the market 45% of the time against 100%" in exposure and "trade in 15 of 18 walk-forward windows" in exposure
    assert "the sizing's crash filter already does most" in exposure
    assert "made the risk-managed exposure worse" in "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(-0.2, base="hold"), base="hold")))
    assert "improved the risk-managed exposure" in "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(0.2, base="hold"), base="hold")))
    # A rule the protocol's 20-train-trade qualification left flat in most windows is untested, not refuted, whatever its deltas say.
    rare = _facts(-0.3, base="hold")
    rare.update({"windows_traded_total": 13, "windows_total": 180})
    text = "\n".join(failure_analysis(_verdict("failed walk-forward", rare, base="hold")))
    assert "traded too rarely for the protocol" in text and "In 167 of 180 windows no bracket variant reached" in text and "untested here, not refuted" in text
    assert "made the risk-managed exposure worse" not in text and "trade in 13 of 180 walk-forward windows" in text
    rare_condition = _facts(-0.3)
    rare_condition.update({"windows_traded_total": 53, "windows_total": 180})
    text = "\n".join(failure_analysis(_verdict("failed walk-forward", rare_condition)))
    assert "removed so many entries" in text and "in 127 of 180 windows no variant reached" in text and "untested by this protocol rather than refuted" in text
    assert "removed good entries along with bad ones" not in text


def test_executive_summary_states_each_verdict_the_readings_and_the_fleet_outcome():
    v = _verdict("failed walk-forward", _facts(0.01))
    v["best"] = {"configuration": "S1+VC XRP-USDT 4H [none]", "calmar": 0.31, "cagr": 0.02, "max_drawdown": 0.08, "failed": ["calmar_gt_0_5"]}
    v["directional"] = {"n": 28, "improved": 20, "threshold": 19, "alpha": 0.05, "p_value": 0.018, "expected_by_chance": 14.0, "replicates_in_direction": True}
    v["pattern"] = {"n": 7, "improved": 3, "min_markets": 5, "consistent_with_round_1": False, "markets_improved": ["XRP-USDT"]}
    run = {"meta": {"evaluate_holdout": True, "v1c_meta": {"holdout_span": "2025-10-20->2026-10-20", "data_span_short": "x"}},
           "reproduction": [{"ok": True}] * 90, "series": [], "verdicts": [v],
           "overall": {"n_judged": 2, "n_passed": 0, "binding_gates": [("calmar_gt_0_5", 2)], "labels": {"H4": "failed walk-forward"}}, "shortlist_additions": []}
    s = "\n".join(executive_summary(run))
    assert "matched the stored numbers" in s and "90 of 90" in s and "**H4 — t: failed walk-forward.** 0 of 2 configurations passed every gate." in s
    assert "Best: S1+VC XRP-USDT 4H [none] with Calmar 0.31" in s and "raised Calmar in 1 of 2 configurations (median 0.30 → 0.31)" in s
    assert "Directional reading: replicates in direction (20 of 28; the 5% level needs 19)" in s and "not consistent here: Calmar rose in 3 of 7" in s
    assert "Nothing passed walk-forward" in s and "Nothing was confirmed, so the fleet's shortlist is unchanged" in s
    assert "untested here rather than refuted" not in s  # 15 of 18 windows traded: the selection rule did not bind
    v["failure_facts"].update({"windows_traded_total": 13, "windows_total": 180})
    assert "let it trade in only 13 of 180 walk-forward windows" in "\n".join(executive_summary(run))
    run["shortlist_additions"] = [{"candidate": "S2+TF", "instrument": "ADA-USDT", "timeframe": "6H"}]
    run["shortlist_note"] = "docs/research/paper_fleet_shortlist_v1c.json now lists 14 configurations (24 fleet accounts)"
    s2 = "\n".join(executive_summary(run))
    assert "1 confirmed configuration(s) were appended" in s2 and "S2+TF ADA-USDT 6H" in s2 and "24 fleet accounts" in s2
