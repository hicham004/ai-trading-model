"""Sprint 2b report: risk-adjusted gates, paper-fleet shortlist, plain-English summary, Markdown rendering."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

GATES = {
    "profit_factor_min": 1.2,
    "max_drawdown_max": 0.20,
    "sharpe_min": 0.7,
    "calmar_min": 0.5,
    "positive_years_min": 4,
    "min_trades": 30,
    "robust_share_min": 0.5,
}
REFERENCE_CANDIDATES = ("hold",)  # passive references: shown, never shortlisted


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
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "-"
    return f"{value * 100:+.1f}%"


def _share(value: Any) -> str:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "-"
    return f"{value * 100:.1f}%"


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(v) else v


def acceptance_check_v1b(oos: Mapping[str, Any], yearly: Mapping[Any, float], robust: Mapping[str, Any]) -> Dict[str, Any]:
    """Sprint 2b risk-adjusted gates (master plan Sprint 2b item 8)."""
    positive_years = sum(1 for v in yearly.values() if v is not None and v > 0)
    years_total = len(yearly)
    need_years = min(GATES["positive_years_min"], max(1, years_total - 1)) if years_total else 1
    checks = {
        "pf_gt_1_2": bool(_num(oos.get("profit_factor")) > GATES["profit_factor_min"]),
        "max_dd_lt_20pct": bool(_num(oos.get("max_drawdown"), 1.0) < GATES["max_drawdown_max"]),
        "sharpe_gt_0_7": bool(_num(oos.get("sharpe")) > GATES["sharpe_min"]),
        "calmar_gt_0_5": bool(_num(oos.get("calmar")) > GATES["calmar_min"]),
        "positive_in_4_of_5_years": bool(years_total >= 2 and positive_years >= need_years),
        "enough_trades": bool(int(_num(oos.get("n_trades"))) >= GATES["min_trades"]),
        "robust_pm30pct": bool(_num(robust.get("share_above_threshold")) >= GATES["robust_share_min"]),
    }
    checks["passed"] = all(checks.values())
    checks["failed"] = [k for k, v in checks.items() if isinstance(v, bool) and not v and k != "passed"]
    checks["positive_years"] = positive_years
    checks["years_total"] = years_total
    return checks


def shortlist(results: Sequence[Mapping[str, Any]], *, n: int = 10) -> List[Dict[str, Any]]:
    """Rank configurations for the paper fleet: passed first, then Calmar, then Sharpe (PF > 1 and ≥ 30 trades required)."""
    rows = []
    for r in results:
        if r.get("candidate") in REFERENCE_CANDIDATES:
            continue
        variants = [("selected", r.get("oos", {}), r.get("acceptance", {}), (r.get("selected_sizing") or {}).get("label", "-"),
                     (r.get("selected_params") or {}).get("bracket", "-"), _num((r.get("dsr") or {}).get("dsr")))]
        pol = r.get("policy") or {}
        if pol:
            variants.append(("policy", pol.get("oos", {}), pol.get("acceptance", {}), "policy " + str((pol.get("sizing") or {}).get("label", "")),
                             (pol.get("selected_params") or {}).get("bracket", "-"), float("nan")))
        for mode, oos, acc, sizing, bracket, dsr in variants:
            if _num(oos.get("profit_factor")) <= 1.0 or int(_num(oos.get("n_trades"))) < GATES["min_trades"]:
                continue
            rows.append({
                "candidate": r["candidate"], "instrument": r["instrument"], "timeframe": r["timeframe"], "mode": mode,
                "sizing": sizing, "bracket": bracket,
                "cagr": _num(oos.get("cagr")), "sharpe": _num(oos.get("sharpe")), "calmar": _num(oos.get("calmar")),
                "max_drawdown": _num(oos.get("max_drawdown"), 1.0), "profit_factor": _num(oos.get("profit_factor")),
                "n_trades": int(_num(oos.get("n_trades"))), "passed": bool(acc.get("passed")), "failed_gates": list(acc.get("failed", [])),
                "dsr": dsr,
            })
    rows.sort(key=lambda x: (not x["passed"], -x["calmar"], -x["sharpe"]))
    for i, row in enumerate(rows[:n], start=1):
        row["rank"] = i
    return rows[:n]


def _gate_failure_counts(results: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in results:
        if r.get("candidate") in REFERENCE_CANDIDATES:
            continue
        for gate in (r.get("acceptance") or {}).get("failed", []):
            counts[gate] = counts.get(gate, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


GATE_LABELS = {
    "pf_gt_1_2": "profit factor above 1.2",
    "max_dd_lt_20pct": "max drawdown under 20%",
    "sharpe_gt_0_7": "Sharpe above 0.7",
    "calmar_gt_0_5": "Calmar above 0.5",
    "positive_in_4_of_5_years": "positive in 4 of 5 years",
    "enough_trades": "at least 30 trades",
    "robust_pm30pct": "robust to ±30% parameter changes",
}


def _bh_for(run: Mapping[str, Any], instrument: str, timeframe: str) -> Optional[Mapping[str, Any]]:
    for b in run.get("benchmark", []):
        if b.get("instrument") == instrument and b.get("timeframe") == timeframe:
            return b
    return None


def executive_summary(run: Mapping[str, Any]) -> List[str]:
    """Five plain-English bullets for a non-technical owner, generated from the numbers."""
    results = [r for r in run.get("results", []) if r.get("candidate") not in REFERENCE_CANDIDATES]
    meta = run.get("meta", {})
    n_runs = len(results)
    passed = [r for r in results if (r.get("acceptance") or {}).get("passed")]
    top = shortlist(results, n=3)
    bullets: List[str] = []

    sizing_n = (meta.get("sizing") or {}).get("grid_size", "many")
    brackets = len(meta.get("bracket_variants", []) or [])
    bullets.append(
        f"**What we did.** We took the Sprint 2 strategies and, instead of betting the whole account on every trade, let the "
        f"computer choose how much to risk: {sizing_n} sizing rules (volatility targeting, fixed fractions, a crash filter that "
        f"cuts exposure when the market is far below its recent high, and a drawdown ladder that halves and then stops trading "
        f"after losses) and {brackets} exit rules (take-profit, trailing stop, time stop). Every choice was made only on past "
        f"data, then tested on the following months, over {n_runs} strategy/market/timeframe combinations from "
        f"{meta.get('data_span_short', 'the stored history')} after fees and slippage."
    )

    policy_runs = [r for r in results if r.get("policy")]
    policy_passed = [r for r in policy_runs if (r["policy"].get("acceptance") or {}).get("passed")]
    policy_label = str(((policy_runs[0].get("policy") or {}).get("sizing") or {}).get("label", "")) if policy_runs else ""
    policy_text = ""
    if policy_runs:
        names_p = ", ".join(f"{r['candidate']} on {r['instrument']} {r['timeframe']}" for r in policy_passed[:4])
        policy_text = (f" With the fixed policy sizing `{policy_label}` (no sizing selection), {len(policy_passed)} of {len(policy_runs)} passed"
                       + (f": {names_p}." if policy_passed else "."))
    if passed:
        names = ", ".join(f"{r['candidate']} on {r['instrument']} {r['timeframe']} ({(r.get('selected_sizing') or {}).get('label', '')})" for r in passed[:4])
        bullets.append(f"**Result.** {len(passed)} of {n_runs} configurations passed every gate with the walk-forward-selected sizing: {names}.{policy_text} "
                       f"These are hypotheses for the forward paper fleet, not strategies to deploy.")
    else:
        counts = _gate_failure_counts(results)
        worst = ", ".join(f"{GATE_LABELS.get(k, k)} ({v} of {n_runs})" for k, v in list(counts.items())[:3])
        bullets.append(f"**Result.** None of the {n_runs} configurations passed all seven gates with the walk-forward-selected sizing. The gates most "
                       f"often missed were: {worst}.{policy_text} Nothing goes to demo or paper trading from this report.")

    if top:
        best = top[0]
        bh = _bh_for(run, best["instrument"], best["timeframe"]) or {}
        bullets.append(
            f"**Best so far.** {best['candidate']} on {best['instrument']} {best['timeframe']} with sizing `{best['sizing']}` and exit "
            f"`{best['bracket']}`: out-of-sample {_pct(best['cagr'])} per year with a worst drawdown of {_share(best['max_drawdown'])} "
            f"(Sharpe {_f(best['sharpe'])}, Calmar {_f(best['calmar'])}, {best['n_trades']} trades). Simply holding "
            f"{best['instrument'].split('-')[0]} over the same months made {_pct(bh.get('cagr'))} per year but with a "
            f"{_share(bh.get('max_drawdown'))} drawdown (Calmar {_f(bh.get('calmar'))})."
            + ("" if best["passed"] else f" It still misses: {', '.join(GATE_LABELS.get(g, g) for g in best['failed_gates'])}.")
        )
    else:
        bullets.append("**Best so far.** No configuration had a profit factor above 1.0 with at least 30 trades, so there is no lead candidate.")

    study = run.get("sizing_study") or {}
    holds = [r for r in run.get("results", []) if r.get("candidate") in REFERENCE_CANDIDATES and int(_num((r.get("oos") or {}).get("n_trades"))) > 0]
    hold_text = ""
    if holds:
        h = max(holds, key=lambda r: _num((r.get("oos") or {}).get("calmar")))
        ho = h.get("oos") or {}
        hold_text = (f" For comparison, simply staying long {h['instrument'].split('-')[0]} ({h['timeframe']}) with the same sizing machinery and no "
                     f"timing rule made {_pct(ho.get('cagr'))} per year with a {_share(ho.get('max_drawdown'))} drawdown (Sharpe {_f(ho.get('sharpe'))}, "
                     f"Calmar {_f(ho.get('calmar'))}) — a timing rule has to beat that to earn its place.")
    if study.get("n"):
        delta = _num(study.get("sized_calmar_median")) - _num(study.get("full_calmar_median"))
        if abs(delta) < 0.1:
            verdict = "In other words, sizing scaled risk and return down together; it made the strategies survivable but did not add edge."
        elif delta > 0:
            verdict = "In other words, sizing improved the risk-adjusted result, not only the drawdown."
        else:
            verdict = "In other words, sizing cost more return than it saved in drawdown on these rules."
        bullets.append(
            f"**What sizing bought us.** Across the {study['n']} runs with a lead rule, replaying the same rule all-in versus with the chosen sizing "
            f"moved the median worst drawdown from {_share(study.get('full_dd_median'))} to {_share(study.get('sized_dd_median'))}, the median "
            f"yearly return from {_pct(study.get('full_cagr_median'))} to {_pct(study.get('sized_cagr_median'))} and the median Calmar from "
            f"{_f(study.get('full_calmar_median'))} to {_f(study.get('sized_calmar_median'))}. {verdict}{hold_text}"
        )
    else:
        bullets.append(f"**What sizing bought us.** The sizing comparison could not be computed for this run.{hold_text}")

    ports = run.get("portfolios") or []
    next_step = run.get("next_step", "See the recommendations at the end of this report.")
    if ports:
        best_p = max(ports, key=lambda p: _num((p.get("metrics") or {}).get("calmar")))
        m = best_p.get("metrics") or {}
        bullets.append(
            f"**Portfolio and next step.** The best portfolio ({best_p.get('name')}) made {_pct(m.get('cagr'))} per year with a "
            f"{_share(m.get('max_drawdown'))} drawdown (Sharpe {_f(m.get('sharpe'))}, Calmar {_f(m.get('calmar'))}) — "
            f"{'better' if _num(m.get('calmar')) > _num(top[0]['calmar'] if top else 0) else 'not better'} than the best single configuration. "
            f"{next_step}"
        )
    else:
        bullets.append(f"**Next step.** {next_step}")
    return bullets


def _median(values: Sequence[Optional[float]]) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v)))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def aggregate_sections(run: Mapping[str, Any]) -> List[str]:
    """Cross-candidate tables answering Sprint 2b items 3 (ladder), 4 (brackets / give-back), 5 (6H vs 4H) and 6 (S5)."""
    results = list(run.get("results", []))
    cands = [r for r in results if r.get("candidate") not in REFERENCE_CANDIDATES]
    lines: List[str] = []

    # Item 3: drawdown ladder cost and gain (chosen sizing with vs without the ladder, fixed replay).
    ladder_rows = [r for r in cands if (r.get("ladder_effect") or {}).get("with") and (r.get("ladder_effect") or {}).get("without")]
    if ladder_rows:
        lines += ["## Drawdown ladder — cost in return, gain in drawdown (chosen sizing with vs without the ladder, fixed replay)", "",
                  "| Candidate | Series | Return without → with | Max DD without → with | Calmar without → with |", "|---|---|---:|---:|---:|"]
        d_ret, d_dd, d_cal = [], [], []
        for r in ladder_rows:
            w, wo = r["ladder_effect"]["with"], r["ladder_effect"]["without"]
            lines.append(f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {_pct(wo.get('total_return'))} → {_pct(w.get('total_return'))} | "
                         f"{_share(wo.get('max_drawdown'))} → {_share(w.get('max_drawdown'))} | {_f(wo.get('calmar'))} → {_f(w.get('calmar'))} |")
            d_ret.append(_num(w.get("total_return")) - _num(wo.get("total_return")))
            d_dd.append(_num(w.get("max_drawdown")) - _num(wo.get("max_drawdown")))
            d_cal.append(_num(w.get("calmar")) - _num(wo.get("calmar")))
        lines += ["", f"Median effect of the ladder over {len(ladder_rows)} runs: return {_pct(_median(d_ret))}, max drawdown {_pct(_median(d_dd))} "
                  f"(negative = smaller drawdown), Calmar {_f(_median(d_cal), '{:+.2f}')}.", ""]

    # Item 4: exit brackets and give-back.
    br_rows = [r for r in cands if (r.get("bracket_effect") or {}).get("selected") and (r.get("bracket_effect") or {}).get("none")]
    if br_rows:
        lines += ["## Exit brackets — give-back before/after (same rule and sizing, fixed replay)", "",
                  "Give-back = trades that reached +3 % unrealized gain yet closed at a loss (the fleets paper's finding); 'none' = the strategy's own exits only.", "",
                  "| Candidate | Series | Bracket compared | Return none → bracket | PF none → bracket | Max DD none → bracket | Give-back share none → bracket | Avg give-back none → bracket |",
                  "|---|---|---|---:|---:|---:|---:|---:|"]
        d_pf, d_gb = [], []
        for r in br_rows:
            s, nn = r["bracket_effect"]["selected"], r["bracket_effect"]["none"]
            lines.append(f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {r['bracket_effect'].get('bracket')} | "
                         f"{_pct(nn.get('total_return'))} → {_pct(s.get('total_return'))} | {_f(nn.get('profit_factor'))} → {_f(s.get('profit_factor'))} | "
                         f"{_share(nn.get('max_drawdown'))} → {_share(s.get('max_drawdown'))} | "
                         f"{_share(nn.get('giveback_share_reached_closed_negative'))} ({nn.get('giveback_n_reached', 0)}) → "
                         f"{_share(s.get('giveback_share_reached_closed_negative'))} ({s.get('giveback_n_reached', 0)}) | "
                         f"{_share(nn.get('giveback_avg_giveback_pct'))} → {_share(s.get('giveback_avg_giveback_pct'))} |")
            d_pf.append(_num(s.get("profit_factor")) - _num(nn.get("profit_factor")))
            d_gb.append(_num(s.get("giveback_share_reached_closed_negative")) - _num(nn.get("giveback_share_reached_closed_negative")))
        selected_brackets = [str((r.get("selected_params") or {}).get("bracket", "none")) for r in cands]
        share_none = sum(1 for b in selected_brackets if b == "none") / len(selected_brackets) if selected_brackets else 0.0
        lines += ["", f"The train stage kept the strategy's own exits (`none`) in {_share(share_none)} of the runs. Median effect of the compared bracket over "
                  f"{len(br_rows)} runs: profit factor {_f(_median(d_pf), '{:+.2f}')}, give-back share {_pct(_median(d_gb))} (negative = fewer winners turned losers).", ""]

    # Item 5: 4H vs 6H.
    by_pair: Dict[Any, Dict[str, Mapping[str, Any]]] = {}
    for r in results:
        by_pair.setdefault((r["candidate"], r["instrument"]), {})[r["timeframe"]] = r
    tf_rows = [(k, v) for k, v in by_pair.items() if "4H" in v and "6H" in v]
    if tf_rows:
        lines += ["## 4H vs 6H (same candidate and instrument, walk-forward numbers)", "",
                  "| Candidate | Instrument | 4H Sharpe / Calmar / max DD / fees-yr / trades | 6H Sharpe / Calmar / max DD / fees-yr / trades | Higher Calmar |",
                  "|---|---|---|---|---|"]
        wins = {"4H": 0, "6H": 0}
        for (cand, inst), v in tf_rows:
            a, b = v["4H"]["oos"], v["6H"]["oos"]
            better = "4H" if _num(a.get("calmar")) >= _num(b.get("calmar")) else "6H"
            wins[better] += 1
            lines.append(f"| {cand} | {inst} | {_f(a.get('sharpe'))} / {_f(a.get('calmar'))} / {_share(a.get('max_drawdown'))} / {_share(a.get('fees_pct_per_year'))} / {a.get('n_trades', 0)} | "
                         f"{_f(b.get('sharpe'))} / {_f(b.get('calmar'))} / {_share(b.get('max_drawdown'))} / {_share(b.get('fees_pct_per_year'))} / {b.get('n_trades', 0)} | {better} |")
        lines += ["", f"6H had the higher Calmar in {wins['6H']} of {len(tf_rows)} pairs, 4H in {wins['4H']}.", ""]

    # Item 6: positioning filter (S5) effect.
    by_key: Dict[Any, Mapping[str, Any]] = {(r["candidate"], r["instrument"], r["timeframe"]): r for r in results}
    s5_rows = []
    for (cand, inst, tf), r in by_key.items():
        if cand.endswith("+S5"):
            base = by_key.get((cand[:-3], inst, tf))
            if base is not None:
                s5_rows.append((base, r))
    if s5_rows:
        lines += ["## Positioning filter (S5) — base rule vs base + funding/open-interest filter", "",
                  "| Base | Series | Base Sharpe / Calmar / max DD / trades | +S5 Sharpe / Calmar / max DD / trades | Data coverage (funding / OI) |",
                  "|---|---|---|---|---|"]
        for base, s5 in s5_rows:
            a, b = base["oos"], s5["oos"]
            pos = (run.get("positioning") or {}).get(base["instrument"], {})
            lines.append(f"| {base['candidate']} | {base['instrument']} {base['timeframe']} | {_f(a.get('sharpe'))} / {_f(a.get('calmar'))} / {_share(a.get('max_drawdown'))} / {a.get('n_trades', 0)} | "
                         f"{_f(b.get('sharpe'))} / {_f(b.get('calmar'))} / {_share(b.get('max_drawdown'))} / {b.get('n_trades', 0)} | "
                         f"{_share(pos.get('funding_coverage'))} / {_share(pos.get('oi_coverage'))} |")
        lines.append("")
    return lines


def default_owner_decisions(run: Mapping[str, Any]) -> List[str]:
    """Decisions this report cannot take; the owner answers them before Sprint 2c / Sprint 5."""
    results = [r for r in run.get("results", []) if r.get("candidate") not in REFERENCE_CANDIDATES]
    passed = [r for r in results if (r.get("acceptance") or {}).get("passed")]
    counts = _gate_failure_counts(results)
    year_fail = counts.get("positive_in_4_of_5_years", 0)
    items = [
        f"**Yearly-consistency gate.** The gate counts calendar years of the stitched out-of-sample curve; the first and last are partial and 2022 "
        f"was a bear year, so {year_fail} of {len(results)} configurations miss it. Keep it as specified, or redefine it on rolling 12-month windows "
        "(e.g. positive in ≥ 75 % of rolling years)? The report keeps the specification.",
        "**Sizing proposal mechanism.** Two mechanisms are shown: train-selected sizing (Calmar under a 10 % train drawdown cap, noisy across "
        "windows) and one fixed policy (10 % vol target, 15 %/90-day crash filter, drawdown ladder). Which one is the 'proposed sizing' for the "
        "gates going forward? The report applies the gates to both and shortlists both.",
        "**Sequencing.** " + ("At least two configurations passed, so Sprint 5's paper fleet can start on the shortlist while Sprint 3 (exchange-side stops) proceeds. "
                              if len(passed) >= 2 else
                              "Nothing passed. Sprint 3 (exchange-side stops in demo) does not depend on this result and can proceed; Sprint 2c "
                              "(research only, proposed in the executive summary) is the next research step. Approve Sprint 2c, reorder, or stop research here?"),
        "**Binance public data.** Funding and open-interest history come from Binance's public endpoints and bulk files under its API terms, used "
        "for internal research only and never traded on. Acceptable as a standing research source (it needs a nightly top-up like the OKX series)?",
        "**Timeframes.** 1H and 1D were not re-run in Sprint 2b (fee drag / too few trades in Sprint 2). Confirm 4H/6H as the research timeframes, or ask for a 1H/1D re-run with sizing.",
        "**Paper fleet controls.** If a paper fleet starts, should it include the `hold` + sizing references as controls so the timing rules are judged against them?",
    ]
    return items


def render_report_v1b(run: Mapping[str, Any]) -> str:
    meta = run["meta"]
    lines: List[str] = []
    lines += [
        "# Ensemble v1b — sizing, risk, timeframe and positioning (walk-forward, SIMULATION ONLY)",
        "",
        f"Generated {meta['generated_at']} by `scripts/run_research_v1b.py`. Data: PUBLIC OKX spot candles from the Parquet lake "
        f"({meta['data_span']}); 6H bars resampled from 1H (UTC-aligned). Positioning features: {meta.get('positioning_source', 'none')} "
        f"(public, research only). Costs: fee {meta['fee_rate'] * 100:.2f}% per side + slippage {meta['slippage_rate'] * 100:.3f}% per side. "
        f"Long-only spot, no leverage. Walk-forward: train {meta['train_days']}d → purge {meta['purge_days']}d → test {meta['test_days']}d, "
        f"rolling; stage 1 selects the trading rule (entries × exit bracket) by {meta['select_by']} with ≥{meta['min_trades']} train trades at full "
        f"size; stage 2 selects the sizing rule for that rule by {meta['sizing']['select_by']} among variants whose TRAIN max drawdown is ≤ "
        f"{meta['sizing']['dd_cap'] * 100:.0f}% ({meta['sizing']['grid_size']} variants: vol targets {meta['sizing'].get('targets')} × lookbacks "
        f"{meta['sizing'].get('lookbacks')} bars, fixed fractions {meta['sizing'].get('fixed')}, crash filter {meta['sizing'].get('crash')} × "
        f"{{half, zero}}, drawdown ladder −{meta['sizing']['ladder']['half_dd'] * 100:.0f}% → half / −{meta['sizing']['ladder']['flat_dd'] * 100:.0f}% → flat, "
        f"re-arm after {meta['sizing']['ladder'].get('recovery_days', '?')} days). Mid-trade adjustments are reduce-only (threshold "
        f"{meta['sizing']['rebalance_threshold']}). Holdout: last {meta['holdout_months']} months ({meta['holdout_span']}), evaluated once and only "
        "for candidates that passed walk-forward.",
        "",
        "**Nothing here authorizes paper, demo or live trading.** A passing candidate is a hypothesis for the forward paper fleet "
        "(Sprint 5), not a strategy to deploy. Every number is a simulation on historical public data.",
        "",
        "## Executive summary (plain English)",
        "",
    ]
    for b in run.get("executive_summary") or executive_summary(run):
        lines.append(f"- {b}")
    lines += [
        "",
        "## Gates (master plan, Sprint 2b item 8 — at the proposed sizing)",
        "",
        f"- Out-of-sample profit factor > {GATES['profit_factor_min']} after costs",
        f"- Max drawdown < {GATES['max_drawdown_max'] * 100:.0f}% at the proposed sizing",
        f"- Sharpe > {GATES['sharpe_min']}",
        f"- Calmar (CAGR / max drawdown) > {GATES['calmar_min']}",
        f"- Positive in ≥ {GATES['positive_years_min']} of 5 yearly out-of-sample windows",
        f"- At least {GATES['min_trades']} out-of-sample trades",
        f"- ≥ {GATES['robust_share_min'] * 100:.0f}% of ±30% parameter neighbours stay profitable (replayed with the proposed sizing)",
        "- Deflated Sharpe reported (no threshold)",
        "",
        "## Summary",
        "",
        "| Candidate | Series | Sizing | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Alloc. | Fees/yr | Pos. years | Robust ±30% | DSR | Verdict |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for r in run["results"]:
        oos = r["oos"]
        acc = r["acceptance"]
        sizing = (r.get("selected_sizing") or {}).get("label", "-")
        bracket = (r.get("selected_params") or {}).get("bracket", "-")
        lines.append(
            f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {sizing} | {bracket} | {_pct(oos.get('total_return'))} | {_pct(oos.get('cagr'))} | "
            f"{_f(oos.get('sharpe'))} | {_f(oos.get('profit_factor'))} | {_share(oos.get('max_drawdown'))} | {_f(oos.get('calmar'))} | "
            f"{oos.get('n_trades', 0)} | {_share(oos.get('avg_allocation'))} | {_share(oos.get('fees_pct_per_year'))} | "
            f"{acc['positive_years']}/{acc['years_total']} | {_share(r['robustness'].get('share_above_threshold'))} | "
            f"{_f(r['dsr'].get('dsr'))} | {'**PASS**' if acc['passed'] else 'fail'} |"
        )
    passed = [r for r in run["results"] if r["acceptance"]["passed"] and r["candidate"] not in REFERENCE_CANDIDATES]
    lines += ["", f"Configurations passing all gates: **{len(passed)}** of {len([r for r in run['results'] if r['candidate'] not in REFERENCE_CANDIDATES])} "
              "(the `hold` rows are passive always-long references with the same sizing machinery, not candidates).", ""]
    if run.get("failures"):
        lines += ["Runs that failed with an error (not evaluated):", ""]
        for f in run["failures"]:
            lines.append(f"- {f['candidate']} on {f['instrument']} {f['timeframe']}: `{f['error']}`")
        lines.append("")
    if run.get("benchmark"):
        lines += ["Buy-and-hold over the same out-of-sample span (after costs, all-in):", "",
                  "| Series | Total | CAGR | Sharpe | Max DD | Calmar |", "|---|---:|---:|---:|---:|---:|"]
        for b in run["benchmark"]:
            lines.append(f"| {b['instrument']} {b['timeframe']} | {_pct(b['total_return'])} | {_pct(b.get('cagr'))} | {_f(b.get('sharpe'))} | "
                         f"{_share(b['max_drawdown'])} | {_f(b.get('calmar'))} |")
        lines.append("")

    # Fixed policy sizing.
    policy_rows = [r for r in run["results"] if r.get("policy")]
    if policy_rows:
        label = str(((policy_rows[0].get("policy") or {}).get("sizing") or {}).get("label", ""))
        lines += [f"## Fixed policy sizing (no sizing selection) — `{label}`", "",
                  "Same rule selection as above, but one a-priori sizing rule for every candidate instead of the train-selected one (a 20% "
                  "drawdown budget with a modest-Sharpe strategy implies roughly a 10% vol target; the crash filter and ladder are the defensive "
                  "defaults). The gap between this table and the summary table is selection noise in the sizing stage.", "",
                  "| Candidate | Series | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Alloc. | Pos. years | Robust ±30% | Verdict |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|"]
        for r in policy_rows:
            p = r["policy"]
            oos = p.get("oos") or {}
            acc = p.get("acceptance") or {}
            lines.append(
                f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {(p.get('selected_params') or {}).get('bracket', '-')} | "
                f"{_pct(oos.get('total_return'))} | {_pct(oos.get('cagr'))} | {_f(oos.get('sharpe'))} | {_f(oos.get('profit_factor'))} | "
                f"{_share(oos.get('max_drawdown'))} | {_f(oos.get('calmar'))} | {oos.get('n_trades', 0)} | {_share(oos.get('avg_allocation'))} | "
                f"{acc.get('positive_years', 0)}/{acc.get('years_total', 0)} | {_share((p.get('robustness') or {}).get('share_above_threshold'))} | "
                f"{'**PASS**' if acc.get('passed') else 'fail'} |"
            )
        lines.append("")

    # Paper-fleet shortlist.
    lines += ["## Paper-fleet shortlist (ranked)", "",
              "Ranked by: passed all gates first, then Calmar, then Sharpe; only configurations with OOS profit factor > 1 and ≥ 30 trades. "
              "These are the configurations Sprint 5's paper fleet should run forward on live public data; none is approved for demo.", ""]
    sl = run.get("shortlist") or shortlist(run["results"])
    if sl:
        lines += ["| # | Candidate | Series | Sizing | Bracket | CAGR | Sharpe | Calmar | Max DD | PF | Trades | DSR | Gates missed |",
                  "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for row in sl:
            missed = ", ".join(GATE_LABELS.get(g, g) for g in row["failed_gates"]) or "none — PASS"
            lines.append(f"| {row['rank']} | {row['candidate']} | {row['instrument']} {row['timeframe']} | {row['sizing']} | {row['bracket']} | "
                         f"{_pct(row['cagr'])} | {_f(row['sharpe'])} | {_f(row['calmar'])} | {_share(row['max_drawdown'])} | {_f(row['profit_factor'])} | "
                         f"{row['n_trades']} | {_f(row['dsr'])} | {missed} |")
    else:
        lines.append("No configuration qualifies for the shortlist (profit factor ≤ 1 or fewer than 30 trades everywhere).")
    lines.append("")

    # Sizing study.
    study = run.get("sizing_study") or {}
    if study.get("rows"):
        lines += ["## Sizing study — all-in vs the chosen sizing (same rule, fixed replay over the test windows)", "",
                  "| Candidate | Series | Rule bracket | All-in CAGR | All-in max DD | All-in Calmar | Chosen sizing | CAGR | Max DD | Calmar | Best sweep by Calmar (informational) |",
                  "|---|---|---|---:|---:|---:|---|---:|---:|---:|---|"]
        for s in study["rows"]:
            lines.append(f"| {s['candidate']} | {s['instrument']} {s['timeframe']} | {s.get('bracket', '-')} | {_pct(s.get('full_cagr'))} | {_share(s.get('full_dd'))} | "
                         f"{_f(s.get('full_calmar'))} | {s.get('sizing', '-')} | {_pct(s.get('sized_cagr'))} | {_share(s.get('sized_dd'))} | {_f(s.get('sized_calmar'))} | "
                         f"{s.get('sweep_best', '-')} |")
        lines += ["", f"Medians over {study['n']} runs: all-in max DD {_share(study.get('full_dd_median'))} → {_share(study.get('sized_dd_median'))}; "
                  f"CAGR {_pct(study.get('full_cagr_median'))} → {_pct(study.get('sized_cagr_median'))}; Calmar {_f(study.get('full_calmar_median'))} → "
                  f"{_f(study.get('sized_calmar_median'))}. {study.get('note', '')}", ""]

    lines += aggregate_sections(run)

    # Portfolios.
    if run.get("portfolios"):
        lines += ["## Portfolio combination (daily compounding of the sleeves' out-of-sample returns)", "",
                  "| Portfolio | Sleeves | Weights | Ladder | CAGR | Sharpe | Max DD | Calmar | Div. ratio | Pos. years |",
                  "|---|---|---|---|---:|---:|---:|---:|---:|---|"]
        for p in run["portfolios"]:
            m = p.get("metrics") or {}
            yearly = p.get("yearly") or {}
            pos = sum(1 for v in yearly.values() if v is not None and v > 0)
            weights = ", ".join(f"{k}={v:.2f}" for k, v in (p.get("weights") or {}).items())
            lines.append(f"| {p['name']} | {len(p.get('weights') or {})} | {weights} | {'yes' if p.get('ladder') else 'no'} | {_pct(m.get('cagr'))} | "
                         f"{_f(m.get('sharpe'))} | {_share(m.get('max_drawdown'))} | {_f(m.get('calmar'))} | {_f(p.get('diversification_ratio'))} | {pos}/{len(yearly)} |")
        lines.append("")
        corr = run.get("portfolio_correlation")
        if corr:
            names = list(corr)
            lines += ["Correlation of daily sleeve returns:", "", "| | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
            for a in names:
                lines.append(f"| {a} | " + " | ".join(_f(corr[a].get(b_)) for b_ in names) + " |")
            lines.append("")
        lines += [f"{run.get('portfolio_note', '')}", ""]

    # Positioning data.
    if run.get("positioning"):
        lines += ["## Positioning data (external, research features only)", "",
                  "| Instrument | Source | Funding span | Funding coverage (in-sample bars) | Open-interest span | OI coverage |",
                  "|---|---|---|---:|---|---:|"]
        for inst, p in run["positioning"].items():
            lines.append(f"| {inst} | {p.get('source')} | {p.get('funding_span', '-')} | {_share(p.get('funding_coverage'))} | {p.get('oi_span', '-')} | {_share(p.get('oi_coverage'))} |")
        lines += ["", run.get("positioning_note", ""), ""]

    # Per-candidate details.
    for r in run["results"]:
        oos = r["oos"]
        lines += [f"## {r['candidate']} — {r['label']} ({r['instrument']} {r['timeframe']})", ""]
        lines += [f"Rule grid: {r['grid_size']} combinations (entries × exit brackets). Windows: {oos.get('windows')} ({oos.get('windows_traded')} traded, "
                  f"{oos.get('windows_positive')} positive). Most-selected rule: `{r.get('selected_params')}`. Most-selected sizing: "
                  f"`{(r.get('selected_sizing') or {}).get('label')}` (selected {r.get('sizing_frequency', {}).get((r.get('selected_sizing') or {}).get('label'), 0)} "
                  f"of {oos.get('windows_traded')} windows; other choices: "
                  f"{', '.join(f'{k}×{v}' for k, v in sorted((r.get('sizing_frequency') or {}).items(), key=lambda kv: -kv[1]) if k != (r.get('selected_sizing') or {}).get('label'))[:4] or 'none'}).", ""]
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
        lines += [f"Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over "
                  f"every out-of-sample test window, no re-selection): selected set {_pct(rb.get('best'))}, neighbours median {_pct(rb.get('median'))}, "
                  f"min {_pct(rb.get('min'))}, share profitable {_share(rb.get('share_above_threshold'))} over {rb.get('n_neighbours')} neighbours.", ""]
        le = r.get("ladder_effect") or {}
        if le.get("with") and le.get("without"):
            w, wo = le["with"], le["without"]
            lines += [f"Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return {_pct(wo.get('total_return'))} → {_pct(w.get('total_return'))}, "
                      f"max DD {_share(wo.get('max_drawdown'))} → {_share(w.get('max_drawdown'))}, Calmar {_f(wo.get('calmar'))} → {_f(w.get('calmar'))}.", ""]
        be = r.get("bracket_effect") or {}
        if be.get("selected") and be.get("none"):
            s, nn = be["selected"], be["none"]
            lines += [f"Exit bracket `{be.get('bracket')}` vs none (same rule, fixed replay): return {_pct(nn.get('total_return'))} → {_pct(s.get('total_return'))}, "
                      f"PF {_f(nn.get('profit_factor'))} → {_f(s.get('profit_factor'))}, max DD {_share(nn.get('max_drawdown'))} → {_share(s.get('max_drawdown'))}. "
                      f"Give-back (trades that reached +3% unrealized yet closed negative): {_share(nn.get('giveback_share_reached_closed_negative'))} of "
                      f"{nn.get('giveback_n_reached', 0)} → {_share(s.get('giveback_share_reached_closed_negative'))} of {s.get('giveback_n_reached', 0)}; "
                      f"average give-back {_share(nn.get('giveback_avg_giveback_pct'))} → {_share(s.get('giveback_avg_giveback_pct'))}.", ""]
        eso = r.get("entry_sized_only")
        if eso:
            lines += [f"Entry-sized only (no mid-trade reductions) for comparison: return {_pct(eso.get('total_return'))}, max DD {_share(eso.get('max_drawdown'))}, "
                      f"Calmar {_f(eso.get('calmar'))}.", ""]
        mc = r.get("montecarlo", {})
        if mc.get("n_trades"):
            lines += [f"Monte Carlo (trade-order bootstrap of equity-level trade returns, {mc['paths']} paths over {mc['n_trades']} OOS trades): terminal growth "
                      f"p05 {_f(mc['terminal_p05'])}× / p50 {_f(mc['terminal_p50'])}× / p95 {_f(mc['terminal_p95'])}×, P(loss) {_share(mc['prob_loss'])}, "
                      f"max DD p50 {_share(mc['max_dd_p50'])}, p95 {_share(mc['max_dd_p95'])}.", ""]
        ss = r.get("slippage_stress", {})
        if ss:
            lines += ["Slippage stress (OOS total return with slippage ×1/×2/×3): " + ", ".join(f"{k}: {_pct(v)}" for k, v in ss.items()), ""]
        d = r["dsr"]
        lines += [f"Deflated Sharpe: {d.get('n_trials')} trials (rules + sizing variants in the last train window), expected max SR (zero skill) "
                  f"{_f(d.get('expected_max_sr'), '{:.3f}')} per bar vs observed OOS {_f(d.get('observed_sr'), '{:.3f}')} → DSR {_f(d.get('dsr'))}.", ""]
        acc = r["acceptance"]
        lines += ["Checks: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in acc.items() if isinstance(v, bool) and k != "passed"), ""]
        pol = r.get("policy") or {}
        if pol:
            po = pol.get("oos") or {}
            pa = pol.get("acceptance") or {}
            lines += [f"Fixed policy sizing `{(pol.get('sizing') or {}).get('label')}`: return {_pct(po.get('total_return'))}, CAGR {_pct(po.get('cagr'))}, "
                      f"Sharpe {_f(po.get('sharpe'))}, PF {_f(po.get('profit_factor'))}, max DD {_share(po.get('max_drawdown'))}, Calmar {_f(po.get('calmar'))}, "
                      f"trades {po.get('n_trades')}, robust {_share((pol.get('robustness') or {}).get('share_above_threshold'))} → "
                      f"{'PASS' if pa.get('passed') else 'fail (' + ', '.join(pa.get('failed', [])) + ')'}.", ""]
        if r.get("holdout"):
            h = r["holdout"]
            lines += [f"**Holdout ({meta['holdout_span']}), evaluated once with the most-selected rule and sizing:** return {_pct(h.get('total_return'))}, "
                      f"CAGR {_pct(h.get('cagr'))}, Sharpe {_f(h.get('sharpe'))}, PF {_f(h.get('profit_factor'))}, max DD {_share(h.get('max_drawdown'))}, "
                      f"Calmar {_f(h.get('calmar'))}, trades {h.get('n_trades')}.", ""]
            if r.get("holdout_event_driven"):
                e = r["holdout_event_driven"]
                lines += [f"Event-driven cross-check on the holdout (reviewed simulator, same costs, full-equity sizing, fixed stop only): return "
                          f"{_pct(e.get('total_return'))}, trades {e.get('n_trades')} vs vectorized full-size {_pct(e.get('vectorized_total_return'))} "
                          f"({e.get('n_trades_vectorized')} trades) — difference {_pct(e.get('difference'))}.", ""]
        elif acc["passed"]:
            lines += ["Holdout: not evaluated in this run (`--evaluate-holdout` not set).", ""]
        else:
            lines += ["Holdout: untouched (candidate did not pass walk-forward).", ""]
        for note in r.get("notes", []):
            lines.append(f"- {note}")
        if r.get("notes"):
            lines.append("")

    lines += ["## Owner decisions (nothing below is decided by this report)", ""]
    for item in run.get("owner_decisions") or default_owner_decisions(run):
        lines.append(f"- {item}")
    lines += [
        "",
        "## Method notes and caveats",
        "",
        "- Engine: `research/engine.py` — next-bar-open execution, intrabar stop with conservative gap fills, fees and slippage per side, fixed ATR "
        "stop at entry, optional take-profit / trailing stop (effective from the bar after the high that armed it) / time stop; sizing by a per-bar "
        "fraction of equity decided one bar earlier; reduce-only mid-trade adjustments; drawdown ladder on the strategy's own equity. With every "
        "overlay off the engine is bit-for-bit the Sprint 2 engine, which is parity-tested against `app/backtest/simulator.py`.",
        "- Vol targeting uses the trailing realized vol of closes (past bars only); the crash filter uses the trailing rolling peak of closes; "
        "both are tested for look-ahead. 6H bars are resampled from stored 1H bars on the UTC grid, complete bars only.",
        "- Two-stage selection (rule, then sizing) uses the train slice only; the purge gap removes boundary leakage; test slices are stitched and "
        "each window restarts from the same capital and flat. Robustness, the sizing sweep, the ladder/bracket comparisons and the slippage stress "
        "are FIXED replays over the same test windows, so they describe sensitivity, not new selections.",
        "- Yearly windows are calendar years of the stitched out-of-sample curve; the first and last years are partial, and 2022 (a bear year for "
        "long-only rules) sits inside the span, so the 4-of-5 yearly gate is strict by construction.",
        "- 1H and 1D were not re-run: Sprint 2 showed 1H rules paying 5–24 %/yr in fees and 1D grids rarely producing enough trades; 4H and 6H "
        "(resampled from 1H) are the working timeframes.",
        "- Deflated Sharpe follows Bailey & López de Prado (2014) over every rule and sizing variant tried in the last train window.",
        "- The Monte Carlo bootstraps equity-level trade contributions (trade return × size fraction); fractional sizing makes paths less extreme than Sprint 2's all-in bootstrap.",
        "- Positioning features (S5) come from Binance public history aligned as-of onto OKX candles (a candle sees only values stamped at or before its open); "
        "where a series is missing the filter passes. Coverage is reported above. OKX keeps collecting its own series for the forward period.",
        "- The event-driven cross-check only runs when the selected rule has no bracket, because the reviewed strategy contract carries a fixed stop only "
        "(exchange-side brackets are Sprint 3 scope); it runs at full size, so it checks the trade sequence, not the sized equity.",
        "- Portfolios compound each sleeve's out-of-sample daily returns in its own capital bucket (no cross-sleeve rebalancing); equal-risk weights use "
        "the sleeves' realized out-of-sample vol (mildly in-sample). The portfolio ladder scales the next day's return by the previous day's multiplier.",
        "- Every number is a simulation on historical public data and proves nothing about the future.",
        "",
    ]
    return "\n".join(lines)
