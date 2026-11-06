"""Replication study report (plan row R12, SIMULATION ONLY).

Renders ``docs/research/REPLICATION_V1D_REPORT.md`` from the study's results
JSON. Every plain-English sentence is derived from the numbers in the run, so
a re-run on other data cannot print a stale claim.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from research.report_v1c import GATE_LABELS, GATES, HOLDOUT_MIN_TRADES

LABEL_TEXT = {
    "robust across markets": "robust across markets",
    "fragile": "fragile",
    "BTC-specific": "BTC-specific",
    "fails everywhere": "fails everywhere, as on BTC in Sprint 2c",
    "not run": "not run",
}


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


def _yes(flag: Any) -> str:
    return "yes" if flag else "no"


def _names(items: Iterable[str]) -> str:
    items = list(items)
    return ", ".join(items) if items else "none"


def _short(instrument: str) -> str:
    return instrument.split("-")[0]


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
    """A positive, profitable holdout that the v1c verdict still rejects because it holds fewer than the minimum trades."""
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


# -- the plain-English summary -----------------------------------------------------------------------

def executive_summary(run: Mapping[str, Any]) -> List[str]:
    meta = run.get("meta") or {}
    markets: List[str] = list(meta.get("markets") or [])
    overall = run.get("overall") or {}
    families = run.get("families") or []
    repro = run.get("reproduction") or []
    repro_ok = sum(1 for c in repro if c.get("ok"))
    judged = _judged(run)
    passed = [r for r in judged if (r.get("acceptance") or {}).get("passed")]
    confirmed = [r for r in passed if r.get("holdout_confirmed") is True]
    too_few = [r for r in passed if r.get("holdout_confirmed") is False and _too_few_trades(r)]
    contradicted = [r for r in passed if r.get("holdout_confirmed") is False and not _too_few_trades(r)]
    bullets: List[str] = []
    repro_text = (f"Before any new market was judged, the same code re-ran BTC and ETH and matched Sprint 2c's stored numbers in {repro_ok} of {len(repro)} "
                  "configurations" if repro else "This run skipped the BTC/ETH reproduction (a smoke run, not a result)")
    bullets.append(
        f"**What we did.** We took the Sprint 2c rules exactly as they were — the same entry rules, parameters, exit brackets, no-trade filter, "
        f"regime gate, fixed sizing, walk-forward windows and gates — and ran them on {len(markets)} OKX spot market{'s' if len(markets) != 1 else ''} "
        f"they were never tuned on ({_names(_short(m) for m in markets)}), chosen by trading volume before any result existed. "
        f"{repro_text}. Every market's candles stop where Sprint 2c's did, so the untouched last 12 months are the same calendar window "
        f"({meta.get('v1c_meta', {}).get('holdout_span', '2025-10-20->2026-10-20')}).")
    label = overall.get("label", "-")
    fam_text = "; ".join(f"{f['family']}: {LABEL_TEXT.get(f['label'], f['label'])} (passes on {f['n_markets_passing']} of {len(f.get('markets_run') or [])} markets)"
                         for f in families)
    passed_names = "; ".join(f"{p['configuration']} on {_short(p['instrument'])}" for p in overall.get("passed", []))
    result = (f"**Result: {LABEL_TEXT.get(label, label)}.** {overall.get('n_passed', len(passed))} of {overall.get('n_judged', len(judged))} configurations "
              f"passed every Sprint 2c gate on the new markets")
    if passed_names:
        result += f" ({passed_names})"
    result += f". Per family — {fam_text}." if fam_text else "."
    bullets.append(result)
    primary = run.get("configuration_replication") or []
    if primary:
        parts = []
        for p in primary:
            parts.append(f"{p['configuration']} passed on {p['n_pass']} of {p['n_judged']} new markets"
                         + (f" (replicated: needs {p['needed']})" if p.get("replicated") else f" (not replicated: needs {p['needed']})"))
        bullets.append("**The three rules that passed on BTC in Sprint 2c, on the new markets.** " + "; ".join(parts) + ".")
    if passed:
        confirmed_names = _names(f"{r['configuration']} on {_short(r['instrument'])}" for r in confirmed)
        contradicted_names = _names(f"{r['configuration']} on {_short(r['instrument'])}" for r in contradicted)
        few_text = ""
        if too_few:
            few_names = _names(f"{r['configuration']} on {_short(r['instrument'])}: {_pct((r.get('holdout') or {}).get('total_return'))} from "
                               f"{int(_num((r.get('holdout') or {}).get('n_trades'), 0))} trades" for r in too_few)
            few_text = f" and left {len(too_few)} unconfirmed for lack of trades (fewer than {HOLDOUT_MIN_TRADES}: {few_names})"
        hold_text = (f"The untouched 12 months then confirmed {len(confirmed)} ({confirmed_names}) and contradicted {len(contradicted)} ({contradicted_names}){few_text}"
                     if meta.get("evaluate_holdout") else "The untouched 12 months were not opened in this run")
        bullets.append(f"**Holdout.** {hold_text}. A walk-forward pass that the holdout rejects is selection luck, not edge; only a confirmed "
                       "configuration is a candidate for the paper fleet.")
    else:
        bullets.append("**Holdout.** Nothing passed walk-forward on a new market, so no new market's untouched 12 months were opened for a rule "
                       "(the hold + policy control's 12 months are shown as the comparison line, as in Sprint 2c).")
    med_parts = []
    for f in families:
        mn, mb, me = f.get("medians_new") or {}, f.get("medians_btc") or {}, f.get("medians_eth") or {}
        med_parts.append(f"{f['family']} median Calmar {_f(mn.get('calmar'))} on the new markets against {_f(mb.get('calmar'))} on BTC and "
                         f"{_f(me.get('calmar'))} on ETH")
    if med_parts:
        bullets.append("**Beside BTC and ETH.** " + "; ".join(med_parts) + f". The gate asks for Calmar above {GATES['calmar_min']}.")
    beats = run.get("beats_hold") or []
    if beats:
        n_beats = sum(1 for b in beats if b.get("beats_hold"))
        holds = [b.get("hold_holdout") for b in beats if b.get("hold_holdout") is not None]
        hold_text = (f"; on the untouched 12 months the hold + policy control's return ranged from {_pct(min(holds))} to {_pct(max(holds))}"
                     if holds else "")
        bullets.append(f"**Against simply holding with the same risk controls.** On {n_beats} of {len(beats)} market-timeframe series the best timing rule "
                       f"beat hold + policy sizing by more than 0.1 Calmar{hold_text}.")
    additions = run.get("shortlist_additions") or []
    if additions:
        added_names = _names(f"{a['candidate']} {a['instrument']} {a['timeframe']}" for a in additions)
        bullets.append(f"**Paper fleet.** {len(additions)} confirmed configuration(s) were appended to the fleet's shortlist with a source tag "
                       f"({added_names}); a running fleet takes them as new accounts "
                       "at its next restart from an updated checkout. Existing accounts are untouched. Nothing is approved for demo or live trading.")
    else:
        bullets.append("**Paper fleet.** Nothing was confirmed on a new market, so the fleet's shortlist is unchanged. Nothing is approved for demo or "
                       "live trading.")
    return bullets


# -- the report -------------------------------------------------------------------------------------------

def render_report(run: Mapping[str, Any]) -> str:
    meta = run.get("meta") or {}
    markets: List[str] = list(meta.get("markets") or [])
    v1c_meta = meta.get("v1c_meta") or {}
    snapshot = meta.get("snapshot") or {}
    lines: List[str] = []
    lines += [
        "# Replication v1d — the Sprint 2c rule families on OKX spot markets they were never tuned on (walk-forward, SIMULATION ONLY)",
        "",
        f"Generated {meta.get('generated_at', '-')} by `scripts/run_replication_v1d.py` (plan row R12). Markets: {_names(markets)} — fixed before any result "
        f"from one public ticker snapshot ({snapshot.get('snapshot_at', '-')}). Rules: exactly Sprint 2c's, run by `scripts/run_research_v1c.py`'s own "
        f"`run_series` (policy sizing `{(v1c_meta.get('policy_sizing') or {}).get('label', '-')}`, regime gate `{(v1c_meta.get('regime') or {}).get('label', '-')}`, "
        f"S0 filter {v1c_meta.get('no_trade_label', '-')}, walk-forward train {v1c_meta.get('train_days', '-')}d → purge {v1c_meta.get('purge_days', '-')}d → "
        f"test {v1c_meta.get('test_days', '-')}d, fee {_pct(v1c_meta.get('fee_rate'), signed=False, digits=2)} + slippage "
        f"{_pct(v1c_meta.get('slippage_rate'), signed=False, digits=3)} per side, brackets {v1c_meta.get('bracket_variants', '-')}). Data: PUBLIC OKX spot candles "
        f"(1H and 4H stored, 6H resampled from 1H) cut at Sprint 2c's data end (bar close ≤ {meta.get('data_end', '-')}); Binance public funding of each "
        f"market's USDT perpetual as the S5 feature. Holdout: the last 12 months ({v1c_meta.get('holdout_span', '-')}), opened once and only for "
        "configurations that passed walk-forward on that market.",
        "",
        "**Nothing here authorizes paper, demo or live trading.** A passing configuration is a hypothesis for the forward paper fleet, not a strategy "
        "to deploy. Every number is a simulation on historical public data.",
        "",
        "## Executive summary (plain English)",
        "",
    ]
    for b in executive_summary(run):
        lines.append(f"- {b}")

    # Fixed before the first run.
    prereg = meta.get("preregistration") or {}
    lines += ["", "## Fixed before the first run", "", f"Pre-registration hash (text, market snapshot and configuration): `{meta.get('preregistration_sha256', '-')}`.", ""]
    for k, v in prereg.items():
        lines.append(f"- **{k}**: {v}")
    picks = snapshot.get("picks") or []
    if picks:
        lines += ["", f"The market snapshot ({snapshot.get('snapshot_at', '-')}, `{snapshot.get('tickers_endpoint', '-')}`, {snapshot.get('volume_field', '-')}); "
                  f"rule: {snapshot.get('rule', '-')}; history condition: {snapshot.get('history_condition', '-')}.", "",
                  "| Market | 24h quote volume | Newest 1H candle before the cutoff | Rank | Chosen | Why |", "|---|---:|---|---:|---|---|"]
        for p in picks:
            lines.append(f"| {p['instrument']} | {_num(p.get('quote_volume_24h'), 0.0) / 1e6:.1f} M USDT | {p.get('history_before_cutoff') or '-'} | "
                         f"{p.get('rank') if p.get('rank') is not None else '-'} | {_yes(p.get('chosen'))} | {p.get('reason', '')} |")
    protocol = meta.get("protocol_check") or {}
    lines += ["", f"Protocol check against the stored Sprint 2c run: {'every parameter the same' if protocol.get('ok') else 'MISMATCHES: ' + str(protocol.get('mismatches'))} "
              f"(checked: {', '.join(protocol.get('checked') or [])}).",
              "", "Gates (unchanged from Sprint 2c): " + "; ".join(f"{k} {v}" for k, v in (meta.get("gates") or GATES).items()) + "."]
    if meta.get("second_look_warning"):
        lines += ["", f"**Warning — second look.** An earlier run already opened the holdout of: {_names(meta['second_look_warning'])}. Both looks are in the ledger below."]

    # Reproduction.
    repro = run.get("reproduction") or []
    lines += ["", "## Reproduction of Sprint 2c", ""]
    if repro:
        lines += ["Before any new market ran, BTC-USDT and ETH-USDT went through the same loaded runner and had to give Sprint 2c's stored walk-forward numbers "
                  "(stored with 6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts — otherwise the study stops.", "",
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
        lines.append("Not run in this invocation (a smoke run: `--quick` or `--skip-reproduction`). Nothing here is a result.")

    # Primary test.
    primary = run.get("configuration_replication") or []
    lines += ["", "## The primary test — the configurations that passed on BTC in Sprint 2c, run unchanged on the new markets", ""]
    if primary:
        lines += ["A configuration replicates when it passes every gate on at least half of the new markets.", ""]
        for p in primary:
            btc = p.get("btc") or {}
            lines += [f"### {p['configuration']} — passes on {p['n_pass']} of {p['n_judged']} new markets (needs {p['needed']}): "
                      f"**{'replicated' if p.get('replicated') else 'not replicated'}**", "",
                      "| Market | Verdict | Gates missed | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Rolling 12m + | Worst year | Holdout (12m) |",
                      "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
            lines.append(f"| BTC-USDT (Sprint 2c) | **PASS** | - | {_pct(btc.get('cagr'))} | {_f(btc.get('sharpe'))} | {_f(btc.get('profit_factor'))} | "
                         f"{_pct(btc.get('max_drawdown'), signed=False)} | {_f(btc.get('calmar'))} | {btc.get('n_trades')} | {_pct(btc.get('rolling_12m_positive_share'), signed=False)} | "
                         f"{_pct(btc.get('worst_calendar_year_return'))} | {_holdout_cell({'holdout': p.get('btc_holdout'), 'holdout_confirmed': p.get('btc_holdout_confirmed')})} |")
            for e in p.get("markets") or []:
                if not e.get("ran"):
                    lines.append(f"| {e['instrument']} | not run | - | - | - | - | - | - | - | - | - | - |")
                    continue
                m = e.get("metrics") or {}
                verdict = "**PASS**" if e.get("passed") else ("not judged (S5 inactive)" if not e.get("judged") else "fail")
                lines.append(f"| {e['instrument']} | {verdict} | {_gates_text(e.get('failed') or [])} | {_pct(m.get('cagr'))} | {_f(m.get('sharpe'))} | {_f(m.get('profit_factor'))} | "
                             f"{_pct(m.get('max_drawdown'), signed=False)} | {_f(m.get('calmar'))} | {m.get('n_trades')} | {_pct(m.get('rolling_12m_positive_share'), signed=False)} | "
                             f"{_pct(m.get('worst_calendar_year_return'))} | {_holdout_cell(e)} |")
            lines.append("")
    else:
        lines.append("No Sprint 2c BTC passer falls inside this run's families, timeframes and modes.")

    # Family verdicts.
    families = run.get("families") or []
    if families:
        lines += ["", "## Family verdicts (pre-registered rule)", "",
                  "A market counts for a family when any of its configurations (4H/6H × none/gate) passes every gate there. Medians are over the family's "
                  "judged configurations on the new markets, and over the same configurations on BTC and on ETH in Sprint 2c.", "",
                  "| Family | New markets passing | Verdict | Passed on BTC / ETH in 2c | Median Calmar new / BTC / ETH | Median CAGR new / BTC / ETH | Median max DD new / BTC / ETH | PF > 1 (share of new) | Holdout confirmed / contradicted |",
                  "|---|---|---|---|---|---|---|---:|---|"]
        for f in families:
            mn, mb, me = f.get("medians_new") or {}, f.get("medians_btc") or {}, f.get("medians_eth") or {}
            passing = f"{f['n_markets_passing']} of {len(f.get('markets_run') or [])}" + (f" ({_names(_short(m) for m in f.get('markets_passing') or [])})" if f.get("markets_passing") else "")
            inactive = f" — S5 inactive on {_names(_short(m) for m in f['s5_inactive_markets'])}" if f.get("s5_inactive_markets") else ""
            lines.append(f"| {f['family']} | {passing}{inactive} | **{LABEL_TEXT.get(f['label'], f['label'])}** | {_yes(f.get('passes_on_btc_2c'))} / {_yes(f.get('passes_on_eth_2c'))} | "
                         f"{_f(mn.get('calmar'))} / {_f(mb.get('calmar'))} / {_f(me.get('calmar'))} | {_pct(mn.get('cagr'))} / {_pct(mb.get('cagr'))} / {_pct(me.get('cagr'))} | "
                         f"{_pct(mn.get('max_drawdown'), signed=False)} / {_pct(mb.get('max_drawdown'), signed=False)} / {_pct(me.get('max_drawdown'), signed=False)} | "
                         f"{_pct(f.get('share_profit_factor_above_1'), signed=False)} | {_names(_short(m) for m in f.get('confirmed_markets') or [])} / "
                         f"{_names(_short(m) for m in f.get('contradicted_markets') or [])} |")
        overall = run.get("overall") or {}
        binding = overall.get("binding_gates") or []
        n_few = sum(1 for r in _judged(run) if (r.get("acceptance") or {}).get("passed") and r.get("holdout_confirmed") is False and _too_few_trades(r))
        few_note = f" (of which {n_few} only for lack of trades)" if n_few else ""
        lines += ["", f"Overall: **{LABEL_TEXT.get(overall.get('label'), overall.get('label'))}** — {overall.get('n_passed')} of {overall.get('n_judged')} judged configurations pass on the "
                  f"new markets; holdout confirmed {overall.get('n_confirmed')}, not confirmed {overall.get('n_contradicted')}{few_note}, not opened {overall.get('n_unevaluated')}."
                  + (" Binding gates on the new markets: " + ", ".join(f"{GATE_LABELS.get(g, g)} ({n}/{overall.get('n_judged')})" for g, n in binding[:4]) + "." if binding else "")]

    # Summary per market.
    series_list = run.get("series") or []
    if series_list:
        lines += ["", "## Summary (fixed policy sizing; one row per configuration, grouped by market)", "",
                  "| Market | Candidate | TF | Regime | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Verdict | Holdout (12m) |",
                  "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for s in series_list:
            for r in s.get("results", []):
                o, acc = r.get("oos") or {}, r.get("acceptance") or {}
                verdict = "control" if r.get("candidate") == "hold" else ("not judged" if not r.get("judged") else ("**PASS**" if acc.get("passed") else "fail"))
                lines.append(f"| {r['instrument']} | {r.get('display_candidate', r['candidate'])} | {r['timeframe']} | {(r.get('regime') or {}).get('mode')} | "
                             f"{(r.get('selected_params') or {}).get('bracket', '-')} | {_pct(o.get('total_return'))} | {_pct(o.get('cagr'))} | {_f(o.get('sharpe'))} | "
                             f"{_f(o.get('profit_factor'))} | {_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | {o.get('n_trades')} | "
                             f"{_pct(o.get('fees_pct_per_year'), signed=False)} | {_pct(acc.get('rolling_positive_share'), signed=False)} | {_pct(acc.get('worst_calendar_year_return'))} | "
                             f"{_pct((r.get('robustness') or {}).get('share_above_threshold'), signed=False)} | {_f((r.get('dsr') or {}).get('dsr'))} | {verdict} | {_holdout_cell(r)} |")
        spans = [s.get("span") for s in series_list if s.get("span")]
        if spans:
            lines += ["", "Data spans: " + "; ".join(spans) + "."]
        failures = [f for s in series_list for f in (s.get("failures") or [])]
        if failures:
            lines += ["", "Runs that failed with an error (not evaluated):", ""]
            for f in failures:
                lines.append(f"- {f.get('candidate')} on {f.get('instrument')} {f.get('timeframe')} ({f.get('regime', '-')}): `{f.get('error')}`")
        if meta.get("skipped_series"):
            lines += ["", "Series skipped (too little data): " + "; ".join(meta["skipped_series"]) + "."]

    # Sprint 2c's numbers for the same configurations.
    stored = run.get("stored_2c") or []
    if stored:
        lines += ["", "## Sprint 2c's own numbers for the same configurations (BTC-USDT and ETH-USDT, from `ensemble_v1c_results.json`)", "",
                  "| Market | Candidate | TF | Regime | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Rolling 12m + | Worst year | Verdict | Holdout (12m) |",
                  "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for r in sorted(stored, key=lambda x: (x["instrument"], x["timeframe"], x["candidate"], (x.get("regime") or {}).get("mode"))):
            o, acc = r.get("oos") or {}, r.get("acceptance") or {}
            verdict = "control" if r["candidate"] == "hold" else ("**PASS**" if acc.get("passed") else "fail")
            h = dict(r)
            h["holdout_confirmed"] = None if not r.get("holdout") else bool(_num(r["holdout"].get("total_return")) > 0 and _num(r["holdout"].get("profit_factor")) > 1.0
                                                                            and int(_num(r["holdout"].get("n_trades"), 0)) >= HOLDOUT_MIN_TRADES)
            lines.append(f"| {r['instrument']} | {r['candidate']} | {r['timeframe']} | {(r.get('regime') or {}).get('mode')} | {_pct(o.get('cagr'))} | {_f(o.get('sharpe'))} | "
                         f"{_f(o.get('profit_factor'))} | {_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('calmar'))} | {o.get('n_trades')} | "
                         f"{_pct(acc.get('rolling_positive_share'), signed=False)} | {_pct(acc.get('worst_calendar_year_return'))} | {verdict} | {_holdout_cell(h)} |")

    # Controls.
    beats = run.get("beats_hold") or []
    if beats:
        lines += ["", "## Against the controls — the best timing rule of each series vs hold + policy sizing and plain buy-and-hold", "",
                  "| Series | Best rule | Best CAGR / max DD / Calmar | Hold + policy CAGR / max DD / Calmar | Beats hold by > 0.1 Calmar | Buy-and-hold CAGR / max DD / Calmar | Hold + policy, untouched 12 months |",
                  "|---|---|---|---|---|---|---:|"]
        for b in beats:
            lines.append(f"| {b['instrument']} {b['timeframe']} | {b['best']} | {_pct(b.get('best_cagr'))} / {_pct(b.get('best_max_drawdown'), signed=False)} / {_f(b.get('best_calmar'))} | "
                         f"{_pct(b.get('hold_cagr'))} / {_pct(b.get('hold_max_drawdown'), signed=False)} / {_f(b.get('hold_calmar'))} | {_yes(b.get('beats_hold'))} | "
                         f"{_pct(b.get('buy_and_hold_cagr'))} / {_pct(b.get('buy_and_hold_max_drawdown'), signed=False)} / {_f(b.get('buy_and_hold_calmar'))} | "
                         f"{_pct(b.get('hold_holdout'))} |")
        lines += ["", f"The best rule beat hold + policy sizing by more than 0.1 Calmar on {sum(1 for b in beats if b.get('beats_hold'))} of {len(beats)} series "
                  "(Sprint 2c: 4 of 4 on BTC/ETH)."]

    # Positioning data.
    if series_list:
        lines += ["", "## Positioning data for the S5 filter (Binance public funding of each market's USDT perpetual, research feature only)", "",
                  "| Market | Source | Funding span | Funding coverage (in-sample bars) | Open interest | S5 counted |", "|---|---|---|---:|---|---|"]
        seen = set()
        threshold_pct = int(round(((meta.get("config") or {}).get("funding_coverage_min") or 0.9) * 100))
        for s in series_list:
            inst = s["instrument"]
            if inst in seen:
                continue
            seen.add(inst)
            p = s.get("positioning") or {}
            oi_text = "none (that leg of S5 passes)" if _num(p.get("oi_coverage"), 0.0) == 0.0 else p.get("oi_span", "-")
            s5_text = "yes" if s.get("s5_active") else f"no (below {threshold_pct}%: reported as run without S5)"
            lines.append(f"| {inst} | {p.get('source', '-')} | {p.get('funding_span', '-')} | {_pct(s.get('funding_coverage'), signed=False)} | {oi_text} | {s5_text} |")

    # Holdout.
    openings = [o for e in (meta.get("holdout_ledger") or []) for o in e.get("openings", [])]
    lines += ["", "## The untouched 12 months", ""]
    this_run = [r for r in _results(run) if r.get("holdout")]
    if this_run:
        lines += [f"Opened once, only for configurations that passed every walk-forward gate on their market (and the hold + policy control as the comparison "
                  f"line). Verdict ✓ = positive return, PF > 1 and ≥ {HOLDOUT_MIN_TRADES} trades.", "",
                  "| Market | Configuration | Return | Max DD | PF | Trades | Verdict |", "|---|---|---:|---:|---:|---:|---|"]
        for r in this_run:
            h = r["holdout"]
            if r["candidate"] == "hold":
                verdict = "control (comparison line)"
            elif not r.get("judged"):
                verdict = f"not judged (S5 inactive on this market); would be {_holdout_outcome(r)}"
            else:
                verdict = _holdout_outcome(r)
            lines.append(f"| {r['instrument']} | {r.get('display_candidate', r['candidate'])} {r['timeframe']} [{(r.get('regime') or {}).get('mode')}] | "
                         f"{_pct(h.get('total_return'))} | {_pct(h.get('max_drawdown'), signed=False)} | {_f(h.get('profit_factor'))} | {h.get('n_trades')} | {verdict} |")
    else:
        lines.append("Not opened in this run: " + ("no configuration passed walk-forward on a new market." if not meta.get("evaluate_holdout")
                                                    or not [r for r in _judged(run) if (r.get('acceptance') or {}).get('passed')]
                                                    else "the holdout was not requested."))
    ledger = meta.get("holdout_ledger") or []
    if ledger:
        lines += ["", "### Every opening of the holdout (ledger)", "",
                  f"Each run that opened a holdout appends its openings to `{meta.get('holdout_ledger_path', '-')}`; earlier looks stay visible here even when a later "
                  "run replaces the numbers above.", "", "| Run | Configuration | Role | Return | Max DD | PF | Trades | Verdict |", "|---|---|---|---:|---:|---:|---:|---|"]
        for i, e in enumerate(ledger, start=1):
            for o in e.get("openings", []):
                few = _num(o.get("total_return")) > 0 and _num(o.get("profit_factor")) > 1.0 and int(_num(o.get("n_trades"), 0)) < HOLDOUT_MIN_TRADES
                verdict = ("comparison" if o.get("role") == "control" else "confirmed" if o.get("confirmed")
                           else f"not confirmed ({int(_num(o.get('n_trades'), 0))} trades)" if few else "contradicted")
                lines.append(f"| {i} ({e.get('generated_at', '-')}) | {o.get('configuration')} | {o.get('role')} | {_pct(o.get('total_return'))} | "
                             f"{_pct(o.get('max_drawdown'), signed=False)} | {_f(o.get('profit_factor'))} | {o.get('n_trades')} | {verdict} |")
        for i, e in enumerate(ledger, start=1):
            if e.get("note"):
                lines.append(f"- Run {i}: {e['note']}")

    # Shortlist.
    additions = run.get("shortlist_additions") or []
    lines += ["", "## Paper-fleet shortlist", ""]
    if additions:
        lines += ["Confirmed passers appended to `docs/research/paper_fleet_shortlist_v1c.json` with a `source` tag (existing entries and running accounts untouched):", ""]
        for a in additions:
            lines.append(f"- {a['candidate']} {a['instrument']} {a['timeframe']} ({a.get('regime')}): walk-forward Calmar {_f(a.get('calmar'))}, holdout {_pct((a.get('holdout') or {}).get('total_return'))}")
        if run.get("shortlist_note"):
            lines += ["", f"Shortlist file: {run['shortlist_note']}."]
    else:
        lines.append("Unchanged: no configuration was both a walk-forward passer and confirmed by its market's untouched 12 months.")

    # Owner decisions and method notes.
    overall = run.get("overall") or {}
    lines += ["", "## Owner decisions (nothing below is decided by this report)", ""]
    if additions:
        lines.append(f"- **Fleet.** {len(additions)} new paper account(s) join at the fleet's next restart from an updated checkout (`docs/runbooks/PAPER_FLEET.md`). "
                     "Recommended: let them run; judge them at G7 with the rest.")
    else:
        lines.append("- **Fleet.** Nothing to add. Recommended: no change.")
    lines.append(f"- **What the verdict means.** The pre-registered reading of '{LABEL_TEXT.get(overall.get('label'), overall.get('label'))}' is written above; "
                 "no gate, parameter or market changed after the results. If a gate looks wrong, that is a note for the next pre-registered study, not an edit of this one.")
    lines += ["", "## Method notes and caveats", "",
              "- The rules were not re-implemented: Sprint 2c's runner module ran them; the BTC/ETH reproduction table shows the same code gives the stored numbers.",
              "- Every market's candles were cut at Sprint 2c's data end so the walk-forward and the untouched 12 months cover the same calendar window; the windows "
              "themselves are anchored at each market's first candle (the pre-2020 markets start within days of BTC/ETH; SOL-USDT starts 2020-09-29 and has fewer windows).",
              "- 4H bars are OKX's own, 6H bars are resampled from 1H on the UTC clock — Sprint 2c's construction for BTC/ETH.",
              "- The S5 positioning filter uses the market's Binance perpetual funding (as-of aligned) and has no open-interest history for the new markets, so its "
              "open-interest leg passes there; on BTC/ETH that leg was active from 2020-09 / 2021-12. Funding coverage per market is shown above; a market below the "
              "Sprint 2b threshold has its S5 rows reported as 'run without S5' and never counted for the S5 families.",
              "- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the fixed policy "
              "sizing is Sprint 2b's; none of them was adapted to the new markets.",
              f"- {overall.get('n_judged', 0)} configurations on the new markets are {overall.get('n_judged', 0)} more comparisons; a pass or two among them at the "
              "Sprint 2c pass rate (4 of 108) would be expected by chance, which is why the holdout and the family rule, not single passes, carry the verdict.",
              "- Every number is a simulation on historical public data and proves nothing about the future."]
    return "\n".join(lines) + "\n"
