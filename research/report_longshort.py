"""Phase 9 design study report: long and short through perpetual swaps without leverage (plan row R9, SIMULATION ONLY).

Renders ``docs/research/LONG_SHORT_STUDY_REPORT.md`` from the study's results
JSON. Every plain-English sentence is derived from the numbers in the run, so
a re-run on other data cannot print a stale claim.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from research.report_v1c import GATE_LABELS, GATES

DESIGN_LABEL = {"hybrid": "hybrid (long spot, short perp)", "perp": "all-perp (long and short perp)"}
RULE_LABELS = {
    "v1c_gates": "(1) v1c gates",
    "short_leg_pf_gt_1": "(2) short leg PF > 1",
    "beats_long_only_calmar": "(3) Calmar above long-only",
}


# -- formatting --------------------------------------------------------------------------------

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


def _yes(flag: Any) -> str:
    return "yes" if flag else "no"


def _results(run: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for s in run.get("series", []) for r in s.get("results", [])]


def _series_label(r: Mapping[str, Any]) -> str:
    return f"{r['instrument']} {r['timeframe']}"


def _cfg_label(r: Mapping[str, Any]) -> str:
    return f"{r['candidate']} {_series_label(r)} {r['variant']}"


def _median(values: Iterable[Any]) -> Optional[float]:
    xs = sorted(_num(v) for v in values if _ok(v))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])


def _year(yearly: Optional[Mapping[str, Any]], year: int) -> Optional[float]:
    if not yearly:
        return None
    v = yearly.get(str(year), yearly.get(year))  # type: ignore[arg-type]
    return None if v is None else _num(v)


def _short_pf(r: Mapping[str, Any]) -> Optional[float]:
    s = (r.get("legs") or {}).get("short") or {}
    return None if not s.get("n_trades") else _num(s.get("profit_factor"))


# -- facts derived from the run ------------------------------------------------------------------

def study_facts(run: Mapping[str, Any]) -> Dict[str, Any]:
    results = _results(run)
    judged = [r for r in results if r.get("phase9_rule") is not None]
    by_design: Dict[str, List[Mapping[str, Any]]] = {}
    for r in judged:
        by_design.setdefault(r["variant"], []).append(r)
    passed_gates = [r for r in judged if (r.get("acceptance") or {}).get("passed")]
    wf_passed = [r for r in judged if (r.get("phase9_rule") or {}).get("walk_forward_passed")]
    opened = [r for r in judged if r.get("holdout")]
    confirmed = [r for r in opened if r.get("holdout_confirmed") is True]
    contradicted = [r for r in opened if r.get("holdout_confirmed") is False]
    facts: Dict[str, Any] = {
        "n_judged": len(judged), "n_gates": len(passed_gates), "n_wf_passed": len(wf_passed), "n_opened": len(opened),
        "confirmed": confirmed, "contradicted": contradicted, "wf_passed": wf_passed, "passed_gates": passed_gates,
        "designs": {},
    }
    for design, rows in by_design.items():
        with_ref = [r for r in rows if (r.get("long_only") or {}).get("oos")]
        better = [r for r in with_ref if _num(r["oos"].get("calmar")) > _num(r["long_only"]["oos"].get("calmar"))]
        y22 = [r for r in with_ref if _year(r.get("yearly"), 2022) is not None and _year((r.get("long_only") or {}).get("yearly"), 2022) is not None]
        better22 = [r for r in y22 if _year(r["yearly"], 2022) > _year(r["long_only"]["yearly"], 2022)]
        pos22 = [r for r in y22 if _year(r["yearly"], 2022) > 0]
        spf = [r for r in rows if _short_pf(r) is not None]
        spf_ok = [r for r in spf if _short_pf(r) > 1.0]
        btc = [r for r in spf if r["instrument"].startswith("BTC")]
        eth = [r for r in spf if r["instrument"].startswith("ETH")]
        facts["designs"][design] = {
            "n": len(rows), "with_ref": len(with_ref), "better_calmar": len(better), "y22": len(y22), "better_2022": len(better22),
            "positive_2022": len(pos22), "short_pf_known": len(spf), "short_pf_gt_1": len(spf_ok),
            "btc_short_losing": sum(1 for r in btc if _short_pf(r) <= 1.0), "btc_n": len(btc),
            "eth_short_winning": sum(1 for r in eth if _short_pf(r) > 1.0), "eth_n": len(eth),
            "median_calmar": _median(r["oos"].get("calmar") for r in rows),
            "median_long_only_calmar": _median(r["long_only"]["oos"].get("calmar") for r in with_ref),
            # legs' funding is in window-capital units (10,000 per window, summed over windows): / 10,000 = share of capital.
            "median_short_funding": _median(_num(((r.get("legs") or {}).get("short") or {}).get("funding"), 0.0) / 10_000.0 for r in rows),
            "median_long_funding": _median(_num(((r.get("legs") or {}).get("long") or {}).get("funding"), 0.0) / 10_000.0 for r in rows),
            "max_leverage": max((_num(r.get("max_leverage"), 0.0) for r in rows), default=0.0),
            "liquidations": sum(int(((r.get("legs") or {}).get("short") or {}).get("liquidations") or 0) for r in rows),
            "median_2022": _median(_year(r["yearly"], 2022) for r in y22),
            "median_2022_long_only": _median(_year(r["long_only"]["yearly"], 2022) for r in y22),
        }
    # Hybrid vs all-perp on the same family and series.
    pairs = _pairs(judged)
    facts["hybrid_beats_perp"] = sum(1 for h, p in pairs if _num(h["oos"].get("cagr")) > _num(p["oos"].get("cagr")))
    facts["n_pairs"] = len(pairs)
    # Fixed default parameters (no selection).
    d_rows = []
    for s in run.get("series", []):
        for fam, dd in (s.get("defaults") or {}).items():
            d_rows.append((fam, s["instrument"], s["timeframe"], dd))
    facts["defaults_n"] = len(d_rows)
    facts["defaults_hybrid_lower_calmar"] = sum(1 for *_, dd in d_rows if _num(dd["hybrid"].get("calmar")) < _num(dd["long_only"].get("calmar")))
    facts["defaults_short_losing"] = sum(1 for *_, dd in d_rows if _num(((dd["hybrid"].get("legs") or {}).get("short") or {}).get("profit_factor"), 0) <= 1.0)
    facts["defaults_better_2022"] = sum(1 for *_, dd in d_rows if _num(_year(dd["hybrid"].get("yearly"), 2022), -9) > _num(_year(dd["long_only"].get("yearly"), 2022), -9))
    # Post-hoc: shorts without the crash filter.
    nc = [r for r in judged if r.get("diagnostic_short_no_crash_filter")]
    facts["no_crash_n"] = len(nc)
    facts["no_crash_worse"] = sum(1 for r in nc if _num(r["diagnostic_short_no_crash_filter"].get("calmar")) < _num(r["oos"].get("calmar")))
    pp = [r for r in judged if r.get("perp_priced")]
    facts["perp_priced_n"] = len(pp)
    facts["perp_priced_max_calmar_change"] = max((abs(_num(r["perp_priced"].get("calmar")) - _num(r["oos"].get("calmar"))) for r in pp), default=None)
    facts["max_leverage"] = max((_num(r.get("max_leverage"), 0.0) for r in judged), default=0.0)
    # The holdout's confirmations, as distinct rules (the two designs of one rule share their signals).
    facts["confirmed_rules"] = sorted({(r["candidate"], r["instrument"], r["timeframe"]) for r in confirmed})
    facts["contradicted_rules"] = sorted({(r["candidate"], r["instrument"], r["timeframe"]) for r in contradicted})
    facts["confirmed_coins"] = sorted({r["instrument"] for r in confirmed})
    facts["confirmed_designs"] = {rule: sorted(r["variant"] for r in confirmed if (r["candidate"], r["instrument"], r["timeframe"]) == rule)
                                  for rule in facts["confirmed_rules"]}
    shorts = [int(((r["holdout"].get("legs") or {}).get("short") or {}).get("n_trades") or 0) for r in confirmed]
    facts["confirmed_short_trades"] = max(shorts) if shorts else None
    return facts


def _majority(k: int, n: int) -> bool:
    return n > 0 and 2 * k > n


def _minority(k: int, n: int) -> bool:
    return n > 0 and 2 * k < n


def _rule_name(rule: Tuple[str, str, str]) -> str:
    c, i, t = rule
    return f"{c} {i} {t}"


def _pairs(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    index = {(r["candidate"], r["instrument"], r["timeframe"], r["variant"]): r for r in rows}
    out = []
    for (fam, inst, tf, design), r in sorted(index.items()):
        if design == "hybrid" and (fam, inst, tf, "perp") in index:
            out.append((r, index[(fam, inst, tf, "perp")]))
    return out


def _rule_text(r: Mapping[str, Any]) -> str:
    rule = r.get("phase9_rule") or {}
    marks = []
    for key, label in RULE_LABELS.items():
        marks.append(("✓" if rule.get(key) else "✗") + label.split(" ", 1)[0])
    return " ".join(marks)


def _holdout_cell(r: Mapping[str, Any]) -> str:
    h = r.get("holdout")
    if not h:
        return "untouched"
    mark = "✓ confirmed" if r.get("holdout_confirmed") else "✗ contradicted"
    return f"{_pct(h.get('total_return'))} / PF {_f(h.get('profit_factor'))} / {int(_num(h.get('n_trades'), 0))} tr {mark}"


def executive_summary(run: Mapping[str, Any]) -> List[str]:
    f = study_facts(run)
    hy = f["designs"].get("hybrid", {})
    pe = f["designs"].get("perp", {})
    desc = run.get("descriptive") or {}
    lines: List[str] = []
    lines.append(
        f"- **What we tested.** Whether the trend rules of Sprint 2c (S1, S2, S4 and S1+S5) earn more, for the risk they take, when they "
        f"may also be SHORT through BTC- and ETH-USDT perpetual swaps with collateral at least equal to the position (no leverage). "
        f"Two designs: the long leg stays on spot and only the short uses the swap (hybrid), or both legs use the swap (all-perp). "
        f"{f['n_judged']} configurations (4 families x BTC/ETH x 4H/6H x 2 designs), the same walk-forward, sizing policy and gates as "
        f"Sprint 2c, after fees, slippage and funding; everything was fixed before the first run.")
    if f["n_wf_passed"]:
        names = ", ".join(_cfg_label(r) for r in f["wf_passed"])
        hold = [f"{_cfg_label(r)}: {_holdout_cell(r)}" for r in f["wf_passed"]]
        lines.append(
            f"- **Result.** {f['n_gates']} of {f['n_judged']} configurations passed the Sprint 2c gates and {f['n_wf_passed']} met the whole "
            f"walk-forward part of the pre-registered rule ({names}). The untouched 12 months then confirmed {len(f['confirmed'])} and "
            f"contradicted {len(f['contradicted'])} ({'; '.join(hold)}).")
    else:
        lines.append(f"- **Result.** {f['n_gates']} of {f['n_judged']} configurations passed the Sprint 2c gates and none met the walk-forward "
                     f"part of the pre-registered rule, so the 12-month holdout stayed untouched.")
    if hy:
        if _minority(hy["better_calmar"], hy["with_ref"]):
            answer = "Mostly not."
        elif _majority(hy["better_calmar"], hy["with_ref"]):
            answer = "Mostly yes."
        else:
            answer = "In half of the cases."
        lo22, ls22 = hy.get("median_2022_long_only"), hy.get("median_2022")
        if _majority(hy["better_2022"], hy["y22"]):
            y22 = f"It made the 2022 bear year better than long-only in {hy['better_2022']} of {hy['y22']} pairs"
        else:
            y22 = f"It made the 2022 bear year better than long-only in only {hy['better_2022']} of {hy['y22']} pairs"
        if lo22 is not None and ls22 is not None:
            moved = "barely moved" if abs(ls22 - lo22) < 0.01 else ("improved" if ls22 > lo22 else "worsened")
            y22 += f"; the median 2022 result {moved} ({_pct(lo22)} long-only, {_pct(ls22)} with shorts)"
        y22 += f", and {hy['positive_2022']} of {hy['y22']} pairs ended 2022 positive."
        lines.append(
            f"- **Did the short side help?** {answer} With the short leg added (hybrid design) the risk-adjusted result (Calmar) beat the "
            f"long-only rule in {hy['better_calmar']} of {hy['with_ref']} family-and-series pairs (median Calmar {_f(hy['median_calmar'])} "
            f"against {_f(hy['median_long_only_calmar'])} long-only). The short leg on its own made money (profit factor above 1 after costs "
            f"and funding) in {hy['short_pf_gt_1']} of {hy['short_pf_known']} configurations: on BTC it lost in {hy['btc_short_losing']} of "
            f"{hy['btc_n']}, on ETH it won in {hy['eth_short_winning']} of {hy['eth_n']}. {y22} With the families' fixed default parameters "
            f"over 2020-01 to the holdout start (no selection at all) the short leg lowered Calmar in {f['defaults_hybrid_lower_calmar']} of "
            f"{f['defaults_n']} pairs and lost money in {f['defaults_short_losing']} of {f['defaults_n']}.")
    if hy and pe:
        btc = (desc.get("BTC-USDT") or {}).get("funding_span_summary") or {}
        eth = (desc.get("ETH-USDT") or {}).get("funding_span_summary") or {}
        means = [_num(btc.get("annualized_mean")), _num(eth.get("annualized_mean"))]
        if all(m > 0 for m in means):
            direction = "Funding flowed mostly from longs to shorts"
        elif all(m < 0 for m in means):
            direction = "Funding flowed mostly from shorts to longs"
        else:
            direction = "Funding flowed both ways"
        short_word = "received" if _num(hy["median_short_funding"], 0) > 0 else "paid"
        long_word = "paid" if _num(pe["median_long_funding"], 0) < 0 else "received"
        if _majority(f["hybrid_beats_perp"], f["n_pairs"]):
            design = ": if shorts ever come, the long side should stay on spot."
        elif _minority(f["hybrid_beats_perp"], f["n_pairs"]):
            design = ": the all-perp design was the cheaper one."
        else:
            design = ": neither design was clearly cheaper."
        lines.append(
            f"- **Funding and the two designs.** {direction}: on the proxy series it averaged {_pct(btc.get('annualized_mean'))} a year for BTC "
            f"and {_pct(eth.get('annualized_mean'))} for ETH (2020 to the holdout start, paid by longs when positive). The hybrid's shorts "
            f"{short_word} a median {_pct(abs(_num(hy['median_short_funding'], 0)), signed=False, digits=2)} of capital over the whole walk-forward; "
            f"the all-perp design's longs {long_word} a median {_pct(abs(_num(pe['median_long_funding'], 0)), signed=False, digits=2)}. The hybrid "
            f"made more than the all-perp design in {f['hybrid_beats_perp']} of {f['n_pairs']} pairs{design}")
    adv = []
    liquidating = []
    for inst in ("BTC-USDT", "ETH-USDT"):
        a = ((desc.get(inst) or {}).get("adverse_moves_spot") or {}).get("720h") or {}
        s1 = (desc.get(inst) or {}).get("adverse_moves_spot") or {}
        if a:
            adv.append(f"{inst.split('-')[0]} rose up to {_pct(a.get('max'), signed=False, digits=0)} within 30 days (from {str(a.get('at', '-'))[:10]}) "
                       f"and up to {_pct(s1.get('largest_one_hour_spike'), signed=False, digits=0)} within one hour")
            if _num(a.get("share_ge_liquidation"), 0.0) > 0:
                liquidating.append(f"{inst.split('-')[0]} {_pct(a.get('share_ge_liquidation'), signed=False, digits=1)}")
    if adv and hy:
        liq = (f"; that rise came within 30 days from {', '.join(liquidating)} of the hourly closes of the span"
               if liquidating else "; it never came within 30 days in this span")
        n_liq = hy["liquidations"] + (pe.get("liquidations", 0) if pe else 0)
        stops = (f"With the study's ATR stops no simulated short was liquidated (highest account leverage {_f(f['max_leverage'])}x)"
                 if n_liq == 0 else f"Even with the study's ATR stops {n_liq} simulated shorts were liquidated")
        need = "every short needs an exchange-side stop" if liquidating else "a protective stop still matters"
        lines.append(f"- **The risk a short carries.** {'; '.join(adv)}. A 1x short with no stop is liquidated by a rise of about 99 %{liq}. "
                     f"{stops}; {need}.")
    lines.append(f"- **What it means.** {_verdict_sentence(f)}")
    return lines


def _verdict_sentence(f: Mapping[str, Any]) -> str:
    hy = f["designs"].get("hybrid", {})
    shorts_lost = bool(hy) and _minority(hy["short_pf_gt_1"], hy["short_pf_known"])
    rules = f["confirmed_rules"]
    if not rules:
        text = "Under the pre-registered rule no configuration counts as evidence for Phase 9."
        if shorts_lost:
            text += (" The short legs lost money in most configurations, so these mirror-image shorts do not improve the trend rules after "
                     "funding and costs; a long/short system would need a different short rule, pre-registered as one.")
        return text
    coins = f["confirmed_coins"]
    names = "; ".join(f"{_rule_name(rule)} ({' and '.join(f['confirmed_designs'][rule])})" for rule in rules)
    plural = len(rules) > 1
    text = f"Under the pre-registered rule {len(rules)} rule{'s' if plural else ''} count{'' if plural else 's'} as evidence: {names}."
    reasons = [f"{len(rules)} rule{'s' if plural else ''} on {len(coins)} coin{'s' if len(coins) > 1 else ''}"]
    if f["contradicted_rules"]:
        reasons.append("the holdout contradicted " + ", ".join(_rule_name(r) for r in f["contradicted_rules"]) +
                       ", which met the same walk-forward rule")
    reasons.append("the holdout's falling direction was known before it was opened, which flatters any rule that can be short (pre-registered)")
    if f.get("confirmed_short_trades") is not None:
        reasons.append(f"the confirmed holdout's short side traded {f['confirmed_short_trades']} times")
    if shorts_lost:
        reasons.append(f"across all configurations the short leg made money in only {hy['short_pf_gt_1']} of {hy['short_pf_known']}")
    strong = len(rules) >= 2 and len(coins) >= 2 and not f["contradicted_rules"]
    if strong:
        return text + (" It is the strongest evidence this study can give, still on a holdout of known direction; whether it is enough for "
                       "Phase 9 is the owner's decision.")
    return text + " It is weak evidence: " + "; ".join(reasons) + ". Not enough to advance Phase 9."


# -- tables -------------------------------------------------------------------------------------------

def _summary_table(results: Sequence[Mapping[str, Any]]) -> List[str]:
    out = ["| Family | Series | Design | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Long-only Calmar | Trades (long/short) | Time short | Short-leg PF | Funding | Gates | Rule (1)(2)(3) | Holdout (12m) |",
           "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in results:
        o = r.get("oos") or {}
        legs = r.get("legs") or {}
        lo = ((r.get("long_only") or {}).get("oos") or {})
        out.append(
            f"| {r['candidate']} | {_series_label(r)} | {r['variant']} | {_pct(o.get('total_return'))} | {_pct(o.get('cagr'))} | "
            f"{_f(o.get('sharpe'))} | {_f(o.get('profit_factor'))} | {_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | "
            f"{_f(lo.get('calmar'))} | {int(_num(o.get('n_trades'), 0))} ({int((legs.get('long') or {}).get('n_trades') or 0)}/"
            f"{int((legs.get('short') or {}).get('n_trades') or 0)}) | {_pct(r.get('short_share'), signed=False, digits=0)} | "
            f"{_f(_short_pf(r))} | {_pct(r.get('funding_total_pct'), digits=2)} | {'**PASS**' if (r.get('acceptance') or {}).get('passed') else 'fail'} | "
            f"{_rule_text(r)} | {_holdout_cell(r)} |")
    return out


def _comparison_table(results: Sequence[Mapping[str, Any]]) -> List[str]:
    out = ["| Family | Series | Long-only Calmar | Hybrid Calmar | All-perp Calmar | Long-only CAGR | Hybrid CAGR | All-perp CAGR | 2022 long-only | 2022 hybrid | 2022 all-perp |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for h, p in _pairs(results):
        lo = (h.get("long_only") or {})
        loo = lo.get("oos") or {}
        out.append(
            f"| {h['candidate']} | {_series_label(h)} | {_f(loo.get('calmar'))} | {_f(h['oos'].get('calmar'))} | {_f(p['oos'].get('calmar'))} | "
            f"{_pct(loo.get('cagr'))} | {_pct(h['oos'].get('cagr'))} | {_pct(p['oos'].get('cagr'))} | {_pct(_year(lo.get('yearly'), 2022))} | "
            f"{_pct(_year(h.get('yearly'), 2022))} | {_pct(_year(p.get('yearly'), 2022))} |")
    return out


def _legs_table(results: Sequence[Mapping[str, Any]]) -> List[str]:
    out = ["| Family | Series | Design | Long trades | Long PF | Long P&L | Long funding | Short trades | Short PF | Short win rate | Short P&L | Short funding | Worst short trade | Worst short excursion | Max leverage |",
           "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        lg = (r.get("legs") or {}).get("long") or {}
        sh = (r.get("legs") or {}).get("short") or {}
        out.append(
            f"| {r['candidate']} | {_series_label(r)} | {r['variant']} | {int(lg.get('n_trades') or 0)} | {_f(lg.get('profit_factor'))} | "
            f"{_pct(_num(lg.get('pnl'), 0) / 10_000)} | {_pct(_num(lg.get('funding'), 0) / 10_000, digits=2)} | {int(sh.get('n_trades') or 0)} | "
            f"{_f(sh.get('profit_factor'))} | {_pct(sh.get('win_rate'), signed=False, digits=0)} | {_pct(_num(sh.get('pnl'), 0) / 10_000)} | "
            f"{_pct(_num(sh.get('funding'), 0) / 10_000, digits=2)} | {_pct(sh.get('worst_return_pct'))} | {_pct(sh.get('worst_mae_pct'))} | "
            f"{_f(r.get('max_leverage'))} |")
    return out


def _defaults_table(run: Mapping[str, Any]) -> List[str]:
    out = ["| Family | Series | Span | Long-only CAGR / max DD / Calmar | Hybrid CAGR / max DD / Calmar | All-perp CAGR / max DD / Calmar | Short-leg PF (hybrid) | 2022 long-only / hybrid |",
           "|---|---|---|---|---|---|---:|---|"]
    for s in run.get("series", []):
        for fam, dd in (s.get("defaults") or {}).items():
            cells = []
            for v in ("long_only", "hybrid", "perp"):
                m = dd.get(v) or {}
                cells.append(f"{_pct(m.get('cagr'))} / {_pct(m.get('max_drawdown'), signed=False)} / {_f(m.get('calmar'))}")
            spf = ((dd.get("hybrid") or {}).get("legs") or {}).get("short", {}).get("profit_factor")
            out.append(f"| {fam} | {s['instrument']} {s['timeframe']} | {dd.get('span', '-')} | {cells[0]} | {cells[1]} | {cells[2]} | {_f(spf)} | "
                       f"{_pct(_year((dd.get('long_only') or {}).get('yearly'), 2022))} / {_pct(_year((dd.get('hybrid') or {}).get('yearly'), 2022))} |")
    return out


def _diagnostics_table(results: Sequence[Mapping[str, Any]]) -> List[str]:
    out = ["| Family | Series | Design | Calmar (as run) | Perp-priced Calmar | No crash filter on shorts: Calmar / short PF | Fixed rule: return | slippage x2 | slippage x3 | funding x0 | funding x2 |",
           "|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|"]
    for r in results:
        st = r.get("stress") or {}
        pp = r.get("perp_priced") or {}
        nc = r.get("diagnostic_short_no_crash_filter") or {}
        nc_spf = ((nc.get("legs") or {}).get("short") or {}).get("profit_factor")
        out.append(
            f"| {r['candidate']} | {_series_label(r)} | {r['variant']} | {_f(r['oos'].get('calmar'))} | {_f(pp.get('calmar'))} | "
            f"{_f(nc.get('calmar'))} / {_f(nc_spf)} | {_pct(st.get('slippage_x1'))} | {_pct(st.get('slippage_x2'))} | {_pct(st.get('slippage_x3'))} | "
            f"{_pct(st.get('funding_x0'))} | {_pct(st.get('funding_x2'))} |")
    return out


def _funding_section(desc: Mapping[str, Any]) -> List[str]:
    out = [f"Proxy: Binance's public USDT-margined funding history (the rate longs pay shorts when positive), {desc.get('span', '-')}. "
           "'Summed' is what a 1x long held through every settlement of the year paid, in % of its notional (a short received it).", "",
           "| Coin | Year | Settlements | Annualized mean | Summed | Negative settlements | Lowest | Highest |",
           "|---|---|---:|---:|---:|---:|---:|---:|"]
    for inst in ("BTC-USDT", "ETH-USDT"):
        fy = (desc.get(inst) or {}).get("funding_by_year") or {}
        for year in sorted(fy, key=lambda y: int(y)):
            v = fy[year]
            out.append(f"| {inst.split('-')[0]} | {year} | {int(v['settlements'])} | {_pct(v['annualized_mean'])} | {_pct(v['summed'])} | "
                       f"{_pct(v['share_negative'], signed=False)} | {_pct(v['min'], digits=3)} | {_pct(v['max'], digits=3)} |")
    out += ["", "OKX's own funding against the proxy, where both exist (OKX's public history keeps only months):", "",
            "| Coin | Settlements matched | Span | Correlation | Same sign | OKX annualized | Binance annualized | Difference |",
            "|---|---:|---|---:|---:|---:|---:|---:|"]
    for inst in ("BTC-USDT", "ETH-USDT"):
        ov = (desc.get(inst) or {}).get("okx_vs_binance_funding") or {}
        if not ov.get("n"):
            out.append(f"| {inst.split('-')[0]} | 0 | - | - | - | - | - | - |")
            continue
        out.append(f"| {inst.split('-')[0]} | {int(ov['n'])} | {str(ov.get('start', ''))[:10]} -> {str(ov.get('end', ''))[:10]} | "
                   f"{_f(ov.get('correlation'))} | {_pct(ov.get('same_sign_share'), signed=False, digits=0)} | {_pct(ov.get('annualized_mean_okx'))} | "
                   f"{_pct(ov.get('annualized_mean_binance'))} | {_pct(ov.get('annualized_mean_difference'))} |")
    return out


def _risk_section(desc: Mapping[str, Any]) -> List[str]:
    out = ["The largest rise a short opened at an hourly close would have faced within each horizon (the highest high of the next hours "
           "against that close), spot and perpetual swap, 2020-01-01 to the holdout start. 'Liquidation share' counts the hourly closes from "
           "which an unprotected 1x isolated short would have been liquidated (a rise of about 99 % with OKX's 0.4 % maintenance margin).", "",
           "| Coin | Market | 4 hours | 1 day | 7 days | 30 days (from) | 30-day windows with >= 20 % rise | Liquidation share (30 days) | Largest 1-hour spike (at) |",
           "|---|---|---:|---:|---:|---|---:|---:|---|"]
    for inst in ("BTC-USDT", "ETH-USDT"):
        for market, key in (("spot", "adverse_moves_spot"), ("perp", "adverse_moves_perp")):
            a = (desc.get(inst) or {}).get(key) or {}
            if not a:
                continue
            m30 = a.get("720h") or {}
            out.append(f"| {inst.split('-')[0]} | {market} | {_pct((a.get('4h') or {}).get('max'), signed=False)} | "
                       f"{_pct((a.get('24h') or {}).get('max'), signed=False)} | {_pct((a.get('168h') or {}).get('max'), signed=False)} | "
                       f"{_pct(m30.get('max'), signed=False)} ({str(m30.get('at', '-'))[:10]}) | {_pct(m30.get('share_ge_20pct'), signed=False)} | "
                       f"{_pct(m30.get('share_ge_liquidation'), signed=False, digits=2)} | {_pct(a.get('largest_one_hour_spike'), signed=False)} "
                       f"({str(a.get('largest_one_hour_spike_at', '-'))[:16]}) |")
    out += ["", "Spot-perp basis (perp close / spot close - 1 at matching hourly closes):", "",
            "| Coin | Hours | Mean | Median | 1st pct | 99th pct | Lowest | Highest | Hours beyond ±0.5 % |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for inst in ("BTC-USDT", "ETH-USDT"):
        b = (desc.get(inst) or {}).get("basis_1h") or {}
        if not b.get("n"):
            continue
        out.append(f"| {inst.split('-')[0]} | {int(b['n'])} | {_pct(b['mean'], digits=3)} | {_pct(b['median'], digits=3)} | {_pct(b['p01'], digits=3)} | "
                   f"{_pct(b['p99'], digits=3)} | {_pct(b['min'], digits=2)} | {_pct(b['max'], digits=2)} | {_pct(b['share_abs_over_0_5pct'], signed=False, digits=2)} |")
    return out


def _detail(r: Mapping[str, Any]) -> List[str]:
    o = r.get("oos") or {}
    acc = r.get("acceptance") or {}
    yg = r.get("yearly_gate") or {}
    rob = r.get("robustness") or {}
    dsr = r.get("dsr") or {}
    mc = r.get("montecarlo") or {}
    years = " · ".join(f"{y} {_pct(v)}" for y, v in sorted((r.get("yearly") or {}).items(), key=lambda kv: int(kv[0])))
    checks = ", ".join(f"{GATE_LABELS.get(k, k)}={_yes(acc.get(k))}" for k in GATE_LABELS)
    lines = [f"### {r['candidate']} {_series_label(r)} — {DESIGN_LABEL.get(r['variant'], r['variant'])}", "",
             f"Rule grid {r.get('grid_size')} combinations; most-selected rule `{r.get('selected_params')}`. "
             f"Windows {o.get('windows')} ({o.get('windows_traded')} traded, {o.get('windows_positive')} positive). "
             f"Time short {_pct(r.get('short_share'), signed=False, digits=0)}, highest account leverage {_f(r.get('max_leverage'))}x, "
             f"net funding {_pct(r.get('funding_total_pct'), digits=2)} of capital.", "",
             f"Calendar years: {years or '-'}. Rolling 12-month windows {yg.get('rolling_windows')} sampled, "
             f"{_pct(yg.get('rolling_positive_share'), signed=False)} positive; worst calendar year {yg.get('worst_calendar_year')} at "
             f"{_pct(yg.get('worst_calendar_year_return'))}.", "",
             f"Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected {_pct(rob.get('best'))}, neighbours "
             f"median {_pct(rob.get('median'))}, min {_pct(rob.get('min'))}, {_pct(rob.get('share_above_threshold'), signed=False)} profitable over "
             f"{rob.get('n_neighbours')}. Deflated Sharpe {_f(dsr.get('dsr'))} ({dsr.get('n_trials')} rule trials in the last train window). "
             f"Monte Carlo (trade order, {mc.get('paths', '-')} paths over {mc.get('n_trades', '-')} trades): terminal growth p05 "
             f"{_f(mc.get('terminal_p05'))}x / p50 {_f(mc.get('terminal_p50'))}x / p95 {_f(mc.get('terminal_p95'))}x, P(loss) "
             f"{_pct(mc.get('prob_loss'), signed=False)}, max DD p50 {_pct(mc.get('max_dd_p50'), signed=False)} / p95 {_pct(mc.get('max_dd_p95'), signed=False)}.", "",
             f"Checks: {checks}. Evidence rule: {_rule_text(r)}. Holdout: {_holdout_cell(r)}.", ""]
    h = r.get("holdout")
    if h:
        lg, sh = (h.get("legs") or {}).get("long") or {}, (h.get("legs") or {}).get("short") or {}
        lines += [f"Holdout {h.get('span')}: return {_pct(h.get('total_return'))}, max DD {_pct(h.get('max_drawdown'), signed=False)}, "
                  f"PF {_f(h.get('profit_factor'))}, {int(_num(h.get('n_trades'), 0))} trades, time short {_pct(h.get('short_share'), signed=False, digits=0)}; "
                  f"long leg {int(lg.get('n_trades') or 0)} trades P&L {_pct(_num(lg.get('pnl'), 0) / 10_000)} (PF {_f(lg.get('profit_factor'))}), "
                  f"short leg {int(sh.get('n_trades') or 0)} trades P&L {_pct(_num(sh.get('pnl'), 0) / 10_000)} (PF {_f(sh.get('profit_factor'))}), "
                  f"funding {_pct(h.get('funding_total_pct'), digits=2)}.", ""]
    for note in r.get("notes") or []:
        lines.append(f"- {note}")
    return lines


def _ledger_section(entries: Sequence[Mapping[str, Any]]) -> List[str]:
    if not entries:
        return []
    out = ["", "### Every opening of the holdout (ledger)", "",
           "Each run that opened the holdout appends its openings to `docs/research/long_short_holdout_ledger.json`; earlier looks stay "
           "visible here even when a later run replaces the numbers above.", "",
           "| Run | Configuration | Return | Max DD | PF | Trades | Verdict |", "|---|---|---:|---:|---:|---:|---|"]
    notes = []
    for k, e in enumerate(entries, start=1):
        for o in e.get("openings") or []:
            verdict = "confirmed" if o.get("confirmed") else "contradicted"
            out.append(f"| {k} ({e.get('generated_at', '-')}) | {o.get('configuration')} | {_pct(o.get('total_return'))} | "
                       f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('profit_factor'))} | {int(_num(o.get('n_trades'), 0))} | {verdict} |")
        if e.get("note"):
            notes.append(f"- Run {k}: {e['note']}")
    if notes:
        out += [""] + notes
    return out


# -- the report -----------------------------------------------------------------------------------------

def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    cfg = meta.get("config") or {}
    pre = meta.get("preregistration") or {}
    results = _results(run)
    f = study_facts(run)
    series = run.get("series") or []
    spans = "; ".join(s.get("span", "") for s in series)
    hold = next((s.get("holdout_span") for s in series if s.get("holdout_span")), "-")
    lines: List[str] = [
        "# Phase 9 design study — long and short through perpetual swaps without leverage (walk-forward, SIMULATION ONLY)", "",
        f"Generated {meta.get('generated_at', '-')} by `scripts/run_long_short_study.py` (plan row R9; {meta.get('elapsed_minutes', '-')} min). "
        f"Data: PUBLIC OKX spot candles from the Parquet lake ({spans}); 6H bars resampled from 1H (UTC). Funding: {cfg.get('funding_source', '-')} "
        f"public funding history as the proxy for OKX's swaps. Perpetual-swap prices: OKX's public BTC-/ETH-USDT-SWAP candles (diagnostic). "
        f"Costs: spot fee {_pct(cfg.get('spot_fee'), signed=False, digits=2)}, swap fee {_pct(cfg.get('perp_fee'), signed=False, digits=2)}, "
        f"slippage {_pct(cfg.get('slippage'), signed=False, digits=2)} per side. Walk-forward: train {cfg.get('train_days')} d -> purge "
        f"{cfg.get('purge_days')} d -> test {cfg.get('test_days')} d, rule selected on the train slice by {cfg.get('select_by')} with >= "
        f"{cfg.get('min_trades')} trades; policy sizing `{cfg.get('policy_sizing')}` on both sides. Holdout: {hold}, opened only for "
        f"configurations meeting the walk-forward part of the evidence rule; every opening is in the ledger below.", "",
        "**Nothing here authorizes paper, demo or live trading, derivatives access or Phase 9.** Trading shorts and perpetual swaps is "
        "forbidden by the safety contract (`CLAUDE.md`, `PROJECT_RULES.md`); this is a paper study the owner asked for so that the Phase 9 "
        "decision rests on numbers. Every number is a simulation on historical public data.", "",
        "## Executive summary (plain English)", "",
        *executive_summary(run), "",
        "## Fixed before the first run", "",
        f"Pre-registration hash (with the configuration): `{meta.get('preregistration_sha256', '-')}`.", "",
    ]
    for key, value in pre.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"- **{key}**: " + "; ".join(str(v) for v in value))
        elif isinstance(value, dict):
            lines.append(f"- **{key}**: " + "; ".join(f"{k}: {v}" for k, v in value.items()))
        else:
            lines.append(f"- **{key}**: {value}")
    post = meta.get("post_hoc") or []
    if post:
        lines += ["", "Added after the pipeline smoke run (diagnostics only; no verdict depends on them):", ""]
        for p in post:
            lines.append(f"- {p.get('added')}: {p.get('what')} — {p.get('why')}")
    fixes = meta.get("review_fixes") or []
    if fixes:
        lines += ["", "Fixed after the first full run, from the independent code review (no gate, rule, configuration or parameter changed; "
                  "the first run's holdout openings are in the ledger below):", ""]
        for fx in fixes:
            lines.append(f"- {fx.get('what')} ({fx.get('effect')})")
    lines += ["", "Gates (unchanged from Sprint 2c): " + "; ".join(f"{k} {v}" for k, v in GATES.items()) + ".", ""]

    lines += ["## Reproduction of Sprint 2c", "",
              "Before anything long/short ran, each family's long-only rule went through the same long/short engine and walk-forward code "
              "and had to give Sprint 2c's stored walk-forward numbers (stored with 6 decimals) — otherwise the study stops.", "",
              "| Family | Series | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Largest difference | Agrees |",
              "|---|---|---|---|---|---:|---|---:|---|"]
    for s in series:
        for c in s.get("reproduction") or []:
            rep, sto = c.get("reproduced") or {}, c.get("stored") or {}
            lines.append(f"| {c['candidate']} | {c['instrument']} {c['timeframe']} | {_f(rep.get('total_return'), '{:.6f}')} / {_f(sto.get('total_return'), '{:.6f}')} | "
                         f"{_f(rep.get('sharpe'), '{:.6f}')} / {_f(sto.get('sharpe'), '{:.6f}')} | {_f(rep.get('max_drawdown'), '{:.6f}')} / "
                         f"{_f(sto.get('max_drawdown'), '{:.6f}')} | {c.get('n_trades')} / {c.get('n_trades_stored')} | {_yes(c.get('selected_matches'))} | "
                         f"{c.get('max_abs_difference_text', '-')} | {'yes' if c.get('ok') else '**NO**'} |")
    if not any(s.get("reproduction") for s in series):
        lines.append("| - | - | not run (quick mode) | - | - | - | - | - | - |")

    lines += ["", "## Summary (one row per family x series x design)", "",
              "Calmar = CAGR / max drawdown of the stitched out-of-sample curve. 'Long-only Calmar' is Sprint 2c's stored result for the same "
              "family and series. 'Funding' is the net funding received (+) or paid (-) over all test windows, in % of window capital. Rule: "
              "the walk-forward part of the pre-registered evidence rule.", ""]
    lines += _summary_table(results)
    lines += ["", "## Did the short side help? Long-only against the two designs", ""]
    lines += _comparison_table(results)
    for design, d in f["designs"].items():
        lines.append("")
        lines.append(f"- {DESIGN_LABEL.get(design, design)}: Calmar above long-only in {d['better_calmar']} of {d['with_ref']} pairs; 2022 better than "
                     f"long-only in {d['better_2022']} of {d['y22']} and positive in {d['positive_2022']}; short leg profitable in {d['short_pf_gt_1']} "
                     f"of {d['short_pf_known']} (BTC losing in {d['btc_short_losing']} of {d['btc_n']}, ETH winning in {d['eth_short_winning']} of "
                     f"{d['eth_n']}); median Calmar {_f(d['median_calmar'])} against {_f(d['median_long_only_calmar'])} long-only.")
    lines += ["", f"The hybrid design (long on spot) made more than the all-perp design in {f['hybrid_beats_perp']} of {f['n_pairs']} pairs.", ""]
    lines += ["## Where the money came from: the two legs", "",
              "P&L includes fees and funding, in % of window capital summed over the test windows (each window restarts at the same capital, "
              "so these are additive contributions, not compounded returns). 'Worst short excursion' is the largest move against a short "
              "while it was open; 'max leverage' is the largest position value / account equity at any bar close.", ""]
    lines += _legs_table(results)
    lines += ["", "## The untouched 12 months", ""]
    opened = [r for r in results if r.get("holdout")]
    if opened:
        lines += ["Known before it was opened (pre-registered): BTC fell about 26 % and ETH about 39 % over these months (Sprint 2c, R5b), so a "
                  "rule that can be short is expected to look better here than a long-only rule. A confirmation is weak evidence; a "
                  "contradiction is strong evidence.", "",
                  "| Family | Series | Design | Return | Max DD | PF | Trades | Time short | Long leg P&L (PF) | Short leg P&L (PF) | Verdict |",
                  "|---|---|---|---:|---:|---:|---:|---:|---|---|---|"]
        for r in opened:
            h = r["holdout"]
            lg, sh = (h.get("legs") or {}).get("long") or {}, (h.get("legs") or {}).get("short") or {}
            lines.append(f"| {r['candidate']} | {_series_label(r)} | {r['variant']} | {_pct(h.get('total_return'))} | {_pct(h.get('max_drawdown'), signed=False)} | "
                         f"{_f(h.get('profit_factor'))} | {int(_num(h.get('n_trades'), 0))} | {_pct(h.get('short_share'), signed=False, digits=0)} | "
                         f"{_pct(_num(lg.get('pnl'), 0) / 10_000)} ({_f(lg.get('profit_factor'))}) | {_pct(_num(sh.get('pnl'), 0) / 10_000)} "
                         f"({_f(sh.get('profit_factor'))}) | {'confirmed' if r.get('holdout_confirmed') else 'contradicted'} |")
    else:
        lines.append("No configuration met the walk-forward part of the evidence rule: the holdout stayed untouched.")
    lines += _ledger_section(meta.get("holdout_ledger") or [])
    lines += ["", "## The same rules with fixed default parameters (no selection), 2020-01-01 to the holdout start", "",
              "Each family's default parameters (fixed in Sprint 2, before any of these studies), no exit bracket, the policy sizing, one "
              "uninterrupted run per series. No parameter was chosen on these data, so this is the plain 'what if it had always run' view; "
              "the walk-forward above is the protocol's answer.", ""]
    lines += _defaults_table(run)
    lines += ["", f"With the short leg the Calmar was lower in {f['defaults_hybrid_lower_calmar']} of {f['defaults_n']} pairs, the short leg lost money in "
              f"{f['defaults_short_losing']} of {f['defaults_n']}, and 2022 was better than long-only in {f['defaults_better_2022']} of {f['defaults_n']}.", ""]
    if _majority(f["no_crash_worse"], f["no_crash_n"]):
        crash = ("halving shorts while the price is far below its peak protected them more than it cost — the sharp rebounds after a "
                 "crash are where shorts get hurt")
    elif _minority(f["no_crash_worse"], f["no_crash_n"]):
        crash = "the crash filter cost the shorts more than it protected them"
    else:
        crash = "the crash filter made no clear difference to the shorts"
    lines += ["## Diagnostics (never gates)", "",
              "- **Perp-priced**: the walk-forward's own per-window selections replayed with the swap leg(s) trading OKX's perpetual-swap "
              "candles (stops and targets on the swap's prices; signals from spot)."
              + (f" Largest Calmar change: {_f(f['perp_priced_max_calmar_change'])}." if f.get("perp_priced_max_calmar_change") is not None else ""),
              f"- **No crash filter on shorts** (post-hoc, see above): the same selections with the shorts sized by the policy minus its crash "
              f"filter. Calmar was lower in {f['no_crash_worse']} of {f['no_crash_n']} configurations: {crash}.",
              "- **Fixed rule / slippage / funding**: the most-selected rule replayed with fixed parameters over every test window (no "
              "re-selection, which is why its return differs from the walk-forward's), with slippage x2 and x3, and with funding switched off "
              "(x0) or doubled (x2).", ""]
    lines += _diagnostics_table(results)
    desc = run.get("descriptive") or {}
    lines += ["", "## Funding, 2020 to the holdout start", ""]
    lines += _funding_section(desc)
    lines += ["", "## What a short would have faced", ""]
    lines += _risk_section(desc)
    lines += ["", "## Per-configuration details", ""]
    for r in results:
        lines += _detail(r)
    lines += ["## Owner decisions (nothing below is decided by this report)", "",
              "- **Phase 9.** Read `docs/PHASE9_DESIGN_STUDY.md` (the design study with the safety rules and the review path). Phase 9 stays "
              "unauthorized; this report does not ask for it.",
              "- **Forward evidence.** Whether to run any long/short configuration forward as a paper-only account (public data, simulated "
              "fills, no derivatives access) is a new scope decision.", ""]
    change = f.get("perp_priced_max_calmar_change")
    if change is None:
        perp_note = "no perp-priced diagnostic was run"
    elif change < 0.10:
        perp_note = f"the perp-priced diagnostic moved no Calmar by more than {_f(change)}"
    else:
        perp_note = f"the perp-priced diagnostic moved a Calmar by up to {_f(change)}"
    lines += ["## Method notes and caveats", "",
              "- The long side of every configuration is Sprint 2c's long-only rule unchanged; shorts only use bars that rule spends flat. "
              "Every conflict falls on the short side: a short that the long side needs is closed at the open (`flip`), before that bar's "
              "stops are checked, so the long enters exactly where the long-only rule enters; a long that gives way to a short keeps the "
              "long-only stop-first rule, and if its stop fires in that bar the short starts one bar later. Without the drawdown ladder the "
              "long side's trades are the long-only engine's to the last price (tested); with it their size differs, because the ladder "
              "watches the combined equity.",
              "- The short rules are mirror images with the same parameters; nothing about them was tuned for shorting. S2 and S4 shorts are "
              "event states: when a breakdown happened while the long side held the bars and no cover event came since, the short starts "
              "as soon as the long side lets go, with the filters checked on that bar.",
              "- Funding comes from Binance's public history as a proxy; OKX's own funding has the same sign most of the time and a similar "
              "level where both exist (table above), but single settlements differ, and OKX settles more often (every 4, 2 or 1 hours) "
              "while a rate sits at its cap or floor. Funding is charged at the close of the bar it settles in, on that close; a stop that "
              "fires inside the bar may make one settlement too many or too few. The OKX-against-proxy comparison uses OKX's public history, "
              "which starts in July 2026 — inside the holdout window; it only calibrates the funding source, and no selection, gate or "
              "verdict uses it.",
              f"- Signals, stops and fills use spot candles for both legs in the main run (the swap tracks spot through funding); {perp_note}.",
              f"- The policy sizing (10 % vol target, crash filter, ladder) was fixed in Sprint 2b for longs and applied unchanged to shorts. "
              f"Positions stay small at this sizing (account leverage at most {_f(f['max_leverage'])}x), so the absolute returns are small too.",
              "- The liquidation tripwire models a 1x isolated short whose margin is its entry value; a gap above the liquidation price fills "
              "at the open, which books more than the margin (conservative; on the exchange an isolated position cannot lose more than its "
              "margin).",
              "- The deflated Sharpe counts the rule trials of the last train window only; the two designs and four families multiply the "
              "number of things tried.",
              "- The holdout's direction was known before it was opened (see above). Hybrid and all-perp versions of one rule share their "
              "signals: they are one rule, not two independent results. Every opening of the holdout is in the ledger above.",
              "- Every number is a simulation on historical public data and proves nothing about the future.", ""]
    return "\n".join(lines)
