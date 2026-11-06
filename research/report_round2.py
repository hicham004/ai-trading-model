"""Research round 2 report (plan row R16, SIMULATION ONLY).

Renders ``docs/research/RESEARCH_ROUND_2_REPORT.md`` from the study's results
JSON. Every plain-English sentence — the summary, each hypothesis's verdict,
the directional and pattern readings and the failure analysis of every
hypothesis that fails — is computed from the numbers in the run, so a re-run
on other data cannot print a stale claim.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from research.report_v1c import GATE_LABELS, GATES, HOLDOUT_MIN_TRADES


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


def _results(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for s in run.get("series", []) for r in s.get("results", [])]


def _judged(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for r in _results(run) if r.get("judged")]


def _holdout_cell(r: Mapping[str, Any]) -> str:
    h = r.get("holdout")
    if not h:
        return "untouched"
    verdict = r.get("holdout_confirmed")
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


def _gates_text(failed: Sequence[str]) -> str:
    return ", ".join(GATE_LABELS.get(g, g) for g in failed) if failed else "-"


def _verdict_word(r: Mapping[str, Any]) -> str:
    role = r.get("role")
    if role == "control":
        return "control"
    if role == "reproduction":
        return "comparison line"
    return "**PASS**" if (r.get("acceptance") or {}).get("passed") else "fail"


def _directional_sentence(d: Mapping[str, Any], base_name: str) -> str:
    if not d or not d.get("n"):
        return "No directional reading: no configuration had a comparison line."
    thr = d.get("threshold")
    thr_text = f"at least {thr} of {d['n']}" if thr is not None else f"more than every one of {d['n']} (too few for the 5% level)"
    verdict = "replicates in direction" if d.get("replicates_in_direction") else "does not replicate in direction"
    return (f"Directional reading (pre-registered): Calmar rose beside {base_name} in {d.get('improved')} of {d['n']} configurations "
            f"({_num(d.get('expected_by_chance')):.0f} expected by chance; the one-sided sign test needs {thr_text} at the {d.get('alpha', 0.05) * 100:.0f}% level; "
            f"P(at least this many by chance) = {_f(d.get('p_value'), '{:.3f}')}): the effect **{verdict}**. The configurations share markets across two "
            "timeframes and two modes, so this is indicative, not a test of independent trials.")


# -- the failure analysis, from the numbers ----------------------------------------------------------

def failure_analysis(v: Mapping[str, Any]) -> List[str]:
    """Sentences for one hypothesis that did not end 'confirmed', every one computed from its failure facts."""
    facts = v.get("failure_facts") or {}
    out: List[str] = []
    n = int(_num(facts.get("n"), 0))
    gates = v.get("binding_gates") or []
    gate_text = ", ".join(f"{GATE_LABELS.get(g, g)} ({c} of {n})" for g, c in gates[:4]) if gates else "none"
    base_name = {"hold": "hold + policy sizing", "S1": "the plain S1 rule", "S2": "the plain S2 rule"}.get(facts.get("base_candidate"), "the base rule")
    if not facts.get("n_compared"):
        out.append(f"No comparison with the base rule was available. Gates missed most often: {gate_text}.")
        return out
    k = int(_num(facts.get("calmar_improved"), 0))
    exposure_rule = facts.get("base_candidate") == "hold"
    traded, total = _num(facts.get("windows_traded_total")), _num(facts.get("windows_total"))
    traded_share = traded / total if _ok(total) and total > 0 and _ok(traded) else float("nan")
    disqualified = _ok(traded_share) and traded_share < 0.5
    out.append(f"Across its {n} configurations the {'rule' if exposure_rule else 'condition'} raised the risk-adjusted result (Calmar) beside {base_name} in {k} and "
               f"lowered it in {n - k}: the median Calmar went from {_f(facts.get('median_base_calmar'))} to {_f(facts.get('median_variant_calmar'))} "
               f"({_f(facts.get('median_delta_calmar'), '{:+.2f}')}), the median yearly return from {_pct(facts.get('median_base_cagr'))} to "
               f"{_pct(facts.get('median_variant_cagr'))}, the median worst drawdown from {_pct(facts.get('median_base_dd'), signed=False)} to "
               f"{_pct(facts.get('median_variant_dd'), signed=False)}, and the median share of positive rolling 12-month windows from "
               f"{_pct(facts.get('median_base_rolling'), signed=False)} to {_pct(facts.get('median_variant_rolling'), signed=False)}.")
    if exposure_rule:
        out.append(f"It was in the market {_pct(facts.get('median_variant_exposure'), signed=False, digits=0)} of the time against "
                   f"{_pct(facts.get('median_base_exposure'), signed=False, digits=0)} for the always-long control, with a median {_f(facts.get('median_variant_trades'), '{:.0f}')} "
                   f"trades over the out-of-sample years; it beat the control by more than 0.1 Calmar (Sprint 2c's acceptance-clause yardstick) in "
                   f"{facts.get('beats_base_by_0_1', 0)} of {n} configurations; the drawdown fell in {facts.get('drawdown_fell', 0)} of {n} and the return fell in "
                   f"{facts.get('return_fell', 0)} of {n}.")
    else:
        out.append(f"It removed a median {_pct(facts.get('median_trades_removed_share'), signed=False, digits=0)} of the base rule's trades (median "
                   f"{_f(facts.get('median_base_trades'), '{:.0f}')} → {_f(facts.get('median_variant_trades'), '{:.0f}')}), changed the time in the market by "
                   f"{_pct(facts.get('median_delta_exposure'))} and the fees per year by {_pct(facts.get('median_delta_fees'), digits=2)}; the drawdown fell in "
                   f"{facts.get('drawdown_fell', 0)} of {n} configurations and the return fell in {facts.get('return_fell', 0)} of {n}.")
    if _ok(total) and total > 0:
        out.append(f"The protocol's selection rule (a bracket variant needs 20 train trades) let the {'rule' if exposure_rule else 'condition'} trade in "
                   f"{_int(traded)} of {_int(total)} walk-forward windows across the configurations; a window without a qualified variant stays flat.")
    if facts.get("median_2022_variant") is not None or facts.get("median_2022_base") is not None:
        out.append(f"In the 2022 bear year the median result moved from {_pct(facts.get('median_2022_base'))} to {_pct(facts.get('median_2022_variant'))}.")
    by_mode = facts.get("by_mode") or {}
    if "gate" in by_mode and "none" in by_mode:
        out.append(f"With the HMM regime gate already on, Calmar still rose in {by_mode['gate'].get('calmar_improved', 0)} of {by_mode['gate'].get('n', 0)} "
                   f"configurations (without the gate: {by_mode['none'].get('calmar_improved', 0)} of {by_mode['none'].get('n', 0)}).")
    by_tf = facts.get("by_timeframe") or {}
    if len(by_tf) > 1:
        out.append("By timeframe: " + "; ".join(f"{tf}: Calmar rose in {e.get('calmar_improved', 0)} of {e.get('n', 0)}" for tf, e in sorted(by_tf.items())) + ".")
    per_market = facts.get("per_market_improved") or {}
    if len(per_market) > 1:
        out.append("By market: " + "; ".join(f"{m} {e.get('calmar_improved', 0)} of {e.get('n', 0)}" for m, e in sorted(per_market.items())) + ".")
    out.append(f"Gates missed most often: {gate_text}.")
    d = _num(facts.get("median_delta_calmar"), 0.0)
    cagr_b, cagr_v = _num(facts.get("median_base_cagr")), _num(facts.get("median_variant_cagr"))
    dd_b, dd_v = _num(facts.get("median_base_dd")), _num(facts.get("median_variant_dd"))
    rel_ret = (cagr_v - cagr_b) / abs(cagr_b) if _ok(cagr_b) and abs(cagr_b) > 1e-9 and _ok(cagr_v) else float("nan")
    rel_dd = (dd_v - dd_b) / abs(dd_b) if _ok(dd_b) and abs(dd_b) > 1e-9 and _ok(dd_v) else float("nan")
    if v.get("n_passed", 0) > 0:
        out.append("Reading: the walk-forward pass did not carry into the untouched 12 months. With the holdout's falling direction known beforehand, a "
                   "rule that trades less or sits out a bear year was expected to look good there; that it did not is the stronger signal, and it says "
                   "the pass was selection luck among the configurations tried.")
    elif disqualified and exposure_rule:
        out.append(f"Reading: the rule traded too rarely for the protocol. In {_int(total - traded)} of {_int(total)} windows no bracket variant reached the 20 train "
                   "trades the selection step requires, so the configurations sat flat and their numbers measure the selection rule, not the idea; where it did "
                   f"trade it beat the control by more than 0.1 Calmar in {facts.get('beats_base_by_0_1', 0)} of {n} configurations. The idea is untested here, not "
                   "refuted: a rule that trades a few times a year needs a pre-registered protocol of its own (a lower qualification threshold for a fixed rule, "
                   "or a forward control account in the paper fleet), which is an owner decision, not an edit of this round.")
    elif disqualified:
        out.append(f"Reading: the condition removed so many entries (a median {_pct(facts.get('median_trades_removed_share'), signed=False, digits=0)} of the base "
                   f"rule's trades) that in {_int(total - traded)} of {_int(total)} windows no variant reached the 20 train trades the selection step requires, so "
                   f"most configurations sat flat; where it did trade, Calmar rose beside the base rule in {k} of {n} configurations. The base rule's entries mostly "
                   "come below the 200-day average — rallies and recoveries — so 'only in uptrends' leaves too little of the rule to judge: untested by this "
                   f"protocol rather than refuted, and the {k} of {n} says the idea is not where the missing edge is either.")
    elif exposure_rule:
        if d > 0.05:
            out.append("Reading: the slow trend filter improved the risk-managed exposure's risk-adjusted result but not enough to clear the gates it still "
                       "misses — the always-long control was itself short of them, and a filter that is flat for long stretches cannot create the return "
                       "it needs; the forward fleet, not a longer backtest, is the place to learn whether it earns its drawdown protection.")
        elif d < -0.05:
            out.append("Reading: the slow trend filter made the risk-managed exposure worse — the crosses of a 200-day average on 4H/6H bars cost fees and "
                       "missed re-entries that the always-long control never pays, and the policy sizing already halves exposure in drawdowns; the "
                       "filter's protection is not worth what it gives up here.")
        else:
            out.append("Reading: the slow trend filter changed little beside the always-long control with the same policy sizing — the sizing's crash "
                       "filter already does most of what the trend filter would do, and the time out of the market cost about what the avoided "
                       "drawdowns saved.")
    elif d <= -0.05:
        if _ok(rel_ret) and _ok(rel_dd) and rel_ret < rel_dd:
            out.append(f"Reading: the condition removed good entries along with bad ones — the return fell by {_pct(abs(rel_ret), signed=False, digits=0)} of itself while "
                       f"the drawdown changed by {_pct(rel_dd, digits=0)} of itself — so the entries it blocks are not the ones that produce the base rule's losses.")
        else:
            out.append("Reading: the condition lowered the drawdown but lowered the return with it; the losses that break the Calmar and consistency gates "
                       "come from entries the condition lets through.")
    elif abs(d) < 0.05:
        out.append("Reading: the condition changed little — it rarely binds where the base rule's losses are, so the losses that break the Calmar and "
                   "consistency gates remain. A stricter version would be a new, pre-registered test, not an edit of this one.")
    else:
        out.append(f"Reading: the condition helped — Calmar rose in {k} of {n} configurations — but not enough to clear the gates it still misses; the thin "
                   "edge of the base rule, not its entry timing, is the limit.")
    return out


# -- the plain-English summary ---------------------------------------------------------------------------

def executive_summary(run: Mapping[str, Any]) -> List[str]:
    meta = run.get("meta") or {}
    verdicts = run.get("verdicts") or []
    overall = run.get("overall") or {}
    repro = run.get("reproduction") or []
    repro_ok = sum(1 for c in repro if c.get("ok"))
    judged = _judged(run)
    passed = [r for r in judged if (r.get("acceptance") or {}).get("passed")]
    confirmed = [r for r in passed if r.get("holdout_confirmed") is True]
    too_few = [r for r in passed if r.get("holdout_confirmed") is False and _too_few_trades(r)]
    contradicted = [r for r in passed if r.get("holdout_confirmed") is False and not _too_few_trades(r)]
    bullets: List[str] = []
    repro_text = (f"Before any new rule was judged, the same unchanged code re-ran hold, S1 and S2 on every market of the round and matched the stored "
                  f"numbers — Sprint 2c's for BTC/ETH, the replication study's for the other seven markets — in {repro_ok} of {len(repro)} configurations"
                  if repro else "This run skipped the reproduction (a smoke run, not a result)")
    titles = "; ".join(f"{v['hypothesis']}: {v['title']}" for v in verdicts)
    n_markets = len({r["instrument"] for r in judged})
    bullets.append(
        f"**What we did.** We tested up to three more pre-registered hypotheses drawn from the failure analyses of the replication study (R12) and research "
        f"round 1 (R13) — {titles} — each written down with its rule, parameters, markets, timeframes, gates, readings and verdict rule before the first run. "
        f"Everything else is Sprint 2c's: the same grids, exit brackets, no-trade filter, regime gate, fixed sizing, walk-forward windows and gates. "
        f"{repro_text}. {len(judged)} configurations on {n_markets} markets were judged on {meta.get('v1c_meta', {}).get('data_span_short', 'the stored history')} "
        f"after fees and slippage; the last 12 months ({meta.get('v1c_meta', {}).get('holdout_span', '2025-10-20->2026-10-20')}) stayed untouched except for "
        "configurations that passed.")
    for v in verdicts:
        best = v.get("best") or {}
        facts = v.get("failure_facts") or {}
        base_name = {"hold": "hold + policy", "S1": "S1", "S2": "S2"}.get(v.get("base_candidate"), "the base rule")
        text = f"**{v['hypothesis']} — {v['title']}: {v['label']}.** {v['n_passed']} of {v['n_configurations']} configurations passed every gate"
        if v.get("passed"):
            text += f" ({_names(v['passed'])})"
        text += "."
        if best:
            text += f" Best: {best.get('configuration')} with Calmar {_f(best.get('calmar'))}, {_pct(best.get('cagr'))} a year at a {_pct(best.get('max_drawdown'), signed=False)} drawdown"
            if best.get("failed"):
                text += f", missing {_gates_text(best['failed'])}"
            text += "."
        if facts.get("n_compared"):
            text += (f" Beside {base_name} it raised Calmar in {facts.get('calmar_improved', 0)} of {facts.get('n_compared')} configurations "
                     f"(median {_f(facts.get('median_base_calmar'))} → {_f(facts.get('median_variant_calmar'))})")
            if v.get("base_candidate") == "hold":
                text += f" and beat the control by more than 0.1 Calmar in {facts.get('beats_base_by_0_1', 0)}."
            else:
                text += f" and removed a median {_pct(facts.get('median_trades_removed_share'), signed=False, digits=0)} of its trades."
        d = v.get("directional") or {}
        if d.get("n"):
            text += (f" Directional reading: {'replicates' if d.get('replicates_in_direction') else 'does not replicate'} in direction "
                     f"({d.get('improved')} of {d.get('n')}; the 5% level needs {d.get('threshold')}).")
        traded, total = _num(facts.get("windows_traded_total")), _num(facts.get("windows_total"))
        if _ok(total) and total > 0 and _ok(traded) and traded / total < 0.5:
            text += (f" The protocol's selection rule (20 train trades) let it trade in only {_int(traded)} of {_int(total)} walk-forward windows, so the result "
                     "measures the selection rule more than the idea: untested here rather than refuted.")
        p = v.get("pattern") or {}
        if p.get("n"):
            text += (f" Round 1's pattern (the gain in the gated 4H configurations) is {'consistent' if p.get('consistent_with_round_1') else 'not consistent'} "
                     f"here: Calmar rose in {p.get('improved')} of {p.get('n')} markets' 4H [gate] configurations (needs {p.get('min_markets')}).")
        bullets.append(text)
    if passed:
        few_text = ""
        if too_few:
            few_names = _names(f"{r['configuration']}: {_pct((r.get('holdout') or {}).get('total_return'))} from {int(_num((r.get('holdout') or {}).get('n_trades'), 0))} trades" for r in too_few)
            few_text = f" and left {len(too_few)} unconfirmed for lack of trades (fewer than {HOLDOUT_MIN_TRADES}: {few_names})"
        hold_text = (f"The untouched 12 months then confirmed {len(confirmed)} ({_names(r['configuration'] for r in confirmed)}) and contradicted "
                     f"{len(contradicted)} ({_names(r['configuration'] for r in contradicted)}){few_text}" if meta.get("evaluate_holdout")
                     else "The untouched 12 months were not opened in this run")
        bullets.append(f"**Holdout.** {hold_text}. The holdout's falling direction was known for every market before this study (pre-registered caveat), and a "
                       "slow trend filter is expected to sit out a bear year, so a confirmation here is necessary, not sufficient; the paper fleet's forward "
                       "record is the judge. The ledger below names, beside every opening, the earlier look at the same months by the comparison line.")
    else:
        bullets.append("**Holdout.** Nothing passed walk-forward, so the untouched 12 months were not opened for any new rule (the hold + policy controls' 12 "
                       "months are shown as the comparison line, as in Sprint 2c and the replication study).")
    binding = overall.get("binding_gates") or []
    if binding:
        bullets.append("**Binding gates.** " + ", ".join(f"{GATE_LABELS.get(g, g)} ({n} of {overall.get('n_judged')})" for g, n in binding[:4])
                       + f". Sprint 2c's own pass rate was 4 of 108, so two or three passes among {overall.get('n_judged')} comparisons would be expected by chance; "
                       "the holdout and the forward fleet, not the pass count, carry the verdict.")
    additions = run.get("shortlist_additions") or []
    if additions:
        added_names = _names(f"{a['candidate']} {a['instrument']} {a['timeframe']}" for a in additions)
        bullets.append(f"**Paper fleet.** {len(additions)} confirmed configuration(s) were appended to the fleet's shortlist with a source tag "
                       f"({added_names}); a running fleet takes them as new accounts at its "
                       "next restart from an updated checkout. Existing accounts are untouched. Nothing is approved for demo or live trading."
                       + (f" Shortlist file: {run['shortlist_note']}." if run.get("shortlist_note") else ""))
    else:
        bullets.append("**Paper fleet.** Nothing was confirmed, so the fleet's shortlist is unchanged. Nothing is approved for demo or live trading.")
    return bullets


# -- the report ---------------------------------------------------------------------------------------------

def _config_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Windows traded | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in rows:
        o, acc = r.get("oos") or {}, r.get("acceptance") or {}
        sel = r.get("selected_params") or {}
        bracket = sel.get("bracket", "-") if "bracket" in sel else "-"
        windows = f"{_int(o.get('windows_traded'))}/{_int(o.get('windows'))}" if o.get("windows") is not None else "-"
        lines.append(f"| {r['configuration']} | {bracket} | {_pct(o.get('total_return'))} | {_pct(o.get('cagr'))} | {_f(o.get('sharpe'))} | {_f(o.get('profit_factor'))} | "
                     f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | {_int(o.get('n_trades'))} | {windows} | {_pct(o.get('exposure'), signed=False, digits=0)} | "
                     f"{_pct(o.get('fees_pct_per_year'), signed=False)} | {_pct(acc.get('rolling_positive_share'), signed=False)} | {_pct(acc.get('worst_calendar_year_return'))} | "
                     f"{_pct((r.get('robustness') or {}).get('share_above_threshold'), signed=False)} | {_f((r.get('dsr') or {}).get('dsr'))} | "
                     f"{_gates_text(acc.get('failed') or []) if r.get('judged') else '-'} | {_verdict_word(r)} | {_holdout_cell(r)} |")
    return lines


def _comparison_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Configuration | Comparison line | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r.get("comparison") or {}
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


def _contradicted_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Breakout configuration (stored) | Study | Its walk-forward Calmar | Its holdout (contradicted) | With the filter: walk-forward | With the filter: Calmar / trades | With the filter: holdout |",
             "|---|---|---:|---|---|---|---|"]
    for e in entries:
        h = e.get("holdout") or {}
        base_hold = f"{_pct(h.get('total_return'))} / PF {_f(h.get('profit_factor'))} / {h.get('n_trades')} tr"
        if not e.get("ran"):
            lines.append(f"| {e['configuration']} | {e.get('study')} | {_f(e.get('calmar'))} | {base_hold} | not run | - | - |")
            continue
        wf = "**PASS**" if e.get("filtered_passed") else f"fail ({_gates_text(e.get('filtered_failed_gates') or [])})"
        fh = e.get("filtered_holdout")
        if fh:
            verdict = e.get("filtered_holdout_confirmed")
            fh_text = f"{_pct(fh.get('total_return'))} / PF {_f(fh.get('profit_factor'))} / {fh.get('n_trades')} tr {'✓' if verdict else '✗'} (known bear year: no verdict weight)"
        else:
            fh_text = "untouched"
        lines.append(f"| {e['configuration']} | {e.get('study')} | {_f(e.get('calmar'))} | {base_hold} | {wf} | {_f(e.get('filtered_calmar'))} / {_int(e.get('filtered_n_trades'))} | {fh_text} |")
    return lines


def _exposure_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| TF configuration | TF Calmar / CAGR / max DD / exposure / trades | Hold + policy Calmar / CAGR / max DD | Beats hold by 0.1 Calmar | S2+TF Calmar / CAGR / max DD | S2 Calmar | Breakout adds to the filter | 2022 TF / hold |",
             "|---|---|---|---|---|---:|---|---|"]

    def trip(m: Optional[Mapping[str, Any]]) -> str:
        return "-" if not m else f"{_f(m.get('calmar'))} / {_pct(m.get('cagr'))} / {_pct(m.get('max_drawdown'), signed=False)}"

    for e in entries:
        tf, hold, s2tf, s2 = e.get("tf") or {}, e.get("hold") or {}, e.get("s2tf"), e.get("s2")
        lines.append(f"| {e['configuration']} | {_f(tf.get('calmar'))} / {_pct(tf.get('cagr'))} / {_pct(tf.get('max_drawdown'), signed=False)} / "
                     f"{_pct(tf.get('exposure'), signed=False, digits=0)} / {_int(tf.get('n_trades'))} | {trip(hold)} | "
                     f"{'-' if e.get('beats_hold') is None else _yes(e.get('beats_hold'))} | {trip(s2tf)} | {_f((s2 or {}).get('calmar'))} | "
                     f"{'-' if e.get('breakout_adds') is None else _yes(e.get('breakout_adds'))} | "
                     f"{_pct((tf.get('yearly') or {}).get('2022'))} / {_pct((hold.get('yearly') or {}).get('2022'))} |")
    return lines


def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    v1c_meta = meta.get("v1c_meta") or {}
    verdicts = run.get("verdicts") or []
    lines: List[str] = []
    lines += [
        "# Research round 2 — three pre-registered hypotheses from the R12 and R13 failure analyses (walk-forward, SIMULATION ONLY)",
        "",
        f"Generated {meta.get('generated_at', '-')} by `scripts/run_research_round_2.py` (plan row R16; {meta.get('elapsed_minutes', '-')} min). Rules: Sprint 2c's, run by "
        f"`scripts/run_research_v1c.py`'s own `run_series`, unchanged (policy sizing `{(v1c_meta.get('policy_sizing') or {}).get('label', '-')}`, regime gate "
        f"`{(v1c_meta.get('regime') or {}).get('label', '-')}`, S0 filter {v1c_meta.get('no_trade_label', '-')}, walk-forward train {v1c_meta.get('train_days', '-')}d → purge "
        f"{v1c_meta.get('purge_days', '-')}d → test {v1c_meta.get('test_days', '-')}d, fee {_pct(v1c_meta.get('fee_rate'), signed=False, digits=2)} + slippage "
        f"{_pct(v1c_meta.get('slippage_rate'), signed=False, digits=3)} per side, brackets {v1c_meta.get('bracket_variants', '-')}). Data: PUBLIC OKX spot candles of nine "
        f"markets (1H and 4H stored, 6H resampled from 1H) frozen at Sprint 2c's data end (bar close ≤ {meta.get('data_end', '-')}). Holdout: the last 12 months "
        f"({v1c_meta.get('holdout_span', '-')}), opened once and only for configurations that passed walk-forward.",
        "",
        "**Nothing here authorizes paper, demo or live trading.** A passing configuration is a hypothesis for the forward paper fleet, not a strategy to deploy. "
        "Every number is a simulation on historical public data.",
        "",
        "## Executive summary (plain English)",
        "",
    ]
    for b in executive_summary(run):
        lines.append(f"- {b}")

    # Fixed before the first run.
    prereg = meta.get("preregistration") or {}
    lines += ["", "## Fixed before the first run (the pre-registration)", "",
              f"Pre-registration hash (text, file and configuration): `{meta.get('preregistration_sha256', '-')}`; file `{meta.get('preregistration_file', '-')}` "
              f"written {meta.get('preregistration_written_at', '-')}.", ""]
    for k, v in prereg.items():
        if k == "hypotheses":
            continue
        lines.append(f"- **{k}**: {v}")
    for hk, h in (prereg.get("hypotheses") or {}).items():
        lines += ["", f"### {hk} — {h.get('title')}", ""]
        for k, v in h.items():
            if k != "title":
                lines.append(f"- **{k}**: {v}")
    protocol = meta.get("protocol_check") or {}
    lines += ["", f"Protocol check against the stored Sprint 2c run: {'every parameter the same' if protocol.get('ok') else 'MISMATCHES: ' + str(protocol.get('mismatches'))} "
              f"(checked: {', '.join(protocol.get('checked') or [])}; new candidates, not in Sprint 2c by design: {_names(protocol.get('new_candidates') or [])}).",
              "", "Gates (unchanged from Sprint 2c): " + "; ".join(f"{k} {v}" for k, v in (meta.get("gates") or GATES).items()) + "."]
    if meta.get("second_look_warning"):
        lines += ["", f"**Warning — second look.** An earlier run already opened the holdout of: {_names(meta['second_look_warning'])}. Both looks are in the ledger below."]

    # Reproduction.
    repro = run.get("reproduction") or []
    lines += ["", "## Reproduction of the stored studies", ""]
    if repro:
        lines += ["Before any new rule ran, hold, S1 and S2 on every market of the round went through the same loaded runner and had to give the stored walk-forward "
                  "numbers (6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts — Sprint 2c's for BTC-USDT and ETH-USDT, the "
                  "replication study's for the other seven markets — otherwise the study stops.", "",
                  "| Candidate | Series | Regime | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Same verdict | Largest difference | Agrees |",
                  "|---|---|---|---|---|---|---:|---|---|---:|---|"]
        for c in repro:
            got, exp = c.get("reproduced") or {}, c.get("stored") or {}
            lines.append(f"| {c['candidate']} | {c['instrument']} {c['timeframe']} | {c.get('regime')} | {_f(got.get('total_return'), '{:.6f}')} / {_f(exp.get('total_return'), '{:.6f}')} | "
                         f"{_f(got.get('sharpe'), '{:.6f}')} / {_f(exp.get('sharpe'), '{:.6f}')} | {_f(got.get('max_drawdown'), '{:.6f}')} / {_f(exp.get('max_drawdown'), '{:.6f}')} | "
                         f"{c.get('n_trades')} / {c.get('n_trades_stored')} | {_yes(c.get('selected_matches'))} | {_yes(c.get('verdict_matches'))} | "
                         f"{_num(c.get('max_abs_difference'), 0.0):.1e} | {_yes(c.get('ok'))} |")
        lines += ["", f"{sum(1 for c in repro if c.get('ok'))} of {len(repro)} reproduced."]
    else:
        lines.append("Not run in this invocation (a smoke run). Nothing here is a result.")

    # Per hypothesis.
    all_results = _results(run)
    base_names = {"hold": "hold + policy sizing", "S1": "the plain S1 rule", "S2": "the plain S2 rule"}
    for v in verdicts:
        hk = v["hypothesis"]
        rows = [r for r in all_results if r.get("hypothesis") == hk and r.get("judged")]
        lines += ["", f"## {hk} — {v['title']}: **{v['label']}**", ""]
        lines += _config_table(rows)
        base_name = base_names.get(v.get("base_candidate"), "the base rule")
        lines += ["", f"Beside {base_name} (same market, timeframe and mode — the control has one mode; stored numbers reproduced in this run):", ""]
        lines += _comparison_table(rows)
        lines += ["", _directional_sentence(v.get("directional") or {}, base_name)]
        p = v.get("pattern")
        if p and p.get("n"):
            lines.append(f"Pattern check (pre-registered): round 1 found the gain concentrated in the gated 4H configurations; here Calmar rose in {p['improved']} of "
                         f"{p['n']} markets' 4H [gate] configurations ({_names(p.get('markets_improved') or [])}), against the pre-registered {p['min_markets']} of 7: "
                         f"**{'consistent with round 1' if p.get('consistent_with_round_1') else 'not consistent with round 1'}**.")
        if v.get("contradicted_outcomes"):
            lines += ["", "The breakout configurations that passed walk-forward and were contradicted by the untouched 12 months (Sprint 2c, the replication study), "
                      "and what the same rule with the slow trend filter did on those series. The base rule's holdout loss in a bear year is known, and a trend filter is "
                      "expected to sit that year out, so the last column carries no verdict weight:", ""]
            lines += _contradicted_table(v["contradicted_outcomes"])
        if v.get("exposure"):
            lines += ["", "The filter as the exposure rule beside the always-long control with the same policy sizing, and beside the filtered breakout rule (H5) on the same series and mode:", ""]
            lines += _exposure_table(v["exposure"])
            adds = [e for e in v["exposure"] if e.get("breakout_adds") is not None]
            if adds:
                n_adds = sum(1 for e in adds if e.get("breakout_adds"))
                beats = [e for e in v["exposure"] if e.get("beats_hold") is not None]
                lines.append(f"The breakout rule added to the filter (S2+TF's Calmar above TF's) on {n_adds} of {len(adds)} series; TF beat hold + policy by more than "
                             f"0.1 Calmar on {sum(1 for e in beats if e.get('beats_hold'))} of {len(beats)}.")
        lines.append("")
        if v["label"] == "confirmed":
            lines.append(f"**Confirmed.** {_names(v.get('confirmed') or [])} passed every walk-forward gate and the untouched 12 months confirmed it; it joins the paper "
                         "fleet's shortlist (below). The holdout's falling direction was known before this study, so the forward fleet, not this confirmation, is the judge.")
            if v.get("n_passed", 0) > v.get("n_confirmed", 0):
                lines.append(f"The other passers were not confirmed: {_names(v.get('contradicted') or [])}. That is {v.get('n_confirmed')} confirmation among "
                             f"{v.get('n_passed')} walk-forward passers — the same order as Sprint 2c (1 of 4) and the replication study (2 of 10), so the condition's "
                             "strong walk-forward direction did not make its passers more durable than the base rules' were.")
            for look in run.get("earlier_looks") or []:
                r_new = next((r for r in rows if r.get("configuration") == look.get("configuration")), None)
                if look.get("earlier_opened") and look.get("earlier_confirmed") is True and r_new is not None and r_new.get("holdout_confirmed") is False:
                    lines.append(f"On {r_new['instrument']} the comparison line's own holdout was confirmed ({look.get('earlier_configuration')}: "
                                 f"{_pct(look.get('earlier_total_return'))}, PF {_f(look.get('earlier_profit_factor'))}, {look.get('earlier_n_trades')} trades) while "
                                 f"{look.get('configuration')} was contradicted ({_pct((r_new.get('holdout') or {}).get('total_return'))}): there the condition changed the "
                                 "selected rule and removed the entries that made the base rule's year.")
        else:
            lines.append("**Failure analysis** (computed from the numbers above):")
            lines.append("")
            for s in failure_analysis(v):
                lines.append(f"- {s}")

    # Controls and reproduction rows for reference.
    ref_rows = [r for r in all_results if r.get("role") in ("control", "reproduction")]
    if ref_rows:
        lines += ["", "## The comparison lines — hold + policy controls and the plain S1 / S2 rules (stored numbers, reproduced here)", ""]
        lines += _config_table(ref_rows)
        spans = [s.get("span") for s in run.get("series", []) if s.get("span")]
        if spans:
            lines += ["", "Data spans: " + "; ".join(spans) + "."]
    failures = [f for s in run.get("series", []) for f in (s.get("failures") or [])]
    if failures:
        lines += ["", "Runs that failed with an error (not evaluated):", ""]
        for f in failures:
            lines.append(f"- {f.get('candidate')} on {f.get('instrument')} {f.get('timeframe')} ({f.get('regime', '-')}): `{f.get('error')}`")
    if meta.get("skipped_series"):
        lines += ["", "Series skipped (too little data): " + "; ".join(meta["skipped_series"]) + "."]

    # Holdout.
    lines += ["", "## The untouched 12 months", ""]
    this_run = [r for r in all_results if r.get("holdout")]
    if this_run:
        lines += [f"Opened once, only for configurations that passed every walk-forward gate (and the hold + policy controls as the comparison line). Verdict ✓ = positive "
                  f"return, PF > 1 and ≥ {HOLDOUT_MIN_TRADES} trades. The holdout's falling direction was known before the run (see the pre-registration).", "",
                  "| Configuration | Return | Max DD | PF | Trades | Verdict |", "|---|---:|---:|---:|---:|---|"]
        for r in this_run:
            h = r["holdout"]
            verdict = "control (comparison line)" if r.get("role") == "control" else ("comparison line" if r.get("role") == "reproduction" else _holdout_outcome(r))
            lines.append(f"| {r['configuration']} | {_pct(h.get('total_return'))} | {_pct(h.get('max_drawdown'), signed=False)} | {_f(h.get('profit_factor'))} | {h.get('n_trades')} | {verdict} |")
    else:
        lines.append("Not opened in this run: " + ("no configuration passed walk-forward." if not meta.get("evaluate_holdout")
                                                    or not [r for r in _judged(run) if (r.get('acceptance') or {}).get('passed')] else "the holdout was not requested."))
    looks = run.get("earlier_looks") or []
    if looks:
        lines += ["", "### Earlier looks at the same months by the comparison lines", "",
                  "A new rule on a series whose base rule already opened its holdout is a near-second look at those months; the base rule's stored result is shown beside it.", "",
                  "| Configuration opened in this run | Comparison line | Study | Its holdout then |", "|---|---|---|---|"]
        for e in looks:
            if e.get("earlier_opened"):
                mark = "" if e.get("earlier_confirmed") is None else (" ✓" if e.get("earlier_confirmed") else " ✗")
                then = f"{_pct(e.get('earlier_total_return'))} / PF {_f(e.get('earlier_profit_factor'))} / {e.get('earlier_n_trades')} tr{mark}"
            else:
                then = "never opened"
            lines.append(f"| {e['configuration']} | {e.get('earlier_configuration') or '-'} | {e.get('earlier_study') or '-'} | {then} |")
    ledger = meta.get("holdout_ledger") or []
    if ledger:
        lines += ["", "### Every opening of the holdout (ledger)", "",
                  f"Each run that opened a holdout appends its openings to `{meta.get('holdout_ledger_path', '-')}`; earlier looks stay visible here even when a later run "
                  "replaces the numbers above.", "", "| Run | Configuration | Role | Return | Max DD | PF | Trades | Verdict |", "|---|---|---|---:|---:|---:|---:|---|"]
        for i, e in enumerate(ledger, start=1):
            for o in e.get("openings", []):
                few = _num(o.get("total_return")) > 0 and _num(o.get("profit_factor")) > 1.0 and int(_num(o.get("n_trades"), 0)) < HOLDOUT_MIN_TRADES
                verdict = ("comparison" if o.get("role") in ("control", "reproduction") else "confirmed" if o.get("confirmed")
                           else f"not confirmed ({int(_num(o.get('n_trades'), 0))} trades)" if few else "contradicted")
                lines.append(f"| {i} ({e.get('generated_at', '-')}) | {o.get('configuration')} | {o.get('role')} | {_pct(o.get('total_return'))} | "
                             f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('profit_factor'))} | {o.get('n_trades')} | {verdict} |")

    # Shortlist.
    additions = run.get("shortlist_additions") or []
    lines += ["", "## Paper-fleet shortlist", ""]
    if additions:
        lines += ["Confirmed passers appended to `docs/research/paper_fleet_shortlist_v1c.json` with a `source` tag (existing entries and running accounts untouched):", ""]
        for a in additions:
            lines.append(f"- {a['candidate']} {a['instrument']} {a['timeframe']} ({a.get('regime')}): walk-forward Calmar {_f(a.get('calmar'))}, holdout "
                         f"{_pct((a.get('holdout') or {}).get('total_return'))}" + (f" — {a['source'].get('note')}" if (a.get('source') or {}).get('note') else ""))
        if run.get("shortlist_note"):
            lines += ["", f"Shortlist file: {run['shortlist_note']}."]
    else:
        lines.append("Unchanged: no configuration was both a walk-forward passer and confirmed by the untouched 12 months.")

    # Owner decisions and method notes.
    overall = run.get("overall") or {}
    lines += ["", "## Owner decisions (nothing below is decided by this report)", ""]
    if additions:
        lines.append(f"- **Fleet.** {len(additions)} new paper account(s) join at the fleet's next restart from an updated checkout (`docs/runbooks/PAPER_FLEET.md`). "
                     "Recommended: let them run; judge them at G7 with the rest.")
    else:
        lines.append("- **Fleet.** Nothing to add. Recommended: no change.")
    lines.append(f"- **What the verdicts mean.** {'; '.join(f'{k}: {v}' for k, v in (overall.get('labels') or {}).items())}. No gate, parameter, condition, market or verdict "
                 "rule changed after the results. If a gate looks wrong, that is a note for the next pre-registered round, not an edit of this one.")
    slow = [v for v in verdicts if _ok(_num((v.get("failure_facts") or {}).get("windows_total"))) and _num((v.get("failure_facts") or {}).get("windows_total")) > 0
            and _num((v.get("failure_facts") or {}).get("windows_traded_total")) / _num((v.get("failure_facts") or {}).get("windows_total")) < 0.5]
    if slow:
        lines.append("- **Slow rules.** " + "; ".join(f"{v['hypothesis']} traded in {_int((v.get('failure_facts') or {}).get('windows_traded_total'))} of "
                                                     f"{_int((v.get('failure_facts') or {}).get('windows_total'))} windows" for v in slow)
                     + ": the protocol's 20-train-trade qualification, built for rules that trade weekly, cannot judge a rule that trades a few times a year. "
                     "Whether to evaluate such rules another way — a forward control account in the paper fleet, or a pre-registered protocol variant with a "
                     "lower qualification threshold for fixed rules — is a decision for the owner (`docs/PLAN_STATUS.md`, section 2); nothing here is retuned.")
    lines.append("- **Next round.** The failure analyses above say which ideas are not worth another test; anything left credible is a decision for the owner, as a "
                 "new plan row.")
    lines += ["", "## Method notes and caveats", "",
              "- The rules were not re-implemented and the runner was not changed: Sprint 2c's runner module ran them; the reproduction table shows the same code "
              "gives the stored numbers for hold, S1 and S2 on every market of the round.",
              "- The conditions gate entries only (an open position is left to the base rule's own exits and stop), exactly as the regime gate, the S5 filter and the "
              "round-1 conditions do; TF is a rule, not a condition: it exits when the close crosses back below its average and carries no stop, so the protocol's "
              "take-profit and trailing brackets are inert for it and its walk-forward selects only between no bracket and the 30-day time stop.",
              "- TF's one parameter is a single grid value; the protocol's robustness replay perturbs it by ±30 % (140 and 260 days) like every rule's numeric "
              "parameters. The protocol's selection rule (20 train trades) applies to it unchanged; the 'Windows traded' column shows where it bound.",
              "- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the fixed "
              "policy sizing is Sprint 2b's; none of them was adapted to the new rules or the new markets.",
              "- The reproduction re-runs stored passers through the same holdout code path (S2 BTC-USDT 4H [gate], S1 SOL-USDT 6H [none], the contradicted S2 rows on "
              "ADA, DOGE and TRX), so their already-opened 12 months appear again in the ledger as comparison lines with their stored numbers; that is a repeat of a "
              "known result, not a new look. A new rule's opening on a series whose base rule already opened its holdout is listed as an earlier look above.",
              f"- {overall.get('n_judged', 0)} judged configurations are {overall.get('n_judged', 0)} more comparisons on the same six years; two or three passes among "
              "them at the Sprint 2c pass rate would be expected by chance, which is why the holdout and the forward fleet, not single passes, carry the verdict. "
              "The directional sign tests treat configurations as trials although they share markets, so they are indicative only.",
              "- The holdout's falling direction was known for every market before this study; every condition reduces time in the market and a slow trend "
              "filter is built to sit out a bear year. Confirmation there is necessary, not sufficient.",
              "- Every number is a simulation on historical public data and proves nothing about the future."]
    return "\n".join(lines) + "\n"
