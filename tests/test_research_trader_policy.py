"""Plan row R18: the Trader Policy tiers, the section 4.6 gates, the size-neutral variant rule, the study's pre-registration, cells, protocol
honesty, reproduction gate, verdicts, ledger, fleet rows and report. The runner is exercised offline on synthetic candles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research import trader_policy as tp
from research import trader_policy_study as st
from research.brakes import TRADER_BRAKES, TURTLE_LADDER_ONLY, TurtleLadder
from research.report_trader_policy import executive_summary, render_report
from research.sizing import SIZING_TIERS
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import param_grid
from tests.test_research_round2 import _frame, _write
from tests.test_research_strategies import synthetic

ROOT = Path(__file__).resolve().parents[1]


# -- the policy module ------------------------------------------------------------------------------------

def test_tiers_are_the_plan_table_and_tier_for_recognises_them():
    assert set(tp.TIERS) == {"reference", "trader", "aggressive", "risk1.5"} and tp.DEFAULT_TIER == "trader"
    assert tp.TIERS["reference"].sizing == SIZING_TIERS["reference"] and not tp.TIERS["reference"].turtle_ladder
    assert tp.TIERS["trader"].label == "vt20/30 crash15/90dh cap2 turtle" and tp.TIERS["aggressive"].label == "vt25/30 crash15/90dh cap2.5 turtle"
    assert tp.TIERS["trader"].brakes(on=False) == TURTLE_LADDER_ONLY and tp.TIERS["trader"].brakes(on=True) == TRADER_BRAKES
    assert tp.TIERS["reference"].brakes(on=False) is None and tp.TIERS["reference"].brakes(on=True).ladder is None
    assert tp.TIERS["trader"].brakes(on=True, heat_cap=0.08).heat_cap == 0.08
    assert tp.COMPARISON_TIERS["trader-reference-ladder"].sizing.ladder and not tp.COMPARISON_TIERS["trader-reference-ladder"].turtle_ladder
    assert tp.COMPARISON_TIERS["trader-no-ladder"].sizing == SIZING_TIERS["trader"] and not tp.COMPARISON_TIERS["trader-no-ladder"].turtle_ladder
    assert tp.tier_for(tp.TIERS["trader"].sizing.to_dict(), TRADER_BRAKES.to_dict()) == "trader"
    assert tp.tier_for(tp.TIERS["trader"].sizing.to_dict(), TURTLE_LADDER_ONLY.to_dict()) == "trader"
    assert tp.tier_for(tp.TIERS["reference"].sizing.to_dict(), None) == "reference"
    assert tp.tier_for(tp.TIERS["trader"].sizing.to_dict(), None) == "trader-no-ladder"
    assert tp.tier_for(dict(tp.TIERS["trader"].sizing.to_dict(), target_vol=0.3), None) is None
    other = dict(TRADER_BRAKES.to_dict(), ladder=TurtleLadder(steps=((0.1, 0.5),)).to_dict())
    assert tp.tier_for(tp.TIERS["trader"].sizing.to_dict(), other) is None
    with pytest.raises(ValueError):
        tp.tier("nope")
    assert tp.brake_spec_from_args(False, False) is None and tp.brake_spec_from_args(True, False) == TURTLE_LADDER_ONLY
    assert tp.brake_spec_from_args(True, True) == TRADER_BRAKES and tp.brake_spec_from_args(False, True).ladder is None
    assert tp.brake_spec_from_args(True, True, 0.08).heat_cap == 0.08


def test_variants_apply_to_the_right_rules_and_build_their_frames():
    combos_s1 = param_grid({"atr_mult": [2.0, 3.0, 4.0], "bracket": ["none", "time30"]}, base=get_candidate("S1").default_params)
    assert set(tp.VARIANTS) == {"none", "add", "scale_out", "conviction", "trail2", "trail3", "wider_stop", "no_time_stop"}
    for v in ("add", "scale_out", "conviction", "trail2", "trail3", "wider_stop", "no_time_stop"):
        assert tp.variant_applies(v, "S1", combos_s1) == (True, "")
    assert tp.variant_applies("conviction", "S1+VC", combos_s1)[0] is False
    assert tp.variant_applies("add", "hold", []) == (False, "the rule has no stop: R is undefined") and tp.variant_applies("trail2", "TF", [])[0] is False
    assert tp.variant_applies("no_time_stop", "S1", [c for c in combos_s1 if c["bracket"] == "none"])[0] is False
    assert [c["atr_mult"] for c in tp.variant_combos("wider_stop", combos_s1)] == [4.0, 4.0, 4.0, 4.0, 5.0, 5.0]  # 2 -> 4, 3 -> 4, 4 -> 5
    assert tp.variant_combos("trail2", combos_s1) == [dict(c) for c in combos_s1]
    df = synthetic(2500)
    ctx = FeatureContext("1H", 8766.0)
    base = tp.variant_frames("none", get_candidate("S1"), df, combos_s1, ctx, no_trade=None)
    assert base is None and tp.variant_frames("add", get_candidate("S1"), df, combos_s1, ctx, no_trade=None) is None
    t2 = tp.variant_frames("trail2", get_candidate("S1"), df, combos_s1, ctx, no_trade=None)
    assert np.all(t2.trail_activate == 1.0) and np.all(t2.trail_dist == 2.0) and t2.time_stops[1] is not None  # the time stop of time30 stays
    assert np.all(tp.variant_frames("trail3", get_candidate("S1"), df, combos_s1, ctx, no_trade=None).trail_dist == 3.0)
    nts = tp.variant_frames("no_time_stop", get_candidate("S1"), df, combos_s1, ctx, no_trade=None)
    assert all(t is None for t in nts.time_stops)
    wide = tp.variant_frames("wider_stop", get_candidate("S1"), df, combos_s1, ctx, no_trade=None)
    ok = np.isfinite(wide.stop[:, 0])
    np.testing.assert_allclose(wide.stop[ok, 0], 2.0 * np.asarray(base_stop(df, ctx, combos_s1[0]))[ok])  # 2 x ATR -> 4 x ATR
    mult = tp.conviction_multiplier(df, "1H")
    assert set(np.unique(mult)) <= {0.75, 1.25} and (mult.iloc[:10] == 0.75).all()
    with pytest.raises(ValueError):
        tp.variant("nope")


def base_stop(df, ctx, params):
    from research.sweep import build_frames

    return build_frames(get_candidate("S1"), df, [params], ctx, no_trade=None).stop[:, 0]


def test_section_4_6_gates_relax_only_at_the_higher_tiers_and_add_the_payoff_gate():
    oos = {"profit_factor": 1.5, "max_drawdown": 0.22, "sharpe": 0.9, "calmar": 0.6, "n_trades": 50, "avg_win": 100.0, "avg_loss": -40.0}
    yearly = {"rolling_windows": 10, "rolling_positive_share": 0.8, "worst_calendar_year_return": -0.12}
    robust = {"share_above_threshold": 0.7}
    ref = tp.acceptance_check_r18(oos, yearly, robust, "reference")
    hi = tp.acceptance_check_r18(oos, yearly, robust, "trader")
    assert not ref["passed"] and set(ref["failed"]) == {"max_dd_within_tier", "worst_calendar_year_within_tier"}
    assert hi["passed"] and hi["failed"] == [] and hi["payoff_ratio"] == pytest.approx(2.5) and hi["thresholds"]["max_drawdown_max"] == 0.25
    poor = tp.acceptance_check_r18(dict(oos, avg_win=60.0), yearly, robust, "aggressive")
    assert poor["failed"] == ["payoff_ge_2"] and poor["payoff_ratio"] == pytest.approx(1.5)
    assert tp.acceptance_check_r18(dict(oos, avg_win=0.0), yearly, robust, "trader")["payoff_ratio"] is None
    assert tp.gate_thresholds("reference") == {"max_drawdown_max": 0.2, "worst_calendar_year_min": -0.1}
    assert tp.gate_thresholds("risk1.5") == {"max_drawdown_max": 0.25, "worst_calendar_year_min": -0.15}
    assert set(tp.GATE_LABELS_R18) == set(k for k in hi if isinstance(hi[k], bool) and k != "passed")


def test_variant_rule_is_size_neutral_and_the_brake_cost_flag_is_0_1_calmar():
    base = {"sharpe": 0.8, "calmar": 0.6, "ann_vol": 0.10, "cagr": 0.06, "max_drawdown": 0.10}
    bigger = {"sharpe": 0.8, "calmar": 0.6, "ann_vol": 0.20, "cagr": 0.12, "max_drawdown": 0.20}  # the same curve at twice the size
    r = tp.variant_counts(base, bigger)
    assert r["counts"] and r["vol_scale"] == pytest.approx(0.5) and r["variant_calmar_vol_matched"] == pytest.approx(0.6)
    worse = tp.variant_counts(base, dict(bigger, sharpe=0.79))
    assert not worse["counts"] and worse["sharpe_ok"] is False and worse["calmar_ok"] is True
    better = tp.variant_counts(base, {"sharpe": 0.9, "calmar": 0.9, "ann_vol": 0.1, "cagr": 0.09, "max_drawdown": 0.1})
    assert better["counts"]
    cost = tp.brake_cost({"calmar": 0.70, "cagr": 0.08, "max_drawdown": 0.1}, {"calmar": 0.55, "cagr": 0.07, "max_drawdown": 0.09})
    assert cost["flagged"] and cost["cost_calmar"] == pytest.approx(0.15)
    assert not tp.brake_cost({"calmar": 0.70}, {"calmar": 0.65})["flagged"]
    assert tp.exposure_ratio({"avg_allocation": 0.2}, {"avg_allocation": 0.1}) == pytest.approx(2.0) and tp.exposure_ratio({"avg_allocation": 0.2}, None) is None
    assert tp.payoff_ratio({"avg_win": 30.0, "avg_loss": -10.0}) == pytest.approx(3.0) and tp.payoff_ratio({"avg_win": 0.0, "avg_loss": -10.0}) is None


def test_trade_stats_count_expectancy_gaps_reentries_and_adds():
    trades = pd.DataFrame({
        "combo": [0, 0, 0, 0], "window": [0, 0, 0, 1], "entry_i": [10, 25, 27, 5], "exit_i": [24, 26, 40, 9],
        "pnl": [300.0, -100.0, -120.0, 200.0], "risk": [100.0, 100.0, 100.0, 100.0], "risk_pct": [0.01, 0.01, 0.02, 0.01],
        "size_fraction": [0.5, 0.5, 1.0, 0.5], "exit_reason": ["signal", "stop_loss", "stop_loss", "signal"],
        "stop_price": [95.0, 95.0, 95.0, 95.0], "exit_price": [110.0, 95.0 * (1 - 0.0005), 93.0, 108.0],  # the second fills AT the stop (slipped), the third gapped
        "adds": [1, 0, 0, 0], "add_worst_case_r": [1.5, np.nan, np.nan, np.nan],
        "scale_outs": [0, 0, 1, 0], "entry_price": [100.0] * 4, "quantity": [1.0] * 4,
    })
    s = tp.trade_stats(trades, slippage_rate=0.0005)
    assert s["n_trades"] == 4 and s["expectancy_r"] == pytest.approx(0.7) and s["payoff_ratio"] == pytest.approx(250.0 / 110.0)
    assert s["stop_outs"] == 2 and s["gap_trades"] == 1 and s["reentries_within_2_bars_of_stop"] == 1 and s["reentry_share_of_stops"] == 0.5
    assert s["risk_pct_mean"] == pytest.approx(0.0125) and s["risk_pct_max"] == 0.02 and s["full_allocation_share"] == 0.25
    assert s["adds"] == 1 and s["add_worst_case_r_mean"] == 1.5 and s["scale_outs"] == 1 and s["win_rate"] == 0.5
    assert tp.trade_stats(trades.iloc[:0], slippage_rate=0.0)["n_trades"] == 0


# -- the study module -------------------------------------------------------------------------------------

def test_cells_jobs_and_the_runner_arguments_of_a_cell():
    assert len(st.CONFIGURATIONS) == 5 and len(st.CONTROLS) == 6 and len(st.TF_CONTROLS) == 4 and len(st.ALL_RUNS) == 15
    assert [c.key for c in st.CONFIGURATIONS] == ["C1", "C2", "C3", "C4", "C5"] and st.BY_KEY["C4"].mode == "gate" and st.BY_KEY["C2"].candidate == "S1"
    assert len(st.CORE_CELLS) == 11 and len(st.VARIANT_CELLS) == 7 and st.FLEET_CELL.key == "trader|brakes|none"
    assert all(c.tier == "trader" and c.brakes for c in st.VARIANT_CELLS)
    assert [c.key for c in st.holdout_cells()] == ["reference|nobrakes|none", "trader|brakes|none", "aggressive|brakes|none"]
    jobs = st.plan_jobs(st.StudyConfig(), evaluate_holdout=True)
    assert len(jobs) == 5 * 18 + 10 * 6 == 150
    assert sum(1 for j in jobs if j["evaluate_holdout"]) == 11 * 3  # the configurations and the hold controls, never the TF forward controls
    assert not any(j["evaluate_holdout"] for j in jobs if j["run"].startswith("T"))
    assert len(st.plan_jobs(st.StudyConfig(runs=("C1",), cells=("trader|brakes|none",)), evaluate_holdout=False)) == 1
    argv = st.cell_argv(st.Cell("trader", True, "add"), st.BY_KEY["C1"], evaluate_holdout=True, lake_dir="x", quick=False)
    assert argv[:6] == ["--strategies", "S1+S5", "--regime-modes", "none", "--timeframes", "6H"]
    assert "--policy-risk-cap" in argv and argv[argv.index("--policy-risk-cap") + 1] == "0.02" and "--policy-no-ladder" in argv
    assert "--turtle-ladder" in argv and "--brakes" in argv and argv[argv.index("--variant") + 1] == "add" and "--evaluate-holdout" in argv
    assert argv[argv.index("--policy-target-vol") + 1] == "0.2" and "measured_btc_eth=0.0005:0.0005" in argv and "altcoin=0.001:0.0015" in argv
    ref = st.cell_argv(st.REFERENCE_CELL, st.BY_KEY["H2"], evaluate_holdout=False, lake_dir=None, quick=True)
    assert "--policy-no-ladder" not in ref and "--turtle-ladder" not in ref and "--brakes" not in ref and "--quick" in ref and argv_value(ref, "--policy-target-vol") == "0.1"
    risk = st.cell_argv(st.Cell("risk1.5", False), st.BY_KEY["C2"], evaluate_holdout=False, lake_dir=None, quick=False)
    assert argv_value(risk, "--policy-kind") == "risk" and argv_value(risk, "--policy-risk") == "0.015" and "--turtle-ladder" in risk
    tf = st.cell_argv(st.REFERENCE_CELL, st.BY_KEY["T2"], evaluate_holdout=False, lake_dir=None, quick=False)
    assert argv_value(tf, "--brackets") == "none" and argv_value(tf, "--min-trades") == "1"
    args = st.cell_args(st.Cell("trader", True), st.BY_KEY["C1"], evaluate_holdout=False, lake_dir="x", quick=False)
    assert args["policy_risk_cap"] == 0.02 and args["turtle_ladder"] and args["brakes"] and args["tier"] == "trader" and args["lake_dir"] == "x"


def argv_value(argv, flag):
    return argv[argv.index(flag) + 1]


def test_protocol_check_records_a_tier_as_an_explained_mismatch_and_stops_on_anything_else():
    meta = json.loads(st.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    ref = st.protocol_check_cell(st.cell_args(st.REFERENCE_CELL, st.BY_KEY["C1"], evaluate_holdout=True, lake_dir="x", quick=False), meta, st.REFERENCE_CELL, st.BY_KEY["C1"])
    assert ref["ok"] and ref["ok_for_cell"] and ref["expected_mismatches"] == {} and ref["r18"]["tier"] == "reference"
    cell = st.Cell("trader", True)
    tr = st.protocol_check_cell(st.cell_args(cell, st.BY_KEY["C1"], evaluate_holdout=True, lake_dir="x", quick=False), meta, cell, st.BY_KEY["C1"])
    assert not tr["ok"] and tr["ok_for_cell"] and set(tr["mismatches"]) == {"policy_sizing"} and "trader" in tr["expected_mismatches"]["policy_sizing"]
    assert tr["r18"]["brakes"] == TRADER_BRAKES.to_dict() and tr["r18"]["variant"] == "none"
    tf = st.protocol_check_cell(st.cell_args(st.REFERENCE_CELL, st.BY_KEY["T2"], evaluate_holdout=False, lake_dir="x", quick=False), meta, st.REFERENCE_CELL, st.BY_KEY["T2"])
    assert not tf["ok"] and tf["ok_for_cell"] and set(tf["mismatches"]) == {"brackets", "min_trades", "strategies"} - {"strategies"} | set(k for k in tf["mismatches"] if k == "strategies")
    assert tf["new_candidates"] == ["TF"]
    wrong = dict(st.cell_args(cell, st.BY_KEY["C1"], evaluate_holdout=True, lake_dir="x", quick=False), train_days=500)
    bad = st.protocol_check_cell(wrong, meta, cell, st.BY_KEY["C1"])
    assert not bad["ok_for_cell"] and "train_days" in bad["unexplained_mismatches"]


def test_preregistration_is_written_once_checked_and_the_committed_file_matches_the_module(tmp_path):
    path = tmp_path / "prereg.json"
    payload = st.preregister(path, now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert payload["sha256"] and payload["preregistration"] == st.PREREGISTRATION and len(payload["cells"]) == 18 and len(payload["configurations"]) == 15
    with pytest.raises(st.TraderPolicyError, match="already fixed"):
        st.preregister(path)
    loaded = st.load_preregistration(path)
    assert loaded["written_at"] == "2026-11-05T00:00:00+00:00"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["preregistration"]["gates"] = "looser"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(st.TraderPolicyError, match="hash"):
        st.load_preregistration(path)
    data["sha256"] = st._sha256_json({k: v for k, v in data.items() if k != "sha256"})
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(st.TraderPolicyError, match="differs"):
        st.load_preregistration(path)
    committed = st.load_preregistration()  # the file in docs/research is intact and matches the module
    assert committed["preregistration"] == st.PREREGISTRATION
    assert st.full_study_requested(st.StudyConfig()) and not st.full_study_requested(st.StudyConfig(quick=True))
    assert not st.full_study_requested(st.StudyConfig(runs=("C1",))) and not st.full_study_requested(st.StudyConfig(reproduction=False))
    cfg = st.StudyConfig(runs=("C1", "H5"))
    assert cfg.markets == ["BTC-USDT", "SOL-USDT"] and st.preregistration_hash(cfg, committed) != st.preregistration_hash(st.StudyConfig(), committed)


@pytest.fixture(scope="module")
def stored_docs():
    return {name: json.loads(p.read_text(encoding="utf-8")) for name, p in (("Sprint 2c", st.V1C_RESULTS), ("R12 replication", st.R12_RESULTS),
                                                                           ("R13 research round 1", st.R13_RESULTS), ("R16 research round 2", st.R16_RESULTS))}


def test_stored_results_are_found_for_every_configuration_and_control(stored_docs):
    stored = st.stored_results(stored_docs)
    for run in st.CONFIGURATIONS + st.CONTROLS:
        r = st.stored_for(run, stored)
        assert r is not None, run.name
        assert r["candidate"] == run.candidate and (r.get("regime") or {}).get("mode") == run.mode
    assert st.stored_for(st.BY_KEY["T2"], stored) is None


@pytest.fixture(scope="module")
def r18_lake(tmp_path_factory):
    """Synthetic 6H candles for BTC-USDT (stored as 6H bars, so no 1H resampling is needed): a trend flip about every 9 days."""
    from app.datalake.layout import LakeLayout

    layout = LakeLayout(tmp_path_factory.mktemp("r18_lake") / "lake")
    n = 5200
    regime = np.sign(np.sin(np.arange(n) / 40.0))
    _write(layout, "BTC-USDT", _frame(7, 0.004 * regime, n=n, freq="6h", start="2021-01-01"), "6H")
    return layout


@pytest.fixture(scope="module")
def synthetic_cells(r18_lake):
    """One configuration (as S1+S5 on the synthetic BTC lake, no funding data: the filter passes) at the Reference and Trader cells, plus a variant and
    one hold control, through the real runner with cut grids."""
    cfg = st.StudyConfig(runs=("C1", "H2"), cells=("reference|nobrakes|none", "trader|nobrakes|none", "trader|brakes|none", "trader|brakes|add", "trader-no-ladder|nobrakes|none"),
                         reproduction=False, quick=True, lake_dir=str(r18_lake.root))
    jobs = st.plan_jobs(cfg, evaluate_holdout=False)
    assert len(jobs) == 5 + 3  # C1: the five cells; H2: the three that are control cells
    outputs = [st.run_job(j) for j in jobs]
    meta = json.loads(st.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    return cfg, st.merge_results(outputs, meta)


def test_run_job_merge_analyses_verdicts_and_report_on_the_synthetic_lake(synthetic_cells, stored_docs):
    cfg, merged = synthetic_cells
    assert set(merged) == {"C1|reference|nobrakes|none", "C1|trader|nobrakes|none", "C1|trader|brakes|none", "C1|trader|brakes|add", "C1|trader-no-ladder|nobrakes|none",
                           "H2|reference|nobrakes|none", "H2|trader|nobrakes|none", "H2|trader|brakes|none"}
    for key, r in merged.items():
        assert not r.get("skipped") and not r["failures"], key
        assert set(r["protocol_check"]["unexplained_mismatches"]) <= {"quick"}, key  # a quick run's cut grids are its one unexplained difference
        assert ("policy_sizing" in r["protocol_check"]["expected_mismatches"]) == (r["cell"]["tier"] != "reference"), key
        assert "r18" in r and "acceptance_r18" in r and r["tier"] == r["cell"]["tier"]  # the tier label is recorded for every cell
    ref, trader, braked, add = (merged[f"C1|{k}"] for k in ("reference|nobrakes|none", "trader|nobrakes|none", "trader|brakes|none", "trader|brakes|add"))
    assert ref["rule_frequency"] == trader["rule_frequency"] == braked["rule_frequency"] == add["rule_frequency"]  # the selection never sees the tier
    assert trader["oos"]["avg_allocation"] > ref["oos"]["avg_allocation"]
    # The cap is set at the decision close; the next open's gap and the entry fee move the realized risk a little (a few percent of it).
    assert trader["r18"]["trades"]["risk_pct_max"] <= 0.02 * 1.08 and trader["r18"]["trades"]["risk_pct_mean"] <= 0.02 * 1.02
    assert braked["r18"]["brake_summary"]["opportunities"] > 0 and set(braked["r18"]["brake_summary"]["counts"]) >= {"ladder", "hard_stop", "entry_after_exit"}
    assert add["r18"]["variant"]["name"] == "add" and add["r18"]["trades"]["adds"] >= 0 and add["r18"]["cost_scenarios"].keys() == st.COST_SCENARIOS.keys()
    assert trader["r18"]["cap"]["cap_binding_share"] is not None and ref["r18"]["cap"]["cap_binding_share"] is None
    rows = st.tier_table(merged, st.BY_KEY["C1"])
    assert [r["cell"]["key"] for r in rows] == ["reference|nobrakes|none", "trader|nobrakes|none", "trader|brakes|none", "trader-no-ladder|nobrakes|none", "trader|brakes|add"]
    assert rows[0]["exposure_ratio"] == 1.0 and rows[1]["exposure_ratio"] > 1.0
    brakes = st.brake_analysis(merged, st.BY_KEY["C1"])
    assert [b["tier"] for b in brakes] == ["trader"] and "cost" in brakes[0] and brakes[0]["ladder_cost"] is not None and brakes[0]["reference_ladder"] is None
    variants = st.variant_analysis(merged, st.BY_KEY["C1"])
    assert [v["variant"] for v in variants] == ["add"] and v_has_rule(variants[0])
    costs = st.cost_table(merged, st.BY_KEY["C1"])
    assert [c["tier"] for c in costs] == ["trader"] and costs[0]["altcoin"]["round_trip"] == pytest.approx(0.005)
    verdict = st.configuration_verdict(merged, st.BY_KEY["C1"])
    assert verdict["fleet_candidate"] is False and ("holdout not opened" in verdict["fleet_reason"] or "fails" in verdict["fleet_reason"])
    overall = st.overall_summary(merged, [verdict, st.configuration_verdict(merged, st.BY_KEY["H2"])])
    assert overall["n_configurations"] == 1 and overall["fleet_candidates"] == [] and "trader" in overall["brake_counts"]
    pooled = st.pooled_conviction_test(merged)
    assert pooled["n_high"] == 0 and pooled["enough_trades"] is False
    assert st.holdout_openings(merged) == [] and st.earlier_looks(merged, st.stored_results(stored_docs)) == []
    run_doc = {"meta": {"generated_at": "now", "evaluate_holdout": False, "v1c_meta": {}, "preregistration": st.PREREGISTRATION, "gates": {}, "holdout_ledger": []},
               "reproduction": [], "results": [{k: v for k, v in r.items() if k not in ("trades", "args")} for r in merged.values()],
               "analyses": {"C1": {"run": dict(st.BY_KEY["C1"].to_dict(), name=st.BY_KEY["C1"].name), "tiers": rows, "brakes": brakes, "variants": variants, "costs": costs},
                            "H2": {"run": dict(st.BY_KEY["H2"].to_dict(), name=st.BY_KEY["H2"].name), "tiers": st.tier_table(merged, st.BY_KEY["H2"]), "brakes": [], "variants": [], "costs": []}},
               "verdicts": [verdict], "overall": overall, "pooled_conviction": pooled, "holdout_openings": [], "earlier_looks": [], "shortlist_additions": []}
    text = render_report(run_doc)
    bullets = executive_summary(run_doc)
    assert "## Executive summary" in text and "S1+S5 BTC-USDT 6H [none]" in text and "Trader tier (brakes on)" in bullets[1]
    assert "The untouched 12 months were not opened in this run" in text and "## Controls" in text and "trader-no-ladder" in text


def v_has_rule(v):
    return v["applies"] and v["rule"] is not None and "counts" in v["rule"]


def test_shortlist_rows_name_the_tier_the_brakes_and_the_control_protocol(synthetic_cells):
    cfg, merged = synthetic_cells
    verdicts = [dict(st.configuration_verdict(merged, st.BY_KEY["C1"]), fleet_candidate=True)]  # pretend the holdout confirmed it
    tf_merged = dict(merged)
    tf_merged["T2|reference|nobrakes|none"] = dict(merged["H2|reference|nobrakes|none"], run=st.BY_KEY["T2"].to_dict(), role="tf_control",
                                                   configuration=st.BY_KEY["T2"].name, candidate="TF")
    rows = st.shortlist_additions(tf_merged, verdicts, source={"study": st.STUDY_NAME, "results": "x.json"})
    assert [r["source"]["role"] for r in rows] == ["candidate", "control"]
    cand, ctl = rows
    assert cand["candidate"] == "S1+S5" and cand["source"]["tier"] == "trader" and cand["source"]["brakes"] == TRADER_BRAKES.to_dict() and cand["source"]["variant"] == "none"
    assert cand["sizing"] == tp.TIERS["trader"].label and cand["sizing_config"]["risk_cap"] == 0.02
    assert ctl["candidate"] == "TF" and ctl["source"]["tier"] == "reference" and "fixed rule" in ctl["source"]["protocol_variant"] and ctl["source"]["brakes"] is None
    # The TF 4H control is reported but not proposed as a fleet row.
    assert st.TF_CONTROL_TIMEFRAMES == ("6H",)


def test_the_cli_applies_the_recorded_rows_with_the_fleet_can_load_check_and_rolls_back_otherwise(tmp_path, capsys):
    """Plan row R18b: ``--apply-shortlist-from-json`` appends the recorded rows through ``append_to_shortlist`` and proves the fleet can
    load the amended file; a row the fleet refuses puts the original file back (the R12 rule). No re-run, no holdout look."""
    import importlib.util

    from research.paper_fleet.config import load_manifest

    spec = importlib.util.spec_from_file_location("r18_cli_apply", ROOT / "scripts" / "run_trader_policy_v1.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    committed = json.loads((ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json").read_text(encoding="utf-8"))
    before = dict(committed, configurations=committed["configurations"][:14], controls=committed["controls"][:8], amendments=committed["amendments"][:3])
    recorded = json.loads((ROOT / "docs" / "research" / "trader_policy_v1_results.json").read_text(encoding="utf-8"))["shortlist_additions"]
    assert len(recorded) == 7 and [a["source"]["role"] for a in recorded] == ["candidate"] * 5 + ["control"] * 2
    shortlist = tmp_path / "shortlist.json"
    shortlist.write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"shortlist_additions": recorded, "shortlist_note": None}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(shortlist), "--report", "-"]) == 0
    out = capsys.readouterr().out
    assert "applied" in out and "31 fleet accounts" in out
    after = json.loads(shortlist.read_text(encoding="utf-8"))
    assert len(after["configurations"]) == 19 and len(after["controls"]) == 10 and after["amendments"][-1]["added"][0] == "S1+S5 SOL-USDT 6H [none] @ trader"
    assert [c["account_id"] for c in [a.to_dict() for a in load_manifest(shortlist).accounts]][14:19] == [
        "c15-s1s5-sol-6h-none-trader", "c16-s1-sol-6h-none-trader", "c17-s1s5-btc-6h-none-trader", "c18-s1vc-doge-4h-gate-trader", "c19-s1vc-btc-4h-gate-trader"]
    assert "applied" in json.loads(results.read_text(encoding="utf-8"))["shortlist_note"]
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(shortlist), "--report", "-"]) == 0  # idempotent: nothing added twice
    assert len(json.loads(shortlist.read_text(encoding="utf-8"))["configurations"]) == 19
    # A tampered row (a tier the study record does not describe) is refused by the fleet: the file is restored byte for byte, exit 1.
    original = json.dumps(before, indent=2) + "\n"
    shortlist.write_text(original, encoding="utf-8")
    bad = json.loads(json.dumps(recorded))
    bad[0]["source"]["tier"] = "aggressive"
    results.write_text(json.dumps({"shortlist_additions": bad}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(shortlist), "--report", "-"]) == 1
    assert shortlist.read_text(encoding="utf-8") == original and "NOT applied" in json.loads(results.read_text(encoding="utf-8"))["shortlist_note"]
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", "-", "--report", "-"]) == 2
    results.write_text(json.dumps({"shortlist_additions": []}), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(shortlist), "--report", "-"]) == 0


def test_ledger_is_append_only_and_second_looks_are_named(tmp_path):
    openings = [{"configuration": "S1+S5 BTC-USDT 6H [none]", "cell": "trader|brakes|none", "role": "configuration", "total_return": 0.03, "profit_factor": 1.3, "n_trades": 30, "confirmed": True},
                {"configuration": "hold BTC-USDT 6H [none]", "cell": "reference|nobrakes|none", "role": "control", "total_return": -0.04, "profit_factor": 0.0, "n_trades": 1, "confirmed": None}]
    path = tmp_path / "ledger.json"
    st.write_ledger(str(path), [{"generated_at": "t1", "openings": openings}])
    ledger = st.load_ledger(str(path))
    assert len(ledger) == 1 and st.guard_second_look(ledger, openings, evaluate_holdout=True) == ["S1+S5 BTC-USDT 6H [none] @ trader|brakes|none"]
    assert st.guard_second_look(ledger, openings, evaluate_holdout=False) == []
    ledger.append({"generated_at": "t2", "openings": openings})
    st.write_ledger(str(path), ledger)
    assert len(st.load_ledger(str(path))) == 2 and "near-second look" in json.loads(path.read_text(encoding="utf-8"))["note"]


def test_the_cli_refuses_the_holdout_outside_the_full_study_and_renders_from_json(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("r18_cli", ROOT / "scripts" / "run_trader_policy_v1.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(["--evaluate-holdout", "--runs", "C1", "--report", "-", "--json", "-"]) == 2
    assert "full pre-registered study" in capsys.readouterr().err
    assert cli.main(["--evaluate-holdout", "--holdout-ledger", "-", "--report", "-", "--json", "-"]) == 2
    missing = tmp_path / "none.json"
    assert cli.main(["--preregistration", str(missing), "--report", "-", "--json", "-"]) == 2
    assert cli.main(["--preregister", "--preregistration", str(missing)]) == 0 and missing.exists()
    assert cli.main(["--preregister", "--preregistration", str(missing)]) == 2  # never twice
    run_doc = {"meta": {"generated_at": "now", "evaluate_holdout": False, "v1c_meta": {}, "preregistration": {}, "gates": {}, "holdout_ledger": []}, "reproduction": [],
               "results": [], "analyses": {}, "verdicts": [], "overall": {}, "pooled_conviction": {}, "holdout_openings": [], "earlier_looks": [], "shortlist_additions": []}
    src = tmp_path / "run.json"
    src.write_text(json.dumps(run_doc), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cli.main(["--render-from-json", str(src), "--report", str(out)]) == 0 and out.read_text(encoding="utf-8").startswith("# Trader Policy v1")
