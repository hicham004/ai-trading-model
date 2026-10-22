"""Phase 9 study report (plan row R9): every plain-English sentence follows the numbers it states."""

from __future__ import annotations

import json

from research.report_longshort import executive_summary, render_report, study_facts


def _result(cand, inst, tf, variant, *, calmar, lo_calmar, short_pf, y22, lo22, passed=False, rule=False, holdout=None, confirmed=None,
            short_funding=50.0, long_funding=0.0):
    return {
        "candidate": cand, "instrument": inst, "timeframe": tf, "variant": variant, "grid_size": 4, "selected_params": {"a": 1},
        "oos": {"total_return": 0.1, "cagr": 0.02 + calmar / 100, "sharpe": 0.5, "profit_factor": 1.2, "max_drawdown": 0.1,
                "calmar": calmar, "n_trades": 100, "windows": 9, "windows_traded": 9, "windows_positive": 5},
        "yearly": {"2021": 0.01, "2022": y22, "2023": 0.02},
        "yearly_gate": {"rolling_windows": 40, "rolling_positive_share": 0.6, "worst_calendar_year": 2022, "worst_calendar_year_return": y22},
        "robustness": {"best": 0.1, "median": 0.08, "min": 0.01, "share_above_threshold": 0.9, "n_neighbours": 10},
        "dsr": {"dsr": 0.2, "n_trials": 144}, "montecarlo": {"paths": 10, "n_trades": 100},
        "stress": {"slippage_x1": 0.1, "slippage_x2": 0.08, "slippage_x3": 0.06, "funding_x0": 0.09, "funding_x2": 0.11},
        "legs": {"long": {"n_trades": 50, "pnl": 500.0, "profit_factor": 1.3, "funding": long_funding, "liquidations": 0},
                 "short": {"n_trades": 50, "pnl": 100.0 if short_pf > 1 else -100.0, "profit_factor": short_pf, "win_rate": 0.4,
                           "funding": short_funding, "worst_return_pct": -0.1, "worst_mae_pct": -0.12, "liquidations": 0}},
        "short_share": 0.3, "max_leverage": 0.8, "funding_total_pct": 0.005,
        "acceptance": {"passed": passed, "failed": [] if passed else ["sharpe_gt_0_7"]},
        "phase9_rule": {"v1c_gates": passed, "short_leg_pf_gt_1": short_pf > 1, "beats_long_only_calmar": calmar > lo_calmar,
                        "walk_forward_passed": rule},
        "long_only": {"oos": {"calmar": lo_calmar, "cagr": 0.02}, "yearly": {"2022": lo22}},
        "perp_priced": {"calmar": calmar + 0.01}, "diagnostic_short_no_crash_filter": {"calmar": calmar - 0.1, "legs": {"short": {"profit_factor": 0.9}}},
        "holdout": holdout, "holdout_confirmed": confirmed, "notes": [],
    }


def _run(results, *, ledger=None):
    return {
        "meta": {"generated_at": "2026-10-22 03:00 UTC", "config": {"policy_sizing": "vt10/30 crash15/90dh ladder", "funding_source": "binance"},
                 "preregistration": {"question": "q"}, "preregistration_sha256": "abc", "post_hoc": [], "review_fixes": [{"what": "w", "effect": "e"}],
                 "holdout_ledger": ledger or []},
        "series": [{"instrument": "BTC-USDT", "timeframe": "4H", "span": "s", "holdout_span": "2025-10-20->2026-10-20", "reproduction": [],
                    "results": results, "defaults": {}}],
        "descriptive": {"BTC-USDT": {"funding_span_summary": {"annualized_mean": 0.13}, "adverse_moves_spot": {"720h": {"max": 1.3, "at": "2020-12-11",
                                                                                                                  "share_ge_liquidation": 0.004}}},
                        "ETH-USDT": {"funding_span_summary": {"annualized_mean": 0.15}}},
    }


def _pairs(n_better: int, n: int = 4, *, short_pf_win: int = 1):
    out = []
    for k in range(n):
        better = k < n_better
        spf = 1.2 if k < short_pf_win else 0.8
        out.append(_result("S1", "BTC-USDT" if k % 2 == 0 else "ETH-USDT", "4H" if k < 2 else "6H", "hybrid", calmar=0.5 if better else 0.1,
                           lo_calmar=0.3, short_pf=spf, y22=0.01, lo22=-0.03))
        out.append(_result("S1", "BTC-USDT" if k % 2 == 0 else "ETH-USDT", "4H" if k < 2 else "6H", "perp", calmar=0.4 if better else 0.05,
                           lo_calmar=0.3, short_pf=spf, y22=0.01, lo22=-0.03, long_funding=-300.0))
    return out


def test_the_answer_follows_the_counts():
    text = "\n".join(executive_summary(_run(_pairs(1))))
    assert "**Did the short side help?** Mostly not." in text
    text = "\n".join(executive_summary(_run(_pairs(3))))
    assert "**Did the short side help?** Mostly yes." in text
    text = "\n".join(executive_summary(_run(_pairs(2))))
    assert "In half of the cases." in text


def test_funding_and_design_sentences_follow_their_numbers():
    text = "\n".join(executive_summary(_run(_pairs(1))))
    assert "Funding flowed mostly from longs to shorts" in text
    assert "the long side should stay on spot" in text  # the hybrid had the higher CAGR in every pair
    run = _run(_pairs(1))
    run["descriptive"]["BTC-USDT"]["funding_span_summary"]["annualized_mean"] = -0.02
    assert "Funding flowed both ways" in "\n".join(executive_summary(run))


def test_the_verdict_counts_rules_not_designs_and_names_a_contradiction():
    rows = _pairs(1)
    conf = {"total_return": 0.04, "profit_factor": 2.4, "n_trades": 14, "legs": {"short": {"n_trades": 6}}}
    contra = {"total_return": -0.05, "profit_factor": 0.6, "n_trades": 40, "legs": {"short": {"n_trades": 20}}}
    rows.append(_result("S2", "ETH-USDT", "6H", "hybrid", calmar=0.6, lo_calmar=0.36, short_pf=1.2, y22=0.02, lo22=-0.02, passed=True, rule=True,
                        holdout=conf, confirmed=True))
    rows.append(_result("S2", "ETH-USDT", "6H", "perp", calmar=0.55, lo_calmar=0.36, short_pf=1.2, y22=0.02, lo22=-0.02, passed=True, rule=True,
                        holdout=conf, confirmed=True))
    rows.append(_result("S2", "ETH-USDT", "4H", "hybrid", calmar=0.66, lo_calmar=0.41, short_pf=1.1, y22=0.02, lo22=-0.01, passed=True, rule=True,
                        holdout=contra, confirmed=False))
    f = study_facts(_run(rows))
    assert f["confirmed_rules"] == [("S2", "ETH-USDT", "6H")] and f["confirmed_designs"][("S2", "ETH-USDT", "6H")] == ["hybrid", "perp"]
    text = "\n".join(executive_summary(_run(rows)))
    assert "1 rule counts as evidence: S2 ETH-USDT 6H (hybrid and perp)" in text
    assert "the holdout contradicted S2 ETH-USDT 4H" in text and "traded 6 times" in text and "Not enough to advance Phase 9" in text


def test_without_a_confirmation_the_verdict_says_so():
    text = "\n".join(executive_summary(_run(_pairs(1))))
    assert "no configuration counts as evidence for Phase 9" in text
    assert "The short legs lost money in most configurations" in text


def test_the_report_renders_the_ledger_and_the_review_fixes():
    ledger = [{"generated_at": "run-1", "note": "first run, before the fix", "openings": [
        {"configuration": "S2 ETH-USDT 6H hybrid", "total_return": 0.04, "max_drawdown": 0.02, "profit_factor": 2.4, "n_trades": 14, "confirmed": True}]}]
    md = render_report(json.loads(json.dumps(_run(_pairs(1), ledger=ledger))))
    assert "### Every opening of the holdout (ledger)" in md and "| 1 (run-1) | S2 ETH-USDT 6H hybrid |" in md
    assert "first run, before the fix" in md
    assert "Fixed after the first full run" in md and "- w (e)" in md
    assert "## Method notes and caveats" in md and "inside the holdout window" in md
