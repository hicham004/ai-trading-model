"""Sprint 2b gates, shortlist, executive summary and report rendering."""

from __future__ import annotations

from research.report_v1b import GATES, acceptance_check_v1b, executive_summary, render_report_v1b, shortlist

GOOD_OOS = {"profit_factor": 1.6, "max_drawdown": 0.12, "sharpe": 1.1, "calmar": 0.9, "n_trades": 45, "total_return": 0.6, "cagr": 0.11,
            "sortino": 1.5, "win_rate": 0.4, "exposure": 0.5, "avg_allocation": 0.3, "fees_pct_per_year": 0.02, "windows": 9,
            "windows_traded": 9, "windows_positive": 6}
YEARLY = {2021: 0.1, 2022: -0.02, 2023: 0.2, 2024: 0.15, 2025: 0.05}


def _result(candidate="S2", instrument="ETH-USDT", timeframe="4H", oos=None, passed=True, sizing="vt15/30 crash15/90dh ladder"):
    oos = dict(GOOD_OOS, **(oos or {}))
    acc = acceptance_check_v1b(oos, YEARLY, {"share_above_threshold": 0.8})
    assert acc["passed"] == passed
    holdout = {"total_return": 0.05, "cagr": 0.05, "sharpe": 0.5, "profit_factor": 1.1, "max_drawdown": 0.08, "calmar": 0.6, "n_trades": 9}
    return {
        "candidate": candidate, "label": "label", "instrument": instrument, "timeframe": timeframe, "grid_size": 252,
        "selected_params": {"entry_days": 10, "bracket": "trail1"}, "selected_sizing": {"label": sizing, "ladder": True},
        "rule_frequency": {}, "sizing_frequency": {sizing: 7, "fixed25": 2}, "oos": oos, "yearly": YEARLY,
        "by_regime": [{"regime": "lowvol_up", "share": 0.5, "total_return": 0.1, "sharpe": 1.0}],
        "robustness": {"best": 0.6, "median": 0.4, "min": 0.1, "share_above_threshold": 0.8, "n_neighbours": 8},
        "dsr": {"n_trials": 600, "expected_max_sr": 0.02, "observed_sr": 0.03, "dsr": 0.6},
        "montecarlo": {"n_trades": 45, "paths": 100, "terminal_p05": 0.9, "terminal_p50": 1.3, "terminal_p95": 1.8, "prob_loss": 0.1,
                       "max_dd_p50": 0.1, "max_dd_p95": 0.2},
        "slippage_stress": {"x1": 0.6, "x2": 0.5, "x3": 0.4},
        "sizing_sweep": {"rows": [], "best_by_calmar": "vt10/60", "all_in": {"cagr": 0.18, "max_drawdown": 0.5, "calmar": 0.36},
                         "chosen": {"sizing": sizing, "cagr": 0.11, "max_drawdown": 0.12, "calmar": 0.9}},
        "ladder_effect": {"with": {"total_return": 0.6, "max_drawdown": 0.12, "calmar": 0.9}, "without": {"total_return": 0.7, "max_drawdown": 0.2, "calmar": 0.6}},
        "bracket_effect": {"bracket": "trail1", "selected": {"total_return": 0.6, "profit_factor": 1.6, "max_drawdown": 0.12,
                                                             "giveback_share_reached_closed_negative": 0.2, "giveback_n_reached": 20, "giveback_avg_giveback_pct": 0.02},
                           "none": {"total_return": 0.5, "profit_factor": 1.4, "max_drawdown": 0.15, "giveback_share_reached_closed_negative": 0.5,
                                    "giveback_n_reached": 22, "giveback_avg_giveback_pct": 0.04}},
        "entry_sized_only": {"total_return": 0.55, "max_drawdown": 0.14, "calmar": 0.7},
        "acceptance": acc,
        "holdout": holdout if passed else None,  # the runner evaluates the holdout only for passers
        "notes": ["a note"],
    }


def test_gates_each_flip_the_verdict():
    good = acceptance_check_v1b(GOOD_OOS, YEARLY, {"share_above_threshold": 0.8})
    assert good["passed"] and good["failed"] == [] and good["positive_years"] == 4 and good["years_total"] == 5
    for key, value, gate in (("profit_factor", 1.1, "pf_gt_1_2"), ("max_drawdown", 0.25, "max_dd_lt_20pct"), ("sharpe", 0.5, "sharpe_gt_0_7"),
                             ("calmar", 0.4, "calmar_gt_0_5"), ("n_trades", 20, "enough_trades")):
        bad = acceptance_check_v1b(dict(GOOD_OOS, **{key: value}), YEARLY, {"share_above_threshold": 0.8})
        assert not bad["passed"] and bad["failed"] == [gate]
    assert acceptance_check_v1b(GOOD_OOS, YEARLY, {"share_above_threshold": 0.4})["failed"] == ["robust_pm30pct"]
    assert acceptance_check_v1b(GOOD_OOS, {2021: 0.1, 2022: -0.1, 2023: -0.1, 2024: 0.2, 2025: 0.1}, {"share_above_threshold": 0.8})["failed"] == ["positive_in_4_of_5_years"]
    assert not acceptance_check_v1b(GOOD_OOS, {}, {"share_above_threshold": 0.8})["positive_in_4_of_5_years"]
    assert GATES["max_drawdown_max"] == 0.20 and GATES["calmar_min"] == 0.5


def test_shortlist_ranks_passed_then_calmar_and_skips_references():
    results = [
        _result("S2", "ETH-USDT", "4H"),
        _result("S4", "BTC-USDT", "6H", oos={"calmar": 0.4, "sharpe": 0.9}, passed=False),
        _result("S1", "BTC-USDT", "4H", oos={"calmar": 0.95, "sharpe": 0.8, "max_drawdown": 0.22}, passed=False),
        _result("hold", "BTC-USDT", "4H"),
        _result("S3", "ETH-USDT", "4H", oos={"profit_factor": 0.9}, passed=False),
        _result("baseline", "BTC-USDT", "4H", oos={"n_trades": 12}, passed=False),
    ]
    sl = shortlist(results)
    assert [r["candidate"] for r in sl] == ["S2", "S1", "S4"]  # passed first, then Calmar; hold/PF<1/too few trades excluded
    assert sl[0]["rank"] == 1 and sl[0]["passed"] and sl[1]["failed_gates"] == ["max_dd_lt_20pct"]
    assert sl[0]["sizing"].startswith("vt15") and sl[0]["bracket"] == "trail1"


def _run(results):
    return {
        "meta": {"generated_at": "2026-10-21 10:00 UTC", "data_span": "BTC-USDT 4H: 2019-12-16->2026-10-20 (14999 bars)", "data_span_short": "2019-12->2026-10",
                 "holdout_span": "2025-10-18->2026-10-18", "holdout_months": 12, "fee_rate": 0.001, "slippage_rate": 0.0005, "train_days": 540,
                 "test_days": 180, "purge_days": 7, "select_by": "sharpe", "min_trades": 20, "positioning_source": "binance",
                 "sizing": {"grid_size": 390, "dd_cap": 0.15, "select_by": "calmar", "min_trades": 10, "rebalance_threshold": 0.25,
                            "ladder": {"half_dd": 0.05, "flat_dd": 0.10, "recovery_days": 30}, "targets": [0.1, 0.15], "lookbacks": [20, 30],
                            "fixed": [0.25, 0.5, 1.0], "crash": [[0.1, 90.0]]},
                 "bracket_variants": ["none", "tp3", "trail1"]},
        "benchmark": [{"instrument": "ETH-USDT", "timeframe": "4H", "total_return": 0.56, "cagr": 0.11, "sharpe": 0.4, "max_drawdown": 0.81, "calmar": 0.14}],
        "results": results,
        "failures": [{"candidate": "S3", "instrument": "BTC-USDT", "timeframe": "6H", "error": "ValueError: boom"}],
        "positioning": {"ETH-USDT": {"source": "binance", "funding_span": "2019-11-27->2026-10-20 (7558 rows)", "funding_coverage": 1.0,
                                     "oi_span": "2021-12-01->2026-10-19", "oi_coverage": 0.67}},
        "positioning_note": "note",
        "sizing_study": {"n": 1, "rows": [{"candidate": "S2", "instrument": "ETH-USDT", "timeframe": "4H", "bracket": "trail1", "sizing": "vt15/30",
                                            "full_cagr": 0.18, "full_dd": 0.5, "full_calmar": 0.36, "sized_cagr": 0.11, "sized_dd": 0.12, "sized_calmar": 0.9,
                                            "sweep_best": "vt10/60"}],
                         "full_dd_median": 0.5, "sized_dd_median": 0.12, "full_cagr_median": 0.18, "sized_cagr_median": 0.11,
                         "full_calmar_median": 0.36, "sized_calmar_median": 0.9, "note": "n."},
        "portfolios": [{"name": "S2+S4 x BTC+ETH, equal capital", "weights": {"S2/ETH/4H": 0.5, "S4/BTC/4H": 0.5}, "ladder": None,
                        "metrics": {"cagr": 0.09, "sharpe": 1.0, "max_drawdown": 0.1, "calmar": 0.9}, "diversification_ratio": 1.3,
                        "yearly": {2022: -0.01, 2023: 0.1}}],
        "portfolio_correlation": {"S2/ETH/4H": {"S2/ETH/4H": 1.0, "S4/BTC/4H": 0.2}, "S4/BTC/4H": {"S2/ETH/4H": 0.2, "S4/BTC/4H": 1.0}},
        "portfolio_note": "sleeve note",
        "next_step": "Next step: do X.",
    }


def test_executive_summary_and_rendering_with_a_pass():
    run = _run([_result(), _result("hold", "ETH-USDT", "4H")])
    bullets = executive_summary(run)
    assert len(bullets) == 5 and "1 of 1 configurations passed" in bullets[1] and "S2 on ETH-USDT 4H" in bullets[1]
    assert "Best so far" in bullets[2] and "holding ETH" in bullets[2]
    assert "median worst drawdown from 50.0% to 12.0%" in bullets[3]
    assert "simply staying long ETH (4H) with the same sizing machinery" in bullets[3]
    assert "Portfolio and next step" in bullets[4] and bullets[4].endswith("Next step: do X.")
    text = render_report_v1b(run)
    for needle in ("# Ensemble v1b", "## Executive summary", "| S2 | ETH-USDT 4H | vt15/30 crash15/90dh ladder | trail1 |", "**PASS**",
                   "## Paper-fleet shortlist", "| 1 | S2 |", "## Sizing study", "## Portfolio combination", "S2+S4 x BTC+ETH, equal capital",
                   "Correlation of daily sleeve returns", "## Positioning data", "| ETH-USDT | binance |", "**Holdout (2025-10-18->2026-10-18)",
                   "Drawdown ladder (chosen sizing", "Exit bracket `trail1` vs none", "Entry-sized only", "- a note", "S3 on BTC-USDT 6H: `ValueError: boom`",
                   "Nothing here authorizes", "passive always-long references"):
        assert needle in text, needle


def test_executive_summary_when_nothing_passes():
    run = _run([_result(oos={"max_drawdown": 0.3, "calmar": 0.3}, passed=False), _result("S4", "BTC-USDT", "6H", oos={"sharpe": 0.2}, passed=False)])
    run["portfolios"] = []
    bullets = executive_summary(run)
    assert "None of the 2 configurations passed" in bullets[1] and "max drawdown under 20%" in bullets[1]
    assert "It still misses" in bullets[2]
    assert bullets[4].startswith("**Next step.** Next step: do X.")
    text = render_report_v1b(run)
    assert "Configurations passing all gates: **0** of 2" in text and "Holdout: untouched" in text
