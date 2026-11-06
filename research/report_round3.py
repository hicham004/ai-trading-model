"""Research round 3 report (plan row R19, SIMULATION ONLY).

Renders ``docs/research/RESEARCH_ROUND_3_REPORT.md`` from the study's results JSON
(or, before the first run, from the pre-registration alone). Every plain-English
sentence - the summary, each hypothesis's verdict, the readings, the bar-size
reading and the failure analysis of every hypothesis that fails - is computed from
the numbers in the run, so a re-run on other data cannot print a stale claim.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from research.report_v1c import HOLDOUT_MIN_TRADES
from research.trader_policy import GATE_LABELS_R18


# -- formatting ---------------------------------------------------------------------------------

def _num(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x


def _ok(v: Any) -> bool:
    x = _num(v)
    return not (math.isnan(x) or math.isinf(x))


def _pct(v: Any, signed: bool = True, digits: int = 1) -> str:
    if not _ok(v):
        return "-"
    return f"{_num(v) * 100:+.{digits}f}%" if signed else f"{_num(v) * 100:.{digits}f}%"


def _f(v: Any, fmt: str = "{:.2f}") -> str:
    if v is None:
        return "-"
    x = _num(v)
    if math.isnan(x):
        return "-"
    if math.isinf(x) or x >= 999:
        return "∞"
    return fmt.format(x)


def _int(v: Any) -> str:
    x = _num(v)
    return "-" if math.isnan(x) else f"{int(round(x))}"


def _yes(flag: Any) -> str:
    return "yes" if flag else "no"


def _names(items: Iterable[str]) -> str:
    items = list(items)
    return ", ".join(items) if items else "none"


def _k(value: Any) -> str:
    """A cell key such as ``trader|brakes|none`` inside a Markdown table cell (the pipes would split the cell)."""
    return str(value).replace("|", "\\|")


def _results(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return list(run.get("results") or [])


def _judged(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for r in _results(run) if r.get("judged")]


def _gates_text(failed: Sequence[str]) -> str:
    return ", ".join(GATE_LABELS_R18.get(g, g) for g in failed) if failed else "-"


def _holdout_cell(r: Mapping[str, Any]) -> str:
    h = r.get("holdout")
    if not h:
        return "untouched"
    verdict = r.get("holdout_confirmed") if r.get("role") != "control" else None  # a control is a comparison line, never judged
    mark = "✓" if verdict is True else ("✗" if verdict is False else "")
    return f"{_pct(h.get('total_return'))} / PF {_f(h.get('profit_factor'))} / {h.get('n_trades')} tr {mark}".strip()


def _too_few_trades(r: Mapping[str, Any]) -> bool:
    h = r.get("holdout") or {}
    return bool(_num(h.get("total_return")) > 0 and _num(h.get("profit_factor")) > 1.0 and int(_num(h.get("n_trades"), 0)) < HOLDOUT_MIN_TRADES)


def _holdout_outcome(r: Mapping[str, Any]) -> str:
    if r.get("holdout_confirmed") is True:
        return "confirmed"
    if _too_few_trades(r):
        return f"not confirmed: {int(_num((r.get('holdout') or {}).get('n_trades'), 0))} trades (fewer than {HOLDOUT_MIN_TRADES})"
    return "contradicted"


def _verdict_word(r: Mapping[str, Any]) -> str:
    if r.get("role") == "control":
        return "control"
    if not r.get("judged"):
        return "information"
    return "**PASS**" if (r.get("acceptance_r18") or {}).get("passed") else "fail"


def _mode(r: Mapping[str, Any]) -> Optional[str]:
    return (r.get("regime") or {}).get("mode")


def _directional_sentence(d: Mapping[str, Any], base_name: str, where: str) -> str:
    if not d or not d.get("n"):
        return f"No directional reading {where}: no configuration had a comparison line."
    thr = d.get("threshold")
    thr_text = f"at least {thr} of {d['n']}" if thr is not None else f"more than every one of {d['n']} (too few for the 5% level)"
    verdict = "replicates in direction" if d.get("replicates_in_direction") else "does not replicate in direction"
    return (f"Directional reading {where} (pre-registered): Calmar higher than {base_name} in {d.get('improved')} of {d['n']} configurations "
            f"({_num(d.get('expected_by_chance')):.0f} expected by chance; the one-sided sign test needs {thr_text} at the {d.get('alpha', 0.05) * 100:.0f}% level; "
            f"P(at least this many by chance) = {_f(d.get('p_value'), '{:.3f}')}; above the control by more than 0.1 Calmar in {d.get('beats_by_0_1', 0)}): "
            f"the rule **{verdict}**. The configurations share markets across two timeframes and two modes, so this is indicative, not a test of independent trials.")


# -- the failure analysis, from the numbers ----------------------------------------------------------

def failure_analysis(v: Mapping[str, Any]) -> List[str]:
    """Sentences for one hypothesis that did not end 'confirmed', every one computed from its failure facts."""
    facts = v.get("failure_facts") or {}
    out: List[str] = []
    n = int(_num(facts.get("n"), 0))
    gates = v.get("binding_gates") or []
    gate_text = ", ".join(f"{GATE_LABELS_R18.get(g, g)} ({c} of {n})" for g, c in gates[:4]) if gates else "none"
    if not facts.get("n_compared"):
        out.append(f"No comparison with hold + policy was available. Gates missed most often: {gate_text}.")
        return out
    k = int(_num(facts.get("calmar_improved"), 0))
    band = facts.get("expected_trades_per_year") or [None, None]
    tpy = facts.get("median_trades_per_year")
    out.append(f"Across its {n} judged configurations the rule family ended with a higher risk-adjusted result (Calmar) than hold + policy sizing at the same budget "
               f"in {k} and a lower one in {n - k}: the median Calmar was {_f(facts.get('median_variant_calmar'))} against {_f(facts.get('median_base_calmar'))} for the "
               f"control ({_f(facts.get('median_delta_calmar'), '{:+.2f}')}), the median yearly return {_pct(facts.get('median_variant_cagr'))} against "
               f"{_pct(facts.get('median_base_cagr'))}, the median worst drawdown {_pct(facts.get('median_variant_dd'), signed=False)} against "
               f"{_pct(facts.get('median_base_dd'), signed=False)}, and the median share of positive rolling 12-month windows "
               f"{_pct(facts.get('median_variant_rolling'), signed=False)} against {_pct(facts.get('median_base_rolling'), signed=False)}; it beat the control by more "
               f"than 0.1 Calmar (Sprint 2c's acceptance-clause yardstick) in {facts.get('beats_base_by_0_1', 0)} of {n}.")
    out.append(f"It traded a median {_f(tpy, '{:.1f}')} times a year (the plan expected {_f(band[0], '{:.0f}')}-{_f(band[1], '{:.0f}')} on daily bars), won a median "
               f"{_pct(facts.get('median_win_rate'), signed=False, digits=0)} of its trades with a median average win of {_f(facts.get('median_payoff'))} x the average loss "
               f"and a median expectancy of {_f(facts.get('median_expectancy_r'))} R, and was in the market {_pct(facts.get('median_exposure'), signed=False, digits=0)} of "
               f"the time against {_pct(facts.get('median_base_exposure'), signed=False, digits=0)} for the always-long control.")
    by_tf = facts.get("by_timeframe") or {}
    if len(by_tf) > 1:
        out.append("By bar size: " + "; ".join(f"{tf}: Calmar above the control in {e.get('calmar_improved', 0)} of {e.get('n', 0)} (median Calmar "
                                                f"{_f(e.get('median_calmar'))}, {_f(e.get('median_trades_per_year'), '{:.1f}')} trades a year)" for tf, e in sorted(by_tf.items())) + ".")
    by_mode = facts.get("by_mode") or {}
    if "gate" in by_mode and "none" in by_mode:
        out.append(f"With the HMM regime gate on, Calmar was above the control in {by_mode['gate'].get('calmar_improved', 0)} of {by_mode['gate'].get('n', 0)} "
                   f"configurations (without the gate: {by_mode['none'].get('calmar_improved', 0)} of {by_mode['none'].get('n', 0)}).")
    per_market = facts.get("per_market") or {}
    if len(per_market) > 1:
        out.append("By market: " + "; ".join(f"{m} {e.get('calmar_improved', 0)} of {e.get('n', 0)} above the control, {e.get('passed', 0)} pass" for m, e in sorted(per_market.items())) + ".")
    if facts.get("median_2022_variant") is not None or facts.get("median_2022_base") is not None:
        out.append(f"In the 2022 bear year the median result was {_pct(facts.get('median_2022_variant'))} against {_pct(facts.get('median_2022_base'))} for the control.")
    out.append(f"Gates missed most often: {gate_text}.")
    # The reading.
    binding = dict(gates)
    few = binding.get("enough_trades", 0)
    d = _num(facts.get("median_delta_calmar"), 0.0)
    if v.get("n_passed", 0) > 0 or v.get("n_passed_replication", 0) > 0:
        out.append("Reading: a walk-forward pass did not carry into the untouched 12 months. With the holdout's falling direction known beforehand, a rule "
                   "that sits out downtrends by construction was expected to look good there; that it did not is the stronger signal, and it says the pass "
                   "was selection luck among the configurations tried.")
    elif n and few >= max(1, n // 2) and tpy is not None and tpy < 7.0:
        out.append(f"Reading: the rule trades too rarely for the gates as fixed. It missed 'at least 30 trades' in {few} of {n} configurations because it fires a "
                   f"few times a year (median {_f(tpy, '{:.1f}')}), so over the 4.3 out-of-sample years one market cannot produce 30 trades; the gate stayed as "
                   "pre-registered and this is the place the report says it binds. Whether the rule has an edge is answered by the pooled reading and the "
                   "comparison with hold + policy above, as information, never as a verdict: a rule this slow needs a forward control account or a "
                   "pre-registered pooled protocol, which is an owner decision, not an edit of this round.")
    elif d <= -0.05:
        out.append("Reading: the setup is worse than simply holding the market with the same risk budget - its entries come after the move has started and "
                   "its exits give back the trend's turns, so the time out of the market cost more than the drawdowns it avoided; the family is refuted on "
                   "these markets under this protocol, not merely untested.")
    elif abs(d) < 0.05:
        out.append("Reading: the setup changed little beside holding the market with the same risk budget - the pullback entry and the trend exit roughly "
                   "offset the drawdowns they avoid - and it does not clear the gates it still misses; the budget, not the entry timing, sets the result.")
    else:
        out.append(f"Reading: the setup improved on holding the market with the same budget (Calmar above the control in {k} of {n}) but not enough to clear the "
                   "gates it still misses; the edge is thin and the gates built for weekly rules are strict for a rule that trades this seldom.")
    return out


# -- the plain-English summary ---------------------------------------------------------------------------

def executive_summary(run: Mapping[str, Any]) -> List[str]:
    meta = run.get("meta") or {}
    verdicts = run.get("verdicts") or []
    overall = run.get("overall") or {}
    repro = run.get("reproduction") or []
    repro_ok = sum(1 for c in repro if c.get("ok"))
    judged = _judged(run)
    bullets: List[str] = []
    if not _results(run):
        bullets.append("**Status: pre-registered, not yet run.** The hypotheses, rules, variants, protocol variant, tier, markets, timeframes, gates, readings "
                       "and verdict rules below were fixed before the first run; the results sections are filled by the study.")
        return bullets
    repro_text = (f"Before anything was judged, the same unchanged code re-ran the configurations this round shares with Sprint 2c, the replication study and the "
                  f"Trader Policy study and matched their stored numbers in {repro_ok} of {len(repro)} cases" if repro else "This run skipped the reproduction (a smoke run, not a result)")
    n_markets = len({r["instrument"] for r in judged})
    bullets.append(
        f"**What we did.** We tested the two asymmetric setups of the Trader Plan - H7: the trend-pullback continuation rule S7 with three variants; H8: the slow "
        f"Turtle System 2 breakout S8 with Garner's channel variant - each written as a fixed rule (one parameter set, nothing to select) and judged under a "
        f"pre-registered fixed-rule protocol variant (the 20-train-trade qualification that silenced round 2's slow rules is skipped; the exit bracket is fixed) at "
        f"the Trader Policy's Trader budget with its brakes, under the plan's section 4.6 gates, on BTC-USDT and ETH-USDT first and the seven R12 markets as "
        f"replication, on 1D and 6H bars; plus the bar-size comparison of the S1 and S2 families on 1D, 6H and 4H bars. Everything else is Sprint 2c's. "
        f"{repro_text}. {len(judged)} configurations on {n_markets} markets were judged on {meta.get('v1c_meta', {}).get('data_span_short', 'the stored history')} after "
        f"fees and slippage; the last 12 months ({meta.get('v1c_meta', {}).get('holdout_span', '2025-10-20->2026-10-20')}) stayed untouched except for configurations that passed.")
    for v in verdicts:
        facts = v.get("failure_facts") or {}
        best = v.get("best_primary") or {}
        text = (f"**{v['hypothesis']} - {v['title']}: {v['label']}** on BTC-USDT and ETH-USDT ({v['n_passed']} of {v['n_primary']} configurations passed every gate"
                + (f": {_names(v['passed'])}" if v.get("passed") else "") + ")")
        text += f"; on the seven replication markets: {v.get('replication_label')} ({v.get('n_passed_replication', 0)} of {v.get('n_replication', 0)} passed"
        text += (f": {_names(v['passed_replication'])}" if v.get("passed_replication") else "") + ")."
        if best:
            text += f" Best on the primary markets: {best.get('configuration')} with Calmar {_f(best.get('calmar'))}, {_pct(best.get('cagr'))} a year at a {_pct(best.get('max_drawdown'), signed=False)} drawdown"
            if best.get("failed"):
                text += f", missing {_gates_text(best['failed'])}"
            text += "."
        if facts.get("n_compared"):
            text += (f" Beside hold + policy at the same budget its Calmar was higher in {facts.get('calmar_improved', 0)} of {facts.get('n_compared')} configurations "
                     f"(median {_f(facts.get('median_variant_calmar'))} against {_f(facts.get('median_base_calmar'))}); it traded a median {_f(facts.get('median_trades_per_year'), '{:.1f}')} "
                     f"times a year (the plan expected {_f((facts.get('expected_trades_per_year') or [None, None])[0], '{:.0f}')}-"
                     f"{_f((facts.get('expected_trades_per_year') or [None, None])[1], '{:.0f}')} on daily bars), with an average win {_f(facts.get('median_payoff'))} x the average loss.")
        d = v.get("directional_all") or {}
        if d.get("n"):
            text += (f" Directional reading over all {d['n']} configurations: {'replicates' if d.get('replicates_in_direction') else 'does not replicate'} in direction "
                     f"({d.get('improved')} of {d.get('n')}; the 5% level needs {d.get('threshold')}).")
        counting = [x for x in (v.get("variants") or []) if (x.get("directional") or {}).get("replicates_in_direction")]
        if v.get("variants"):
            text += (f" Variants beside the base rule: {_names(f'{x['variant']} raised Calmar in {x['directional']['improved']} of {x['directional']['n']}' for x in v['variants'])}"
                     + (f"; {_names(x['variant'] for x in counting)} replicate(s) in direction." if counting else "; none replicates in direction."))
        bullets.append(text)
    passed = [r for r in judged if (r.get("acceptance_r18") or {}).get("passed")]
    confirmed = [r for r in passed if r.get("holdout_confirmed") is True]
    contradicted = [r for r in passed if r.get("holdout_confirmed") is False and not _too_few_trades(r)]
    too_few = [r for r in passed if r.get("holdout_confirmed") is False and _too_few_trades(r)]
    if passed:
        few_text = ""
        if too_few:
            few_text = f" and left {len(too_few)} unconfirmed for lack of trades (fewer than {HOLDOUT_MIN_TRADES}: " + _names(
                f"{r['configuration']}: {_pct((r.get('holdout') or {}).get('total_return'))} from {int(_num((r.get('holdout') or {}).get('n_trades'), 0))} trades" for r in too_few) + ")"
        hold_text = (f"The untouched 12 months then confirmed {len(confirmed)} ({_names(r['configuration'] for r in confirmed)}) and contradicted {len(contradicted)} "
                     f"({_names(r['configuration'] for r in contradicted)}){few_text}" if meta.get("evaluate_holdout") else "The untouched 12 months were not opened in this run")
        bullets.append(f"**Holdout.** {hold_text}. The holdout's falling direction was known for every market before this study (pre-registered caveat) and both rules sit "
                       "out downtrends by construction, so a confirmation here is necessary, not sufficient; the paper fleet's forward record is the judge. The ledger "
                       "below names, beside every opening, the earlier look at the same months by that market's stored hold + policy control.")
    else:
        bullets.append("**Holdout.** Nothing passed walk-forward, so the untouched 12 months were not opened for any new rule (the hold + policy controls' 12 "
                       "months at the Trader budget are shown as the comparison line, as in every study).")
    bs = (run.get("barsize") or {}).get("reading") or {}
    if bs.get("n_comparisons"):
        med = bs.get("medians_by_timeframe") or {}
        fams = bs.get("families") or {}
        text = (f"**Bar size.** The claim '6H is the cost-adjusted sweet spot' {'holds' if bs.get('holds') else 'does not hold'} under the pre-registered reading: "
                f"at the Trader budget 6H had the highest Calmar of the three bar sizes in {bs.get('six_h_best_at_gate_cost')} of {bs.get('n_comparisons')} "
                f"(rule, market, mode) comparisons at the 0.30 % gate cost and in {bs.get('six_h_best_at_measured_cost')} of {bs.get('n_comparisons')} at the "
                f"measured 0.20 % (at least {bs.get('needed')} needed at both).")
        if bs.get("untested"):
            text += (f" In {len(bs['untested'])} of those comparisons one bar size produced no trade at all because the protocol's 20-train-trade qualification silenced "
                     f"every walk-forward window there ({_names(bs['untested'])}) - the same limit that stopped round 2's slow rules - so that bar size is untested, not "
                     f"beaten; setting it aside (a clarification applied after the run, the verdict unchanged) gives {bs.get('six_h_best_at_gate_cost_clarified')} of "
                     f"{bs.get('n_comparisons')} and {bs.get('six_h_best_at_measured_cost_clarified')} of {bs.get('n_comparisons')}: the claim "
                     f"{'holds' if bs.get('holds_clarified') else 'still does not hold'}.")
        if fams:
            text += " By family (untested bar sizes set aside; best bar size at 0.30 % / 0.20 %): " + "; ".join(
                f"{fam} family ({e.get('n')} comparisons): " + ", ".join(f"{tf} {c.get('gate_cost')} / {c.get('measured_cost')}" for tf, c in (e.get('best_counts') or {}).items())
                for fam, e in fams.items()) + "."
        text += (" Median Calmar by bar size at the Trader budget (0.30 % / 0.20 %): "
                 + "; ".join(f"{tf} {_f((e or {}).get('calmar_trader'))} / {_f((e or {}).get('calmar_trader_measured'))} ({_f((e or {}).get('trades_per_year'), '{:.0f}')} trades a year, "
                             f"fees {_pct((e or {}).get('fees_pct_per_year'), signed=False)} a year)" for tf, e in med.items())
                 + ". Two pre-registered-or-stated caveats: the tier's volatility window is 30 bars (30 days at 1D, 5 days at 4H), so the comparison also compares "
                 "volatility estimators; and the 0.20 % column is the Trader Policy study's construction - the most-often-selected rule replayed over every window - "
                 "which for a swept family also removes the per-window selection, so it is information beside the 0.30 % walk-forward, not the walk-forward at a lower cost.")
        bullets.append(text)
    binding = overall.get("binding_gates") or []
    if binding:
        bullets.append("**Binding gates.** " + ", ".join(f"{GATE_LABELS_R18.get(g, g)} ({n} of {overall.get('n_judged')})" for g, n in binding[:4])
                       + f". {overall.get('n_judged')} judged configurations at Sprint 2c's own pass rate (4 of 108) would give about {overall.get('expected_passes_by_chance')} "
                       "passes by chance; the holdout and the forward fleet, not the pass count, carry the verdict.")
    additions = run.get("shortlist_additions") or []
    recorded = run.get("shortlist_recorded_only") or []
    if additions:
        bullets.append(f"**Paper fleet.** {len(additions)} confirmed configuration(s) were appended to the fleet's shortlist as new Trader-tier accounts with a source "
                       f"tag naming the fixed-rule protocol ({_names(f'{a['candidate']} {a['instrument']} {a['timeframe']}' for a in additions)}); a running fleet takes "
                       "them at its next restart from an updated checkout. Existing accounts are untouched. Nothing is approved for demo or live trading."
                       + (f" Shortlist file: {run['shortlist_note']}." if run.get("shortlist_note") else ""))
    else:
        bullets.append("**Paper fleet.** Nothing fleet-eligible was confirmed, so the fleet's shortlist is unchanged. Nothing is approved for demo or live trading.")
    if recorded:
        bullets.append(f"**Recorded, not applied.** {len(recorded)} confirmed passer(s) the fleet cannot run as it is: "
                       + _names(f"{a['candidate']} {a['instrument']} {a['timeframe']} ({'; '.join(a.get('reasons') or [])})" for a in recorded)
                       + ". Each is a decision for the owner (docs/PLAN_STATUS.md, section 2).")
    return bullets


# -- tables ----------------------------------------------------------------------------------------------------

def _config_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Trades/yr | Win | Avg win/avg loss | Expectancy (R) | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | Gates missed | Verdict | Holdout (12m) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in rows:
        o, acc = r.get("oos") or {}, r.get("acceptance_r18") or {}
        tr = ((r.get("r18") or {}).get("trades") or {})
        sel = r.get("selected_params") or {}
        lines.append(f"| {r['configuration']} | {sel.get('bracket', '-')} | {_pct(o.get('total_return'))} | {_pct(o.get('cagr'))} | {_f(o.get('sharpe'))} | {_f(o.get('profit_factor'))} | "
                     f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | {_int(o.get('n_trades'))} | {_f(o.get('trades_per_year'), '{:.1f}')} | "
                     f"{_pct(o.get('win_rate'), signed=False, digits=0)} | {_f(acc.get('payoff_ratio'))} | {_f(tr.get('expectancy_r'))} | {_pct(o.get('exposure'), signed=False, digits=0)} | "
                     f"{_pct(o.get('fees_pct_per_year'), signed=False)} | {_pct(acc.get('rolling_positive_share'), signed=False)} | {_pct(acc.get('worst_calendar_year_return'))} | "
                     f"{_pct((r.get('robustness') or {}).get('share_above_threshold'), signed=False)} | {_gates_text(acc.get('failed') or []) if r.get('judged') else '-'} | "
                     f"{_verdict_word(r)} | {_holdout_cell(r)} |")
    return lines


def _comparison_table(rows: Sequence[Mapping[str, Any]], key: str = "comparison") -> List[str]:
    lines = ["| Configuration | Comparison line | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r.get(key) or {}
        if not c.get("available"):
            continue
        v, b = c["variant"], c["base"]
        y22 = (c.get("yearly") or {}).get("2022") or {}
        lines.append(f"| {r['configuration']} | {c.get('base_configuration')} | {_f(b['calmar'])} → {_f(v['calmar'])} | {_pct(b['cagr'])} → {_pct(v['cagr'])} | "
                     f"{_pct(b['max_drawdown'], signed=False)} → {_pct(v['max_drawdown'], signed=False)} | {_f(b['sharpe'])} → {_f(v['sharpe'])} | {_f(b['profit_factor'])} → {_f(v['profit_factor'])} | "
                     f"{_int(b['n_trades'])} → {_int(v['n_trades'])} | {_pct(b['exposure'], signed=False, digits=0)} → {_pct(v['exposure'], signed=False, digits=0)} | "
                     f"{_pct(b['rolling_12m_positive_share'], signed=False)} → {_pct(v['rolling_12m_positive_share'], signed=False)} | "
                     f"{_pct(b['worst_calendar_year_return'])} → {_pct(v['worst_calendar_year_return'])} | {_pct(y22.get('base'))} → {_pct(y22.get('variant'))} | "
                     f"{_yes(b['passed'])} / {_yes(v['passed'])} |")
    return lines


def _reference_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Configuration | Reference cell: CAGR / max DD / Calmar / passes | Trader cell: CAGR / max DD / Calmar / passes | x Reference exposure | Realized vol | Risk/trade (mean, max) | Cap binds | Gaps | Re-entries ≤ 2 bars | Expectancy (R) | P(DD ≥ 30 %) |",
             "|---|---|---|---:|---:|---|---:|---:|---|---:|---:|"]
    for r in rows:
        ref = r.get("reference") or {}
        o = r.get("oos") or {}
        x = r.get("r18") or {}
        tr = x.get("trades") or {}
        mc = r.get("montecarlo") or {}
        risk = f"{_pct(tr.get('risk_pct_mean'), signed=False)}, {_pct(tr.get('risk_pct_max'), signed=False)}"
        lines.append(f"| {r['configuration']} | {_pct(ref.get('cagr'))} / {_pct(ref.get('max_drawdown'), signed=False)} / {_f(ref.get('calmar'))} / {_yes(ref.get('passed'))} | "
                     f"{_pct(o.get('cagr'))} / {_pct(o.get('max_drawdown'), signed=False)} / {_f(o.get('calmar'))} / {_yes((r.get('acceptance_r18') or {}).get('passed'))} | "
                     f"{_f(ref.get('exposure_ratio'))} | {_pct(o.get('ann_vol'), signed=False)} | {risk} | {_pct((x.get('cap') or {}).get('cap_binding_share'), signed=False, digits=0)} | "
                     f"{_int(tr.get('gap_trades'))} | {_int(tr.get('reentries_within_2_bars_of_stop'))}/{_int(tr.get('stop_outs'))} | {_f(tr.get('expectancy_r'))} | "
                     f"{_pct(mc.get('prob_max_dd_ge_30'), signed=False)} |")
    return lines


def _replication_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Primary passer | Passed on | Replication markets: pass / judged | Needed | Replicates | Per market (Calmar; pass; holdout) |", "|---|---|---:|---:|---|---|"]
    for e in entries:
        per = "; ".join(f"{m['instrument'].split('-')[0]} {_f(m.get('calmar'))}{' PASS' if m.get('passed') else ''}"
                        + (f" {_pct((m.get('holdout') or {}).get('total_return'))}{'✓' if m.get('holdout_confirmed') else '✗'}" if m.get("holdout") else "")
                        if m.get("ran") else f"{m['instrument'].split('-')[0]} not run" for m in e.get("markets") or [])
        lines.append(f"| {e['configuration']} | {_names(e.get('passed_on') or [])} | {e.get('n_pass')} / {e.get('n_ran')} | {e.get('needed')} | {_yes(e.get('replicated'))} | {per} |")
    return lines


def _variants_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Variant | Beside | Series compared | Calmar higher in | Sign test (needs) | Median Δ Calmar | Median Δ CAGR | Median Δ max DD | Median Δ avg win/avg loss | Median Δ trades/yr | Judged passes |",
             "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|"]
    for e in entries:
        d = e.get("directional") or {}
        lines.append(f"| {e['variant']} | {e['base']} | {e.get('n')} | {d.get('improved')} of {d.get('n')} | {'replicates' if d.get('replicates_in_direction') else 'no'} ({d.get('threshold')}) | "
                     f"{_f(e.get('median_delta_calmar'), '{:+.2f}')} | {_pct(e.get('median_delta_cagr'))} | {_pct(e.get('median_delta_max_drawdown'))} | "
                     f"{_f(e.get('median_delta_payoff'), '{:+.2f}')} | {_f(e.get('median_delta_trades_per_year'), '{:+.1f}')} | {e.get('judged_passed')} of {e.get('judged_n')} |")
    return lines


def _pooled_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Rule | Bars | Mode | Markets | Pooled trades | Pooled PF | Pooled avg win/avg loss | Pooled win rate | Pooled expectancy (R) | Median Calmar | Median Calmar hold + policy | Calmar above hold | Passes |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for e in entries:
        lines.append(f"| {e['candidate']} | {e['timeframe']} | {e['mode']} | {e.get('n_markets')} | {e.get('pooled_trades')} | {_f(e.get('pooled_profit_factor'))} | {_f(e.get('pooled_payoff_ratio'))} | "
                     f"{_pct(e.get('pooled_win_rate'), signed=False, digits=0)} | {_f(e.get('pooled_expectancy_r'))} | {_f(e.get('median_calmar'))} | {_f(e.get('median_calmar_hold'))} | "
                     f"{e.get('calmar_above_hold')} of {e.get('n_markets')} | {e.get('passed')} |")
    return lines


def _barsize_tables(bs: Mapping[str, Any]) -> List[str]:
    rows = bs.get("rows") or []
    lines: List[str] = []
    if not rows:
        return ["Not run in this invocation."]
    lines += ["| Rule | Market | Mode | Bars | Cell | Bracket | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Trades/yr | Fees/yr | Exposure | Realized vol | 0.20 %: CAGR / Calmar / max DD | Hold + policy Calmar | Gates | Passes |",
              "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---|"]
    for x in rows:
        m = x.get("measured") or {}
        meas = f"{_pct(m.get('cagr'))} / {_f(m.get('calmar'))} / {_pct(m.get('max_drawdown'), signed=False)}" if m else ("n/a (untested)" if x.get("untested") else "-")
        trades = f"{_int(x.get('n_trades'))}" + (" (no window qualified)" if x.get("untested") else "")
        lines.append(f"| {x['candidate']} | {x['instrument']} | {x['mode']} | {x['timeframe']} | {x['tier']} | {x.get('bracket', '-')} | {_pct(x.get('cagr'))} | {_f(x.get('sharpe'))} | "
                     f"{_pct(x.get('max_drawdown'), signed=False)} | {_f(x.get('calmar'))} | {_f(x.get('profit_factor'))} | {trades} | {_f(x.get('trades_per_year'), '{:.1f}')} | "
                     f"{_pct(x.get('fees_pct_per_year'), signed=False)} | {_pct(x.get('exposure'), signed=False, digits=0)} | {_pct(x.get('ann_vol'), signed=False)} | {meas} | "
                     f"{_f(x.get('hold_calmar'))} | {_gates_text(x.get('failed') or [])} | {_yes(x.get('passed'))} |")
    best = bs.get("best") or []
    if best:
        lines += ["", "Which bar size had the highest Calmar at the Trader budget, per rule, market and mode (an untested bar size - no window qualified a rule there - is "
                      "named and set aside; 'literal' is the pre-registered reading with its 0.00 counted):", "",
                  "| Rule | Market | Mode | Calmar by bars (0.30 %) | Best at 0.30 % | Literal | Calmar by bars (0.20 %) | Best at 0.20 % | Literal | Untested |", "|---|---|---|---|---|---|---|---|---|---|"]
        for b in best:
            lines.append(f"| {b['candidate']} | {b['instrument']} | {b['mode']} | " + ", ".join(f"{tf} {_f(c)}" for tf, c in (b.get('calmar_by_timeframe') or {}).items())
                         + f" | {b.get('best_at_gate_cost') or '-'} | {b.get('best_at_gate_cost_literal') or '-'} | " + ", ".join(f"{tf} {_f(c)}" for tf, c in (b.get('calmar_measured_by_timeframe') or {}).items())
                         + f" | {b.get('best_at_measured_cost') or '-'} | {b.get('best_at_measured_cost_literal') or '-'} | {_names(b.get('untested_timeframes') or [])} |")
    reading = bs.get("reading") or {}
    if reading.get("n_comparisons"):
        counts = reading.get("best_counts") or {}
        lines += ["", f"Pre-registered reading (taken literally): 6H had the highest Calmar in {reading.get('six_h_best_at_gate_cost')} of {reading.get('n_comparisons')} comparisons at the "
                      f"gate cost and {reading.get('six_h_best_at_measured_cost')} of {reading.get('n_comparisons')} at the measured cost (at least {reading.get('needed')} needed at both): the claim "
                      f"**{'holds' if reading.get('holds') else 'does not hold'}**. Best-bar-size counts (0.30 % / 0.20 %): "
                      + "; ".join(f"{tf} {c.get('gate_cost')} / {c.get('measured_cost')}" for tf, c in counts.items()) + "."]
        if reading.get("untested"):
            fams = reading.get("families") or {}
            lines += ["", f"Clarification applied after the run (the verdict is the same either way): {_names(reading['untested'])} produced no trade because the protocol's "
                          "20-train-trade qualification silenced every walk-forward window at that bar size - the limit that stopped round 2's slow rules - so that bar size is "
                          f"untested there, not beaten, and its 0.20 % replay (the default parameters) is not shown. With those set aside: 6H best in "
                          f"{reading.get('six_h_best_at_gate_cost_clarified')} of {reading.get('n_comparisons')} at the gate cost and {reading.get('six_h_best_at_measured_cost_clarified')} "
                          f"of {reading.get('n_comparisons')} at the measured cost: the claim **{'holds' if reading.get('holds_clarified') else 'still does not hold'}**. By family: "
                          + "; ".join(f"{fam} ({e.get('n')} comparisons, {e.get('untested')} with an untested bar size): " + ", ".join(f"{tf} {c.get('gate_cost')} / {c.get('measured_cost')}"
                                                                                                                      for tf, c in (e.get('best_counts') or {}).items()) for fam, e in fams.items()) + ".",
                      "", "The 0.20 % column is the Trader Policy study's construction: the most-often-selected rule replayed over every window with the same gate and sizing. "
                          "For a swept family that also removes the per-window selection, so it is information beside the 0.30 % walk-forward, not the walk-forward at a lower cost; "
                          "a future bar-size study should pre-register a gate-cost replay of the same fixed rule beside it, and a fixed-rule protocol for a family the qualification "
                          "silences at a bar size."]
        lines += [
                  "", "| Bars | Median Calmar (Reference) | Median Calmar (Trader, 0.30 %) | Median Calmar (Trader, 0.20 %) | Median Sharpe (Trader) | Median trades/yr | Median fees/yr | Passes at the Trader cell |",
                  "|---|---:|---:|---:|---:|---:|---:|---|"]
        for tf, e in (reading.get("medians_by_timeframe") or {}).items():
            lines.append(f"| {tf} | {_f(e.get('calmar_reference'))} | {_f(e.get('calmar_trader'))} | {_f(e.get('calmar_trader_measured'))} | {_f(e.get('sharpe_trader'))} | "
                         f"{_f(e.get('trades_per_year'), '{:.1f}')} | {_pct(e.get('fees_pct_per_year'), signed=False)} | {e.get('passed_trader')} of {e.get('n_trader')} |")
    return lines


# -- the report ---------------------------------------------------------------------------------------------

def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    v1c_meta = meta.get("v1c_meta") or {}
    verdicts = run.get("verdicts") or []
    ran = bool(_results(run))
    lines: List[str] = []
    lines += [
        "# Research round 3 — asymmetric setups: trend-pullback continuation (S7), the slow breakout (S8) and the bar size after costs (walk-forward, SIMULATION ONLY)",
        "",
        (f"Generated {meta.get('generated_at', '-')} by `scripts/run_research_round_3.py` (plan row R19; {meta.get('elapsed_minutes', '-')} min). " if ran else
         f"Pre-registered {meta.get('preregistration_written_at', '-')} by `scripts/run_research_round_3.py --preregister` (plan row R19); not yet run. ")
        + "Rules: Sprint 2c's runner (`scripts/run_research_v1c.py`'s own `run_series`) with the Trader Policy's Trader tier and brakes (plan row R18, the fleet cell "
        "`trader|brakes|none`; the Reference cell `vt10/30 crash15/90dh ladder` beside it for information) and, for the fixed rules, the pre-registered fixed-rule "
        "protocol variant (the exit bracket fixed, no train-trade qualification); everything else is Sprint 2c's "
        f"(regime gate `{(v1c_meta.get('regime') or {}).get('label', 'hmm3 bear>=0.5 gate')}`, S0 filter {v1c_meta.get('no_trade_label', 'S0 vol×3 spread p98 gap3 FOMC±6/6h')}, "
        f"walk-forward train {v1c_meta.get('train_days', 540)}d → purge {v1c_meta.get('purge_days', 7)}d → test {v1c_meta.get('test_days', 180)}d, fee "
        f"{_pct(v1c_meta.get('fee_rate', 0.001), signed=False, digits=2)} + slippage {_pct(v1c_meta.get('slippage_rate', 0.0005), signed=False, digits=3)} per side). Data: PUBLIC OKX spot "
        f"candles of nine markets (1H and 4H stored; 6H and 1D resampled from 1H) frozen at Sprint 2c's data end (bar close ≤ {meta.get('data_end', '-')}). Holdout: the last 12 months "
        f"({v1c_meta.get('holdout_span', '2025-10-20->2026-10-20')}), opened once and only for configurations that passed every gate at the Trader cell.",
        "",
        "**Nothing here authorizes paper, demo or live trading.** A passing configuration is a hypothesis for the forward paper fleet, not a strategy to deploy. "
        "Every number is a simulation on historical public data.",
        "",
        "## Executive summary (plain English)",
        "",
    ]
    for b in executive_summary(run):
        lines.append(f"- {b}")

    prereg = meta.get("preregistration") or {}
    lines += ["", "## Fixed before the first run (the pre-registration)", "",
              f"Pre-registration hash (text, file and configuration): `{meta.get('preregistration_sha256', '-')}`; file `{meta.get('preregistration_file', '-')}` "
              f"written {meta.get('preregistration_written_at', '-')}.", ""]
    for k, v in prereg.items():
        if k in ("hypotheses", "parked", "trade_count_check"):
            continue
        lines.append(f"- **{k}**: {v}")
    for hk, h in (prereg.get("hypotheses") or {}).items():
        lines += ["", f"### {hk} — {h.get('title')}", ""]
        for k, v in h.items():
            if k == "title":
                continue
            if k == "variants" and isinstance(v, dict):
                lines.append("- **variants**: " + "; ".join(f"`{a}`: {b}" for a, b in v.items()))
            else:
                lines.append(f"- **{k}**: {v}")
    counts = prereg.get("trade_count_check") or {}
    if counts:
        lines += ["", "Trade-count check before the pre-registration (entries a year on the in-sample candles, counts only, no returns were looked at):", "",
                  "| Series | " + " | ".join(next(iter(counts.values())).keys()) + " |", "|---|" + "---:|" * len(next(iter(counts.values())))]
        for series, c in counts.items():
            lines.append(f"| {series} | " + " | ".join(f"{v:.1f}" for v in c.values()) + " |")
    parked = prereg.get("parked") or {}
    if parked:
        lines += ["", "Parked by the plan (not tested here), with the reason:", ""]
        for name, why in parked.items():
            lines.append(f"- **{name}**: {why}")
    if ran:
        protocol = meta.get("protocol_check") or {}
        lines += ["", f"Protocol check of a Reference cell against the stored Sprint 2c run: {'every parameter the same' if protocol.get('ok') else 'MISMATCHES: ' + str(protocol.get('mismatches'))} "
                  f"(checked: {', '.join(protocol.get('checked') or [])}). Every job's check is stored with its results: a tier is a recorded `policy_sizing` mismatch, the "
                  "fixed-rule protocol recorded `brackets` / `min_trades` mismatches, 1D bars a recorded `timeframes` mismatch; the study stops on any mismatch a job does not explain.",
                  "", "Gates: Sprint 2c's (" + "; ".join(f"{k} {v}" for k, v in (meta.get("gates") or {}).items()) + ") with max drawdown ≤ 25 % and worst calendar year ≥ -15 % at the "
                  "Trader tier (≤ 20 % and ≥ -10 % at the Reference cell), plus average win / average loss ≥ 2; expectancy in R reported, never gated."]
        if meta.get("second_look_warning"):
            lines += ["", f"**Warning — second look.** An earlier run already opened the holdout of: {_names(meta['second_look_warning'])}. Both looks are in the ledger below."]

    repro = run.get("reproduction") or []
    lines += ["", "## Reproduction of the stored studies", ""]
    if repro:
        lines += ["Before anything was judged, the Reference cell re-ran hold, S1, S2, S1+S5 and S2+S5 on BTC-USDT and ETH-USDT 4H and 6H (Sprint 2c's stored numbers) and hold on "
                  "the seven replication markets at 6H (the replication study's), and the Trader cell re-ran S1+S5 BTC-USDT 6H [none] and the hold controls the Trader Policy study "
                  "stored at that cell; each had to give the stored walk-forward numbers (6 decimals), the same trade counts, the same most-selected rules and the same gate "
                  "verdicts, otherwise the study stops.", "",
                  "| Configuration | Cell | Stored by | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Same verdict | Largest difference | Agrees |",
                  "|---|---|---|---|---|---|---:|---|---|---:|---|"]
        for c in repro:
            got, exp = c.get("reproduced") or {}, c.get("stored") or {}
            lines.append(f"| {c.get('configuration')} | {_k(c.get('cell'))} | {c.get('study')} | {_f(got.get('total_return'), '{:.6f}')} / {_f(exp.get('total_return'), '{:.6f}')} | "
                         f"{_f(got.get('sharpe'), '{:.6f}')} / {_f(exp.get('sharpe'), '{:.6f}')} | {_f(got.get('max_drawdown'), '{:.6f}')} / {_f(exp.get('max_drawdown'), '{:.6f}')} | "
                         f"{c.get('n_trades')} / {c.get('n_trades_stored')} | {_yes(c.get('selected_matches'))} | {_yes(c.get('verdict_matches'))} | "
                         f"{_num(c.get('max_abs_difference'), 0.0):.1e} | {_yes(c.get('ok'))} |")
        lines += ["", f"{sum(1 for c in repro if c.get('ok'))} of {len(repro)} reproduced."]
    else:
        lines.append("Not run in this invocation (a smoke run, or not yet run). Nothing here is a result.")

    all_results = _results(run)
    for v in verdicts:
        hk = v["hypothesis"]
        judged_rows = [r for r in all_results if r.get("hypothesis") == hk and r.get("judged")]
        primary = [r for r in judged_rows if r.get("primary")]
        repl = [r for r in judged_rows if not r.get("primary")]
        lines += ["", f"## {hk} — {v['title']}: **{v['label']}** on BTC-USDT and ETH-USDT; **{v.get('replication_label')}** on the replication markets", ""]
        lines += ["The judged cell (the Trader tier with the brakes) on the primary markets:", ""]
        lines += _config_table(primary)
        if repl:
            lines += ["", "The replication markets (same cell):", ""]
            lines += _config_table(repl)
        lines += ["", "Beside hold + policy sizing at the same cell (same market and bars; the control has one mode):", ""]
        lines += _comparison_table(judged_rows)
        lines += ["", _directional_sentence(v.get("directional_primary") or {}, "hold + policy", "on the primary markets"),
                  _directional_sentence(v.get("directional_replication") or {}, "hold + policy", "on the replication markets")]
        lines += ["", "The Trader cell beside the Reference cell (the same rule at today's budget): exposure ratio, risk per trade, how often the 2 % cap bound, gaps past the "
                  "stop, the rule's own re-entries within two bars of a stop-out, and the bootstrap chance of touching the -30 % hard stop:", ""]
        lines += _reference_table(judged_rows)
        if v.get("replication"):
            lines += ["", "The R12 reading for every configuration that passed on a primary market (replicates when it passes on at least 4 of the 7 markets):", ""]
            lines += _replication_table(v["replication"])
        if v.get("variants"):
            lines += ["", f"The variants beside the base rule {v.get('base')} (every series, mode and cell; the sign test at the 5 % level):", ""]
            lines += _variants_table(v["variants"])
        if v.get("pooled"):
            lines += ["", "Pooled over the nine markets at the judged cell (pre-registered as information for a rule that trades a few times a year; never a verdict, never a fleet ticket):", ""]
            lines += _pooled_table(v["pooled"])
        flagged = v.get("turnover_flagged") or []
        if flagged:
            lines += ["", f"Above the plan's turnover ceiling (40 trades a year; a fleet condition): {_names(flagged)}."]
        lines.append("")
        if v["label"] == "confirmed" or v.get("replication_label") == "confirmed":
            where = []
            if v.get("confirmed"):
                where.append(f"{_names(v['confirmed'])} on the primary markets")
            if v.get("confirmed_replication"):
                where.append(f"{_names(v['confirmed_replication'])} on the replication markets")
            lines.append(f"**Confirmed.** {'; '.join(where)} passed every section 4.6 gate at the Trader cell and the untouched 12 months confirmed it. Fleet-eligible: "
                         f"{_names(v.get('fleet_eligible') or [])}" + (f"; recorded only: {_names(e['configuration'] + ' (' + '; '.join(e.get('reasons') or []) + ')' for e in v.get('recorded_only') or [])}"
                                                                         if v.get("recorded_only") else "") + ". The holdout's falling direction was known before this study, so the forward fleet, not this confirmation, is the judge.")
            contradicted = (v.get("contradicted") or []) + (v.get("contradicted_replication") or [])
            if contradicted:
                lines.append(f"The other passers were not confirmed: {_names(contradicted)}.")
        else:
            lines.append("**Failure analysis** (computed from the numbers above):")
            lines.append("")
            for s in failure_analysis(v):
                lines.append(f"- {s}")

    lines += ["", "## The bar size after costs — the S1 and S2 families on 1D, 6H and 4H bars (information, never a hypothesis)", ""]
    if ran:
        lines += ["S1, S2, S1+S5 and S2+S5 with Sprint 2c's grids, brackets and selection on BTC-USDT and ETH-USDT, at the Reference and the Trader cell, at the 0.30 % gate cost "
                  "and the measured 0.20 % replay (the selected rule, same windows, gate and sizing). No holdout was opened for these rows; a 1D configuration that passes is a "
                  "candidate for a future pre-registered row, nothing more. The tier's 30-bar volatility window is 30 days on 1D bars and 5 days on 4H bars (pre-registered caveat).", ""]
    lines += _barsize_tables(run.get("barsize") or {})

    ref_rows = [r for r in all_results if r.get("role") == "control"]
    if ref_rows:
        lines += ["", "## The comparison lines — hold + policy sizing at both cells", ""]
        lines += ["| Configuration | Cell | CAGR | Sharpe | Max DD | Calmar | Exposure | Realized vol | Worst year | Rolling 12m + | Holdout (12m) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for r in sorted(ref_rows, key=lambda x: (x["instrument"], x["timeframe"], x["cell"]["key"])):
            o, acc = r.get("oos") or {}, r.get("acceptance_r18") or {}
            lines.append(f"| {r['configuration']} | {_k(r['cell']['key'])} | {_pct(o.get('cagr'))} | {_f(o.get('sharpe'))} | {_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | "
                         f"{_pct(o.get('exposure'), signed=False, digits=0)} | {_pct(o.get('ann_vol'), signed=False)} | {_pct(acc.get('worst_calendar_year_return'))} | "
                         f"{_pct(acc.get('rolling_positive_share'), signed=False)} | {_holdout_cell(r) if r.get('holdout') else 'untouched'} |")
    info = run.get("series_info") or {}
    spans = [s.get("span") for s in info.values() if s.get("span")]
    if spans:
        lines += ["", "Data spans: " + "; ".join(spans) + "."]
    failures = [f for s in info.values() for f in (s.get("failures") or [])]
    if failures:
        lines += ["", "Runs that failed with an error (not evaluated):", ""]
        for f in failures:
            lines.append(f"- {f.get('candidate')} on {f.get('instrument')} {f.get('timeframe')} ({f.get('regime', '-')}): `{f.get('error')}`")
    skipped = [f"{s['instrument']} {s['timeframe']}: {s['skipped']}" for s in info.values() if s.get("skipped")]
    if skipped:
        lines += ["", "Series skipped (too little data): " + "; ".join(skipped) + "."]

    lines += ["", "## The untouched 12 months", ""]
    openings = run.get("holdout_openings") or []
    if openings:
        lines += [f"Opened once, only for configurations that passed every section 4.6 gate at the Trader cell (and the hold + policy controls at that cell as the comparison line). "
                  f"Verdict ✓ = positive return, PF > 1 and ≥ {HOLDOUT_MIN_TRADES} trades. The holdout's falling direction was known before the run (see the pre-registration).", "",
                  "| Configuration | Cell | Role | Return | Max DD | PF | Trades | Verdict |", "|---|---|---|---:|---:|---:|---:|---|"]
        by_name = {(r["configuration"], r["cell"]["key"]): r for r in all_results}
        for o in openings:
            r = by_name.get((o["configuration"], o.get("cell")))
            verdict = "control (comparison line)" if o.get("role") == "control" else (_holdout_outcome(r) if r is not None else ("confirmed" if o.get("confirmed") else "contradicted"))
            lines.append(f"| {o['configuration']} | {_k(o.get('cell'))} | {o.get('role')} | {_pct(o.get('total_return'))} | {_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('profit_factor'))} | {o.get('n_trades')} | {verdict} |")
    else:
        lines.append("Not opened in this run" + (": no configuration passed walk-forward." if ran and meta.get("evaluate_holdout") else "." if ran else " (not yet run)."))
    looks = run.get("earlier_looks") or []
    if looks:
        lines += ["", "### Earlier looks at the same months by the comparison lines", "",
                  "A new rule on a market whose hold + policy control already opened its holdout is a near-second look at those months; the control's stored result is shown beside it "
                  "(at 6H when the opening is at 1D, where no stored look at that bar size exists).", "",
                  "| Configuration opened in this run | Cell | Comparison line | Study | Same bars | Its holdout then |", "|---|---|---|---|---|---|"]
        for e in looks:
            then = (f"{_pct(e.get('earlier_total_return'))} / PF {_f(e.get('earlier_profit_factor'))} / {e.get('earlier_n_trades')} tr" if e.get("earlier_opened") else "never opened")
            lines.append(f"| {e['configuration']} | {_k(e.get('cell'))} | {e.get('earlier_configuration') or '-'} | {e.get('earlier_study') or '-'} | {_yes(e.get('same_bar_size'))} | {then} |")
    ledger = meta.get("holdout_ledger") or []
    if ledger:
        lines += ["", "### Every opening of the holdout (ledger)", "",
                  f"Each run that opened a holdout appends its openings to `{meta.get('holdout_ledger_path', '-')}`; earlier looks stay visible here even when a later run replaces the numbers above.",
                  "", "| Run | Configuration | Cell | Role | Return | Max DD | PF | Trades | Verdict |", "|---|---|---|---|---:|---:|---:|---:|---|"]
        for i, e in enumerate(ledger, start=1):
            for o in e.get("openings", []):
                few = _num(o.get("total_return")) > 0 and _num(o.get("profit_factor")) > 1.0 and int(_num(o.get("n_trades"), 0)) < HOLDOUT_MIN_TRADES
                verdict = ("comparison" if o.get("role") == "control" else "confirmed" if o.get("confirmed") else f"not confirmed ({int(_num(o.get('n_trades'), 0))} trades)" if few else "contradicted")
                lines.append(f"| {i} ({e.get('generated_at', '-')}) | {o.get('configuration')} | {_k(o.get('cell'))} | {o.get('role')} | {_pct(o.get('total_return'))} | "
                             f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('profit_factor'))} | {o.get('n_trades')} | {verdict} |")

    additions = run.get("shortlist_additions") or []
    recorded = run.get("shortlist_recorded_only") or []
    lines += ["", "## Paper-fleet shortlist", ""]
    if additions:
        lines += ["Confirmed, fleet-eligible passers appended to `docs/research/paper_fleet_shortlist_v1c.json` as new Trader-tier accounts with a `source` tag naming this study, "
                  "the tier, the brakes, the cell and the fixed-rule protocol variant (existing entries and running accounts untouched):", ""]
        for a in additions:
            lines.append(f"- {a['candidate']} {a['instrument']} {a['timeframe']} ({a.get('regime')}; bracket {a.get('bracket')}): walk-forward Calmar {_f(a.get('calmar'))}, holdout "
                         f"{_pct((a.get('holdout') or {}).get('total_return'))}")
        if run.get("shortlist_note"):
            lines += ["", f"Shortlist file: {run['shortlist_note']}."]
    else:
        lines.append("Unchanged: no configuration was both a walk-forward passer at the Trader cell, confirmed by the untouched 12 months, and runnable by the fleet.")
    if recorded:
        lines += ["", "Recorded only (confirmed, but the fleet cannot run them as it is; each a decision for the owner):", ""]
        for a in recorded:
            lines.append(f"- {a['candidate']} {a['instrument']} {a['timeframe']} ({a.get('regime')}): walk-forward Calmar {_f(a.get('calmar'))}, holdout "
                         f"{_pct((a.get('holdout') or {}).get('total_return'))} — {'; '.join(a.get('reasons') or [])}")

    overall = run.get("overall") or {}
    lines += ["", "## Owner decisions (nothing below is decided by this report)", ""]
    if ran:
        if additions:
            lines.append(f"- **Fleet.** {len(additions)} new paper account(s) join at the fleet's next restart from an updated checkout (`docs/runbooks/PAPER_FLEET.md`). "
                         "Recommended: let them run; judge them at G7 with the rest.")
        else:
            lines.append("- **Fleet.** Nothing to add. Recommended: no change.")
        if recorded:
            lines.append(f"- **Recorded passers.** {_names(f'{a['candidate']} {a['instrument']} {a['timeframe']}' for a in recorded)}: confirmed, but " + "; ".join(sorted({x for a in recorded for x in (a.get("reasons") or [])}))
                         + ". Recommended: a forward control account only if the fleet learns the bar size, as a new plan row; nothing is retuned.")
        lines.append(f"- **What the verdicts mean.** {'; '.join(f'{k}: {v}' for k, v in (overall.get('labels') or {}).items())} on the primary markets; "
                     f"{'; '.join(f'{k}: {v}' for k, v in (overall.get('replication_labels') or {}).items())} on the replication markets. No gate, parameter, rule, market, "
                     "cell or verdict rule changed after the results. If a gate looks wrong, that is a note for the next pre-registered round, not an edit of this one.")
        slow = [v for v in verdicts if dict(v.get("binding_gates") or []).get("enough_trades", 0) >= max(1, int(_num(v.get("n_configurations"), 0)) // 2)]
        if slow:
            lines.append("- **Slow rules and the 30-trade gate.** " + "; ".join(f"{v['hypothesis']} missed 'at least 30 trades' in {dict(v.get('binding_gates') or []).get('enough_trades', 0)} of "
                                                                                     f"{v.get('n_configurations')} configurations" for v in slow)
                         + ": a rule that fires a few times a year cannot produce 30 trades on one market over 4.3 out-of-sample years, whatever its edge. The gate stayed as "
                         "pre-registered (the plan fixed it) and the pooled reading is information only. Whether to judge such a rule another way — a forward control account in "
                         "the paper fleet, or a pre-registered pooled protocol over markets — is a decision for the owner (`docs/PLAN_STATUS.md`, section 2); nothing here is retuned.")
        lines.append("- **Next round.** The failure analyses above say which setups are not worth another test; anything left credible is a decision for the owner, as a new plan row.")
    else:
        lines.append("- Not yet run: the decisions come with the results.")
    lines += ["", "## Method notes and caveats", "",
              "- The rules were not re-implemented and the runner was not changed: Sprint 2c's runner module ran them with its plan-row-R18 arguments; the reproduction table shows "
              "the same code gives the stored numbers of Sprint 2c, the replication study and the Trader Policy study where this round shares a configuration with them.",
              "- The fixed-rule protocol variant applies only to S7, S8 and their variants: one parameter set each, the exit bracket fixed (`none`, or `trail3` for S7t) and never "
              "selected, and `min_trades 0` so that every walk-forward window runs the rule's test slice (there is nothing to select, so no window is silenced). The bar-size "
              "families keep Sprint 2c's selection, the 20-train-trade qualification included.",
              "- Every lookback is in calendar days converted to bars of the timeframe; the +-30 % robustness replay perturbs every grid number (the four S7 numbers, the three S8 "
              "numbers), as it does for every rule.",
              "- The tier's 30-bar volatility window is 30 days on 1D bars, 7.5 days on 6H and 5 days on 4H (Sprint 2b's definition, a protocol fact); the crash window and the ladder "
              "re-arm are in days. The S0 filter's one-day volatility leg is inert on 1D bars (a one-bar window).",
              "- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the Trader tier and its brakes "
              "are exactly the Trader Policy study's; none of them was adapted to the new rules or to 1D bars.",
              f"- {overall.get('n_judged', 0)} judged configurations are {overall.get('n_judged', 0)} more comparisons on the same six years; at Sprint 2c's pass rate about "
              f"{overall.get('expected_passes_by_chance', '-')} passes among them would be expected by chance, which is why the holdout and the forward fleet, not single passes, carry "
              "the verdict. The directional sign tests treat configurations as trials although they share markets, so they are indicative only.",
              "- The holdout's falling direction was known for every market before this study; both rules sit out downtrends by construction. Confirmation there is necessary, not sufficient.",
              "- Every number is a simulation on historical public data and proves nothing about the future."]
    for note in meta.get("run_notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
