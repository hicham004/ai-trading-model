"""Research round 1 report (plan row R13, SIMULATION ONLY).

Renders ``docs/research/RESEARCH_ROUND_1_REPORT.md`` from the study's results
JSON. Every plain-English sentence — the summary, each hypothesis's verdict and
the failure analysis of every hypothesis that fails — is computed from the
numbers in the run, so a re-run on other data cannot print a stale claim.
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
    return [r for r in _results(run) if r.get("judged")] + [c for c in run.get("combined", []) if c.get("judged")]


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
    if role == "leg":
        return "leg (not judged)"
    return "**PASS**" if (r.get("acceptance") or {}).get("passed") else "fail"


# -- the failure analysis, from the numbers ----------------------------------------------------------

def failure_analysis(v: Mapping[str, Any]) -> List[str]:
    """Sentences for one hypothesis that did not end 'confirmed', every one computed from its failure facts."""
    facts = v.get("failure_facts") or {}
    out: List[str] = []
    n = int(_num(facts.get("n"), 0))
    gates = v.get("binding_gates") or []
    gate_text = ", ".join(f"{GATE_LABELS.get(g, g)} ({c} of {n})" for g, c in gates[:4]) if gates else "none"
    if v.get("combined"):
        mc, ms1 = facts.get("median_calmar"), facts.get("median_best_s1_calmar")
        out.append(f"The one-position curve's median Calmar was {_f(mc)} against {_f(ms1)} for the better of the two plain S1 rules on the same bars: "
                   f"it beat both plain S1 rules in {facts.get('beats_best_s1', 0)} of {n} configurations and the hold + policy controls of both markets in "
                   f"{facts.get('beats_hold', 0)} of {n}.")
        out.append(f"It traded a median {_f(facts.get('median_trades_per_year'), '{:.0f}')} times a year against {_f(facts.get('median_s1_trades_per_year'), '{:.0f}')} "
                   f"for plain S1 on one market, and was in the market {_pct(facts.get('median_exposure'), signed=False, digits=0)} of the time against "
                   f"{_pct(facts.get('median_s1_exposure'), signed=False, digits=0)} for plain S1: the switches between the two markets are extra trades at full "
                   "cost, and the 'both trends up' condition keeps the position out whenever one market lags.")
        if facts.get("median_2022") is not None:
            out.append(f"In the 2022 bear year the median result was {_pct(facts.get('median_2022'))} against {_pct(facts.get('median_s1_2022'))} for plain S1.")
        legs = facts.get("legs") or []
        if legs:
            out.append("The legs on their own: " + "; ".join(f"{l['configuration']} Calmar {_f(l.get('calmar'))}, {_int(l.get('n_trades'))} trades, "
                                                                 f"PF {_f(l.get('profit_factor'))}" for l in legs) + ".")
        out.append(f"Gates missed most often: {gate_text}.")
        if _ok(mc) and _ok(ms1) and _num(mc) < _num(ms1):
            out.append("Reading: concentrating the one position in the stronger market did not beat simply running the plain trend rule on each market — "
                       "the relative-strength switches added trades and fees without adding return, and requiring both trends to be up removed "
                       "exposure in the months the trend rules earn their return. The idea is not where the missing edge is.")
        elif v.get("n_passed", 0) == 0:
            out.append("Reading: the concentration helped the risk-adjusted result but the curve still misses the gates above for the same reasons the "
                       "plain rules miss them — the thin edge of long-only timing, not the choice between the two markets.")
        else:
            out.append("Reading: the walk-forward pass did not carry into the untouched 12 months; with the holdout's falling direction known beforehand, "
                       "that is the expected fate of a rule that only concentrates a long position.")
        return out
    if not facts.get("n_compared"):
        out.append(f"No comparison with the base rule was available. Gates missed most often: {gate_text}.")
        return out
    k = int(_num(facts.get("calmar_improved"), 0))
    out.append(f"Across its {n} configurations the condition raised the risk-adjusted result (Calmar) in {k} and lowered it in {n - k}: the median Calmar went from "
               f"{_f(facts.get('median_base_calmar'))} to {_f(facts.get('median_variant_calmar'))} ({_f(facts.get('median_delta_calmar'), '{:+.2f}')}), the median "
               f"yearly return from {_pct(facts.get('median_base_cagr'))} to {_pct(facts.get('median_variant_cagr'))}, the median worst drawdown from "
               f"{_pct(facts.get('median_base_dd'), signed=False)} to {_pct(facts.get('median_variant_dd'), signed=False)}, and the median share of positive rolling "
               f"12-month windows from {_pct(facts.get('median_base_rolling'), signed=False)} to {_pct(facts.get('median_variant_rolling'), signed=False)}.")
    out.append(f"It removed a median {_pct(facts.get('median_trades_removed_share'), signed=False, digits=0)} of the base rule's trades (median "
               f"{_f(facts.get('median_base_trades'), '{:.0f}')} → {_f(facts.get('median_variant_trades'), '{:.0f}')}), changed the time in the market by "
               f"{_pct(facts.get('median_delta_exposure'))} and the fees per year by {_pct(facts.get('median_delta_fees'), digits=2)}; the drawdown fell in "
               f"{facts.get('drawdown_fell', 0)} of {n} configurations and the return fell in {facts.get('return_fell', 0)} of {n}.")
    if facts.get("median_2022_variant") is not None or facts.get("median_2022_base") is not None:
        out.append(f"In the 2022 bear year the median result moved from {_pct(facts.get('median_2022_base'))} to {_pct(facts.get('median_2022_variant'))}.")
    by_mode = facts.get("by_mode") or {}
    if "gate" in by_mode and "none" in by_mode:
        out.append(f"With the HMM regime gate already on, the condition still raised Calmar in {by_mode['gate'].get('calmar_improved', 0)} of {by_mode['gate'].get('n', 0)} "
                   f"configurations (without the gate: {by_mode['none'].get('calmar_improved', 0)} of {by_mode['none'].get('n', 0)}).")
    out.append(f"Gates missed most often: {gate_text}.")
    d = _num(facts.get("median_delta_calmar"), 0.0)
    cagr_b, cagr_v = _num(facts.get("median_base_cagr")), _num(facts.get("median_variant_cagr"))
    dd_b, dd_v = _num(facts.get("median_base_dd")), _num(facts.get("median_variant_dd"))
    rel_ret = (cagr_v - cagr_b) / abs(cagr_b) if _ok(cagr_b) and abs(cagr_b) > 1e-9 and _ok(cagr_v) else float("nan")
    rel_dd = (dd_v - dd_b) / abs(dd_b) if _ok(dd_b) and abs(dd_b) > 1e-9 and _ok(dd_v) else float("nan")
    if v.get("n_passed", 0) > 0:
        out.append("Reading: the walk-forward pass did not carry into the untouched 12 months. With the holdout's falling direction known beforehand, a "
                   "condition that only trades less was expected to look good there; that it did not is the stronger signal, and it says the pass was "
                   "selection luck among the configurations tried.")
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
    repro_text = (f"Before any new rule was judged, the same code (with the one change: a feature context that also carries the other market's candles) "
                  f"re-ran hold, S1 and S2 on BTC and ETH and matched Sprint 2c's stored numbers in {repro_ok} of {len(repro)} configurations"
                  if repro else "This run skipped the BTC/ETH reproduction (a smoke run, not a result)")
    titles = "; ".join(f"{v['hypothesis']}: {v['title']}" for v in verdicts)
    bullets.append(
        f"**What we did.** We tested up to three new entry conditions on top of the unchanged Sprint 2c rules ({titles}), each written down with its "
        f"rule, parameters, markets, timeframes, gates and verdict rule before the first run. Everything else is Sprint 2c's: the same grids, exit brackets, "
        f"no-trade filter, regime gate, fixed sizing, walk-forward windows and gates. {repro_text}. {len(judged)} configurations were judged on "
        f"{meta.get('v1c_meta', {}).get('data_span_short', 'the stored history')} after fees and slippage; the last 12 months "
        f"({meta.get('v1c_meta', {}).get('holdout_span', '2025-10-20->2026-10-20')}) stayed untouched except for configurations that passed.")
    for v in verdicts:
        best = v.get("best") or {}
        facts = v.get("failure_facts") or {}
        text = f"**{v['hypothesis']} — {v['title']}: {v['label']}.** {v['n_passed']} of {v['n_configurations']} configurations passed every gate"
        if v.get("passed"):
            text += f" ({_names(v['passed'])})"
        text += "."
        if best:
            text += f" Best: {best.get('configuration')} with Calmar {_f(best.get('calmar'))}, {_pct(best.get('cagr'))} a year at a {_pct(best.get('max_drawdown'), signed=False)} drawdown"
            if best.get("failed"):
                text += f", missing {_gates_text(best['failed'])}"
            text += "."
        if v.get("combined"):
            if facts.get("median_calmar") is not None:
                text += (f" The one-position curve's median Calmar was {_f(facts.get('median_calmar'))} against {_f(facts.get('median_best_s1_calmar'))} for the "
                         f"better plain S1 rule; it beat both plain S1 rules in {facts.get('beats_best_s1', 0)} of {v['n_configurations']} configurations.")
        elif facts.get("n_compared"):
            text += (f" Beside the base rule the condition raised Calmar in {facts.get('calmar_improved', 0)} of {facts.get('n_compared')} configurations "
                     f"(median {_f(facts.get('median_base_calmar'))} → {_f(facts.get('median_variant_calmar'))}) and removed a median "
                     f"{_pct(facts.get('median_trades_removed_share'), signed=False, digits=0)} of its trades.")
        bullets.append(text)
    if passed:
        few_text = ""
        if too_few:
            few_names = _names(f"{r['configuration']}: {_pct((r.get('holdout') or {}).get('total_return'))} from {int(_num((r.get('holdout') or {}).get('n_trades'), 0))} trades" for r in too_few)
            few_text = f" and left {len(too_few)} unconfirmed for lack of trades (fewer than {HOLDOUT_MIN_TRADES}: {few_names})"
        hold_text = (f"The untouched 12 months then confirmed {len(confirmed)} ({_names(r['configuration'] for r in confirmed)}) and contradicted "
                     f"{len(contradicted)} ({_names(r['configuration'] for r in contradicted)}){few_text}" if meta.get("evaluate_holdout")
                     else "The untouched 12 months were not opened in this run")
        bullets.append(f"**Holdout.** {hold_text}. The holdout's falling direction was known before this study (pre-registered caveat), so a confirmation "
                       "here is necessary, not sufficient; the paper fleet's forward record is the judge.")
    else:
        bullets.append("**Holdout.** Nothing passed walk-forward, so the untouched 12 months were not opened for any new rule (the hold + policy controls' 12 "
                       "months are shown as the comparison line, as in Sprint 2c).")
    binding = overall.get("binding_gates") or []
    if binding:
        bullets.append("**Binding gates.** " + ", ".join(f"{GATE_LABELS.get(g, g)} ({n} of {overall.get('n_judged')})" for g, n in binding[:4])
                       + f". Sprint 2c's own pass rate was 4 of 108, so a pass or two among {overall.get('n_judged')} comparisons would be expected by chance; "
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
    lines = ["| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in rows:
        o, acc = r.get("oos") or {}, r.get("acceptance") or {}
        sel = r.get("selected_params") or {}
        bracket = sel.get("bracket", "-") if "bracket" in sel else ("/".join(str((p or {}).get("bracket", "-")) for p in sel.values()) if sel else "-")
        lines.append(f"| {r['configuration']} | {bracket} | {_pct(o.get('total_return'))} | {_pct(o.get('cagr'))} | {_f(o.get('sharpe'))} | {_f(o.get('profit_factor'))} | "
                     f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | {_int(o.get('n_trades'))} | {_pct(o.get('exposure'), signed=False, digits=0)} | "
                     f"{_pct(o.get('fees_pct_per_year'), signed=False)} | {_pct(acc.get('rolling_positive_share'), signed=False)} | {_pct(acc.get('worst_calendar_year_return'))} | "
                     f"{_pct((r.get('robustness') or {}).get('share_above_threshold'), signed=False)} | {_f((r.get('dsr') or {}).get('dsr'))} | "
                     f"{_gates_text(acc.get('failed') or []) if r.get('judged') else '-'} | {_verdict_word(r)} | {_holdout_cell(r)} |")
    return lines


def _comparison_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Configuration | Base | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |",
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


def _h3_comparison_table(facts: Mapping[str, Any]) -> List[str]:
    lines = ["| Combined configuration | Combined Calmar / CAGR / max DD / trades / exposure | S1 BTC Calmar / CAGR / max DD | S1 ETH Calmar / CAGR / max DD | Hold+policy BTC / ETH Calmar | Leg BTC Calmar / trades | Leg ETH Calmar / trades | 2022 combined / S1 BTC / S1 ETH |",
             "|---|---|---|---|---|---|---|---|"]

    def trip(m: Optional[Mapping[str, Any]]) -> str:
        return "-" if not m else f"{_f(m.get('calmar'))} / {_pct(m.get('cagr'))} / {_pct(m.get('max_drawdown'), signed=False)}"

    for c in facts.get("comparisons") or []:
        m = c["combined"]
        hb, he = c.get("hold_btc") or {}, c.get("hold_eth") or {}
        lb, le = c.get("leg_btc") or {}, c.get("leg_eth") or {}
        lines.append(f"| {c['configuration']} | {_f(m.get('calmar'))} / {_pct(m.get('cagr'))} / {_pct(m.get('max_drawdown'), signed=False)} / {_int(m.get('n_trades'))} / "
                     f"{_pct(m.get('exposure'), signed=False, digits=0)} | {trip(c.get('s1_btc'))} | {trip(c.get('s1_eth'))} | {_f(hb.get('calmar'))} / {_f(he.get('calmar'))} | "
                     f"{_f(lb.get('calmar'))} / {_int(lb.get('n_trades'))} | {_f(le.get('calmar'))} / {_int(le.get('n_trades'))} | "
                     f"{_pct((m.get('yearly') or {}).get('2022'))} / {_pct(((c.get('s1_btc') or {}).get('yearly') or {}).get('2022'))} / "
                     f"{_pct(((c.get('s1_eth') or {}).get('yearly') or {}).get('2022'))} |")
    return lines


def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    v1c_meta = meta.get("v1c_meta") or {}
    verdicts = run.get("verdicts") or []
    lines: List[str] = []
    lines += [
        "# Research round 1 — three pre-registered entry conditions on the unchanged Sprint 2c rules (walk-forward, SIMULATION ONLY)",
        "",
        f"Generated {meta.get('generated_at', '-')} by `scripts/run_research_round_1.py` (plan row R13; {meta.get('elapsed_minutes', '-')} min). Rules: Sprint 2c's, run by "
        f"`scripts/run_research_v1c.py`'s own `run_series` (policy sizing `{(v1c_meta.get('policy_sizing') or {}).get('label', '-')}`, regime gate "
        f"`{(v1c_meta.get('regime') or {}).get('label', '-')}`, S0 filter {v1c_meta.get('no_trade_label', '-')}, walk-forward train {v1c_meta.get('train_days', '-')}d → purge "
        f"{v1c_meta.get('purge_days', '-')}d → test {v1c_meta.get('test_days', '-')}d, fee {_pct(v1c_meta.get('fee_rate'), signed=False, digits=2)} + slippage "
        f"{_pct(v1c_meta.get('slippage_rate'), signed=False, digits=3)} per side, brackets {v1c_meta.get('bracket_variants', '-')}), with one addition: a feature context that "
        f"also carries the other market's candles for the cross-asset rules. Data: the same PUBLIC OKX spot candles as Sprint 2c (1H and 4H stored, 6H resampled from "
        f"1H) frozen at Sprint 2c's data end (bar close ≤ {meta.get('data_end', '-')}). Holdout: the last 12 months ({v1c_meta.get('holdout_span', '-')}), opened once "
        "and only for configurations that passed walk-forward.",
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
    lines += ["", "## Reproduction of Sprint 2c", ""]
    if repro:
        lines += ["Before any new rule ran, hold, S1 and S2 on BTC-USDT and ETH-USDT went through the same loaded runner with the cross-asset context and had to give "
                  "Sprint 2c's stored walk-forward numbers (6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts — otherwise the study stops.", "",
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
    combined = run.get("combined") or []
    for v in verdicts:
        hk = v["hypothesis"]
        lines += ["", f"## {hk} — {v['title']}: **{v['label']}**", ""]
        if v.get("combined"):
            rows = [c for c in combined if c.get("hypothesis") == hk]
            legs = [r for r in all_results if r.get("hypothesis") == hk]
            lines += ["The combined one-position curve per timeframe and regime mode (judged), built bar by bar from the two legs' stitched out-of-sample returns:", ""]
            lines += _config_table(rows)
            lines += ["", "The legs on their own (components, not judged):", ""]
            lines += _config_table(legs)
            lines += ["", "Beside the plain S1 rule on each market and the hold + policy controls (same timeframe and mode; Sprint 2c's stored numbers, reproduced in this run):", ""]
            lines += _h3_comparison_table(v.get("failure_facts") or {})
        else:
            rows = [r for r in all_results if r.get("hypothesis") == hk and r.get("judged")]
            lines += _config_table(rows)
            lines += ["", "Beside the base rule (same instrument, timeframe and mode; Sprint 2c's stored numbers, reproduced in this run):", ""]
            lines += _comparison_table(rows)
        lines.append("")
        if v["label"] == "confirmed":
            lines.append(f"**Confirmed.** {_names(v.get('confirmed') or [])} passed every walk-forward gate and the untouched 12 months confirmed it; it joins the paper "
                         "fleet's shortlist (below). The holdout's falling direction was known before this study, so the forward fleet, not this confirmation, is the judge.")
        else:
            lines.append("**Failure analysis** (computed from the numbers above):")
            lines.append("")
            for s in failure_analysis(v):
                lines.append(f"- {s}")

    # Controls and reproduction rows for reference.
    ref_rows = [r for r in all_results if r.get("role") in ("control", "reproduction")]
    if ref_rows:
        lines += ["", "## The comparison lines — hold + policy controls and the plain S1 / S2 rules (Sprint 2c's numbers, reproduced here)", ""]
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
    this_run = [r for r in all_results if r.get("holdout")] + [c for c in combined if c.get("holdout")]
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
    lines.append(f"- **What the verdicts mean.** {'; '.join(f'{k}: {v}' for k, v in (overall.get('labels') or {}).items())}. No gate, parameter, condition or verdict rule "
                 "changed after the results. If a gate looks wrong, that is a note for the next pre-registered round (R16), not an edit of this one.")
    lines.append("- **Next round.** Plan row R16 draws its hypotheses from the failure analyses above and R12's; the readings there say which ideas are not worth "
                 "another test.")
    lines += ["", "## Method notes and caveats", "",
              "- The rules were not re-implemented: Sprint 2c's runner module ran them; the reproduction table shows the same code with the cross-asset context gives "
              "the stored numbers for hold, S1 and S2.",
              "- The new conditions gate entries only (an open position is left to the base rule's own exits and stop), exactly as the regime gate and the S5 "
              "filter do; H3's legs are states (a leg exits when its condition ends, so the position moves to the other market at the next open).",
              "- A cross-asset rule sees the other market's bar that closed at the same instant, never a later one; where that bar is missing it does not enter.",
              "- H3's combined curve multiplies the legs' bar returns, which is exact for a fraction-of-equity sizing while at most one leg is in the market; the "
              "drawdown ladder acted on each leg's own equity, so a ladder on the combined account would differ slightly. Its DSR is a probabilistic Sharpe "
              "against the larger of the legs' expected maximum Sharpe; its robustness share is the smaller leg's.",
              "- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the fixed "
              "policy sizing is Sprint 2b's; none of them was adapted to the new rules.",
              "- The reproduction re-runs Sprint 2c's own passers through the same holdout code path (S2 BTC-USDT 4H [gate]), so their already-opened 12 months "
              "appear again in the ledger as comparison lines with Sprint 2c's numbers; that is a repeat of a known result, not a new look.",
              f"- {overall.get('n_judged', 0)} judged configurations are {overall.get('n_judged', 0)} more comparisons on the same six years; a pass or two among them at "
              "the Sprint 2c pass rate would be expected by chance, which is why the holdout and the forward fleet, not single passes, carry the verdict.",
              "- The holdout's falling direction was known before this study; every one of the three conditions reduces time in the market. Confirmation there is "
              "necessary, not sufficient.",
              "- Every number is a simulation on historical public data and proves nothing about the future."]
    return "\n".join(lines) + "\n"
