"""Render the honest research report (Markdown) from runner results (plain dicts)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

import math

import pandas as pd

ACCEPTANCE = {
    "profit_factor_min": 1.2,
    "positive_years_min": 3,
    "max_drawdown_max": 0.20,
    "robust_share_min": 0.5,
}


def _f(value: Any, fmt: str = "{:.2f}") -> str:
    if value is None:
        return "-"
    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "∞" if value == math.inf else "-"
        return fmt.format(value)
    except (TypeError, ValueError):
        return str(value)


def _pct(value: Any) -> str:
    """Signed percentage (returns)."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "-"
    return f"{value * 100:+.1f}%"


def _share(value: Any) -> str:
    """Unsigned percentage (drawdowns, rates, shares)."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "-"
    return f"{value * 100:.1f}%"


def acceptance_check(oos: Mapping[str, Any], yearly: Mapping[str, float], robust: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply the master-plan Sprint 2 acceptance criteria to one candidate."""
    positive_years = sum(1 for v in yearly.values() if v is not None and v > 0)
    years_total = len(yearly)
    pf = oos.get("profit_factor", 0.0) or 0.0
    mdd = oos.get("max_drawdown", 1.0)
    share = robust.get("share_above_threshold", 0.0) or 0.0
    checks = {
        "pf_gt_1_2": bool(pf > ACCEPTANCE["profit_factor_min"]),
        "positive_in_3_of_4_years": bool(positive_years >= min(ACCEPTANCE["positive_years_min"], max(1, years_total - 1))) if years_total else False,
        "max_dd_lt_20pct": bool(mdd < ACCEPTANCE["max_drawdown_max"]),
        "robust_pm30pct": bool(share >= ACCEPTANCE["robust_share_min"]),
        "enough_trades": bool((oos.get("n_trades", 0) or 0) >= 30),
    }
    checks["passed"] = all(checks.values())
    checks["positive_years"] = positive_years
    checks["years_total"] = years_total
    return checks


def render_report(run: Mapping[str, Any]) -> str:
    """``run`` is the JSON-serializable structure produced by ``scripts/run_research.py``."""
    lines: List[str] = []
    meta = run["meta"]
    lines += [
        "# Ensemble v1 — walk-forward research report (SIMULATION ONLY)",
        "",
        f"Generated {meta['generated_at']} by `scripts/run_research.py`. Data: PUBLIC OKX spot candles from the "
        f"Parquet lake ({meta['data_span']}). Costs: fee {meta['fee_rate'] * 100:.2f}% per side + slippage "
        f"{meta['slippage_rate'] * 100:.3f}% per side. Sizing: {meta['size_fraction'] * 100:.0f}% of equity per entry "
        "(gross edge; production sizing is smaller). Long-only spot. Walk-forward: train "
        f"{meta['train_days']}d → purge {meta['purge_days']}d → test {meta['test_days']}d, rolling; selection by "
        f"{meta['select_by']} with ≥{meta['min_trades']} train trades. Holdout: last {meta['holdout_months']} months "
        f"({meta['holdout_span']}), evaluated once and only for candidates that passed walk-forward.",
        "",
        "**Nothing here authorizes paper, demo or live trading.** A passing candidate is a hypothesis for the "
        "forward paper fleet (Sprint 5), not a strategy to deploy.",
        "",
        "## Acceptance criteria (master plan, Sprint 2)",
        "",
        f"- Out-of-sample profit factor > {ACCEPTANCE['profit_factor_min']} after costs",
        f"- Positive in ≥ {ACCEPTANCE['positive_years_min']} of 4 yearly out-of-sample windows",
        f"- Max drawdown < {ACCEPTANCE['max_drawdown_max'] * 100:.0f}%",
        f"- Not dependent on one parameter: ≥ {ACCEPTANCE['robust_share_min'] * 100:.0f}% of grid neighbours within ±30% stay profitable",
        "- At least 30 out-of-sample trades",
        "",
        "## Summary",
        "",
        "| Candidate | Series | OOS return | CAGR | Sharpe | Sortino | PF | Max DD | Trades | Win | Exposure | Fees/yr | Pos. years | Robust ±30% | DSR | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for r in run["results"]:
        oos = r["oos"]
        acc = r["acceptance"]
        lines.append(
            f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {_pct(oos.get('total_return'))} | {_pct(oos.get('cagr'))} | "
            f"{_f(oos.get('sharpe'))} | {_f(oos.get('sortino'))} | {_f(oos.get('profit_factor'))} | {_share(oos.get('max_drawdown'))} | "
            f"{oos.get('n_trades', 0)} | {_share(oos.get('win_rate'))} | {_share(oos.get('exposure'))} | {_share(oos.get('fees_pct_per_year'))} | "
            f"{acc['positive_years']}/{acc['years_total']} | {_share(r['robustness'].get('share_above_threshold'))} | "
            f"{_f(r['dsr'].get('dsr'))} | {'**PASS**' if acc['passed'] else 'fail'} |"
        )
    passed = [r for r in run["results"] if r["acceptance"]["passed"]]
    lines += ["", f"Candidates passing all criteria: **{len(passed)}** of {len(run['results'])}.", ""]
    if run.get("failures"):
        lines += ["Runs that failed with an error (not evaluated):", ""]
        for f in run["failures"]:
            lines.append(f"- {f['candidate']} on {f['instrument']} {f['timeframe']}: `{f['error']}`")
        lines.append("")
    if run.get("benchmark"):
        lines += ["Buy-and-hold over the same out-of-sample span (after costs):", ""]
        for b in run["benchmark"]:
            lines.append(f"- {b['instrument']} {b['timeframe']}: {_pct(b['total_return'])} total, max DD {_share(b['max_drawdown'])}")
        lines.append("")

    for r in run["results"]:
        oos = r["oos"]
        lines += [f"## {r['candidate']} — {r['label']} ({r['instrument']} {r['timeframe']})", ""]
        lines += [f"Grid: {r['grid_size']} combinations. Windows: {oos.get('windows')} ({oos.get('windows_traded')} traded, "
                  f"{oos.get('windows_positive')} positive). Most-selected parameters: `{r.get('selected_params')}`.", ""]
        if r.get("yearly"):
            lines += ["| Year | OOS return |", "|---|---:|"]
            for year, value in r["yearly"].items():
                lines.append(f"| {year} | {_pct(value)} |")
            lines.append("")
        if r.get("by_regime"):
            lines += ["| Regime | Share of time | OOS return | Sharpe |", "|---|---:|---:|---:|"]
            for row in r["by_regime"]:
                lines.append(f"| {row['regime']} | {_share(row['share'])} | {_pct(row['total_return'])} | {_f(row['sharpe'])} |")
            lines.append("")
        rb = r["robustness"]
        lines += [f"Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED "
                  f"parameters over every out-of-sample test window, no re-selection): selected set {_pct(rb.get('best'))}, "
                  f"neighbours median {_pct(rb.get('median'))}, min {_pct(rb.get('min'))}, share profitable "
                  f"{_share(rb.get('share_above_threshold'))} over {rb.get('n_neighbours')} neighbours.", ""]
        mc = r.get("montecarlo", {})
        if mc.get("n_trades"):
            lines += [f"Monte Carlo (trade-order bootstrap, {mc['paths']} paths over {mc['n_trades']} OOS trades): terminal growth "
                      f"p05 {_f(mc['terminal_p05'])}× / p50 {_f(mc['terminal_p50'])}× / p95 {_f(mc['terminal_p95'])}×, P(loss) "
                      f"{_share(mc['prob_loss'])}, max DD p50 {_share(mc['max_dd_p50'])}, p95 {_share(mc['max_dd_p95'])}.", ""]
        ss = r.get("slippage_stress", {})
        if ss:
            lines += ["Slippage stress (OOS total return with slippage ×1/×2/×3): " + ", ".join(f"{k}: {_pct(v)}" for k, v in ss.items()), ""]
        d = r["dsr"]
        lines += [f"Deflated Sharpe: {d.get('n_trials')} trials in the last train window, expected max SR (zero skill) "
                  f"{_f(d.get('expected_max_sr'), '{:.3f}')} per bar vs observed OOS {_f(d.get('observed_sr'), '{:.3f}')} → DSR {_f(d.get('dsr'))} "
                  "(probability the OOS Sharpe beats the best-of-N noise level).", ""]
        acc = r["acceptance"]
        lines += ["Checks: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in acc.items() if isinstance(v, bool) and k != "passed"), ""]
        if r.get("holdout"):
            h = r["holdout"]
            lines += [f"**Holdout ({meta['holdout_span']}), evaluated once with `{r.get('selected_params')}`:** return {_pct(h.get('total_return'))}, "
                      f"Sharpe {_f(h.get('sharpe'))}, PF {_f(h.get('profit_factor'))}, max DD {_share(h.get('max_drawdown'))}, trades {h.get('n_trades')}.", ""]
            if r.get("holdout_event_driven"):
                e = r["holdout_event_driven"]
                lines += [f"Event-driven cross-check on the holdout (reviewed simulator, same costs, full-equity sizing): return "
                          f"{_pct(e.get('total_return'))}, trades {e.get('n_trades')}, rejected entries {e.get('rejected_entries')} — "
                          f"difference vs vectorized engine {_pct(e.get('difference'))}.", ""]
        elif acc["passed"]:
            lines += ["Holdout: not evaluated in this run (`--evaluate-holdout` not set).", ""]
        else:
            lines += ["Holdout: untouched (candidate did not pass walk-forward).", ""]
        if r.get("notes"):
            for note in r["notes"]:
                lines.append(f"- {note}")
            lines.append("")

    lines += [
        "## Method notes and caveats",
        "",
        "- Engine: `research/engine.py`, next-bar-open execution, intrabar stop with conservative gap fills, fees and slippage per side, "
        "fixed ATR stop at entry, optional time stop; identical conventions to `app/backtest/simulator.py`.",
        "- S0 (no-trade filter: vol spike, extreme bar range, data gaps) gates every candidate's entries.",
        "- Walk-forward selection uses only the train slice; the purge gap removes boundary leakage; test slices are stitched. "
        "Each test window restarts from the same capital, so the stitched curve compounds window returns.",
        "- Robustness replays ±30% parameter perturbations with fixed parameters over the same test windows (no re-selection), "
        "so it measures how sensitive the out-of-sample result is to the chosen parameters.",
        "- Yearly windows are calendar years of the stitched out-of-sample curve; early years can be partial.",
        "- Deflated Sharpe follows Bailey & López de Prado (2014) using the per-bar Sharpe of every grid point tried in the last train window.",
        "- OKX 1D candles are UTC+8 aligned; 1H/4H are UTC aligned. Holdout = last 12 months of the stored data, evaluated once.",
        "- Derivatives features (S5) exist only for the months OKX serves on its public rubik endpoints; the filter passes where data are missing.",
        "- Every number is a simulation on historical public data and proves nothing about the future.",
        "",
    ]
    return "\n".join(lines)
