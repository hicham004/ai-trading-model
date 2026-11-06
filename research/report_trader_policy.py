"""Trader Policy v1 report (plan row R18, SIMULATION ONLY).

Renders ``docs/research/TRADER_POLICY_V1_REPORT.md`` from the study's results
JSON. Every plain-English sentence is computed from the numbers in the run,
so a re-run cannot print a stale claim.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from research.report_v1c import GATES, HOLDOUT_MIN_TRADES
from research.trader_policy import BRAKE_COST_FLAG, GATE_LABELS_R18, PAYOFF_MIN, TIER_GATES, TIERS, VARIANTS

TIER_ORDER = ("reference", "trader", "aggressive", "risk1.5", "trader-reference-ladder", "aggressive-reference-ladder", "trader-no-ladder", "aggressive-no-ladder")
BRAKE_LABELS = {"ladder": "Turtle ladder cut an entry", "hard_stop": "hard stop blocked", "entry_cap_market_day": "1/market/day blocked",
                "entry_after_exit": "bar-after-exit blocked", "daily_loss": "24 h loss limit blocked", "weekly_loss": "weekly limit blocked",
                "monthly_loss": "monthly limit blocked", "heat_cap": "heat cap cut"}


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


def _gates_text(failed: Sequence[str]) -> str:
    return ", ".join(GATE_LABELS_R18.get(g, g) for g in failed) if failed else "-"


def _holdout_cell(row: Mapping[str, Any]) -> str:
    h = row.get("holdout")
    if not h:
        return "untouched"
    verdict = row.get("holdout_confirmed")
    mark = "✓" if verdict is True else ("✗" if verdict is False else "")
    return f"{_pct(h.get('total_return'))} / PF {_f(h.get('profit_factor'))} / {h.get('n_trades')} tr {mark}".strip()


def _opening_verdict(o: Mapping[str, Any]) -> str:
    if o.get("role") == "configuration":
        return "confirmed" if o.get("confirmed") else "contradicted"
    if o.get("role") == "tf_control":
        return "forward control: opened by the runner's passer rule, not pre-registered; no verdict"
    return "comparison line"


def _tier_name(t: str) -> str:
    return {"reference": "Reference", "trader": "Trader", "aggressive": "Aggressive", "risk1.5": "risk1.5 (info)"}.get(t, t)


def _rows(run: Mapping[str, Any], key: str) -> List[Mapping[str, Any]]:
    return list(((run.get("analyses") or {}).get(key) or {}).get("tiers") or [])


def _row_for(rows: Sequence[Mapping[str, Any]], tier: str, brakes: bool, variant: str = "none") -> Optional[Mapping[str, Any]]:
    for r in rows:
        if r["tier"] == tier and bool(r["brakes"]) == brakes and r.get("variant", "none") == variant:
            return r
    return None


def _configs(run: Mapping[str, Any], role: str) -> List[Mapping[str, Any]]:
    return [a for a in (run.get("analyses") or {}).values() if (a.get("run") or {}).get("role") == role]


# -- the executive summary --------------------------------------------------------------------------

def executive_summary(run: Mapping[str, Any]) -> List[str]:
    meta = run.get("meta") or {}
    overall = run.get("overall") or {}
    repro = run.get("reproduction") or []
    repro_ok = sum(1 for c in repro if c.get("ok"))
    confs = _configs(run, "configuration")
    bullets: List[str] = []
    repro_text = (f"Before any tier was judged, the Reference cell of every configuration and hold control went through the same unchanged selection and "
                  f"matched the stored numbers (Sprint 2c's, the replication study's, round 1's, round 2's) in {repro_ok} of {len(repro)} cases"
                  if repro else "This run skipped the reproduction (a smoke run, not a result)")
    bullets.append(
        f"**What we did.** The five configurations the earlier studies confirmed were re-judged at three fixed risk budgets — Reference (today's 10 % "
        "volatility target), Trader (20 % target, at most 2 % of the account at risk on one stop, the Turtle ladder) and Aggressive (25 %, 2.5 %) — "
        "plus Kovner's 1.5 %-per-stop rule for information, with the section 4.3 brakes on and off and each section 4.2 position-management "
        f"variant on alone, under the Sprint 2c walk-forward and the section 4.6 gates written down before the run. {repro_text}. The rule each "
        "walk-forward window selects never sees the budget, so every configuration kept its ATR multiple and exit bracket; only the size of the same "
        f"trades changes. {len(run.get('results') or [])} cells ran on {meta.get('v1c_meta', {}).get('data_span_short', 'the stored history')} after fees and slippage.")
    # Per configuration: the tier line.
    for a in confs:
        rows = a["tiers"]
        name = a["run"]["name"] if "name" in a["run"] else f"{a['run']['candidate']} {a['run']['instrument']} {a['run']['timeframe']} [{a['run']['mode']}]"
        ref, tr, ag = _row_for(rows, "reference", False), _row_for(rows, "trader", True), _row_for(rows, "aggressive", True)
        if ref is None or tr is None:
            continue
        text = (f"**{name}.** Reference: {_pct(ref['cagr'])} a year, worst drawdown {_pct(ref['max_drawdown'], False)}, Calmar {_f(ref['calmar'])}, "
                f"realized volatility {_pct(ref['ann_vol'], False)}. Trader tier (brakes on): {_pct(tr['cagr'])} a year, drawdown {_pct(tr['max_drawdown'], False)}, "
                f"Calmar {_f(tr['calmar'])}, volatility {_pct(tr['ann_vol'], False)}, {_f(tr['exposure_ratio'])} x the Reference exposure, a stop costs "
                f"{_pct(tr['risk_pct_mean'], False)} of the account on average (cap binding on {_pct(tr['cap_binding_share'], False, 0)} of entries), "
                f"average win {_f(tr['payoff_ratio'], '{:.1f}')} x average loss, expectancy {_f(tr['expectancy_r'])} R, "
                f"{'passes' if tr['passed'] else 'fails (' + _gates_text(tr['failed']) + ')'} the section 4.6 gates; "
                f"holdout {_holdout_cell(tr)}; chance of touching -30 % {_pct(tr['prob_dd_30'], False)}.")
        if ag is not None:
            text += (f" Aggressive: {_pct(ag['cagr'])} a year, drawdown {_pct(ag['max_drawdown'], False)}, volatility {_pct(ag['ann_vol'], False)}, "
                     f"{'passes' if ag['passed'] else 'fails (' + _gates_text(ag['failed']) + ')'}, -30 % chance {_pct(ag['prob_dd_30'], False)}.")
        bullets.append(text)
    # Brakes.
    counts = overall.get("brake_counts") or {}
    tr_counts = counts.get("trader") or {}
    zero = [BRAKE_LABELS.get(k, k) for k in ("daily_loss", "weekly_loss", "monthly_loss", "heat_cap") if int(tr_counts.get(k, 0)) == 0]
    nonzero = {k: v for k, v in tr_counts.items() if int(v) > 0}
    bullets.append(
        "**Brakes.** At the Trader tier, over the five configurations' walk-forward years, the brakes acted as follows: "
        + (", ".join(f"{BRAKE_LABELS.get(k, k)} {v} times" for k, v in sorted(nonzero.items(), key=lambda kv: -int(kv[1]))) or "never")
        + (f"; never: {_names(zero)}" if zero else "") + ". "
        + (f"Their cost exceeded {BRAKE_COST_FLAG:g} Calmar (flagged for you) on: {_names(overall.get('brake_cost_flagged') or [])}. "
           if overall.get("brake_cost_flagged") else f"No sleeve lost more than {BRAKE_COST_FLAG:g} Calmar to the brakes. ")
        + (f"The Turtle ladder cost more than {BRAKE_COST_FLAG:g} Calmar beside no ladder on: {_names(overall.get('ladder_cost_flagged') or [])}."
           if overall.get("ladder_cost_flagged") else f"The Turtle ladder cost no sleeve more than {BRAKE_COST_FLAG:g} Calmar beside the same sleeve without a ladder."))
    # Variants.
    counting = overall.get("variants_counting") or {}
    if counting:
        bullets.append("**Variants (size-neutral rule).** The ones that counted — Sharpe at least the base's and Calmar at least the base's after matching the "
                       "base's volatility — per sleeve: " + "; ".join(f"{VARIANTS[k].name if k in VARIANTS else k}: {_names(v)}" for k, v in counting.items())
                       + ". No variant joins the fleet in this row; a variant that counts is a candidate for a pre-registered forward test.")
    else:
        bullets.append("**Variants.** None of the position-management variants counted under the size-neutral rule on any sleeve: the base rules keep their "
                       "trend's own exits and a single unit.")
    pooled = run.get("pooled_conviction") or {}
    if pooled:
        if pooled.get("enough_trades"):
            bullets.append(f"**Conviction split.** Pooled over {_names(pooled.get('sleeves') or [])}: the 1.25 x trades ({pooled.get('n_high')}) earned "
                           f"{_f(pooled.get('expectancy_r_high'))} R each against {_f(pooled.get('expectancy_r_low'))} R for the 0.75 x trades ({pooled.get('n_low')}): "
                           f"the split {'passes' if pooled.get('high_beats_low') else 'fails'} its pre-registered test.")
        else:
            bullets.append(f"**Conviction split.** Too few high-conviction trades for the pre-registered test even pooled ({pooled.get('n_high')} at 1.25 x, "
                           f"{pooled.get('n_low')} at 0.75 x; 30 each needed): inconclusive, and it does not size anything.")
    # Holdout and fleet.
    fleet = overall.get("fleet_candidates") or []
    tf_openings = sorted({f"{o['configuration']} @ {o['cell']}" for o in (run.get("holdout_openings") or []) if o.get("role") == "tf_control"})
    if meta.get("evaluate_holdout"):
        if tf_openings:
            bullets.append(f"**A look the pre-registration did not list.** The runner opens the holdout for any cell that passes the gates, and the TF forward "
                           f"control passed at {_names(tf_openings)}, so its 12 months were opened there (the pre-registration listed only the configurations "
                           "and the hold controls). Recorded in the ledger; TF is never judged and joins the fleet as a control regardless; the job planner "
                           "now excludes the TF controls from the holdout.")
        bullets.append(f"**Holdout and fleet.** {len(fleet)} of {len(confs)} configurations pass every section 4.6 gate at the Trader tier with the brakes on and "
                       f"are confirmed by their untouched 12 months at that tier ({_names(fleet)}). A tier changes only the size of the same trades, so these "
                       "holdout looks are near-second looks at months the Reference tier already opened (the ledger names each earlier look); they confirm "
                       "the plumbing of the tier, not the edge. The rows for the paper fleet (the base rule at the Trader tier, all variants off, plus the "
                       "'always long above the 200-day average' forward control) are RECORDED in the results for plan row R18b, which extends the fleet's "
                       "loader before applying them; the shortlist file and every running account are untouched. Nothing is approved for demo or live trading.")
    else:
        bullets.append("**Holdout and fleet.** The untouched 12 months were not opened in this run (not the full pre-registered study); nothing joins the fleet.")
    return bullets


# -- tables -------------------------------------------------------------------------------------------

def _tier_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Cell | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Win | Avg win/avg loss | Expectancy (R) | Realized vol | Avg allocation | x Reference | Risk/trade (mean, max) | Cap binds | All-in | Gaps | Re-entries <= 2 bars | P(DD >= 30 %) | Worst year | Rolling 12 m + | Gates missed | Verdict | Holdout (12 m) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in rows:
        risk = f"{_pct(r.get('risk_pct_mean'), False)}, {_pct(r.get('risk_pct_max'), False)}"
        lines.append(f"| {r['cell']['label']} | {_pct(r.get('cagr'))} | {_f(r.get('sharpe'))} | {_pct(r.get('max_drawdown'), False)} | {_f(r.get('calmar'))} | {_f(r.get('profit_factor'))} | "
                     f"{_int(r.get('n_trades'))} | {_pct(r.get('win_rate'), False, 0)} | {_f(r.get('payoff_ratio'), '{:.1f}')} | {_f(r.get('expectancy_r'))} | {_pct(r.get('ann_vol'), False)} | "
                     f"{_pct(r.get('avg_allocation'), False)} | {_f(r.get('exposure_ratio'))} | {risk} | {_pct(r.get('cap_binding_share'), False, 0)} | "
                     f"{_pct(r.get('full_allocation_share'), False, 0)} | {_int(r.get('gap_trades'))} | {_int(r.get('reentries'))}/{_int(r.get('stop_outs'))} | "
                     f"{_pct(r.get('prob_dd_30'), False)} | {_pct(r.get('worst_calendar_year_return'))} | {_pct(r.get('rolling_positive_share'), False)} | "
                     f"{_gates_text(r.get('failed') or [])} | {'**PASS**' if r.get('passed') else 'fail'} | {_holdout_cell(r)} |")
    return lines


def _brake_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Tier | Entry opportunities | " + " | ".join(BRAKE_LABELS[k] for k in BRAKE_LABELS) + " | Hard-stop trips | 24 h / week / month trips | Trades on / off | Calmar off → on | Cost (Calmar) | Flagged |",
             "|---|---:|" + "---:|" * len(BRAKE_LABELS) + "---:|---|---|---|---:|---|"]
    for b in entries:
        c = b.get("counts") or {}
        t = b.get("trips") or {}
        cost = b.get("cost") or {}
        lines.append(f"| {_tier_name(b['tier'])} | {_int(b.get('opportunities'))} | " + " | ".join(_int(c.get(k, 0)) for k in BRAKE_LABELS)
                     + f" | {_int(t.get('hard_stop', 0))} | {_int(t.get('daily_loss', 0))} / {_int(t.get('weekly_loss', 0))} / {_int(t.get('monthly_loss', 0))} | "
                     f"{_int(b.get('n_trades_on'))} / {_int(b.get('n_trades_off'))} | {_f(cost.get('calmar_without'))} → {_f(cost.get('calmar_with'))} | "
                     f"{_f(cost.get('cost_calmar'), '{:+.2f}')} | {_yes(cost.get('flagged'))} |")
    return lines


def _ladder_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Tier | No ladder: CAGR / max DD / Calmar | Turtle ladder: CAGR / max DD / Calmar | Ladder cost (Calmar) | Flagged | Bars at x0.8 / x0.64 | Reference ladder instead: CAGR / max DD / Calmar / passes |",
             "|---|---|---|---:|---|---|---|"]
    for b in entries:
        lc = b.get("ladder_cost")
        if not lc:
            continue
        rl = b.get("reference_ladder") or {}
        bars = b.get("ladder_bars") or {}
        lines.append(f"| {_tier_name(b['tier'])} | {_pct(lc.get('cagr_without'))} / {_pct(lc.get('max_dd_without'), False)} / {_f(lc.get('calmar_without'))} | "
                     f"{_pct(lc.get('cagr_with'))} / {_pct(lc.get('max_dd_with'), False)} / {_f(lc.get('calmar_with'))} | {_f(lc.get('cost_calmar'), '{:+.2f}')} | "
                     f"{_yes(lc.get('flagged'))} | {_int(bars.get('x0.8', 0))} / {_int(bars.get('x0.64', 0))} | "
                     f"{_pct(rl.get('cagr'))} / {_pct(rl.get('max_drawdown'), False)} / {_f(rl.get('calmar'))} / {_yes(rl.get('passed'))} |")
    return lines


def _variant_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Variant | Applies | Sharpe base → variant | Calmar base → variant (vol-matched) | CAGR | Max DD | PF | Trades | Avg win/avg loss | Expectancy (R) | Adds (worst case R mean / max) | Scale-outs | Gates | Counts |",
             "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|"]
    for v in entries:
        if not v.get("applies"):
            lines.append(f"| {v['variant']} | no: {v.get('why_not')} | - | - | - | - | - | - | - | - | - | - | - | n/a |")
            continue
        rule = v.get("rule") or {}
        m = v.get("variant_metrics") or {}
        t = v.get("trades") or {}
        adds = f"{_int(t.get('adds'))} ({_f(t.get('add_worst_case_r_mean'))} / {_f(t.get('add_worst_case_r_max'))})" if t.get("adds") else "-"
        counts = v.get("counts")
        extra = ""
        if v["variant"] == "conviction":
            extra = f" ({v.get('conviction_note')})"
        lines.append(f"| {v['variant']} | yes | {_f(rule.get('base_sharpe'))} → {_f(rule.get('variant_sharpe'))} | {_f(rule.get('base_calmar'))} → "
                     f"{_f(rule.get('variant_calmar'))} ({_f(rule.get('variant_calmar_vol_matched'))}) | {_pct(m.get('cagr'))} | {_pct(m.get('max_drawdown'), False)} | "
                     f"{_f(m.get('profit_factor'))} | {_int(m.get('n_trades'))} | {_f(v.get('payoff_ratio'), '{:.1f}')} | {_f(t.get('expectancy_r'))} | {adds} | "
                     f"{_int(t.get('scale_outs'))} | {'pass' if v.get('passed') else _gates_text(v.get('failed') or [])} | "
                     f"{('**yes**' if counts else 'no') + extra} |")
    return lines


def _cost_table(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| Tier | 0.30 % a round trip (gate cost): return / CAGR / Calmar / max DD | 0.20 % (measured BTC/ETH): return / CAGR / Calmar / max DD | 0.50 % (altcoins): return / CAGR / Calmar / max DD |",
             "|---|---|---|---|"]
    for e in entries:
        g = e.get("gate_cost") or {}
        m = e.get("measured_btc_eth") or {}
        a = e.get("altcoin") or {}
        cell = lambda d: f"{_pct(d.get('total_return'))} / {_pct(d.get('cagr'))} / {_f(d.get('calmar'))} / {_pct(d.get('max_drawdown'), False)}"  # noqa: E731
        lines.append(f"| {_tier_name(e['tier'])} | {cell(g)} | {cell(m)} | {cell(a)} |")
    return lines


def _yearly_table(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    years = sorted({y for r in rows for y in (r.get("yearly") or {})})
    if not years:
        return []
    lines = ["| Cell | " + " | ".join(years) + " |", "|---|" + "---:|" * len(years)]
    for r in rows:
        if r.get("variant", "none") != "none":
            continue
        y = r.get("yearly") or {}
        lines.append(f"| {r['cell']['label']} | " + " | ".join(_pct(y.get(k)) for k in years) + " |")
    return lines


# -- the report -------------------------------------------------------------------------------------------

def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    v1c_meta = meta.get("v1c_meta") or {}
    lines: List[str] = []
    lines += [
        "# Trader Policy v1 — the confirmed configurations at three fixed risk budgets, with brakes and variants (walk-forward, SIMULATION ONLY)",
        "",
        f"Generated {meta.get('generated_at', '-')} by `scripts/run_trader_policy_v1.py` (plan row R18; {meta.get('elapsed_minutes', '-')} min). Rules: Sprint 2c's, run by "
        f"`scripts/run_research_v1c.py`'s own `run_series` with its plan-row-R18 arguments; everything the tier does not define is Sprint 2c's (regime gate "
        f"`{(v1c_meta.get('regime') or {}).get('label', '-')}` where the configuration has one, S0 filter {v1c_meta.get('no_trade_label', '-')}, walk-forward train "
        f"{v1c_meta.get('train_days', '-')}d → purge {v1c_meta.get('purge_days', '-')}d → test {v1c_meta.get('test_days', '-')}d, fee {_pct(v1c_meta.get('fee_rate'), signed=False, digits=2)} + "
        f"slippage {_pct(v1c_meta.get('slippage_rate'), signed=False, digits=3)} per side, brackets {v1c_meta.get('bracket_variants', '-')}). Data: PUBLIC OKX spot candles of "
        f"BTC-USDT, ETH-USDT, SOL-USDT and DOGE-USDT (1H and 4H stored, 6H resampled from 1H) frozen at Sprint 2c's data end (bar close ≤ {meta.get('data_end', '-')}). "
        f"Holdout: the last 12 months ({v1c_meta.get('holdout_span', '-')}), opened only for the pre-registered cells.",
        "",
        "**Nothing here authorizes paper, demo or live trading.** A tier that passes is a hypothesis for the forward paper fleet, not a budget to deploy. "
        "Every number is a simulation on historical public data. The demo shadow run, its caps and the 0.60 confidence floor are untouched.",
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
        if isinstance(v, dict):
            lines.append(f"- **{k}**:")
            for kk, vv in v.items():
                lines.append(f"  - {kk}: {vv}")
        elif isinstance(v, list):
            lines.append(f"- **{k}**: " + "; ".join(str(x) for x in v))
        else:
            lines.append(f"- **{k}**: {v}")
    protocol = meta.get("protocol_check") or {}
    lines += ["", f"Protocol check of the Reference cell against the stored Sprint 2c run: {'every parameter the same' if protocol.get('ok') else 'MISMATCHES: ' + str(protocol.get('mismatches'))} "
              f"(checked: {', '.join(protocol.get('checked') or [])}). Every other cell's check is stored with its result: a tier is a recorded `policy_sizing` "
              "mismatch (and the TF control's fixed-rule protocol a recorded `brackets` / `min_trades` mismatch); the study stops on any mismatch the cell does not explain.",
              "", "Gates: Sprint 2c's (" + "; ".join(f"{k} {v}" for k, v in (meta.get("gates") or GATES).items()) + "), with max drawdown ≤ "
              f"{TIER_GATES['higher']['max_drawdown_max'] * 100:.0f} % and worst calendar year ≥ {TIER_GATES['higher']['worst_calendar_year_min'] * 100:.0f} % at the higher tiers "
              f"(≤ {TIER_GATES['reference']['max_drawdown_max'] * 100:.0f} % and ≥ {TIER_GATES['reference']['worst_calendar_year_min'] * 100:.0f} % at the Reference tier), "
              f"plus average win / average loss ≥ {PAYOFF_MIN:g}. Expectancy in R is reported, never gated."]
    if meta.get("second_look_warning"):
        lines += ["", f"**Warning — second look.** An earlier run of this study already opened the holdout of: {_names(meta['second_look_warning'])}. Both looks are in the ledger below."]

    repro = run.get("reproduction") or []
    lines += ["", "## Reproduction of the stored studies", ""]
    if repro:
        lines += ["The Reference cell (brakes off) of every configuration and hold control had to give the stored walk-forward numbers (6 decimals), the same trade "
                  "counts, the same most-selected rules and the same gate verdicts, otherwise the study stops.", "",
                  "| Configuration | Stored by | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Same verdict | Largest difference | Agrees |",
                  "|---|---|---|---|---|---:|---|---|---:|---|"]
        for c in repro:
            got, exp = c.get("reproduced") or {}, c.get("stored") or {}
            lines.append(f"| {c['configuration']} | {c.get('study')} | {_f(got.get('total_return'), '{:.6f}')} / {_f(exp.get('total_return'), '{:.6f}')} | "
                         f"{_f(got.get('sharpe'), '{:.6f}')} / {_f(exp.get('sharpe'), '{:.6f}')} | {_f(got.get('max_drawdown'), '{:.6f}')} / {_f(exp.get('max_drawdown'), '{:.6f}')} | "
                         f"{c.get('n_trades')} / {c.get('n_trades_stored')} | {_yes(c.get('selected_matches'))} | {_yes(c.get('verdict_matches'))} | "
                         f"{_num(c.get('max_abs_difference'), 0.0):.1e} | {_yes(c.get('ok'))} |")
        lines += ["", f"{sum(1 for c in repro if c.get('ok'))} of {len(repro)} reproduced."]
    else:
        lines.append("Not run in this invocation (a smoke run). Nothing here is a result.")

    # Per configuration.
    for a in _configs(run, "configuration"):
        name = a["run"].get("name") or f"{a['run']['candidate']} {a['run']['instrument']} {a['run']['timeframe']} [{a['run']['mode']}]"
        rows = a["tiers"]
        verdict = next((v for v in (run.get("verdicts") or []) if v["run"] == a["run"]["key"]), {})
        lines += ["", f"## {name} — {'**fleet candidate at the Trader tier**' if verdict.get('fleet_candidate') else verdict.get('fleet_reason', '')}", ""]
        lines += ["Every cell is the same rule and the same walk-forward selection; only the size of the trades changes. Risk/trade is the money at the initial "
                  "stop over the equity at entry; 'cap binds' is the share of entries at which the per-trade cap, not the volatility target, set the size; "
                  "'all-in' the share of entries that put 100 % of the account in; gaps are stop-loss exits filled below the stop; re-entries are the rule's own "
                  "re-entries within two bars of a stop-out (counted, not changed); P(DD ≥ 30 %) is the bootstrap share of trade-order paths that touch the hard stop.", ""]
        core = [r for r in rows if r.get("variant", "none") == "none"]
        lines += _tier_table(core)
        yearly = _yearly_table(core)
        if yearly:
            lines += ["", "Calendar years (out of sample, stitched):", ""] + yearly
        lines += ["", "### Brakes (entries only) — trigger counts and cost", ""]
        lines += _brake_table(a.get("brakes") or [])
        lines += ["", "The Turtle ladder's cost beside the same tier with no ladder, and the higher tier under the Reference ladder (which reduces open positions) instead:", ""]
        lines += _ladder_table(a.get("brakes") or [])
        lines += ["", "### Variants (each alone, Trader tier, brakes on) — the size-neutral rule", ""]
        lines += _variant_table(a.get("variants") or [])
        lines += ["", "### Costs — the selected rule replayed at other fee + slippage pairs (same windows, same sizing, brakes on)", ""]
        lines += _cost_table(a.get("costs") or [])

    # Controls.
    lines += ["", "## Controls — hold + policy sizing at each tier, and the slow-trend forward control", ""]
    lines += ["The hold controls have no stop, so the per-trade cap cannot act on them: at the higher tiers they are the volatility target alone with the Turtle "
              "ladder on entries. TF (long above the 200-day average, policy sizing) ran as a fixed rule (no exit bracket, no 20-train-trade qualification; a "
              "recorded protocol deviation): it is the forward control of plan row R18b, never judged.", ""]
    lines += ["| Control | Cell | CAGR | Sharpe | Max DD | Calmar | Trades | Realized vol | Avg allocation | Worst year | Holdout (12 m) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for a in _configs(run, "control") + _configs(run, "tf_control"):
        name = a["run"].get("name") or f"{a['run']['candidate']} {a['run']['instrument']} {a['run']['timeframe']}"
        for r in a["tiers"]:
            lines.append(f"| {name} | {r['cell']['label']} | {_pct(r.get('cagr'))} | {_f(r.get('sharpe'))} | {_pct(r.get('max_drawdown'), False)} | {_f(r.get('calmar'))} | "
                         f"{_int(r.get('n_trades'))} | {_pct(r.get('ann_vol'), False)} | {_pct(r.get('avg_allocation'), False)} | {_pct(r.get('worst_calendar_year_return'))} | {_holdout_cell(r)} |")

    # Holdout.
    openings = run.get("holdout_openings") or []
    lines += ["", "## The untouched 12 months", ""]
    if openings:
        lines += [f"Opened only for the pre-registered cells. A configuration's 12 months count as confirmed with a positive return, PF > 1 and at least {HOLDOUT_MIN_TRADES} trades. "
                  "A tier changes only the size of the same trades, so an opening at a tier is a near-second look at months the Reference tier already opened; the earlier look is named beside it.", "",
                  "| Configuration | Cell | Role | Return | Max DD | PF | Trades | Verdict | Earlier look (study: return / PF / trades, confirmed) |", "|---|---|---|---:|---:|---:|---:|---|---|"]
        looks = {(e["configuration"], e["cell"]): e for e in (run.get("earlier_looks") or [])}
        for o in openings:
            e = looks.get((o["configuration"], o["cell"]))
            earlier = (f"{e.get('earlier_study')}: {_pct(e.get('earlier_total_return'))} / {_f(e.get('earlier_profit_factor'))} / {e.get('earlier_n_trades')}, "
                       f"{_yes(e.get('earlier_confirmed'))}" if e and e.get("earlier_opened") else ("not opened before" if e else "-"))
            verdict = _opening_verdict(o)
            lines.append(f"| {o['configuration']} | {o['cell']} | {o.get('role')} | {_pct(o.get('total_return'))} | {_pct(o.get('max_drawdown'), False)} | {_f(o.get('profit_factor'))} | "
                         f"{o.get('n_trades')} | {verdict} | {earlier} |")
    else:
        lines.append("Not opened in this run.")
    ledger = meta.get("holdout_ledger") or []
    lines += ["", "### Every opening of the holdout (ledger)", ""]
    if ledger:
        lines += ["| Run (generated) | Configuration | Cell | Return | PF | Trades | Verdict |", "|---|---|---|---:|---:|---:|---|"]
        for entry in ledger:
            for o in entry.get("openings", []):
                verdict = _opening_verdict(o)
                lines.append(f"| {entry.get('generated_at')} | {o['configuration']} | {o.get('cell')} | {_pct(o.get('total_return'))} | {_f(o.get('profit_factor'))} | {o.get('n_trades')} | {verdict} |")
    else:
        lines.append("The ledger is empty: this run opened no holdout.")

    # Fleet.
    additions = run.get("shortlist_additions") or []
    lines += ["", "## Paper-fleet rows (recorded for plan row R18b)", ""]
    if additions:
        lines += ["| Candidate | Market, bars | Regime | Role | Tier | Walk-forward CAGR / max DD / Calmar | Holdout |", "|---|---|---|---|---|---|---|"]
        for a in additions:
            src = a.get("source") or {}
            h = a.get("holdout") or {}
            lines.append(f"| {a['candidate']} | {a['instrument']} {a['timeframe']} | {a.get('regime')} | {src.get('role')} | {src.get('tier')} | "
                         f"{_pct(a.get('cagr'))} / {_pct(a.get('max_drawdown'), False)} / {_f(a.get('calmar'))} | "
                         f"{_pct(h.get('total_return')) + ' / PF ' + _f(h.get('profit_factor')) + ' / ' + str(h.get('n_trades')) + ' tr' if h else 'untouched'} |")
        lines += ["", run.get("shortlist_note") or ""]
    else:
        lines.append("None recorded (no configuration passed at the Trader tier with a confirming holdout, or this was not the full study).")

    # Owner decisions.
    overall = run.get("overall") or {}
    lines += ["", "## Owner decisions (nothing below is decided by this report)", "",
              f"- **The budget.** The Trader tier is the default the plan proposed for the paper fleet; {len(overall.get('fleet_candidates') or [])} of "
              f"{overall.get('n_configurations', 0)} configurations qualify at it. Decide at G7, after 60+ fleet days, with these backtest numbers beside the forward ones.",
              f"- **Brakes flagged for cost.** {_names(overall.get('brake_cost_flagged') or []) if overall.get('brake_cost_flagged') else 'None'}; "
              f"ladder flagged: {_names(overall.get('ladder_cost_flagged') or []) if overall.get('ladder_cost_flagged') else 'none'}. A flagged brake is a question, not a removal.",
              "- **Variants that counted** are candidates for a pre-registered forward test, never a change to a running account.",
              "- **Plan row R18b** adds the recorded rows to the paper fleet (loader extension first), the fleet engine's transcription of the tier and the brakes with its parity test, "
              "and the weekly report's tier-beside-tier view; nothing here changes demo or live."]

    lines += ["", "## Method notes and caveats", "",
              "- The walk-forward's test windows restart flat from the same capital every 180 days (Sprint 2c's protocol), so the ladder's equity peak, the hard stop and the "
              "loss windows restart with them; the stitched curve's worst drawdown can exceed any window's, and a −30 % drawdown inside one window is rare by construction. "
              "The brakes' counts are per-window counts summed.",
              "- The per-trade cap reads the stop the trade actually carries (the selected ATR multiple; the wider stop under that variant); without a stop (hold, TF) it cannot act. "
              "It is set at the decision close: the next open's gap and the entry fee move the realized risk per trade a little above or below it (the table shows the realized mean and maximum).",
              "- The add variant: one add of half the initial quantity at +1 R, with its own stop from the add bar; the first unit keeps its stop; if the whole position's stop is "
              "hit both units fill at that price (conservative); the reduce-only overlay treats a held add as a deliberate increase, not an over-allocation. Worst case at the "
              "stops is reported in first-unit R per add.",
              "- The scale-out variant sells half at +2 R through the reduce-only path; the trade stays one trade with its P&L pooled (a partial exit otherwise counts as a win by construction).",
              "- Costs: the gate cost is the engine's 0.30 % a round trip; the 0.20 % and 0.50 % lines are fixed replays of the selected rule (same windows, same sizing), not re-selections.",
              "- A tier changes the size of the same trades, so every tier's holdout is a near-second look at months already opened at the Reference tier; the ledger names each earlier look. "
              "The holdout's falling direction was known for every market before this study.",
              "- The Monte Carlo resamples the order of the realized (sized) trade returns with replacement, 2,000 paths; it ignores the brakes' path dependence and the window restarts.",
              "- The study's first run (the ledger's first entry) had a unit bug in the brakes' bar calendar: stored 4H candles carry millisecond timestamps, which were read "
              "as nanoseconds, so every 4H bar fell on one calendar day and the one-entry-per-day cap blocked almost every entry on the 4H series (the 6H series, resampled "
              "from 1H with nanosecond timestamps, were right). Its own brake counts exposed it; the calendar was fixed and the whole study re-run with the pre-registration "
              "unchanged. Both runs' holdout openings stay in the append-only ledger; the second-look warning above names the configurations opened twice, and no gate, "
              "threshold or rule changed between the runs.",
              "- Nothing here changes the demo shadow run, its caps, the 0.60 confidence floor or any file under app/ or config/."]
    return "\n".join(lines) + "\n"
