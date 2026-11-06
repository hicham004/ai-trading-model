"""Sprint 2c gates (rolling-12-month yearly gate), shortlist file, studies, executive summary and report rendering."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.report_v1c import (
    GATES,
    SHORTLIST_STATUS,
    acceptance_check_v1c,
    calendar_year_returns,
    controls,
    executive_summary,
    regime_study,
    render_report_v1c,
    rolling_12m_returns,
    shortlist,
    turnover_study,
    write_shortlist_file,
    yearly_gate_v2,
)

GOOD_OOS = {"profit_factor": 1.6, "max_drawdown": 0.12, "sharpe": 1.1, "calmar": 0.9, "n_trades": 45, "total_return": 0.6, "cagr": 0.11,
            "sortino": 1.5, "win_rate": 0.4, "exposure": 0.5, "avg_allocation": 0.3, "fees_pct_per_year": 0.02, "windows": 9,
            "windows_traded": 9, "windows_positive": 6, "gate_blocked_share": 0.1, "trades_per_year": 12.0}
GOOD_YEARLY = {"rolling_windows": 40, "rolling_positive_share": 0.9, "rolling_min": -0.02, "rolling_median": 0.1,
               "calendar_years": {2021: 0.1, 2022: -0.05, 2023: 0.2}, "worst_calendar_year": 2022, "worst_calendar_year_return": -0.05}


def _equity(years: int = 4, drift: float = 0.0004, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=years * 365 * 6, freq="4h", tz="UTC")
    return pd.Series(np.exp(np.cumsum(rng.normal(drift, 0.004, len(idx)))), index=idx)


def test_rolling_12m_and_calendar_years():
    eq = pd.Series(np.linspace(1.0, 2.0, 365 * 3 + 1), index=pd.date_range("2021-01-01", periods=365 * 3 + 1, freq="D", tz="UTC"))
    rolling = rolling_12m_returns(eq)
    assert len(rolling) >= 20 and (rolling > 0).all() and rolling.index[0] >= eq.index[0] + pd.Timedelta(days=365)
    years = calendar_year_returns(eq)
    assert set(years) == {2021, 2022, 2023}
    stub = pd.Series([1.0, 1.1], index=pd.date_range("2021-12-30", periods=2, freq="D", tz="UTC"))
    assert calendar_year_returns(pd.concat([stub, eq.iloc[1:]])) .get(2021) is not None  # 2021 is a full year here
    assert 2021 not in calendar_year_returns(stub)  # a two-day stub is not judged
    gate = yearly_gate_v2(eq)
    assert gate["rolling_positive_share"] == 1.0 and gate["worst_calendar_year_return"] > 0
    assert rolling_12m_returns(pd.Series(dtype=float)).empty and calendar_year_returns(pd.Series(dtype=float)) == {}


def test_gates_each_flip_the_verdict():
    good = acceptance_check_v1c(GOOD_OOS, GOOD_YEARLY, {"share_above_threshold": 0.8})
    assert good["passed"] and good["failed"] == []
    for key, value, gate in (("profit_factor", 1.1, "pf_gt_1_2"), ("max_drawdown", 0.25, "max_dd_lt_20pct"), ("sharpe", 0.5, "sharpe_gt_0_7"),
                             ("calmar", 0.4, "calmar_gt_0_5"), ("n_trades", 20, "enough_trades")):
        bad = acceptance_check_v1c(dict(GOOD_OOS, **{key: value}), GOOD_YEARLY, {"share_above_threshold": 0.8})
        assert not bad["passed"] and bad["failed"] == [gate]
    assert acceptance_check_v1c(GOOD_OOS, GOOD_YEARLY, {"share_above_threshold": 0.4})["failed"] == ["robust_pm30pct"]
    assert acceptance_check_v1c(GOOD_OOS, dict(GOOD_YEARLY, rolling_positive_share=0.6), {"share_above_threshold": 0.8})["failed"] == ["rolling_12m_75pct_positive"]
    assert acceptance_check_v1c(GOOD_OOS, dict(GOOD_YEARLY, worst_calendar_year_return=-0.2), {"share_above_threshold": 0.8})["failed"] == ["no_calendar_year_below_minus_10pct"]
    assert acceptance_check_v1c(GOOD_OOS, dict(GOOD_YEARLY, rolling_windows=2), {"share_above_threshold": 0.8})["failed"] == ["rolling_12m_75pct_positive"]
    assert GATES["rolling_12m_positive_min"] == 0.75 and GATES["worst_calendar_year_min"] == -0.10


def _result(candidate="S2", instrument="ETH-USDT", timeframe="4H", mode="gate", oos=None, passed=True, yearly=None):
    oos = dict(GOOD_OOS, **(oos or {}))
    acc = acceptance_check_v1c(oos, GOOD_YEARLY, {"share_above_threshold": 0.8})
    assert acc["passed"] == passed
    return {
        "candidate": candidate, "label": "label", "instrument": instrument, "timeframe": timeframe,
        "regime": {"mode": mode, "label": "hmm3 bear>=0.5 gate" if mode == "gate" else ("hmm3 bear>=0.5 scale0.25" if mode == "scale" else "no regime gate"),
                   "bear_prob_max": 0.5, "n_states": 3, "vol_window_days": 7.0},
        "policy_sizing": {"label": "vt10/30 crash15/90dh ladder"}, "grid_size": 100,
        "selected_params": {"entry_days": 10, "bracket": "none", "funding_z_window": 21}, "rule_frequency": {},
        "oos": oos, "yearly": yearly or {2021: 0.1, 2022: -0.05, 2023: 0.2}, "yearly_gate": GOOD_YEARLY,
        "robustness": {"best": 0.6, "median": 0.4, "min": 0.1, "share_above_threshold": 0.8, "n_neighbours": 8},
        "dsr": {"n_trials": 60, "expected_max_sr": 0.02, "observed_sr": 0.03, "dsr": 0.6},
        "montecarlo": {"n_trades": 45, "paths": 100, "terminal_p05": 0.9, "terminal_p50": 1.3, "terminal_p95": 1.8, "prob_loss": 0.1, "max_dd_p50": 0.1, "max_dd_p95": 0.2},
        "slippage_stress": {"x1": 0.6, "x2": 0.5, "x3": 0.4}, "full_size": {"total_return": 1.2, "max_drawdown": 0.5, "calmar": 0.4},
        "comparison": {"cagr": 0.08, "max_drawdown": 0.15, "calmar": 0.5}, "comparison_frequency": {"vt15/30 crash15/90dh ladder": 7},
        "regime_train_bear_share_median": 0.2, "regime_test_bear_share_median": 0.25, "positioning_coverage": 0.9,
        "acceptance": acc, "windows": [], "notes": ["a note"],
        "holdout": {"total_return": 0.05, "cagr": 0.05, "sharpe": 0.5, "profit_factor": 1.1, "max_drawdown": 0.08, "calmar": 0.6, "n_trades": 9} if passed else None,
    }


def test_shortlist_controls_and_file(tmp_path):
    results = [
        _result("S2", mode="gate"),
        _result("S4", instrument="BTC-USDT", mode="none", oos={"calmar": 0.3, "sharpe": 0.4}, passed=False),
        _result("hold", instrument="BTC-USDT", mode="none", oos={"calmar": 0.45, "sharpe": 0.6}, passed=False),
        _result("S1", instrument="BTC-USDT", mode="scale", oos={"profit_factor": 0.9}, passed=False),
        _result("S3", instrument="BTC-USDT", mode="none", oos={"n_trades": 10}, passed=False),
    ]
    rows = shortlist(results)
    assert [r["candidate"] for r in rows] == ["S2", "S4"] and rows[0]["rank"] == 1 and rows[0]["passed"]
    assert rows[0]["regime"].endswith("gate") and rows[0]["sizing"].startswith("vt10")
    benchmark = [{"instrument": "BTC-USDT", "timeframe": "4H", "cagr": 0.3, "sharpe": 0.7, "calmar": 0.4, "max_drawdown": 0.77, "total_return": 2.0}]
    ctrl = controls(results, benchmark)
    assert [c["candidate"] for c in ctrl] == ["hold", "buy_and_hold"] and ctrl[0]["role"].startswith("control")
    run = {"meta": {"generated_at": "now", "report_path": "r.md", "policy_sizing": {"label": "p"}}, "shortlist": rows, "controls": ctrl}
    path = tmp_path / "shortlist.json"
    write_shortlist_file(path, run)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == SHORTLIST_STATUS and len(payload["configurations"]) == 2 and len(payload["controls"]) == 2
    assert payload["configurations"][0]["params"]["entry_days"] == 10


def test_studies_and_report_render():
    results = [
        _result("S1", instrument="BTC-USDT", mode="none", oos={"calmar": 0.2, "fees_pct_per_year": 0.03}, passed=False, yearly={2021: 0.1, 2022: -0.2, 2023: 0.2}),
        _result("S1", instrument="BTC-USDT", mode="gate", oos={"calmar": 0.6}, yearly={2021: 0.1, 2022: -0.02, 2023: 0.2}),
        _result("S1", instrument="BTC-USDT", mode="scale", oos={"calmar": 0.4, "sharpe": 0.6}, passed=False),
        _result("S1w", instrument="BTC-USDT", mode="none", oos={"calmar": 0.3, "fees_pct_per_year": 0.01, "sharpe": 0.5}, passed=False),
        _result("S1+S5s", instrument="BTC-USDT", mode="none", oos={"calmar": 0.25, "sharpe": 0.5}, passed=False),
        _result("hold", instrument="BTC-USDT", mode="none", oos={"calmar": 0.35, "sharpe": 0.5}, passed=False),
    ]
    study = regime_study(results)
    assert study["n"] == 1 and study["rows"][0]["none_2022"] == -0.2 and study["rows"][0]["gate_2022"] == -0.02
    assert study["gate_calmar_median"] == 0.6 and study["gate_wins_calmar"] == 1 and "verdict" in study
    turn = turnover_study(results, {"S1w": "S1"})
    assert turn["n"] == 1 and turn["rows"][0]["base_fees"] == 0.03 and turn["variant_fees_median"] == 0.01
    assert regime_study([]) == {"n": 0, "rows": []} and turnover_study([], {"S1w": "S1"}) == {"n": 0, "rows": []}
    run = {
        "meta": {"generated_at": "2026-10-20 20:00 UTC", "data_span": "BTC-USDT 4H: 2019->2026", "data_span_short": "2019->2026", "holdout_span": "2025->2026",
                 "holdout_months": 12, "fee_rate": 0.001, "slippage_rate": 0.0005, "train_days": 540, "test_days": 180, "purge_days": 7, "select_by": "sharpe",
                 "min_trades": 20, "policy_sizing": {"label": "vt10/30 crash15/90dh ladder"}, "regime": {"label": "hmm3 bear>=0.5 gate", "n_states": 3,
                 "vol_window_days": 7.0, "bear_prob_max": 0.5}, "n_regime_modes": 3, "no_trade_label": "S0 FOMC", "bracket_variants": ["none", "tp2"],
                 "shortlist_path": "x.json"},
        "benchmark": [{"instrument": "BTC-USDT", "timeframe": "4H", "total_return": 1.7, "cagr": 0.26, "sharpe": 0.7, "max_drawdown": 0.77, "calmar": 0.34}],
        "results": results, "failures": [{"candidate": "S3", "instrument": "BTC-USDT", "timeframe": "4H", "regime": "none", "error": "boom"}],
        "regime_study": study, "regime_sensitivity": [{"candidate": "S1", "instrument": "BTC-USDT", "timeframe": "4H", "bear_prob_max": 0.35, "cagr": 0.05,
                                                       "max_drawdown": 0.1, "calmar": 0.5, "sharpe": 0.6, "n_trades": 40, "y2022": -0.01}],
        "turnover_study": turn, "s5_study": [{"variant": "S1+S5s", "instrument": "BTC-USDT", "timeframe": "4H", "regime": "none", "base": GOOD_OOS,
                                              "s5_long": None, "s5_short": GOOD_OOS, "params": {"funding_z_window": 21}, "coverage": 0.9}],
        "portfolios": [{"name": "S1+S2+S4 x BTC+ETH — jointly sized", "weights": {"a": 0.5, "b": 0.5}, "regime": "gate",
                        "metrics": {"cagr": 0.06, "sharpe": 0.8, "max_drawdown": 0.1, "calmar": 0.6}, "avg_scale": 0.7, "pooled_trades": 120,
                        "pooled_profit_factor": 1.3, "acceptance": acceptance_check_v1c(dict(GOOD_OOS, profit_factor=1.3, n_trades=120), GOOD_YEARLY, {"share_above_threshold": 1.0})}],
        "portfolio_correlation": {"a": {"a": 1.0, "b": 0.2}, "b": {"a": 0.2, "b": 1.0}},
        "shortlist": shortlist(results), "controls": controls(results, [{"instrument": "BTC-USDT", "timeframe": "4H", "cagr": 0.26, "sharpe": 0.7, "calmar": 0.34, "max_drawdown": 0.77, "total_return": 1.7}]),
        "next_step": "Do X.", "owner_decisions": ["Decide Y."],
    }
    bullets = executive_summary(run)
    assert len(bullets) == 5 and bullets[1].startswith("**Result.**") and "1 of 5" in bullets[1] and "2022" in bullets[3]
    text = render_report_v1c(run)
    for needle in ("# Ensemble v1c", "## Executive summary", "## Gates", "**PASS**", "## Regime v2 as an entry gate", "## Portfolio-level sizing",
                   "## Lower-turnover variants", "## Positioning filter re-test", "## Paper-fleet shortlist", "forward evidence only", "control",
                   "## Owner decisions", "Decide Y.", "Do X.", "boom", "Gate-threshold sensitivity", "## Method notes"):
        assert needle in text, needle
    empty = dict(run, results=[r for r in results if r["candidate"] == "hold"], regime_study={"n": 0, "rows": []}, turnover_study={"n": 0, "rows": []},
                 shortlist=[], portfolios=[], s5_study=[], regime_sensitivity=[])
    assert "No configuration qualifies" in render_report_v1c(empty)
    assert executive_summary(empty)[2].startswith("**Best so far.** No configuration")
