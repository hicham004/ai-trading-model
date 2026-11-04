"""Research round 1 (plan row R13): the three pre-registered rules and the cross-asset context, the patched Sprint 2c runner,
the H3 combination and its holdout, the verdict rules, the pre-registration file, the ledger, the shortlist additions, the report
and the command line. Everything runs offline on synthetic candles."""

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
from research import round1 as r1
from research.data import bars_per_year, load_or_resample_candles, split_holdout
from research.gated_walkforward import regimes_for_windows
from research.report_round1 import executive_summary, failure_analysis, render_report
from research.strategies import ALL_KEYS, CANDIDATES, ROUND1_BASES, get_candidate
from research.strategies.base import FeatureContext
from research.strategies.round1 import CrossAssetContext, DualMomentumLeg, ReferenceTrendGated, VolumeConfirmed, reference_trend_up
from research.strategies.s1_tsmom import TimeSeriesMomentum
from research.walkforward import make_windows

ROOT = Path(__file__).resolve().parents[1]
N = 7600


# -- synthetic candles -------------------------------------------------------------------------------------

def _frame(seed: int, drift: np.ndarray, *, n: int = N, freq: str = "4h", start: str = "2021-01-01", volume_seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC", name="open_time")
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.012, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = np.random.default_rng(volume_seed + seed).lognormal(3, 0.5, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _pair(n: int = N):
    """Two correlated markets with a trend flip about every 9 days, so the trend rules qualify in every train window."""
    regime = np.sign(np.sin(np.arange(n) / 60.0))
    common = 0.004 * regime
    btc = _frame(1, common, n=n)
    eth = _frame(2, common + 0.001 * np.sign(np.sin(np.arange(n) / 300.0)), n=n)
    return btc, eth


def _ctx(instrument: str, references: dict, timeframe: str = "4H") -> CrossAssetContext:
    return CrossAssetContext(timeframe=timeframe, periods_per_year=bars_per_year(timeframe), instrument=instrument, references=references)


def _write(layout: LakeLayout, inst: str, df: pd.DataFrame, bar: str = "4H") -> None:
    n = len(df)
    table = pa.table({
        "open_time": pa.array([t.to_pydatetime() for t in df.index], type=TS_TYPE), "instrument": pa.array([inst] * n), "timeframe": pa.array([bar] * n),
        "open": pa.array(df["open"].to_numpy()), "high": pa.array(df["high"].to_numpy()), "low": pa.array(df["low"].to_numpy()),
        "close": pa.array(df["close"].to_numpy()), "volume": pa.array(df["volume"].to_numpy()), "confirmed": pa.array([True] * n),
    }, schema=CANDLE_SCHEMA)
    write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file(inst, bar, y))


@pytest.fixture(scope="module")
def pair_lake(tmp_path_factory):
    layout = LakeLayout(tmp_path_factory.mktemp("r13_lake") / "lake")
    btc, eth = _pair()
    _write(layout, "BTC-USDT", btc)
    _write(layout, "ETH-USDT", eth)
    return layout


def _entries_only(out: pd.Series, base: pd.Series, ok: pd.Series) -> None:
    """``out`` is the entries-only gate of ``base`` by ``ok``: a subset of base, and every new run starts on an allowed bar."""
    o, b, k = out.to_numpy(dtype=bool), base.to_numpy(dtype=bool), ok.to_numpy(dtype=bool)
    assert not (o & ~b).any()
    starts = o & ~np.concatenate([[False], o[:-1]])
    assert k[starts].all()
    # inside a desired run the position persists once entered, even when ok turns off
    assert ((o[1:] | ~(o[:-1] & b[1:]))).all()


# -- the rules -------------------------------------------------------------------------------------------------

def test_round1_candidates_are_registered_with_their_base_grids_and_fixed_conditions():
    for key, base_key in ROUND1_BASES.items():
        assert key in CANDIDATES and key in ALL_KEYS
        c, base = get_candidate(key), get_candidate(base_key)
        assert c.grid == base.grid and c.default_params == base.default_params, key
    assert isinstance(CANDIDATES["S1+BT"], ReferenceTrendGated) and CANDIDATES["S1+BT"].reference == "BTC-USDT"
    assert isinstance(CANDIDATES["S2+BT"], ReferenceTrendGated) and CANDIDATES["S2+BT"].base.key == "S2"
    assert isinstance(CANDIDATES["S1+VC"], VolumeConfirmed) and (CANDIDATES["S1+VC"].z_days, CANDIDATES["S1+VC"].z_min) == (30.0, 1.0)
    assert isinstance(CANDIDATES["DM-BTC"], DualMomentumLeg) and CANDIDATES["DM-BTC"].tie_wins and CANDIDATES["DM-BTC"].own == "BTC-USDT"
    assert isinstance(CANDIDATES["DM-ETH"], DualMomentumLeg) and not CANDIDATES["DM-ETH"].tie_wins and CANDIDATES["DM-ETH"].other == "BTC-USDT"
    assert CANDIDATES["DM-BTC"].lookback_days == 90.0
    # The Sprint 2c runner gives the new keys the none/gate modes and the full bracket set, like S1 and S2.
    v1c = r1.load_v1c_runner()
    for key in ROUND1_BASES:
        assert v1c.modes_for(key, ["none", "gate", "scale"]) == ["none", "gate"]
        assert v1c._brackets_for(argparse.Namespace(quick=False, brackets=v1c.DEFAULT_BRACKETS), key) == v1c.DEFAULT_BRACKETS


def test_reference_trend_gate_blocks_entries_only_and_fails_closed():
    btc, eth = _pair(3000)
    ctx = _ctx("ETH-USDT", {"BTC-USDT": btc})
    c = get_candidate("S1+BT")
    out = c.build(eth, c.default_params, ctx)
    base = c.base.build(eth, c.default_params, ctx)
    ok = reference_trend_up(ctx, "BTC-USDT", eth.index)
    assert ok.any() and not ok.all()
    _entries_only(out.desired, base.desired, ok)
    assert out.stop_distance.equals(base.stop_distance) and out.strength[~out.desired].isna().all()
    # A reference that always trends up changes nothing; one that never does blocks every entry.
    up = btc.copy()
    up["close"] = np.linspace(100, 400, len(up))
    up["open"], up["high"], up["low"] = up["close"].shift(1).fillna(100), up["close"] * 1.001, up["close"].shift(1).fillna(100) * 0.999
    assert c.build(eth, c.default_params, _ctx("ETH-USDT", {"BTC-USDT": up})).desired.equals(base.desired)
    down = up.copy()
    down["close"] = np.linspace(400, 100, len(down))
    down["open"], down["high"], down["low"] = down["close"].shift(1).fillna(400), down["close"].shift(1).fillna(400) * 1.001, down["close"] * 0.999
    assert not c.build(eth, c.default_params, _ctx("ETH-USDT", {"BTC-USDT": down})).desired.any()
    # Missing reference bars fail closed; a context without the reference raises.
    holes = btc.iloc[::2]
    gated = c.build(eth, c.default_params, _ctx("ETH-USDT", {"BTC-USDT": holes}))
    assert gated.desired.sum() <= out.desired.sum()
    with pytest.raises(ValueError, match="carries no BTC-USDT candles"):
        c.build(eth, c.default_params, FeatureContext(timeframe="4H", periods_per_year=bars_per_year("4H")))
    # A sub-index (the adapter hands the holdout slice only) aligns by timestamp.
    sub = eth.iloc[2000:]
    part = c.build(sub, c.default_params, ctx)
    assert part.desired.index.equals(sub.index)


def test_volume_confirmation_allows_entries_only_on_high_volume_bars():
    btc, eth = _pair(3000)
    ctx = _ctx("BTC-USDT", {"ETH-USDT": eth})
    c = get_candidate("S1+VC")
    out = c.build(btc, c.default_params, ctx)
    base = c.base.build(btc, c.default_params, ctx)
    ok = c.volume_ok(btc, ctx)
    assert 0.0 < ok.mean() < 0.5
    _entries_only(out.desired, base.desired, ok)
    flat = btc.copy()
    flat["volume"] = 5.0  # a constant volume has no z-score: no entry is ever confirmed
    assert not c.build(flat, c.default_params, ctx).desired.any()


def test_dual_momentum_legs_are_mutually_exclusive_and_bound_to_their_market():
    btc, eth = _pair(3000)
    ctx_b, ctx_e = _ctx("BTC-USDT", {"ETH-USDT": eth}), _ctx("ETH-USDT", {"BTC-USDT": btc})
    lb, le = get_candidate("DM-BTC"), get_candidate("DM-ETH")
    for params in (lb.default_params, dict(lb.default_params, lookbacks_days=(30, 60, 90), vote=3)):
        fb, fe = lb.build(btc, params, ctx_b), le.build(eth, params, ctx_e)
        assert fb.desired.any() and fe.desired.any()
        assert not (fb.desired & fe.desired).any()
        s1 = TimeSeriesMomentum()
        up_b, up_e = s1.build(btc, params, ctx_b).desired, s1.build(eth, params, ctx_e).desired
        assert not (fb.desired & ~(up_b & up_e)).any() and not (fe.desired & ~(up_b & up_e)).any()
        assert fb.stop_distance.equals(s1.build(btc, params, ctx_b).stop_distance)
    # Different parameters per leg keep the legs exclusive (the relative-strength comparison does not depend on them).
    fb = lb.build(btc, dict(lb.default_params, vote=1), ctx_b)
    fe = le.build(eth, dict(le.default_params, vote=3), ctx_e)
    assert not (fb.desired & fe.desired).any()
    # An exact tie goes to BTC: identical markets -> the ETH leg never enters.
    same = _ctx("ETH-USDT", {"BTC-USDT": btc})
    assert not le.build(btc, le.default_params, same).desired.any() and lb.build(btc, lb.default_params, _ctx("BTC-USDT", {"ETH-USDT": btc})).desired.any()
    with pytest.raises(ValueError, match="must run on BTC-USDT"):
        lb.build(eth, lb.default_params, ctx_e)


def test_cross_asset_context_leaves_the_sprint_2c_rules_unchanged():
    btc, eth = _pair(3000)
    plain = FeatureContext(timeframe="4H", periods_per_year=bars_per_year("4H"))
    cross = _ctx("ETH-USDT", {"BTC-USDT": btc})
    for key in ("hold", "S1", "S2", "S1+S5"):
        c = get_candidate(key)
        a, b = c.build(eth, c.default_params, plain), c.build(eth, c.default_params, cross)
        assert a.desired.equals(b.desired) and a.stop_distance.equals(b.stop_distance) and a.strength.equals(b.strength), key


# -- the patched runner and its context ----------------------------------------------------------------------------

def test_patched_runner_carries_the_other_market_and_keeps_the_sprint_2c_protocol(pair_lake):
    ctx = r1.cross_asset_positioning_context(pair_lake, "ETH-USDT", "4H")
    assert isinstance(ctx, CrossAssetContext) and ctx.instrument == "ETH-USDT" and set(ctx.references) == {"BTC-USDT"}
    assert len(ctx.references["BTC-USDT"]) == N and ctx.funding is None and ctx.open_interest is None
    assert r1.cross_asset_positioning_context(pair_lake, "ETH-USDT", "4H").references["BTC-USDT"] is ctx.references["BTC-USDT"]  # cached per process
    v1c = r1.patched_runner()
    assert v1c.positioning_context is r1.cross_asset_positioning_context and r1.patched_runner() is v1c
    assert hasattr(v1c, "_round1_original_positioning_context")
    cfg = r1.Round1Config(lake_dir=str(pair_lake.root))
    args = r1.round1_args(cfg, list(r1.REPRODUCTION_STRATEGIES) + ["S1+VC", "DM-BTC"], evaluate_holdout=True)
    assert args["evaluate_holdout"] and args["lake_dir"] == str(pair_lake.root) and "DM-BTC" in args["strategies"]
    meta = json.loads(r1.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    check = r1.protocol_check_round1(args, meta)
    assert check["ok"], check["mismatches"]
    assert check["new_candidates"] == ["S1+VC", "DM-BTC"]
    quick = r1.protocol_check_round1(r1.round1_args(r1.Round1Config(quick=True), ["S1"], evaluate_holdout=False), meta)
    assert not quick["ok"] and "quick" in quick["mismatches"]
    jobs = r1.plan_jobs(r1.Round1Config(), evaluate_holdout=False)
    assert len(jobs) == 16 and sum(1 for j in jobs if j["kind"] == "reproduction") == 4
    assert {(j["instrument"], j["strategies"][0]) for j in jobs if j["kind"] == "H1"} == {("ETH-USDT", "S1+BT"), ("ETH-USDT", "S2+BT")}
    assert all(j["strategies"] == list(r1.REPRODUCTION_STRATEGIES) for j in jobs if j["kind"] == "reproduction")
    assert r1.full_study_requested(r1.Round1Config())
    for bad in (r1.Round1Config(quick=True), r1.Round1Config(reproduction=False), r1.Round1Config(hypotheses=("H1",)),
                r1.Round1Config(timeframes=("4H",)), r1.Round1Config(regime_modes=("none",))):
        assert not r1.full_study_requested(bad)


# -- H3: the combination and its holdout ------------------------------------------------------------------------------

def test_combined_returns_are_the_product_of_the_legs_and_refuse_misaligned_legs():
    idx = pd.date_range("2022-01-01", periods=6, freq="4h", tz="UTC")
    r_b = pd.Series([0.01, 0.0, 0.0, -0.02, 0.0, 0.0], index=idx)
    r_e = pd.Series([0.0, 0.03, 0.0, 0.0, 0.01, 0.0], index=idx)
    rc = r1.combined_returns(r_b, r_e)
    assert rc.tolist() == pytest.approx([0.01, 0.03, 0.0, -0.02, 0.01, 0.0])
    with pytest.raises(r1.Round1Error):
        r1.combined_returns(r_b, r_e.iloc[:-1])
    with pytest.raises(r1.Round1Error):
        r1.combined_returns(r_b, r_e.shift(freq="4h"))


def _leg(key, inst, tf, mode, *, share, n_trials=10, exp_sr=0.01):
    return {"candidate": key, "instrument": inst, "timeframe": tf, "regime": {"mode": mode, "label": mode}, "selected_params": {"vote": 2, "bracket": "none"},
            "configuration": f"{key} {inst} {tf} [{mode}]", "oos": {"exposure": 0.2, "avg_allocation": 0.05, "traded_bars_share": 1.0, "windows": 5, "windows_traded": 5,
                                                                      "gate_blocked_share": 0.0},
            "robustness": {"share_above_threshold": share, "n_neighbours": 7}, "dsr": {"n_trials": n_trials, "expected_max_sr": exp_sr}, "policy_sizing": {"label": "p"}}


def test_combine_legs_builds_a_judged_result_with_pooled_trades_and_the_smaller_robustness_share():
    n = 2200
    idx = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    rng = np.random.default_rng(5)
    r_b = pd.Series(np.where(np.arange(n) % 2 == 0, rng.normal(0.0005, 0.004, n), 0.0), index=idx)
    r_e = pd.Series(np.where(np.arange(n) % 2 == 1, rng.normal(0.0005, 0.004, n), 0.0), index=idx)
    t_b = pd.DataFrame({"pnl": [10.0, -4.0], "entry_price": [1.0, 1.0], "exit_price": [1.1, 0.9], "quantity": [1.0, 1.0], "fees": [0.1, 0.1], "bars_held": [3, 2]})
    t_e = pd.DataFrame({"pnl": [6.0], "entry_price": [1.0], "exit_price": [1.1], "quantity": [1.0], "fees": [0.1], "bars_held": [4]})
    legs = (_leg("DM-BTC", "BTC-USDT", "4H", "none", share=0.9), _leg("DM-ETH", "ETH-USDT", "4H", "none", share=0.4, exp_sr=0.02))
    c = r1.combine_legs(legs[0], legs[1], r_b, r_e, t_b, t_e, bars_per_year("4H"), timeframe="4H", mode="none")
    assert c["candidate"] == "DM" and c["instrument"] == "BTC+ETH" and c["judged"] and c["hypothesis"] == "H3" and c["configuration"] == "DM BTC+ETH 4H [none]"
    assert c["oos"]["n_trades"] == 3 and c["oos"]["profit_factor"] == pytest.approx(16.0 / 4.0)
    assert c["oos"]["exposure"] == pytest.approx(0.4) and c["robustness"]["share_above_threshold"] == 0.4 and c["robustness"]["n_neighbours"] == 14
    assert c["dsr"]["expected_max_sr"] == 0.02 and c["dsr"]["n_trials"] == 20 and 0.0 <= c["dsr"]["dsr"] <= 1.0
    expected_total = float(np.prod(1.0 + r1.combined_returns(r_b, r_e)) - 1.0)
    assert c["oos"]["total_return"] == pytest.approx(expected_total)
    assert set(c["acceptance"]) >= {"passed", "failed", "robust_pm30pct"} and c["acceptance"]["robust_pm30pct"] is False
    assert c["legs"] == ["DM-BTC BTC-USDT 4H [none]", "DM-ETH ETH-USDT 4H [none]"] and c["holdout_confirmed"] is None
    assert set(c["yearly"]) == {2022, 2023}


def _candidate_run(v1c, layout, instrument, timeframe, key, mode, *, evaluate_holdout):
    cfg = r1.Round1Config(timeframes=(timeframe,), regime_modes=(mode,), quick=True, lake_dir=str(layout.root))
    args = argparse.Namespace(**r1.round1_args(cfg, [key], evaluate_holdout=evaluate_holdout))
    df_all = load_or_resample_candles(layout, instrument, timeframe)
    df_in, _ = split_holdout(df_all, holdout_months=args.holdout_months)
    ppy = bars_per_year(timeframe)
    windows = make_windows(len(df_in), v1c._wf_config(args, timeframe))
    regimes = regimes_for_windows(df_in, windows, v1c._regime_cfg(args, mode), timeframe, ppy)
    costs = v1c.Costs(fee_rate=args.fee, slippage_rate=args.slippage)
    res, stitched, _, trades = v1c.run_candidate(args, layout, df_all, instrument, timeframe, key, mode, costs, regimes)
    return vars(args), df_all, res, stitched, trades


@pytest.mark.parametrize("mode", ["none", "gate"])
def test_leg_holdout_matches_the_sprint_2c_runners_own_holdout(pair_lake, monkeypatch, mode):
    """The study's holdout simulation of a leg is the runner's holdout code path: same return, drawdown and trades."""
    v1c = r1.patched_runner()
    args, df_all, res, _, _ = _candidate_run(v1c, pair_lake, "BTC-USDT", "4H", "hold", mode, evaluate_holdout=True)
    assert res.get("holdout"), "the hold control's holdout is always evaluated"
    returns, trades, metrics = r1.leg_holdout(args, pair_lake, df_all, "BTC-USDT", "4H", "hold", mode, res["selected_params"])
    for k in ("total_return", "max_drawdown", "n_trades", "avg_allocation", "sharpe"):
        assert metrics[k] == pytest.approx(res["holdout"][k], abs=1e-9), k
    assert len(returns) == len(split_holdout(df_all, holdout_months=args["holdout_months"])[1])
    assert float(np.prod(1.0 + returns) - 1.0) == pytest.approx(metrics["total_return"], abs=1e-9)
    # A rule with a stop and a bracket grid: force the acceptance to pass so the runner opens its holdout, then compare.
    monkeypatch.setattr(v1c, "acceptance_check_v1c", lambda oos, yearly, robust: {"passed": True, "failed": [], "rolling_positive_share": 1.0, "worst_calendar_year_return": 0.0})
    args, df_all, res, _, _ = _candidate_run(v1c, pair_lake, "ETH-USDT", "4H", "DM-ETH", mode, evaluate_holdout=True)
    assert res.get("holdout")
    returns, trades, metrics = r1.leg_holdout(args, pair_lake, df_all, "ETH-USDT", "4H", "DM-ETH", mode, res["selected_params"])
    for k in ("total_return", "max_drawdown", "n_trades", "profit_factor"):
        assert metrics[k] == pytest.approx(res["holdout"][k], abs=1e-9), k
    assert int(metrics["n_trades"]) == len(trades)


# -- an end-to-end quick study on the synthetic lake ------------------------------------------------------------------

@pytest.fixture(scope="module")
def quick_study(pair_lake):
    cfg = r1.Round1Config(hypotheses=("H2", "H3"), timeframes=("4H",), regime_modes=("none",), reproduction=False, quick=True, lake_dir=str(pair_lake.root))
    jobs = r1.plan_jobs(cfg, evaluate_holdout=False)
    assert [(j["instrument"], j["strategies"]) for j in jobs] == [("BTC-USDT", ["S1+VC"]), ("BTC-USDT", ["DM-BTC"]), ("ETH-USDT", ["S1+VC"]), ("ETH-USDT", ["DM-ETH"])]
    outputs = [r1.run_job(j) for j in jobs]
    merged = r1.merge_series(outputs)
    stored = json.loads(r1.V1C_RESULTS.read_text(encoding="utf-8"))["results"]
    r1.annotate_all(merged, stored)
    combined = r1.build_combined_results(merged, cfg, evaluate_holdout=False, layout=pair_lake)
    return cfg, merged, combined


def test_run_job_merge_annotate_and_combine_on_the_synthetic_lake(quick_study):
    cfg, merged, combined = quick_study
    assert set(merged) == {("BTC-USDT", "4H"), ("ETH-USDT", "4H")}
    btc = merged[("BTC-USDT", "4H")]
    assert {r["candidate"] for r in btc["results"]} == {"S1+VC", "DM-BTC"} and btc["kinds"] == ["H2", "H3"] and btc["benchmark"]["instrument"] == "BTC-USDT"
    assert set(btc["sleeves"]) == {"S1+VC|none", "DM-BTC|none"} and set(btc["trades"]) == {"S1+VC|none", "DM-BTC|none"}
    by = {r["configuration"]: r for r in btc["results"]}
    vc, leg = by["S1+VC BTC-USDT 4H [none]"], by["DM-BTC BTC-USDT 4H [none]"]
    assert vc["hypothesis"] == "H2" and vc["role"] == "configuration" and vc["judged"] and vc["base_candidate"] == "S1"
    assert vc["comparison"]["available"] and vc["comparison"]["base_configuration"] == "S1 BTC-USDT 4H [none]"  # from the stored Sprint 2c run
    assert set(vc["comparison"]["delta"]) >= {"calmar", "n_trades", "exposure"} and "2022" in vc["comparison"]["yearly"]
    assert leg["hypothesis"] == "H3" and leg["role"] == "leg" and not leg["judged"]
    assert all("holdout" not in r and r["holdout_confirmed"] is None for r in btc["results"])
    assert len(combined) == 1 and combined[0]["configuration"] == "DM BTC+ETH 4H [none]" and combined[0]["judged"] and "holdout" not in combined[0]
    assert combined[0]["oos"]["n_trades"] == leg["oos"]["n_trades"] + merged[("ETH-USDT", "4H")]["results"][1]["oos"]["n_trades"]
    verdicts = r1.hypothesis_verdicts(merged, combined, cfg)
    assert [v["hypothesis"] for v in verdicts] == ["H2", "H3"]
    h2, h3 = verdicts
    assert h2["n_configurations"] == 2 and h2["label"] in ("failed walk-forward", "passed walk-forward, holdout not opened")
    assert h2["failure_facts"]["n_compared"] == 2 and h2["failure_facts"]["median_base_calmar"] is not None
    assert h3["combined"] and h3["n_configurations"] == 1 and len(h3["failure_facts"]["comparisons"]) == 1 and len(h3["failure_facts"]["legs"]) == 2
    overall = r1.overall_summary(verdicts, merged, combined)
    assert overall["n_judged"] == 3 and set(overall["labels"]) == {"H2", "H3"}
    assert r1.holdout_openings(merged, combined) == []
    assert r1.shortlist_additions(merged, combined, source={"study": "t"}) == []
    v1c = r1.patched_runner()
    for s in merged.values():
        assert not s["failures"], s["failures"]
    assert v1c.positioning_context is r1.cross_asset_positioning_context


def test_the_quick_study_renders_a_report_whose_sentences_follow_the_numbers(quick_study, tmp_path):
    cfg, merged, combined = quick_study
    verdicts = r1.hypothesis_verdicts(merged, combined, cfg)
    run = {"meta": {"generated_at": "2026-11-04 20:00 UTC", "elapsed_minutes": 0.1, "config": cfg.to_dict(), "preregistration": r1.PREREGISTRATION,
                    "preregistration_sha256": "abc", "preregistration_file": "p.json", "protocol_check": {"ok": True, "checked": ["fee"], "new_candidates": ["S1+VC"]},
                    "v1c_meta": {"holdout_span": "2025-10-20->2026-10-20", "policy_sizing": {"label": "p"}, "regime": {"label": "g"}, "fee_rate": 0.001, "slippage_rate": 0.0005,
                                 "data_span_short": "x"}, "evaluate_holdout": False, "data_end": r1.DATA_END, "gates": {"calmar_min": 0.5}, "holdout_ledger": []},
           "reproduction": [], "series": [{k: v for k, v in s.items() if k not in ("sleeves", "trades", "args")} for s in merged.values()],
           "combined": combined, "verdicts": verdicts, "overall": r1.overall_summary(verdicts, merged, combined), "shortlist_additions": []}
    text = render_report(run)
    for heading in ("## Executive summary", "## Fixed before the first run", "### H2 —", "### H3 —", "## Reproduction of Sprint 2c", "## H2 —", "## H3 —",
                    "The legs on their own", "**Failure analysis**", "## The untouched 12 months", "## Paper-fleet shortlist", "## Owner decisions", "## Method notes and caveats"):
        assert heading in text, heading
    assert "DM BTC+ETH 4H [none]" in text and "S1+VC BTC-USDT 4H [none]" in text and "skipped the BTC/ETH reproduction" in text
    assert "**Nothing here authorizes paper, demo or live trading.**" in text


# -- the pre-registration file, the ledger, the shortlist -------------------------------------------------------------------

def test_preregistration_file_is_written_once_and_checked(tmp_path, monkeypatch):
    path = tmp_path / "prereg.json"
    payload = r1.preregister(path, now=datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc))
    assert payload["written_at"] == "2026-11-04T18:00:00+00:00" and payload["preregistration"] == r1.PREREGISTRATION and payload["gates"]["calmar_min"] == 0.5
    loaded = r1.load_preregistration(path)
    assert loaded["sha256"] == payload["sha256"] and loaded["configuration"]["hypotheses"] == ["H1", "H2", "H3"]
    with pytest.raises(r1.Round1Error, match="already fixed"):
        r1.preregister(path)
    r1.preregister(path, force=True)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["preregistration"]["hypotheses"]["H2"]["rule"] = "a looser rule"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(r1.Round1Error, match="hash mismatch"):
        r1.load_preregistration(path)
    # The text in the module may not drift from the registered file either.
    r1.preregister(path, force=True)
    changed = copy.deepcopy(r1.PREREGISTRATION)
    changed["hypotheses"]["H2"]["rule"] = "a looser rule"
    monkeypatch.setattr(r1, "PREREGISTRATION", changed)
    with pytest.raises(r1.Round1Error, match="differs from the registered file"):
        r1.load_preregistration(path)
    assert r1.preregistration_hash(r1.Round1Config(), loaded) != r1.preregistration_hash(r1.Round1Config(quick=True), loaded)


def test_the_committed_preregistration_is_intact_and_matches_the_module():
    data = r1.load_preregistration(r1.PREREGISTRATION_PATH)
    assert data["preregistration"] == r1.PREREGISTRATION and data["configuration"] == r1.Round1Config().to_dict()
    assert sorted(data["preregistration"]["hypotheses"]) == ["H1", "H2", "H3"]


def _res(cand, inst, tf, mode, *, calmar, passed, holdout=None, base=None, n_trades=60):
    r = {"candidate": cand, "instrument": inst, "timeframe": tf, "regime": {"mode": mode, "label": mode}, "selected_params": {"bracket": "none"},
         "oos": {"calmar": calmar, "cagr": calmar / 10, "max_drawdown": 0.1, "profit_factor": 1.1 + calmar, "sharpe": calmar, "n_trades": n_trades, "total_return": 0.1,
                 "trades_per_year": n_trades / 4.0, "exposure": 0.5, "avg_allocation": 0.06, "fees_pct_per_year": 0.01, "win_rate": 0.4},
         "acceptance": {"passed": passed, "failed": [] if passed else ["calmar_gt_0_5", "sharpe_gt_0_7"], "rolling_positive_share": 0.7, "worst_calendar_year_return": -0.05},
         "robustness": {"share_above_threshold": 0.8}, "dsr": {"dsr": 0.1}, "policy_sizing": {"label": "p"}, "yearly": {"2022": -0.02, "2023": 0.05}}
    if holdout is not None:
        r["holdout"] = {"total_return": holdout, "profit_factor": 1.5 if holdout > 0 else 0.5, "n_trades": 20, "max_drawdown": 0.05}
    return r1.annotate_result(r, base)


def _merged(results_by_series):
    out = {}
    for (inst, tf), results in results_by_series.items():
        out[(inst, tf)] = {"instrument": inst, "timeframe": tf, "results": results, "failures": [], "benchmark": {}, "span": f"{inst} {tf}", "holdout_span": "2025-10-20->2026-10-20",
                           "positioning": {}, "s0_blocked_share": 0.0, "skipped": None, "sleeves": {}, "trades": {}, "kinds": [], "args": {}}
    return out


def test_verdict_labels_failure_facts_openings_and_shortlist_rows_follow_the_preregistered_rules(tmp_path):
    cfg = r1.Round1Config(hypotheses=("H1", "H2"), timeframes=("4H",), regime_modes=("none",))
    s1_eth = _res("S1", "ETH-USDT", "4H", "none", calmar=0.3, passed=False)
    s2_eth = _res("S2", "ETH-USDT", "4H", "none", calmar=0.4, passed=False)
    s1_btc = _res("S1", "BTC-USDT", "4H", "none", calmar=0.25, passed=False)
    hold = _res("hold", "BTC-USDT", "4H", "none", calmar=0.3, passed=False, holdout=-0.04)
    merged = _merged({
        ("ETH-USDT", "4H"): [s1_eth, s2_eth, _res("S1+BT", "ETH-USDT", "4H", "none", calmar=0.9, passed=True, holdout=0.03, base=s1_eth),
                             _res("S2+BT", "ETH-USDT", "4H", "none", calmar=0.2, passed=False, base=s2_eth),
                             _res("S1+VC", "ETH-USDT", "4H", "none", calmar=0.8, passed=True, holdout=-0.02, base=s1_eth)],
        ("BTC-USDT", "4H"): [hold, s1_btc, _res("S1+VC", "BTC-USDT", "4H", "none", calmar=0.1, passed=False, base=s1_btc)],
    })
    assert hold["role"] == "control" and s1_eth["role"] == "reproduction" and not s1_eth["judged"]
    verdicts = {v["hypothesis"]: v for v in r1.hypothesis_verdicts(merged, [], cfg)}
    assert verdicts["H1"]["label"] == "confirmed" and verdicts["H1"]["confirmed"] == ["S1+BT ETH-USDT 4H [none]"] and verdicts["H1"]["n_configurations"] == 2
    assert verdicts["H2"]["label"] == "passed walk-forward, contradicted by the holdout" and verdicts["H2"]["contradicted"] == ["S1+VC ETH-USDT 4H [none]"]
    f = verdicts["H2"]["failure_facts"]
    assert f["n_compared"] == 2 and f["calmar_improved"] == 1 and f["median_delta_calmar"] == pytest.approx((0.5 - 0.15) / 2)
    assert f["median_2022_base"] == pytest.approx(-0.02) and f["by_mode"]["none"]["n"] == 2
    overall = r1.overall_summary(list(verdicts.values()), merged, [])
    assert (overall["n_judged"], overall["n_passed"], overall["n_confirmed"], overall["n_contradicted"]) == (4, 2, 1, 1)
    assert overall["binding_gates"][0][0] == "calmar_gt_0_5"
    openings = r1.holdout_openings(merged, [])
    assert [(o["configuration"], o["role"], o["confirmed"]) for o in openings] == [
        ("S1+BT ETH-USDT 4H [none]", "configuration", True), ("S1+VC ETH-USDT 4H [none]", "configuration", False), ("hold BTC-USDT 4H [none]", "control", None)]
    path = str(tmp_path / "ledger.json")
    r1.write_round1_ledger(path, [{"generated_at": "a", "openings": openings}])
    ledger = r1.load_ledger(path)
    assert len(ledger) == 1 and ledger[0]["openings"][0]["configuration"] == "S1+BT ETH-USDT 4H [none]"
    assert r1.guard_second_look(ledger, openings, evaluate_holdout=True) == ["S1+BT ETH-USDT 4H [none]", "S1+VC ETH-USDT 4H [none]"]
    assert r1.guard_second_look(ledger, openings, evaluate_holdout=False) == []
    additions = r1.shortlist_additions(merged, [], source={"study": r1.STUDY_NAME, "results": "r.json"})
    assert [(a["candidate"], a["instrument"]) for a in additions] == [("S1+BT", "ETH-USDT")] and additions[0]["source"]["hypothesis"] == "H1"
    assert additions[0]["holdout_confirmed"] is True and additions[0]["passed"] is True
    # A hypothesis with no passer: 'failed walk-forward'; a passer with no holdout look: 'holdout not opened'.
    cfg1 = r1.Round1Config(hypotheses=("H1",), timeframes=("4H",), regime_modes=("none",))
    merged2 = _merged({("ETH-USDT", "4H"): [s1_eth, _res("S1+BT", "ETH-USDT", "4H", "none", calmar=0.2, passed=False, base=s1_eth)]})
    assert r1.hypothesis_verdicts(merged2, [], cfg1)[0]["label"] == "failed walk-forward"
    merged3 = _merged({("ETH-USDT", "4H"): [s1_eth, _res("S1+BT", "ETH-USDT", "4H", "none", calmar=0.9, passed=True, base=s1_eth)]})
    assert r1.hypothesis_verdicts(merged3, [], cfg1)[0]["label"] == "passed walk-forward, holdout not opened"


def test_a_confirmed_h3_adds_both_legs_to_the_shortlist_as_one_position():
    cfg = r1.Round1Config(hypotheses=("H3",), timeframes=("4H",), regime_modes=("none",))
    lb = _res("DM-BTC", "BTC-USDT", "4H", "none", calmar=0.6, passed=False)
    le = _res("DM-ETH", "ETH-USDT", "4H", "none", calmar=0.7, passed=False)
    assert lb["role"] == "leg" and not lb["judged"]
    merged = _merged({("BTC-USDT", "4H"): [lb], ("ETH-USDT", "4H"): [le]})
    combined = {"candidate": "DM", "instrument": "BTC+ETH", "timeframe": "4H", "regime": {"mode": "none"}, "hypothesis": "H3", "role": "configuration", "judged": True,
                "configuration": "DM BTC+ETH 4H [none]", "oos": {"calmar": 1.0, "cagr": 0.1, "max_drawdown": 0.1, "profit_factor": 2.0, "sharpe": 1.0, "n_trades": 40,
                                                                  "total_return": 0.5, "trades_per_year": 10, "exposure": 0.4},
                "acceptance": {"passed": True, "failed": [], "rolling_positive_share": 0.9, "worst_calendar_year_return": 0.0}, "robustness": {"share_above_threshold": 0.8},
                "dsr": {"dsr": 0.2}, "yearly": {"2022": 0.01}, "selected_params": {"DM-BTC": lb["selected_params"], "DM-ETH": le["selected_params"]},
                "holdout": {"total_return": 0.05, "profit_factor": 1.4, "n_trades": 12, "max_drawdown": 0.03}, "holdout_confirmed": True}
    verdicts = r1.hypothesis_verdicts(merged, [combined], cfg)
    assert verdicts[0]["label"] == "confirmed" and verdicts[0]["confirmed"] == ["DM BTC+ETH 4H [none]"]
    rows = r1.shortlist_additions(merged, [combined], source={"study": r1.STUDY_NAME, "results": "r.json"})
    assert [(a["candidate"], a["instrument"]) for a in rows] == [("DM-ETH", "ETH-USDT"), ("DM-BTC", "BTC-USDT")]
    assert all(a["holdout_confirmed"] and "one leg of the confirmed combined configuration" in a["source"]["note"] for a in rows)
    openings = r1.holdout_openings(merged, [combined])
    assert [(o["configuration"], o["confirmed"]) for o in openings] == [("DM BTC+ETH 4H [none]", True)]


def _cli():
    spec = importlib.util.spec_from_file_location("run_research_round_1", ROOT / "scripts" / "run_research_round_1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_shortlist_amendment_the_fleet_cannot_load_is_rolled_back(tmp_path):
    cli = _cli()
    path = tmp_path / "shortlist.json"
    original = (ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json").read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    s1 = _res("S1", "ETH-USDT", "4H", "none", calmar=0.3, passed=False)
    merged = _merged({("ETH-USDT", "4H"): [s1, _res("S1+BT", "ETH-USDT", "4H", "none", calmar=0.9, passed=True, holdout=0.03, base=s1)]})
    additions = r1.shortlist_additions(merged, [], source={"study": r1.STUDY_NAME, "results": "docs/research/missing_results.json"})
    note = cli._apply_shortlist_additions(path, additions)
    assert note.startswith("NOT applied") and path.read_text(encoding="utf-8") == original
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"shortlist_additions": additions, "meta": {}, "series": [], "combined": [], "verdicts": [], "overall": {}}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(path), "--report", "-"]) == 1
    assert path.read_text(encoding="utf-8") == original
    results.write_text(json.dumps({"shortlist_additions": []}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(path), "--report", "-"]) == 0


def test_the_cli_opens_the_holdout_only_for_the_full_preregistered_study(tmp_path, capsys):
    cli = _cli()
    prereg = tmp_path / "prereg.json"
    r1.preregister(prereg)
    common = ["--preregistration", str(prereg), "--lake-dir", str(tmp_path / "lake"), "--study-lake-dir", str(tmp_path / "study"), "--report", "-", "--json", "-"]
    for argv in (["--evaluate-holdout", "--quick"], ["--evaluate-holdout", "--hypotheses", "H2"], ["--evaluate-holdout", "--timeframes", "4H"],
                 ["--evaluate-holdout", "--regime-modes", "none"], ["--evaluate-holdout", "--skip-reproduction"], ["--evaluate-holdout", "--holdout-ledger", "-"]):
        assert cli.main(argv + common) == 2, argv
    assert cli.main(["--preregister", "--preregistration", str(prereg)]) == 2  # written once
    assert cli.main(["--quick", "--preregistration", str(tmp_path / "missing.json"), "--report", "-", "--json", "-"]) == 2
    err = capsys.readouterr().err
    assert "full pre-registered study" in err and "needs a holdout ledger" in err and "run --preregister first" in err


def test_render_from_json_rebuilds_the_report(tmp_path):
    cli = _cli()
    cfg = r1.Round1Config(hypotheses=("H1",), timeframes=("4H",), regime_modes=("none",))
    s1 = _res("S1", "ETH-USDT", "4H", "none", calmar=0.3, passed=False)
    merged = _merged({("ETH-USDT", "4H"): [s1, _res("S1+BT", "ETH-USDT", "4H", "none", calmar=0.2, passed=False, base=s1)]})
    verdicts = r1.hypothesis_verdicts(merged, [], cfg)
    run = {"meta": {"generated_at": "2026-11-04 20:00 UTC", "config": cfg.to_dict(), "preregistration": r1.PREREGISTRATION, "preregistration_sha256": "abc",
                    "protocol_check": {"ok": True, "checked": [], "new_candidates": ["S1+BT"]}, "v1c_meta": {}, "evaluate_holdout": True, "gates": {"calmar_min": 0.5},
                    "holdout_ledger": [{"generated_at": "2026-11-04 20:00 UTC", "openings": [{"configuration": "hold BTC-USDT 4H [none]", "role": "control", "total_return": -0.04,
                                                                                               "max_drawdown": 0.05, "profit_factor": 0.0, "n_trades": 1, "confirmed": None}]}],
                    "holdout_ledger_path": "ledger.json"},
           "reproduction": [{"candidate": "S1", "instrument": "ETH-USDT", "timeframe": "4H", "regime": "none", "ok": True, "max_abs_difference": 0.0, "n_trades": 5,
                             "n_trades_stored": 5, "selected_matches": True, "verdict_matches": True, "reproduced": {"total_return": 0.1}, "stored": {"total_return": 0.1}}],
           "series": [{k: v for k, v in s.items() if k not in ("sleeves", "trades", "args")} for s in merged.values()], "combined": [], "verdicts": verdicts,
           "overall": r1.overall_summary(verdicts, merged, []), "shortlist_additions": []}
    src = tmp_path / "results.json"
    src.write_text(json.dumps(run), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cli.main(["--render-from-json", str(src), "--report", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Research round 1") and "1 of 1 reproduced" in text and "### Every opening of the holdout (ledger)" in text
    assert "H1 — a BTC-trend condition for ETH entries: **failed walk-forward**" in text


# -- the report's sentences --------------------------------------------------------------------------------------------

def _verdict(label, facts, *, combined=False, n_passed=0, gates=(("calmar_gt_0_5", 2),)):
    return {"hypothesis": "H2", "title": "t", "label": label, "combined": combined, "n_configurations": 2, "n_passed": n_passed, "n_confirmed": 0,
            "n_contradicted": 1 if label.startswith("passed") else 0, "n_unevaluated": 0, "configurations": ["a", "b"], "passed": [], "confirmed": [], "contradicted": [],
            "binding_gates": list(gates), "best": None, "failure_facts": facts}


def _facts(delta, *, base_cagr=0.03, var_cagr=0.02, base_dd=0.10, var_dd=0.08):
    return {"n": 2, "n_compared": 2, "calmar_improved": 1, "drawdown_fell": 2, "return_fell": 1, "median_delta_calmar": delta, "median_base_calmar": 0.3,
            "median_variant_calmar": 0.3 + delta, "median_base_cagr": base_cagr, "median_variant_cagr": var_cagr, "median_base_dd": base_dd, "median_variant_dd": var_dd,
            "median_base_rolling": 0.6, "median_variant_rolling": 0.65, "median_trades_removed_share": 0.4, "median_base_trades": 100, "median_variant_trades": 60,
            "median_delta_exposure": -0.1, "median_delta_fees": -0.004, "median_2022_base": -0.03, "median_2022_variant": -0.01,
            "by_mode": {"none": {"calmar_improved": 1, "n": 1}, "gate": {"calmar_improved": 0, "n": 1}}}


def test_failure_analysis_readings_follow_the_deltas():
    worse = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(-0.2, base_cagr=0.04, var_cagr=0.01, base_dd=0.10, var_dd=0.09))))
    assert "removed good entries along with bad ones" in worse and "the return fell by 75% of itself" in worse
    worse2 = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(-0.2, base_cagr=0.04, var_cagr=0.03, base_dd=0.10, var_dd=0.05))))
    assert "lowered the drawdown but lowered the return with it" in worse2
    same = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(0.01))))
    assert "changed little" in same and "With the HMM regime gate already on" in same and "removed a median 40%" in same
    better = "\n".join(failure_analysis(_verdict("failed walk-forward", _facts(0.2))))
    assert "the condition helped" in better and "Calmar above 0.5 (2 of 2)" in better
    contradicted = "\n".join(failure_analysis(_verdict("passed walk-forward, contradicted by the holdout", _facts(0.2), n_passed=1)))
    assert "did not carry into the untouched 12 months" in contradicted
    h3 = {"n": 1, "comparisons": [], "median_calmar": 0.2, "median_best_s1_calmar": 0.4, "beats_best_s1": 0, "beats_hold": 0, "median_trades_per_year": 40,
          "median_s1_trades_per_year": 30, "median_exposure": 0.3, "median_s1_exposure": 0.5, "median_2022": -0.01, "median_s1_2022": -0.03, "legs": []}
    text = "\n".join(failure_analysis(_verdict("failed walk-forward", h3, combined=True)))
    assert "did not beat simply running the plain trend rule" in text and "0.20 against 0.40" in text
    h3b = dict(h3, median_calmar=0.5)
    assert "the concentration helped" in "\n".join(failure_analysis(_verdict("failed walk-forward", h3b, combined=True)))


def test_executive_summary_states_each_verdict_and_the_fleet_outcome():
    v = _verdict("failed walk-forward", _facts(0.01))
    v["best"] = {"configuration": "S1+VC BTC-USDT 4H [none]", "calmar": 0.31, "cagr": 0.02, "max_drawdown": 0.08, "failed": ["calmar_gt_0_5"]}
    run = {"meta": {"evaluate_holdout": True, "v1c_meta": {"holdout_span": "2025-10-20->2026-10-20", "data_span_short": "x"}},
           "reproduction": [{"ok": True}] * 36, "series": [], "combined": [], "verdicts": [v],
           "overall": {"n_judged": 2, "n_passed": 0, "binding_gates": [("calmar_gt_0_5", 2)], "labels": {"H2": "failed walk-forward"}}, "shortlist_additions": []}
    s = "\n".join(executive_summary(run))
    assert "matched Sprint 2c's stored numbers in 36 of 36" in s and "**H2 — t: failed walk-forward.** 0 of 2 configurations passed every gate." in s
    assert "Best: S1+VC BTC-USDT 4H [none] with Calmar 0.31" in s and "raised Calmar in 1 of 2 configurations (median 0.30 → 0.31)" in s
    assert "Nothing passed walk-forward" in s and "Nothing was confirmed, so the fleet's shortlist is unchanged" in s
    assert "Calmar above 0.5 (2 of 2)" in s
    run["shortlist_additions"] = [{"candidate": "S1+BT", "instrument": "ETH-USDT", "timeframe": "6H"}]
    run["shortlist_note"] = "docs/research/paper_fleet_shortlist_v1c.json now lists 13 configurations (23 fleet accounts)"
    s2 = "\n".join(executive_summary(run))
    assert "1 confirmed configuration(s) were appended" in s2 and "S1+BT ETH-USDT 6H" in s2 and "23 fleet accounts" in s2


# -- the paper fleet can run the confirmed configuration -------------------------------------------------------------

def test_the_fleet_loads_and_decides_for_the_confirmed_volume_confirmation_account():
    """The confirmed H2 configuration is a single-market rule (its own bars' volume), so the fleet's existing decision path runs it."""
    from dataclasses import replace

    from research.paper_fleet.config import load_manifest
    from research.paper_fleet.signals import decide_sleeve, frame_decisions
    from research.regime_v2 import RegimeV2Config

    acc = load_manifest().account("c13-s1vc-btc-4h-gate")
    assert acc.sleeve.candidate == "S1+VC" and acc.sleeve.regime.mode == "gate" and acc.expectations["source"]["study"] == r1.STUDY_NAME
    spec = replace(acc.sleeve, regime=RegimeV2Config(mode="none"))  # the gate needs a regime fit; the candidate's own path is what is checked here
    btc, _ = _pair(3000)
    ctx = FeatureContext(timeframe="4H", periods_per_year=bars_per_year("4H"))
    info = decide_sleeve(spec, btc, ctx)
    assert isinstance(info.decision.desired, bool) and info.diagnostics["window_bars"] > 0 and info.signal["action"] in ("long", "flat")
    decisions = frame_decisions(spec, btc, ctx, start=btc.index[-400])
    assert len(decisions) == 400 and any(d.desired for d in decisions)
