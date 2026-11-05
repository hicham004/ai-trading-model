"""Breadth report (plan row R20, SIMULATION ONLY).

Renders ``docs/research/BREADTH_V1_REPORT.md`` from the study's results JSON (or, before
the first run, from the pre-registration alone). Every plain-English sentence - the
summary, the book's verdict, the brakes' reading, the diversification reading, the
rotation's verdict - is computed from the numbers in the run, so a re-run on other
data cannot print a stale claim.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from research.report_v1c import HOLDOUT_MIN_TRADES
from research.trader_policy import GATE_LABELS_R18


# -- formatting ------------------------------------------------------------------------------------------

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
        return "inf"
    return fmt.format(x)


def _int(v: Any) -> str:
    x = _num(v)
    return "-" if math.isnan(x) else f"{int(round(x))}"


def _yes(flag: Any) -> str:
    return "yes" if flag else "no"


def _names(items: Iterable[str]) -> str:
    items = list(items)
    return ", ".join(items) if items else "none"


def _times(n: Any) -> str:
    k = int(_num(n, 0.0)) if _ok(n) else 0
    return "never" if k == 0 else ("once" if k == 1 else f"{k} times")


def _k(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _gates_text(failed: Sequence[str]) -> str:
    return ", ".join(GATE_LABELS_R18.get(g, g) for g in failed) if failed else "none - PASS"


def _holdout_cell(h: Optional[Mapping[str, Any]], confirmed: Optional[bool]) -> str:
    if not h:
        return "untouched"
    mark = "yes" if confirmed is True else ("no" if confirmed is False else "")
    return f"{_pct(h.get('total_return'))} / PF {_f(h.get('profit_factor'))} / {h.get('n_trades')} tr {mark}".strip()


def _results(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return list(run.get("results") or [])


# -- the executive summary ------------------------------------------------------------------------------

def executive_summary(run: Mapping[str, Any]) -> List[str]:
    book = run.get("book") or {}
    rot = run.get("rotation") or {}
    overall = run.get("overall") or {}
    div = run.get("diversification") or {}
    out: List[str] = []
    if not run.get("results"):
        out.append("**Pre-registration only.** The questions, the book construction, the brakes, the costs, the gates, the candidate rule and the rotation "
                   "rule below were fixed before the first run; no result exists yet.")
        return out
    rep = run.get("reproduction") or []
    if rep:
        n_ok = sum(1 for c in rep if c.get("ok"))
        out.append(f"**Reproduction.** {n_ok} of {len(rep)} stored results (Sprint 2c, the replication study, rounds 1 and 2 at the Reference cell; the Trader "
                   f"Policy study and round 3 at the Trader cell) were reproduced to 6 decimals before anything was judged.")
    n_in = overall.get("n_sleeves_in_book")
    n_own = overall.get("sleeves_passing_own")
    if book:
        j = book.get("judged") or {}
        o = j.get("oos") or {}
        acc = j.get("acceptance_r18") or {}
        v = book.get("verdict") or {}
        hold = book.get("hold_btc_trader") or {}
        clock = book.get("clock") or {}
        out.append(f"**The breadth book** - the S1 family ({n_in} sleeves on {len(book.get('markets') or [])} markets, 6H bars) as one account at the Trader tier with "
                   f"the book-level brakes and the correlation cap, {clock.get('first_bar', '')[:10]} to {clock.get('last_bar', '')[:10]} - made {_pct(o.get('cagr'))} a year "
                   f"with a {_pct(o.get('max_drawdown'), False)} worst fall (Sharpe {_f(o.get('sharpe'))}, Calmar {_f(o.get('calmar'))}, profit factor {_f(o.get('profit_factor'))}, "
                   f"{_int(o.get('n_trades'))} trades, {_pct(o.get('ann_vol'), False)} realized volatility, on average {_pct(o.get('avg_allocation'), False)} of the money at work). "
                   + ("It **passes** every section 4.6 gate at the Trader tier." if acc.get("passed") else f"It **fails** the section 4.6 gates: {_gates_text(acc.get('failed') or [])}."))
        out.append(f"**Beside its parts.** {n_own} of {n_in} sleeves pass on their own at the Trader cell; their median Calmar is {_f(div.get('sleeves_median_calmar'))} "
                   f"and the best sleeve's {_f((div.get('best_sleeve') or {}).get('calmar'))} ({(div.get('best_sleeve') or {}).get('configuration', '-')}); holding BTC with the "
                   f"Trader policy sizing made {_pct(hold.get('cagr'))} a year at a {_pct(hold.get('max_drawdown'), False)} fall (Calmar {_f(hold.get('calmar'))}). The "
                   f"diversification gain in Calmar is {_f(div.get('gain_vs_sleeves_median'), '{:+.2f}')} against the median sleeve, {_f(div.get('gain_vs_best_sleeve'), '{:+.2f}')} "
                   f"against the best sleeve and {_f(div.get('gain_vs_hold_btc'), '{:+.2f}')} against holding BTC"
                   + (f"; {_f(div.get('gain_vs_equal_weight_nine'), '{:+.2f}')} against the equal-weight hold of the nine at the same volatility target." if div.get("equal_weight_nine") else "."))
        halted = (j.get("brakes") or {}).get("halted_from")
        if halted:
            out.append(f"**The hard stop ended the book.** The book's equity fell 30 % below its peak on {halted}; as pre-registered for a simulated account, no new entry was "
                       f"funded from then on, so the book sat flat for {_pct((j.get('brakes') or {}).get('halted_days_share'), False)} of its days and the numbers above are "
                       "those of an account that stopped trading there. " + _post_hoc_sentence(book))
        out.append("**Candidate?** " + ("**Yes** - " if v.get("candidate") else "**No** - ") + f"{v.get('reason', '-')}. "
                   + ("The paper fleet's forward record is the judge; the row is recorded for the fleet (a book account type is the next row's work)." if v.get("candidate")
                      else "Nothing joins the fleet from the book."))
        out.append(_brakes_sentence(book))
    if rot:
        lines = rot.get("lines") or {}
        r, b = lines.get("rotation") or {}, lines.get("btc_vt20") or {}
        checks = rot.get("checks") or {}
        span = rot.get("span") or {}
        out.append(f"**The rotation test** (top 3 of the nine by 3-week return, weekly, BTC 200-day filter, 20 % volatility target; {span.get('start')} to {span.get('end')}) "
                   f"made {_pct(r.get('cagr'))} a year with a {_pct(r.get('max_drawdown'), False)} worst fall (Calmar {_f(r.get('calmar'))}, Sharpe {_f(r.get('sharpe'))}, "
                   f"{_f(r.get('turnover_per_year'), '{:.1f}')} x equity a year of turnover, {_pct(r.get('fees_pct_per_year'), False)} a year in costs); holding BTC with the same "
                   f"sizing made {_pct(b.get('cagr'))} at a {_pct(b.get('max_drawdown'), False)} fall (Calmar {_f(b.get('calmar'))}). "
                   + ("It **beats BTC** by the pre-registered rule" if rot.get("passed") else "It **does not beat BTC** by the pre-registered rule")
                   + f" (Calmar ahead by more than 0.1: {_yes(checks.get('calmar_beats_btc_by_margin'))}; CAGR ahead: {_yes(checks.get('cagr_above_btc'))}; drawdown within 25 %: "
                   f"{_yes(checks.get('max_drawdown_within_tier'))}), " + ("as expected before the run. The question is closed with our own numbers." if not rot.get("passed")
                                                                             else "against the pre-registered expectation; its holdout decides whether it is recorded for the fleet."))
    conf, contra = overall.get("sleeves_holdout_confirmed") or [], overall.get("sleeves_holdout_contradicted") or []
    if n_own:
        in_fleet = _fleet_trader_rows()
        names_own = list(overall.get("sleeves_passing_own_names") or [])
        already = [n for n in names_own if _config_key(n) in in_fleet]
        new_conf = [n for n in conf if _config_key(n) not in in_fleet]
        out.append(f"**The sleeves on their own.** The {n_own} that pass at the Trader cell are {_names(names_own)}; their untouched 12 months (a near-second look for most "
                   f"of them, see the ledger) confirmed {len(conf)} ({_names(c.split(' 6H')[0] for c in conf)}) and contradicted {len(contra)} ({_names(c.split(' 6H')[0] for c in contra)}). "
                   f"{len(already)} of the {n_own} already run in the paper fleet at the Trader tier ({_names(c.split(' 6H')[0] for c in already)})"
                   + (f"; {_names(c.split(' 6H')[0] for c in new_conf)} pass and are confirmed but are NOT in the fleet, and this study's pre-registration lists no fleet ticket for a "
                      "single sleeve (an owner decision, below)." if new_conf else "."))
    rec = run.get("shortlist_recorded_only") or []
    out.append(f"**Fleet.** {len(rec)} row(s) recorded for the paper fleet ({_names(r.get('kind') for r in rec)}); none applied, because the fleet has no account type for a "
               "multi-market book or a weekly rotation. Nothing here is approved for demo or live.")
    return out


def _post_hoc_sentence(book: Mapping[str, Any]) -> str:
    ph = (book.get("post_hoc") or {}).get("no_hard_stop")
    if not ph:
        return ""
    o = ph.get("oos") or {}
    acc = ph.get("acceptance_r18") or {}
    return (f"Post hoc (NOT pre-registered, added after the first run, never a candidate): the same book with the hard stop off made {_pct(o.get('cagr'))} a year with a "
            f"{_pct(o.get('max_drawdown'), False)} worst fall (Sharpe {_f(o.get('sharpe'))}, Calmar {_f(o.get('calmar'))}, profit factor {_f(o.get('profit_factor'))}, "
            f"{_int(o.get('n_trades'))} trades); it would "
            + ("pass" if acc.get("passed") else f"still fail the section 4.6 gates ({_gates_text(acc.get('failed') or [])})") + ".")


def _brakes_sentence(book: Mapping[str, Any]) -> str:
    j = book.get("judged") or {}
    b = j.get("brakes") or {}
    c = b.get("counts") or {}
    trips = b.get("trips") or {}
    abl = book.get("ablations") or {}
    costs = []
    for name, label in (("no_brakes", "every brake off"), ("no_corr_cap", "the correlation cap off"), ("heat_8pct", "the 8 % heat cap"), ("uniform_cost", "no altcoin surcharge")):
        a = abl.get(name)
        if a:
            vb = a.get("versus_book") or {}
            costs.append(f"{label}: Calmar {_f(vb.get('calmar_ablation'))} ({_f(vb.get('cost_calmar'), '{:+.2f}')})")
    flagged = [name for name, a in abl.items() if (a.get("versus_book") or {}).get("flagged")]
    return (f"**The brakes at book level.** Of {_int(c.get('opportunities'))} entry opportunities the book funded {_int(c.get('entries'))}: the one-entry-per-market-per-day cap "
            f"blocked {_int(c.get('entry_cap_market_day'))}, the three-per-day cap {_int(c.get('entry_cap_book_day'))}, the bar-after-an-exit rule {_int(c.get('entry_after_exit'))}, "
            f"the rolling 24-hour loss limit {_int(c.get('daily_loss'))} (tripped {_times(trips.get('daily_loss'))}), the weekly limit {_int(c.get('weekly_loss'))} "
            f"(tripped {_times(trips.get('weekly_loss'))}), the monthly limit {_int(c.get('monthly_loss'))} (tripped {_times(trips.get('monthly_loss'))}), the hard stop "
            f"{_int(c.get('hard_stop'))} (tripped {_times(trips.get('hard_stop'))}); the Turtle ladder cut {_int(c.get('ladder'))} entries; the heat cap scaled {_int(c.get('heat_cap_entries'))} "
            f"entries and reduced open positions {_int(c.get('heat_cap_reductions'))} times (the highest heat wanted at an entry: {_pct(b.get('heat_total_max'), False)} of equity); "
            f"the correlation cap acted on {_int(b.get('corr_cap_days'))} days; the cash ran short on {_int(c.get('cash_bound_entries'))} entries and blocked "
            f"{_int(c.get('cash_blocked_entries'))}. The same signals with one layer switched off: {'; '.join(costs) if costs else '-'}. "
            + (f"Flagged above 0.1 Calmar (a layer that costs more than that): {_names(flagged)}." if flagged else "No layer costs more than 0.1 Calmar."))


def book_failure_analysis(run: Mapping[str, Any]) -> List[str]:
    """Sentences on the book's failure, each computed from the run: the funding, the trims, the payoff, the fees, the markets, the post-hoc line."""
    book = run.get("book") or {}
    j = book.get("judged") or {}
    o = j.get("oos") or {}
    b = j.get("brakes") or {}
    c = b.get("counts") or {}
    ts = j.get("trades") or {}
    sleeves = [s for s in (run.get("sleeves") or []) if s.get("in_book") and s.get("trader")]
    trades = book.get("trades") or []
    out: List[str] = []
    n_tr = len(trades)
    reduced = sum(1 for t in trades if int(t.get("reductions") or 0) > 0)
    n_red = sum(int(t.get("reductions") or 0) for t in trades)
    opp = _num(c.get("opportunities"), 0.0)
    funded = _num(c.get("entries"), 0.0)
    halted = b.get("halted_from")
    if halted:
        out.append(f"**The hard stop ended it early.** The book funded {_int(funded)} of {_int(opp)} entry opportunities; it lost 30 % of its equity by {halted} and, as "
                   f"pre-registered for a simulated account, took no new entry afterwards ({_int(c.get('hard_stop'))} opportunities blocked, {_pct(b.get('halted_days_share'), False)} "
                   f"of its days flat). Its calendar years read: " + ", ".join(f"{y} {_pct(v)}" for y, v in sorted((j.get('yearly') or {}).items())) + ".")
    if n_tr:
        med_payoff = _median_of([(s["trader"] or {}).get("payoff_ratio") for s in sleeves])
        med_exp = _median_of([(s["trader"] or {}).get("expectancy_r") for s in sleeves])
        out.append(f"**The heat cap trimmed the winners.** With nine markets that move together, the book's sleeves formed one bet most of the time, so every new signal in "
                   f"the bet scaled every open position down equally, as pre-registered: {_int(n_red)} reductions on {_int(n_tr)} trades ({_int(reduced)} trades were trimmed at least "
                   f"once, {_f(n_red / max(1, n_tr), '{:.1f}')} trims per trade on average; the heat cap alone reduced open positions {_int(c.get('heat_cap_reductions'))} times "
                   f"and scaled {_int(c.get('heat_cap_entries'))} entries). A trend rule earns its keep by letting winners run; here the average win was "
                   f"{_f(ts.get('payoff_ratio'))} x the average loss against a median of {_f(med_payoff)} x for the same sleeves on their own, and the expectancy was "
                   f"{_f(ts.get('expectancy_r'), '{:+.2f}')} R a trade against a median of {_f(med_exp, '{:+.2f}')} R on their own.")
    by_m: Dict[str, List[float]] = {}
    for t in trades:
        by_m.setdefault(str(t.get("instrument")), [0.0, 0.0])
        by_m[str(t.get("instrument"))][0] += 1
        by_m[str(t.get("instrument"))][1] += _num(t.get("pnl"), 0.0)
    if by_m:
        init = _num(book.get("config", {}).get("init_cash"), 10_000.0) or 10_000.0
        losers = sorted(by_m.items(), key=lambda kv: kv[1][1])
        neg = sum(1 for _, v in by_m.items() if v[1] < 0)
        out.append(f"**Every market lost in the book.** {neg} of {len(by_m)} markets ended with a loss; the worst: "
                   + ", ".join(f"{m.split('-')[0]} {_pct(v[1] / init)} over {_int(v[0])} trades" for m, v in losers[:4]) + f"; BTC, the market whose sleeves are the "
                   f"strongest on their own, {_pct(by_m.get('BTC-USDT', [0, 0.0])[1] / init)} over {_int(by_m.get('BTC-USDT', [0, 0.0])[0])} trades, because its positions were "
                   "trimmed whenever an altcoin signal fired.")
    ph = (book.get("post_hoc") or {}).get("no_hard_stop") or {}
    if ph:
        po, pb = ph.get("oos") or {}, (ph.get("brakes") or {}).get("counts") or {}
        out.append(f"**The halt is not the cause.** Post hoc (not pre-registered), with the hard stop off the same book traded on: {_int(po.get('n_trades'))} trades, "
                   f"{_int(pb.get('heat_cap_reductions'))} heat-cap reductions, {_pct(po.get('fees_pct_per_year'), False)} of equity a year in costs against "
                   f"{_pct(o.get('fees_pct_per_year'), False)} for the registered book and a median of {_pct(_median_of([(s['trader'] or {}).get('fees_pct_per_year') for s in sleeves]), False)} "
                   f"for a sleeve on its own, and it ended at {_pct(po.get('cagr'))} a year with a {_pct(po.get('max_drawdown'), False)} worst fall. The construction, not the hard stop, "
                   "loses the money.")
    abl = book.get("ablations") or {}
    raw, nob = abl.get("raw") or {}, abl.get("no_brakes") or {}
    if raw and nob:
        out.append(f"**The brakes did what they are for.** Without them the same signals lost {_pct((raw.get('oos') or {}).get('cagr'))} a year with a "
                   f"{_pct((raw.get('oos') or {}).get('max_drawdown'), False)} fall (no brake, no correlation cap) and {_pct((nob.get('oos') or {}).get('cagr'))} with "
                   f"{_pct((nob.get('oos') or {}).get('max_drawdown'), False)} (the correlation cap alone): the brakes cut the fall to {_pct(o.get('max_drawdown'), False)}. They cannot "
                   "make a losing construction win.")
    out.append("**What this says and does not say.** The S1 family's edge lives in a few markets (BTC, SOL and, at the Trader cell, S1+VC on ETH) and the fleet already runs "
               "those sleeves one by one. Pooling 26 sleeves of one highly correlated bet into one account under a cap that trims open positions is a different trading rule, "
               "and it fails; it does not retest the sleeves. A future portfolio study, if any, would pre-register a heat cap that acts on NEW entries only, one sleeve per "
               "market, and a re-arm rule for the hard stop - as a new row, never as an edit of this one.")
    return out


def _config_key(name: str) -> tuple:
    """``"S1+VC SOL-USDT 6H [none]"`` -> (candidate, instrument, timeframe, mode)."""
    try:
        head, mode = name.split(" [")
        cand, inst, tf = head.split(" ")
        return (cand, inst, tf, mode.rstrip("]"))
    except ValueError:
        return (name,)


def _fleet_trader_rows() -> set:
    """The (candidate, instrument, timeframe, mode) of the shortlist rows tagged with the Trader tier (empty when the file is not at hand)."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "docs" / "research" / "paper_fleet_shortlist_v1c.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out = set()
    for row in data.get("configurations") or []:
        src = row.get("source") or {}
        if src.get("tier") == "trader":
            out.add((row.get("candidate"), row.get("instrument"), row.get("timeframe"), (row.get("regime_config") or {}).get("mode")))
    return out


def _median_of(values: Sequence[Any]) -> Optional[float]:
    xs = sorted(float(v) for v in values if v is not None and _ok(v))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])


# -- sections -------------------------------------------------------------------------------------------

def _prereg_section(run: Mapping[str, Any]) -> List[str]:
    meta = run.get("meta") or {}
    p = meta.get("preregistration") or {}
    lines = ["## Fixed before the first run (the pre-registration)", ""]
    lines.append(f"Written {meta.get('preregistration_written_at', '-')} to `{meta.get('preregistration_file', '-')}` (sha256 of the study's fixed text, file and configuration: "
                 f"`{str(meta.get('preregistration_sha256', '-'))[:16]}...`). The study refuses to run if the text in `research/breadth_study.py` differs from the file.")
    lines.append("")
    for key in ("question", "markets", "sleeves", "sleeve_verdicts", "book", "brakes", "allocator_v2", "costs", "ablation_rule", "gates", "candidate_rule", "comparison_lines",
                "diversification_reading", "brake_judgement", "holdout", "fleet", "protocol", "data", "reproduction", "no_changes_after_results"):
        if key in p:
            lines.append(f"- **{key.replace('_', ' ')}**: {p[key]}")
    abl = p.get("ablations") or {}
    if abl:
        lines.append("- **ablations**: " + "; ".join(f"`{k}` = {v}" for k, v in abl.items()))
    rot = p.get("rotation") or {}
    if rot:
        lines.append("")
        lines.append("### The rotation test, as fixed")
        lines.append("")
        for key in ("rule", "comparison", "span", "pass_rule", "expectation"):
            if key in rot:
                lines.append(f"- **{key.replace('_', ' ')}**: {rot[key]}")
    lines.append("")
    return lines


def _reproduction_section(run: Mapping[str, Any]) -> List[str]:
    rep = run.get("reproduction") or []
    lines = ["## Reproduction of the stored studies", ""]
    if not rep:
        lines.append("Not run (a smoke run), or no stored counterpart." if run.get("results") else "Runs before anything is judged.")
        lines.append("")
        return lines
    n_ok = sum(1 for c in rep if c.get("ok"))
    lines.append(f"{n_ok} of {len(rep)} stored results reproduced exactly (metrics to the stored 6 decimals, the same trade counts, the same most-selected rules, the same "
                 "gate verdicts). The study stops if any differs.")
    lines.append("")
    lines.append("| Configuration | Cell | Stored by | Max abs. difference | Trades (now / stored) | Rule matches | Verdict matches | OK |")
    lines.append("|---|---|---|---:|---:|---|---|---|")
    for c in sorted(rep, key=lambda x: (x.get("cell", ""), x.get("configuration", ""))):
        lines.append(f"| {c.get('configuration')} | {_k(c.get('cell'))} | {c.get('study')} | {_f(c.get('max_abs_difference'), '{:.1e}')} | {c.get('n_trades')} / {c.get('n_trades_stored')} | "
                     f"{_yes(c.get('selected_matches'))} | {_yes(c.get('verdict_matches'))} | {_yes(c.get('ok'))} |")
    lines.append("")
    return lines


def _sleeves_section(run: Mapping[str, Any]) -> List[str]:
    sleeves = run.get("sleeves") or []
    lines = ["## The sleeves on their own (both cells)", ""]
    if not sleeves:
        lines.append("No sleeve ran.")
        lines.append("")
        return lines
    lines.append("Each sleeve as Sprint 2c's runner judges it alone: the Reference cell (today's policy, for information) and the Trader cell (vt20/30 crash15/90dh cap2, the "
                 "Turtle ladder, the brakes on one sleeve), the section 4.6 gates at the Trader tier, the holdout where the runner opened it. 'In book' marks the sleeves the "
                 "book funds; an S1+S5 sleeve whose market's funding covers less than 90 % of the in-sample bars is run without S5 and left out.")
    lines.append("")
    lines.append("| Market | Rule | In book | Reference: CAGR / max DD / Calmar | Trader: CAGR / max DD / Calmar / Sharpe / PF / trades / payoff / risk per trade | Trader gates missed | Holdout (Trader) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in sleeves:
        ref, tr = s.get("reference") or {}, s.get("trader") or {}
        lines.append(f"| {s['instrument']} | {s.get('display_candidate') or s['candidate']} | {_yes(s.get('in_book'))} | {_pct(ref.get('cagr'))} / {_pct(ref.get('max_drawdown'), False)} / {_f(ref.get('calmar'))} | "
                     f"{_pct(tr.get('cagr'))} / {_pct(tr.get('max_drawdown'), False)} / {_f(tr.get('calmar'))} / {_f(tr.get('sharpe'))} / {_f(tr.get('profit_factor'))} / {_int(tr.get('n_trades'))} / "
                     f"{_f(tr.get('payoff_ratio'))} / {_pct(tr.get('risk_pct_mean'), False)} | {('**PASS**' if s.get('passed_own') else _gates_text(tr.get('failed') or []))} | "
                     f"{_holdout_cell(s.get('holdout'), s.get('holdout_confirmed'))} |")
    lines.append("")
    n_in = sum(1 for s in sleeves if s.get("in_book"))
    n_own = sum(1 for s in sleeves if s.get("in_book") and s.get("passed_own"))
    lines.append(f"{n_own} of the {n_in} sleeves in the book pass the section 4.6 gates on their own at the Trader cell: {_names(s['configuration'] for s in sleeves if s.get('in_book') and s.get('passed_own'))}.")
    lines.append("")
    return lines


def _book_table_row(label: str, o: Mapping[str, Any], acc: Optional[Mapping[str, Any]] = None) -> str:
    gates = "-" if acc is None else ("**PASS**" if acc.get("passed") else _gates_text(acc.get("failed") or []))
    return (f"| {label} | {_pct(o.get('cagr'))} | {_pct(o.get('ann_vol'), False)} | {_f(o.get('sharpe'))} | {_pct(o.get('max_drawdown'), False)} | {_f(o.get('calmar'))} | "
            f"{_f(o.get('profit_factor'))} | {_int(o.get('n_trades'))} | {_pct(o.get('avg_allocation'), False)} | {_pct(o.get('fees_pct_per_year'), False)} | {gates} |")


def _book_section(run: Mapping[str, Any]) -> List[str]:
    book = run.get("book")
    lines = ["## The breadth book", ""]
    if not book:
        lines.append("Not run." if run.get("results") else "Runs after the sleeves.")
        lines.append("")
        return lines
    j = book.get("judged") or {}
    o = j.get("oos") or {}
    acc = j.get("acceptance_r18") or {}
    clock = book.get("clock") or {}
    v = book.get("verdict") or {}
    div = run.get("diversification") or {}
    lines.append(f"{book.get('n_sleeves')} sleeves on {len(book.get('markets') or [])} markets ({_names(m.split('-')[0] for m in (book.get('markets') or []))}), 6H bars, "
                 f"{clock.get('first_bar', '')[:10]} to {clock.get('last_bar', '')[:10]} ({clock.get('bars')} bars, {clock.get('days')} days). Configuration: {(book.get('config') or {}).get('label')}. "
                 f"Costs per side: " + "; ".join(f"{m.split('-')[0]} {c['fee_rate'] * 100:.2f}% + {c['slippage_rate'] * 100:.2f}%" for m, c in sorted((book.get('costs') or {}).items())) + ".")
    lines.append("")
    lines.append("| | CAGR | Vol | Sharpe | Max DD | Calmar | PF | Trades | Avg invested | Fees / yr | Section 4.6 gates (Trader tier) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    lines.append(_book_table_row("**The book (pre-registered)**", o, acc))
    for name, a in (book.get("ablations") or {}).items():
        lines.append(_book_table_row(f"ablation `{name}`: {a.get('label')}", a.get("oos") or {}, a.get("acceptance_r18")))
    hold = book.get("hold_btc_trader") or {}
    if hold:
        lines.append(_book_table_row("hold BTC + Trader policy sizing (the runner's control, windows restart flat)", hold))
    hb = book.get("hold_btc_book_sim") or {}
    if hb:
        lines.append(_book_table_row("hold BTC + Trader policy sizing through the book simulator (continuous)", hb))
    bh = book.get("btc_buy_and_hold_span") or {}
    if bh:
        lines.append(f"| BTC buy-and-hold over the book's span | {_pct(bh.get('cagr'))} | {_pct(bh.get('ann_vol'), False)} | {_f(bh.get('sharpe'))} | {_pct(bh.get('max_drawdown'), False)} | "
                     f"{_f(bh.get('calmar'))} | - | - | 100% | - | - |")
    ew = div.get("equal_weight_nine") or {}
    if ew:
        lines.append(f"| equal-weight hold of the nine, 20 % volatility target (daily basket) | {_pct(ew.get('cagr'))} | {_pct(ew.get('ann_vol'), False)} | {_f(ew.get('sharpe'))} | "
                     f"{_pct(ew.get('max_drawdown'), False)} | {_f(ew.get('calmar'))} | - | - | - | - | - |")
    lines.append("")
    yearly = j.get("yearly") or {}
    if yearly:
        years = sorted(yearly)
        lines.append("| Calendar year | " + " | ".join(str(y) for y in years) + " |")
        lines.append("|---|" + "---:|" * len(years))
        lines.append("| the book | " + " | ".join(_pct(yearly[y]) for y in years) + " |")
        for name, a in (book.get("ablations") or {}).items():
            ay = a.get("yearly") or {}
            lines.append(f"| `{name}` | " + " | ".join(_pct(ay.get(y, ay.get(str(y)))) for y in years) + " |")
        for name, a in (book.get("post_hoc") or {}).items():
            ay = a.get("yearly") or {}
            lines.append(f"| post hoc `{name}` (not pre-registered) | " + " | ".join(_pct(ay.get(y, ay.get(str(y)))) for y in years) + " |")
        hy = (run.get("results") and next((r.get("yearly") for r in run["results"] if r.get("candidate") == "hold" and r.get("instrument") == "BTC-USDT" and r["cell"]["key"] == "trader|brakes|none"), None)) or {}
        if hy:
            lines.append("| hold BTC + Trader policy sizing | " + " | ".join(_pct(hy.get(str(y), hy.get(y))) for y in years) + " |")
        lines.append("")
    yg = j.get("yearly_gate") or {}
    lines.append(f"Gates at the Trader tier: profit factor above 1.2 {_yes(acc.get('pf_gt_1_2'))} ({_f(o.get('profit_factor'))}); max drawdown at most 25 % {_yes(acc.get('max_dd_within_tier'))} "
                 f"({_pct(o.get('max_drawdown'), False)}); Sharpe above 0.7 {_yes(acc.get('sharpe_gt_0_7'))} ({_f(o.get('sharpe'))}); Calmar above 0.5 {_yes(acc.get('calmar_gt_0_5'))} "
                 f"({_f(o.get('calmar'))}); 75 % of rolling 12-month windows positive {_yes(acc.get('rolling_12m_75pct_positive'))} ({_pct(yg.get('rolling_positive_share'), False)} of "
                 f"{yg.get('rolling_windows')}); worst calendar year at least -15 % {_yes(acc.get('worst_calendar_year_within_tier'))} ({_pct(yg.get('worst_calendar_year_return'))}, "
                 f"{yg.get('worst_calendar_year')}); at least 30 trades {_yes(acc.get('enough_trades'))} ({_int(o.get('n_trades'))}); average win at least 2 x average loss "
                 f"{_yes(acc.get('payoff_ge_2'))} ({_f(acc.get('payoff_ratio'))}); robustness carried by the sleeves. **Verdict: {'PASS' if acc.get('passed') else 'fail'}.**")
    lines.append("")
    lines.append(f"**Candidate under the R5b rule: {'yes' if v.get('candidate') else 'no'}** - {v.get('reason')}.")
    lines.append("")
    # The brakes.
    lines.append("### What the book-level rules did")
    lines.append("")
    b = j.get("brakes") or {}
    c = b.get("counts") or {}
    trips = b.get("trips") or {}
    lines.append("| Rule | Acted | Note |")
    lines.append("|---|---:|---|")
    lines.append(f"| entry opportunities / funded entries | {_int(c.get('opportunities'))} / {_int(c.get('entries'))} | bars on which at least one entry was blocked: {_int(c.get('bars_blocked'))} |")
    lines.append(f"| 1 new entry per market per day | {_int(c.get('entry_cap_market_day'))} | across the market's sleeves |")
    lines.append(f"| 3 new entries per day across the book | {_int(c.get('entry_cap_book_day'))} | the rules' strength, then the market order, decide who enters |")
    lines.append(f"| no entry in a market on the bar after an exit there | {_int(c.get('entry_after_exit'))} | |")
    lines.append(f"| rolling 24-hour loss limit (3 %) | {_int(c.get('daily_loss'))} entries blocked | tripped {_times(trips.get('daily_loss'))} |")
    lines.append(f"| weekly loss limit (6 % from Monday 00:00 UTC) | {_int(c.get('weekly_loss'))} entries blocked | tripped {_times(trips.get('weekly_loss'))} |")
    lines.append(f"| monthly loss limit (10 %) | {_int(c.get('monthly_loss'))} entries blocked | tripped {_times(trips.get('monthly_loss'))} |")
    lines.append(f"| hard stop (-30 %) | {_int(c.get('hard_stop'))} entries blocked | tripped {_times(trips.get('hard_stop'))}"
                 + (f"; the book was halted from {b.get('halted_from')} ({_pct(b.get('halted_days_share'), False)} of its days): as pre-registered, a simulated account "
                    "never re-arms" if b.get("halted_from") else "") + " |")
    lad = b.get("ladder_bars") or {}
    lines.append(f"| Turtle ladder | {_int(c.get('ladder'))} entries cut | bars at x0.8: {_int(lad.get('x0.8'))}, at x0.64: {_int(lad.get('x0.64'))} |")
    lines.append(f"| heat cap (6 % total, 3 % per bet) | {_int(c.get('heat_cap_entries'))} entries scaled, {_int(c.get('heat_cap_reductions'))} open positions reduced | highest heat wanted at an entry {_pct(b.get('heat_total_max'), False)}; mean {_pct(b.get('heat_total_mean_at_entries'), False)} |")
    lines.append(f"| correlation cap (50 % per bet, allocator v2) | {_int(b.get('corr_cap_days'))} days | {_int(c.get('corr_cap_reductions'))} positions reduced, {_int(c.get('corr_cap_entries'))} entries scaled; average cut {_pct(b.get('corr_cap_average_cut'), False)} |")
    lines.append(f"| cash (spot, no leverage) | {_int(c.get('cash_bound_entries'))} entries took less than the tier asked | {_int(c.get('cash_blocked_entries'))} entries found no cash at all |")
    lines.append("")
    ts = j.get("trades") or {}
    prof = book.get("monthly_positions") or {}
    lines.append(f"Effective risk per funded entry (the per-entry loss at the stop as a share of equity, after the ladder, heat and correlation multipliers and the cash constraint): "
                 f"mean {_pct(ts.get('risk_pct_mean'), False)}, median {_pct(ts.get('risk_pct_median'), False)}, max {_pct(ts.get('risk_pct_max'), False)}; expectancy {_f(ts.get('expectancy_r'), '{:+.2f}')} R "
                 f"a trade, {_pct(ts.get('win_rate'), False)} winners, average win {_f(ts.get('payoff_ratio'))} x the average loss; {_int(ts.get('stop_outs'))} stop-outs, {_int(ts.get('gap_trades'))} "
                 f"gaps past the stop, {_int(ts.get('reentries_within_2_bars_of_stop'))} re-entries within two bars of a stop-out. Positions: the book was flat on "
                 f"{_pct(prof.get('bars_flat_share'), False)} of bars, held {_f(prof.get('positions_mean'))} positions on average and {_int(prof.get('positions_max'))} at most, "
                 f"with {_pct(prof.get('invested_share_mean'), False)} of equity invested on average and {_pct(prof.get('invested_share_max'), False)} at most.")
    lines.append("")
    abl = book.get("ablations") or {}
    if abl:
        lines.append("| Ablation (the same signals, one layer changed) | Calmar | vs the book | CAGR | Max DD | Trades | Flag (> 0.1 Calmar) |")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for name, a in abl.items():
            vb = a.get("versus_book") or {}
            lines.append(f"| `{name}`: {a.get('label')} | {_f(vb.get('calmar_ablation'))} | {_f(vb.get('cost_calmar'), '{:+.2f}')} | {_pct(vb.get('cagr_ablation'))} | {_pct(vb.get('max_dd_ablation'), False)} | "
                         f"{_int(vb.get('n_trades_ablation'))} | {'**flagged**' if vb.get('flagged') else '-'} |")
        lines.append("")
        lines.append("A positive 'vs the book' means the layer costs Calmar when it is on (the ablation without it does better); a layer that costs more than 0.1 Calmar is flagged for "
                     "the owner, never silently kept or dropped. The ablations are diagnostics, not candidates.")
        lines.append("")
    ph = book.get("post_hoc") or {}
    if ph:
        lines.append("| Post-hoc diagnostic (NOT pre-registered; added after the first run; never a candidate) | CAGR | Vol | Sharpe | Max DD | Calmar | PF | Trades | Gates (information) |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for name, a in ph.items():
            o = a.get("oos") or {}
            acc = a.get("acceptance_r18") or {}
            lines.append(f"| `{name}`: {a.get('label')} | {_pct(o.get('cagr'))} | {_pct(o.get('ann_vol'), False)} | {_f(o.get('sharpe'))} | {_pct(o.get('max_drawdown'), False)} | "
                         f"{_f(o.get('calmar'))} | {_f(o.get('profit_factor'))} | {_int(o.get('n_trades'))} | {('would pass' if acc.get('passed') else _gates_text(acc.get('failed') or []))} |")
        lines.append("")
        lines.append("The post-hoc line answers one question the first run raised - how much of the book's result is the hard stop's permanent halt - and nothing else: it was "
                     "not pre-registered, it opens no holdout and it changes no verdict.")
        lines.append("")
    # Per-sleeve contributions.
    ps = j.get("per_sleeve") or {}
    if ps:
        lines.append("| Sleeve in the book | Funded trades | P&L (% of start) | Win rate | PF | Risk per entry | Funding multiplier (mean) | Cash-bound entries |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for name, s in sorted(ps.items(), key=lambda kv: -_num(kv[1].get("pnl_pct_of_start"), 0.0)):
            lines.append(f"| {name} | {_int(s.get('n_trades'))} | {_pct(s.get('pnl_pct_of_start'))} | {_pct(s.get('win_rate'), False)} | {_f(s.get('profit_factor'))} | {_pct(s.get('risk_pct_mean'), False)} | "
                         f"{_f(s.get('funded_multiplier_mean'))} | {_int(s.get('cash_bound'))} |")
        lines.append("")
    # Diversification and correlations.
    lines.append("### Diversification and correlations")
    lines.append("")
    lines.append(f"The book's Calmar is {_f(div.get('book_calmar'))} against a median of {_f(div.get('sleeves_median_calmar'))} over its {div.get('n_sleeves')} sleeves on their own "
                 f"(mean {_f(div.get('sleeves_mean_calmar'))}; best {_f((div.get('best_sleeve') or {}).get('calmar'))}, {(div.get('best_sleeve') or {}).get('configuration', '-')}), "
                 f"{_f((div.get('hold_btc_trader') or {}).get('calmar'))} for holding BTC with the Trader policy sizing and {_f((div.get('equal_weight_nine') or {}).get('calmar'))} for the "
                 f"equal-weight hold of the nine at the same volatility target. Its realized volatility is {_pct(div.get('book_ann_vol'), False)} against a median sleeve volatility of "
                 f"{_pct(div.get('sleeves_median_ann_vol'), False)}.")
    lines.append("")
    corr = run.get("correlations") or {}
    for key, label in (("in_sample", "the in-sample years"), ("recent", "since 2024-01-01 (in-sample part)")):
        cw = corr.get(key) or {}
        if not cw:
            continue
        lines.append(f"Daily-return correlations of the nine markets over {label} ({cw.get('start')} to {cw.get('end')}, {cw.get('days')} days): median pairwise {_f(cw.get('median_pairwise'))} "
                     f"(range {_f(cw.get('min_pairwise'))} to {_f(cw.get('max_pairwise'))}); among BTC, ETH, SOL and DOGE {_f(cw.get('confirmed_four_min'))} to {_f(cw.get('confirmed_four_max'))}; "
                     f"BTC against each: " + ", ".join(f"{m.split('-')[0]} {_f(v)}" for m, v in (cw.get("btc_vs_each") or {}).items()) + ".")
        lines.append("")
    sc = book.get("sleeve_correlations") or {}
    if sc.get("n_sleeves"):
        lines.append(f"Inside the book, the sleeves' daily P&L contributions correlate at a median of {_f(sc.get('median_pairwise'))} pairwise (range {_f(sc.get('min_pairwise'))} to "
                     f"{_f(sc.get('max_pairwise'))}; {sc.get('note')}).")
        lines.append("")
    if not acc.get("passed"):
        lines.append("### Why the book fails while most of its sleeves do not (computed from the numbers)")
        lines.append("")
        for s_ in book_failure_analysis(run):
            lines.append(f"- {s_}")
        lines.append("")
    # Holdout.
    h = book.get("holdout") or {}
    lines.append("### The book on the untouched 12 months")
    lines.append("")
    if h.get("evaluated"):
        ho = h.get("oos") or {}
        lines.append(f"Opened because the book passed the gates: {h.get('first_bar', '')[:10]} to {h.get('last_bar', '')[:10]} ({h.get('bars')} bars). Return {_pct(ho.get('total_return'))}, "
                     f"max drawdown {_pct(ho.get('max_drawdown'), False)}, profit factor {_f(ho.get('profit_factor'))}, {_int(ho.get('n_trades'))} trades: "
                     + ("**confirmed**" if h.get("confirmed") else "**not confirmed**") + f" (positive return, PF > 1, at least {HOLDOUT_MIN_TRADES} trades). "
                     f"Holding BTC with the Trader policy sizing over the same months: {_pct((h.get('hold_btc_trader_holdout') or {}).get('total_return'))}. {h.get('note')}")
    else:
        lines.append(f"Not opened: {h.get('reason', 'not evaluated')}.")
    lines.append("")
    return lines


def _rotation_section(run: Mapping[str, Any]) -> List[str]:
    rot = run.get("rotation")
    lines = ["## The rotation test", ""]
    if not rot:
        lines.append("Not run." if run.get("results") else "Runs after the sleeves.")
        lines.append("")
        return lines
    span = rot.get("span") or {}
    lines.append(f"One configuration, fixed before the run: the top {3} of the nine by trailing 3-week return, equal weight, decided at Sunday's close and filled Monday 00:00 UTC, long only, "
                 f"only while BTC's close is above its 200-day average (a close below it sends the basket to cash at the next open), sized by a 20 % volatility target, 0.15 % a side on "
                 f"BTC/ETH and 0.25 % on the altcoins. Span: {span.get('start')} to {span.get('end')} ({span.get('days')} days), every line over the same days.")
    lines.append("")
    lines.append("| Line | CAGR | Vol | Sharpe | Max DD | Calmar | Turnover / yr | Costs / yr | Invested (mean) | Days in cash by the filter | Rolling 12m + | Worst year |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    labels = {"rotation": "**rotation (pre-registered)**", "rotation_no_filter": "rotation without the BTC filter (diagnostic)", "btc_vt20": "hold BTC, 20 % volatility target (the comparison)",
              "btc_buy_and_hold": "BTC buy-and-hold", "equal_weight_nine_vt20": "equal-weight hold of the nine, 20 % volatility target", "equal_weight_nine_buy_and_hold": "equal-weight hold of the nine, fully invested"}
    for key, label in labels.items():
        m = (rot.get("lines") or {}).get(key)
        if not m:
            continue
        yg = m.get("yearly_gate") or {}
        lines.append(f"| {label} | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'), False)} | {_f(m.get('sharpe'))} | {_pct(m.get('max_drawdown'), False)} | {_f(m.get('calmar'))} | "
                     f"{_f(m.get('turnover_per_year'), '{:.1f}')} x | {_pct(m.get('fees_pct_per_year'), False)} | {_pct(m.get('invested_share_mean'), False)} | {_pct(m.get('days_filtered_out_share'), False)} | "
                     f"{_pct(yg.get('rolling_positive_share'), False)} | {_pct(yg.get('worst_calendar_year_return'))} |")
    lines.append("")
    yearly = rot.get("yearly") or {}
    years = sorted({int(y) for v in yearly.values() if v for y in v})
    if years:
        lines.append("| Calendar year | " + " | ".join(str(y) for y in years) + " |")
        lines.append("|---|" + "---:|" * len(years))
        for key, label in labels.items():
            yv = yearly.get(key) or {}
            if yv:
                lines.append(f"| {label.replace('**', '')} | " + " | ".join(_pct(yv.get(str(y), yv.get(y))) for y in years) + " |")
        lines.append("")
    checks = rot.get("checks") or {}
    r, b = (rot.get("lines") or {}).get("rotation") or {}, (rot.get("lines") or {}).get("btc_vt20") or {}
    lines.append(f"Pre-registered rule: Calmar ahead of the BTC comparison by more than 0.1 ({_f(r.get('calmar'))} vs {_f(b.get('calmar'))}): {_yes(checks.get('calmar_beats_btc_by_margin'))}; "
                 f"CAGR ahead ({_pct(r.get('cagr'))} vs {_pct(b.get('cagr'))}): {_yes(checks.get('cagr_above_btc'))}; max drawdown at most 25 % ({_pct(r.get('max_drawdown'), False)}): "
                 f"{_yes(checks.get('max_drawdown_within_tier'))}. **Verdict: {'beats BTC' if rot.get('passed') else 'does not beat BTC'}** "
                 + ("(the pre-registered expectation; the question is closed with our own numbers)." if not rot.get("passed") else "(against the pre-registered expectation)."))
    lines.append("")
    ew = (rot.get("lines") or {}).get("equal_weight_nine_vt20") or {}
    if r and b:
        lines.append(f"For information (no verdict rests on it): the rotation's worst fall was {_pct(r.get('max_drawdown'), False)} against {_pct(b.get('max_drawdown'), False)} for "
                     f"holding BTC at the same volatility target, which is the drawdown cut the plan's section 2.7 attributes to the BTC 200-day filter; its return stayed below "
                     f"BTC's, as the same section expected. The equal-weight hold of the nine at the same target made {_pct(ew.get('cagr'))} a year at a {_pct(ew.get('max_drawdown'), False)} "
                     f"fall (Calmar {_f(ew.get('calmar'))}) - a yardstick, not a candidate (it was pre-registered as a comparison line only).")
        lines.append("")
    counts = rot.get("selection_counts") or {}
    ws = rot.get("whipsaws") or {}
    if counts:
        total = sum(counts.values())
        lines.append("How often each market was in the top 3 (share of the weekly selections): " + ", ".join(f"{m.split('-')[0]} {_pct(v / total, False, 0)}" for m, v in sorted(counts.items(), key=lambda kv: -kv[1])) + ".")
    lines.append(f"The BTC filter sent the basket to cash {_int(ws.get('filter_exits'))} times, {_int(ws.get('reentered_within_30_days'))} of them followed by a re-entry within 30 days "
                 f"(the plan's whipsaw reading); the basket sat in cash by the filter on {_pct(r.get('days_filtered_out_share'), False)} of days.")
    lines.append("")
    h = rot.get("holdout") or {}
    if h.get("evaluated"):
        hr, hb = h.get("rotation") or {}, h.get("btc_vt20") or {}
        lines.append(f"Untouched 12 months ({(h.get('span') or {}).get('start')} to {(h.get('span') or {}).get('end')}): rotation {_pct(hr.get('total_return'))} (max DD {_pct(hr.get('max_drawdown'), False)}) "
                     f"against hold BTC vt20 {_pct(hb.get('total_return'))}: " + ("**confirmed**." if h.get("confirmed") else "**not confirmed**."))
    else:
        lines.append(f"Untouched 12 months: not opened - {h.get('reason', 'not evaluated')}.")
    lines.append("")
    return lines


def _holdout_section(run: Mapping[str, Any]) -> List[str]:
    lines = ["## The untouched 12 months", ""]
    openings = run.get("holdout_openings") or []
    looks = run.get("earlier_looks") or []
    if not openings:
        lines.append("No holdout was opened in this run." if run.get("results") else "Opened only as pre-registered.")
        lines.append("")
        return lines
    lines.append("### Every opening of the holdout (ledger)")
    lines.append("")
    lines.append("| Configuration | Cell | Role | Span | Return | Max DD | PF | Trades | Confirms |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---|")
    for o in openings:
        conf = o.get("confirmed")
        lines.append(f"| {o.get('configuration')} | {_k(o.get('cell'))} | {o.get('role')} | {o.get('span') or '-'} | {_pct(o.get('total_return'))} | {_pct(o.get('max_drawdown'), False)} | "
                     f"{_f(o.get('profit_factor'))} | {_int(o.get('n_trades'))} | {'yes' if conf is True else ('no' if conf is False else 'comparison line')} |")
    lines.append("")
    opened_looks = [x for x in looks if x.get("earlier_opened")]
    if opened_looks:
        lines.append("Earlier looks at the same months by the stored studies (the holdout is a near-second look for these sleeves):")
        lines.append("")
        lines.append("| Configuration | Earlier study | Cell | Earlier return | Earlier PF | Earlier trades | Earlier verdict |")
        lines.append("|---|---|---|---:|---:|---:|---|")
        for x in opened_looks:
            for e in x.get("earlier_looks") or []:
                conf = e.get("confirmed")
                lines.append(f"| {x.get('configuration')} | {e.get('study')} ({e.get('configuration')}) | {e.get('cell')} | {_pct(e.get('total_return'))} | {_f(e.get('profit_factor'))} | "
                             f"{_int(e.get('n_trades'))} | {'confirmed' if conf is True else ('contradicted' if conf is False else 'comparison line')} |")
        lines.append("")
    meta = run.get("meta") or {}
    if meta.get("second_look_warning"):
        lines.append("Second looks (configurations whose holdout an earlier run of this study already opened; both looks stay in the ledger): " + _names(meta["second_look_warning"]) + ".")
        lines.append("")
    return lines


def _fleet_section(run: Mapping[str, Any]) -> List[str]:
    lines = ["## Paper-fleet shortlist", ""]
    rec = run.get("shortlist_recorded_only") or []
    if not run.get("results"):
        lines.append("Nothing yet.")
    elif not rec:
        lines.append(f"Nothing recorded for the fleet: {run.get('shortlist_note', '-')}. Existing accounts are untouched; nothing joins demo or live.")
    else:
        for r in rec:
            lines.append(f"- RECORDED, not applied: {r.get('label')} - {r.get('note')}.")
    lines.append("")
    return lines


def owner_decisions(run: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    if not run.get("results"):
        return ["Nothing yet: the study has not run."]
    book = run.get("book") or {}
    v = book.get("verdict") or {}
    rot = run.get("rotation") or {}
    if v.get("candidate"):
        out.append("The breadth book is a candidate under the pre-registered rule; the fleet has no account type that runs a multi-market Trader-tier book, so running it "
                   "forward needs a new plan row (the fleet side). Recommendation: yes, as a new row, with the book as ONE account beside the Trader-tier sleeves it is made of.")
    elif (book.get("judged") or {}).get("acceptance_r18", {}).get("passed"):
        out.append(f"The breadth book passes the section 4.6 gates but is not a candidate ({v.get('reason')}). Recommendation: nothing joins the fleet; the sleeves that pass on their "
                   "own are already in it at the Trader tier, and the book's only value over them is the smoother curve shown above.")
    else:
        out.append("The breadth book does not pass the section 4.6 gates. Recommendation: nothing to decide; the confirmed sleeves stay in the fleet as they are.")
    halted = ((book.get("judged") or {}).get("brakes") or {}).get("halted_from")
    if halted:
        ph = ((book.get("post_hoc") or {}).get("no_hard_stop") or {})
        po = ph.get("oos") or {}
        out.append(f"The pre-registered book treats the -30 % hard stop as the end of the simulated account (it halted on {halted} and never re-armed), which is what the plan's "
                   f"rule says for a live account until the owner has reviewed; a real owner would review and decide. The post-hoc reading with the hard stop off (not "
                   f"pre-registered) gives {_pct(po.get('cagr'))} a year at a {_pct(po.get('max_drawdown'), False)} fall (Calmar {_f(po.get('calmar'))}). Decision: whether a future "
                   "portfolio study should pre-register a re-arm rule for the hard stop in simulation (for example re-arm after 30 flat days with the peak reset, as the "
                   "Reference ladder does). Recommendation: yes, as a pre-registered rule of the next study, never as an edit of this one.")
    flagged = [name for name, a in (book.get("ablations") or {}).items() if (a.get("versus_book") or {}).get("flagged")]
    if flagged:
        out.append(f"A book-level layer costs more than 0.1 Calmar on the book: {_names(flagged)}. Recommendation: keep every layer as pre-registered and read the flag again "
                   "beside a forward record; a layer is removed by a pre-registered decision, never by a result.")
    overall = run.get("overall") or {}
    in_fleet = _fleet_trader_rows()
    new_conf = [n for n in (overall.get("sleeves_holdout_confirmed") or []) if _config_key(n) not in in_fleet]
    if new_conf:
        sleeves = {s_["configuration"]: s_ for s_ in (run.get("sleeves") or [])}
        parts = []
        for n in new_conf:
            t = (sleeves.get(n) or {}).get("trader") or {}
            rf = (sleeves.get(n) or {}).get("reference") or {}
            h = (sleeves.get(n) or {}).get("holdout") or {}
            parts.append(f"{n} (walk-forward Calmar {_f(t.get('calmar'))} at the Trader cell against {_f(rf.get('calmar'))} at the Reference cell, {_pct(t.get('cagr'))} a year at a "
                         f"{_pct(t.get('max_drawdown'), False)} fall; holdout {_pct(h.get('total_return'))}, PF {_f(h.get('profit_factor'))}, {_int(h.get('n_trades'))} trades)")
        out.append(f"Two findings this study was not pre-registered to act on: {'; '.join(parts)} pass the section 4.6 gates at the Trader tier and their untouched 12 months "
                   "confirm them, but neither runs in the paper fleet, and this study's pre-registration lists a fleet ticket only for the book and the rotation. Decision: "
                   "whether to add them as Trader-tier accounts through the R18 loader path (a small new row). Recommendation: yes for S1 BTC-USDT 6H, as one small account read "
                   "as a hypothesis (it never passed at the Reference tier, where its Calmar sat below the 0.5 gate; the larger size lifts the Calmar above it); no for now for "
                   "S1+VC SOL-USDT 6H, whose holdout the round-2 study contradicted at the Reference tier (-1.6 %) and this study confirms at the Trader tier (+5.0 %) - the same "
                   "rule, two tiers, two verdicts on one year of data is noise, and the fleet already runs the SOL S1 and S1+S5 sleeves at both tiers.")
    if rot:
        if rot.get("passed"):
            out.append("The rotation beat BTC in sample against the pre-registered expectation; whether to build a rotation account type for the fleet is a new plan row. "
                       "Recommendation: only if its holdout confirmed it (see above), and even then as one small account.")
        else:
            out.append("The rotation did not beat holding BTC with the same sizing, as pre-registered. Recommendation: nothing to build; the question is closed with our own numbers.")
    return out


def _method_notes(run: Mapping[str, Any]) -> List[str]:
    meta = run.get("meta") or {}
    lines = ["## Method notes and caveats", ""]
    notes = [
        "The sleeves' own verdicts come from Sprint 2c's runner (walk-forward windows that restart flat every 180 days); the book replays the per-window selected rules "
        "continuously from the first test window of any sleeve, so its drawdown can exceed any window's and its equity is one account, not a stitch.",
        "A sleeve joins the book when its own first test window starts (SOL's history is shorter); the hold comparison through the book simulator starts with BTC's first window.",
        "Each entry is sized by the Trader tier on the book's equity marked at the previous close, capped by the cash left; the engine sizes a single sleeve on its cash, which is "
        "the same thing when the sleeve is flat (the parity test), and the book never sells an open position to make room for a new one.",
        "The heat cap and the correlation cap scale open positions down at the next open (a reduce-only sale), as section 4.3 and allocator v2 prescribe; an open position whose "
        "stop has moved above the price carries no risk and is left alone by the heat cap.",
        "The brakes' equity arithmetic (ladder, hard stop, loss limits) is the R18 EntryBrakes state machine run on the book's equity as one column, so a count here means what it "
        "meant in the single-sleeve studies.",
        "Correlations use one close per UTC day from the 6H bars; the 'recent' window ends at the in-sample end, so the untouched months never enter a correlation shown here.",
        "The rotation's volatility window is 30 DAYS of daily returns (allocator v1's convention); the tier's is 30 bars of 6H candles. The last in-sample day may be a part day; "
        "every rotation line books the same days.",
        "Every number is a simulation on historical public data at the modelled costs and proves nothing about the future; nothing here authorizes paper, demo or live trading.",
    ]
    for n in notes:
        lines.append(f"- {n}")
    for n in meta.get("run_notes") or []:
        lines.append(f"- {n}")
    if meta.get("skipped_series"):
        lines.append(f"- Skipped series: {_names(meta['skipped_series'])}.")
    lines.append("")
    return lines


# -- the report ---------------------------------------------------------------------------------------------

def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    lines: List[str] = []
    lines.append("# Breadth v1 - the S1 family on nine OKX markets as ONE Trader-tier book, and one rotation test (walk-forward, SIMULATION ONLY)")
    lines.append("")
    lines.append(f"Plan row R20 (`docs/TRADER_PLAN_2026-11-05.md`, section 6.1). Generated {meta.get('generated_at', '(pre-registration only)')} by `scripts/run_breadth_v1.py`"
                 + (f" in {meta.get('elapsed_minutes')} minutes on {meta.get('workers')} worker(s)" if meta.get("elapsed_minutes") is not None else "")
                 + f". Data: PUBLIC OKX spot candles frozen at Sprint 2c's data end (bar close <= {meta.get('data_end', '-')}); the untouched 12 months are "
                 f"{(meta.get('v1c_meta') or {}).get('holdout_span', '2025-10-20->2026-10-20')}. Research evidence for the paper fleet; nothing approved.")
    lines.append("")
    lines.append("## Executive summary (plain English)")
    lines.append("")
    for s in executive_summary(run):
        lines.append(f"- {s}")
    lines.append("")
    lines.extend(_prereg_section(run))
    lines.extend(_reproduction_section(run))
    lines.extend(_sleeves_section(run))
    lines.extend(_book_section(run))
    lines.extend(_rotation_section(run))
    lines.extend(_holdout_section(run))
    lines.extend(_fleet_section(run))
    lines.append("## Owner decisions (nothing below is decided by this report)")
    lines.append("")
    for s in owner_decisions(run):
        lines.append(f"- {s}")
    lines.append("")
    lines.extend(_method_notes(run))
    return "\n".join(lines) + "\n"
