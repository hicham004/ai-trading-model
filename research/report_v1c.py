"""Sprint 2c report: v1c gates (rolling-12-month yearly gate), paper-fleet shortlist file, summary, Markdown.

Gates (master plan Sprint 2b item 8 + planner decision 1, applied to the
stitched out-of-sample curve at the FIXED POLICY sizing — planner decision 2):

- profit factor > 1.2 after costs;
- max drawdown < 20 %;
- Sharpe > 0.7; Calmar > 0.5;
- rolling 12-month windows ≥ 75 % positive AND no calendar year worse than −10 %;
- ≥ 30 out-of-sample trades;
- ≥ 50 % of ±30 % parameter neighbours profitable (replayed with the same gate and sizing);
- deflated Sharpe reported (no threshold).

The shortlist file is machine-readable and labelled "forward evidence only;
nothing approved" (Sprint 2c item 7). Every number is a simulation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

GATES = {
    "profit_factor_min": 1.2,
    "max_drawdown_max": 0.20,
    "sharpe_min": 0.7,
    "calmar_min": 0.5,
    "rolling_12m_positive_min": 0.75,
    "worst_calendar_year_min": -0.10,
    "min_trades": 30,
    "robust_share_min": 0.5,
    "min_year_days": 60,  # calendar years shorter than this (stubs) are not judged
}
REFERENCE_CANDIDATES = ("hold",)
SHORTLIST_STATUS = "forward evidence only; nothing approved"
GATE_LABELS = {
    "pf_gt_1_2": "profit factor above 1.2",
    "max_dd_lt_20pct": "max drawdown under 20%",
    "sharpe_gt_0_7": "Sharpe above 0.7",
    "calmar_gt_0_5": "Calmar above 0.5",
    "rolling_12m_75pct_positive": "75% of rolling 12-month windows positive",
    "no_calendar_year_below_minus_10pct": "no calendar year worse than -10%",
    "enough_trades": "at least 30 trades",
    "robust_pm30pct": "robust to ±30% parameter changes",
}


# -- formatting helpers -----------------------------------------------------------

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


# -- the yearly gate v2 -----------------------------------------------------------

def rolling_12m_returns(equity: pd.Series, *, step_days: int = 30) -> pd.Series:
    """Trailing 12-month returns of ``equity`` sampled every ``step_days`` days (first sample one year in)."""
    if equity.empty:
        return pd.Series(dtype=float)
    eq = equity.astype(float).sort_index()
    start = eq.index[0]
    year = pd.Timedelta(days=365.25)
    samples = []
    t = start + year
    end = eq.index[-1]
    while t <= end:
        samples.append(t)
        t = t + pd.Timedelta(days=int(step_days))
    if not samples:
        return pd.Series(dtype=float)
    now_vals = eq.reindex(pd.DatetimeIndex(samples), method="ffill")
    prev_vals = eq.reindex(pd.DatetimeIndex([s - year for s in samples]), method="ffill")
    out = pd.Series(now_vals.to_numpy(dtype=float) / prev_vals.to_numpy(dtype=float) - 1.0, index=pd.DatetimeIndex(samples))
    return out.dropna()


def calendar_year_returns(equity: pd.Series, *, min_days: int = GATES["min_year_days"]) -> Dict[int, float]:
    """Calendar-year returns of ``equity`` for years spanning at least ``min_days`` of data (stubs excluded)."""
    if equity.empty:
        return {}
    eq = equity.astype(float).sort_index()
    out: Dict[int, float] = {}
    prev_last = float(eq.iloc[0])
    for year, group in eq.groupby(eq.index.year):
        span_days = (group.index[-1] - group.index[0]).total_seconds() / 86_400.0
        last = float(group.iloc[-1])
        if span_days >= min_days:
            out[int(year)] = last / prev_last - 1.0
        prev_last = last
    return out


def yearly_gate_v2(equity: pd.Series) -> Dict[str, Any]:
    rolling = rolling_12m_returns(equity)
    years = calendar_year_returns(equity)
    share = float((rolling > 0).mean()) if len(rolling) else 0.0
    worst = min(years.values()) if years else float("nan")
    return {
        "rolling_windows": int(len(rolling)),
        "rolling_positive_share": share,
        "rolling_min": float(rolling.min()) if len(rolling) else float("nan"),
        "rolling_median": float(rolling.median()) if len(rolling) else float("nan"),
        "calendar_years": {int(k): float(v) for k, v in years.items()},
        "worst_calendar_year": None if not years else int(min(years, key=years.get)),
        "worst_calendar_year_return": worst,
    }


def acceptance_check_v1c(oos: Mapping[str, Any], yearly: Mapping[str, Any], robust: Mapping[str, Any]) -> Dict[str, Any]:
    """Sprint 2c gates. ``yearly`` is :func:`yearly_gate_v2`'s output."""
    worst = yearly.get("worst_calendar_year_return")
    worst_ok = worst is not None and not (isinstance(worst, float) and math.isnan(worst)) and worst >= GATES["worst_calendar_year_min"]
    checks = {
        "pf_gt_1_2": bool(_num(oos.get("profit_factor")) > GATES["profit_factor_min"]),
        "max_dd_lt_20pct": bool(_num(oos.get("max_drawdown"), 1.0) < GATES["max_drawdown_max"]),
        "sharpe_gt_0_7": bool(_num(oos.get("sharpe")) > GATES["sharpe_min"]),
        "calmar_gt_0_5": bool(_num(oos.get("calmar")) > GATES["calmar_min"]),
        "rolling_12m_75pct_positive": bool(int(_num(yearly.get("rolling_windows"))) >= 4 and _num(yearly.get("rolling_positive_share")) >= GATES["rolling_12m_positive_min"]),
        "no_calendar_year_below_minus_10pct": bool(worst_ok),
        "enough_trades": bool(int(_num(oos.get("n_trades"))) >= GATES["min_trades"]),
        "robust_pm30pct": bool(_num(robust.get("share_above_threshold")) >= GATES["robust_share_min"]),
    }
    checks["passed"] = all(checks.values())
    checks["failed"] = [k for k, v in checks.items() if isinstance(v, bool) and not v and k != "passed"]
    checks["rolling_positive_share"] = _num(yearly.get("rolling_positive_share"))
    checks["worst_calendar_year_return"] = None if worst is None else _num(worst)
    return checks


# -- holdout verdict ---------------------------------------------------------------

HOLDOUT_MIN_TRADES = 10


def holdout_verdict(r: Mapping[str, Any]) -> Optional[bool]:
    """True = the untouched holdout confirmed the walk-forward result (positive return, PF > 1, enough trades);
    False = it contradicted it; None = not evaluated."""
    h = r.get("holdout")
    if not h:
        return None
    return bool(_num(h.get("total_return")) > 0 and _num(h.get("profit_factor")) > 1.0 and int(_num(h.get("n_trades"))) >= HOLDOUT_MIN_TRADES)


def _rank_class(passed: bool, verdict: Optional[bool]) -> int:
    if passed and verdict is True:
        return 0
    if passed and verdict is None:
        return 1
    if passed:
        return 2
    return 3


# -- shortlist ----------------------------------------------------------------------

def _row(r: Mapping[str, Any]) -> Dict[str, Any]:
    oos = r.get("oos") or {}
    acc = r.get("acceptance") or {}
    return {
        "holdout": r.get("holdout"), "holdout_confirmed": holdout_verdict(r),
        "candidate": r["candidate"], "instrument": r["instrument"], "timeframe": r["timeframe"],
        "regime": (r.get("regime") or {}).get("label", "no regime gate"), "regime_config": r.get("regime"),
        "sizing": (r.get("policy_sizing") or {}).get("label", "-"), "sizing_config": r.get("policy_sizing"),
        "bracket": (r.get("selected_params") or {}).get("bracket", "-"), "params": r.get("selected_params"),
        "cagr": _num(oos.get("cagr")), "sharpe": _num(oos.get("sharpe")), "calmar": _num(oos.get("calmar")),
        "max_drawdown": _num(oos.get("max_drawdown"), 1.0), "profit_factor": _num(oos.get("profit_factor")),
        "n_trades": int(_num(oos.get("n_trades"))), "fees_pct_per_year": _num(oos.get("fees_pct_per_year")),
        "rolling_12m_positive_share": _num(acc.get("rolling_positive_share")),
        "worst_calendar_year_return": acc.get("worst_calendar_year_return"),
        "passed": bool(acc.get("passed")), "failed_gates": list(acc.get("failed", [])),
        "dsr": _num((r.get("dsr") or {}).get("dsr")),
    }


def shortlist(results: Sequence[Mapping[str, Any]], *, n: int = 10) -> List[Dict[str, Any]]:
    """Rank configurations for the paper fleet: passed first, then Calmar, then Sharpe (PF > 1 and ≥ 30 trades required)."""
    rows = []
    for r in results:
        if r.get("candidate") in REFERENCE_CANDIDATES:
            continue
        oos = r.get("oos") or {}
        if _num(oos.get("profit_factor")) <= 1.0 or int(_num(oos.get("n_trades"))) < GATES["min_trades"]:
            continue
        rows.append(_row(r))
    rows.sort(key=lambda x: (_rank_class(x["passed"], x["holdout_confirmed"]), -x["calmar"], -x["sharpe"]))
    for i, row in enumerate(rows[:n], start=1):
        row["rank"] = i
    return rows[:n]


def controls(results: Sequence[Mapping[str, Any]], benchmark: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Planner decision 6: hold + policy sizing on BTC and ETH, and plain buy-and-hold."""
    out: List[Dict[str, Any]] = []
    for r in results:
        if r.get("candidate") in REFERENCE_CANDIDATES:
            row = _row(r)
            row["role"] = "control: always-long with policy sizing" + (" and regime gate" if (r.get("regime") or {}).get("mode", "none") != "none" else "")
            out.append(row)
    for b in benchmark:
        out.append({"role": "control: plain buy-and-hold (all-in, after costs)", "candidate": "buy_and_hold", "instrument": b["instrument"],
                    "timeframe": b["timeframe"], "cagr": _num(b.get("cagr")), "sharpe": _num(b.get("sharpe")), "calmar": _num(b.get("calmar")),
                    "max_drawdown": _num(b.get("max_drawdown"), 1.0), "total_return": _num(b.get("total_return"))})
    return out


def write_shortlist_file(path: Path, run: Mapping[str, Any]) -> None:
    payload = {
        "status": SHORTLIST_STATUS,
        "generated_at": run["meta"].get("generated_at"),
        "source_report": run["meta"].get("report_path"),
        "gates": GATES,
        "sizing_proposal": run["meta"].get("policy_sizing"),
        "note": ("Configurations ranked by the Sprint 2c gates at the fixed policy sizing; the paper fleet (Sprint 5) runs them forward on "
                 "live public data next to the controls. Nothing here is approved for demo or live trading."),
        "configurations": run.get("shortlist", []),
        "controls": run.get("controls", []),
    }
    Path(path).write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return str(value)


# -- executive summary ------------------------------------------------------------

def _gate_failure_counts(results: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in results:
        if r.get("candidate") in REFERENCE_CANDIDATES:
            continue
        for gate in (r.get("acceptance") or {}).get("failed", []):
            counts[gate] = counts.get(gate, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _bh_for(run: Mapping[str, Any], instrument: str, timeframe: str) -> Optional[Mapping[str, Any]]:
    for b in run.get("benchmark", []):
        if b.get("instrument") == instrument and b.get("timeframe") == timeframe:
            return b
    return None


def _median(values: Sequence[Optional[float]]) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v)))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def executive_summary(run: Mapping[str, Any]) -> List[str]:
    """Five plain-English bullets for a non-technical owner, generated from the numbers."""
    results = [r for r in run.get("results", []) if r.get("candidate") not in REFERENCE_CANDIDATES]
    meta = run.get("meta", {})
    passed = [r for r in results if (r.get("acceptance") or {}).get("passed")]
    top = shortlist(results, n=3)
    study = run.get("regime_study") or {}
    bullets: List[str] = []

    modes = sorted({(r.get("regime") or {}).get("mode", "none") for r in results})
    bullets.append(
        f"**What we did.** We kept every entry rule from Sprint 2 exactly as it was and changed only when it is allowed to trade and how "
        f"much: a market-regime model (a 3-state hidden Markov model on returns and volatility, fitted only on past data inside every "
        f"walk-forward window) either blocks new entries in the bear state or shrinks them to a quarter size; a scheduled-event filter "
        f"(FOMC days) and the no-trade filter block entries around shocks; sizing is one fixed, pre-declared policy "
        f"(`{(meta.get('policy_sizing') or {}).get('label', '')}`); lower-turnover clocks (weekly, daily-entry, hysteresis) cut fees; "
        f"the positioning filter was re-tested with a 7–14-day funding window; and the sleeves were also sized jointly as one portfolio "
        f"against a 15 % drawdown budget. {len(results)} configurations ({', '.join(modes)}) over {meta.get('data_span_short', 'the stored history')}, "
        f"after fees and slippage; the last 12 months stayed untouched except for configurations that passed."
    )

    if passed:
        confirmed = [r for r in passed if holdout_verdict(r) is True]
        contradicted = [r for r in passed if holdout_verdict(r) is False]

        def _name(r):
            return f"{r['candidate']} on {r['instrument']} {r['timeframe']} ({(r.get('regime') or {}).get('label', '')})"

        def _hold(r):
            h = r.get("holdout") or {}
            return f"{_name(r)}: {_pct(h.get('total_return'))}, PF {_f(h.get('profit_factor'))}, {h.get('n_trades')} trades"

        text = f"**Result.** {len(passed)} of {len(results)} configurations passed every Sprint 2c gate on the walk-forward at the fixed policy sizing: {', '.join(_name(r) for r in passed[:4])}. "
        if confirmed or contradicted:
            text += (f"The untouched 12-month holdout then confirmed {len(confirmed)} of them ({'; '.join(_hold(r) for r in confirmed) or 'none'}) and "
                     f"contradicted {len(contradicted)} ({'; '.join(_hold(r) for r in contradicted) or 'none'}). ")
            text += ("Only the confirmed configurations are candidates for the forward paper fleet; a walk-forward pass that the holdout rejects is treated "
                     "as selection luck among 108 configurations, not as edge.")
        else:
            text += "The holdout was not evaluated in this run; these are hypotheses for the forward paper fleet, not strategies to deploy."
        bullets.append(text)
    else:
        counts = _gate_failure_counts(results)
        worst = ", ".join(f"{GATE_LABELS.get(k, k)} ({v} of {len(results)})" for k, v in list(counts.items())[:3])
        bullets.append(f"**Result.** None of the {len(results)} configurations passed all eight gates at the fixed policy sizing. The gates most "
                       f"often missed were: {worst}. Nothing goes to demo or paper trading as a strategy from this report.")

    if top:
        best = top[0]
        bh = _bh_for(run, best["instrument"], best["timeframe"]) or {}
        hold = next((r for r in run.get("results", []) if r.get("candidate") in REFERENCE_CANDIDATES and r.get("instrument") == best["instrument"]
                     and r.get("timeframe") == best["timeframe"] and (r.get("regime") or {}).get("mode", "none") == "none"), None)
        hold_text = ""
        if hold is not None:
            ho = hold.get("oos") or {}
            hh = hold.get("holdout") or {}
            hold_text = (f" Simply staying long {best['instrument'].split('-')[0]} with the same policy sizing and no timing rule made "
                         f"{_pct(ho.get('cagr'))} per year with a {_share(ho.get('max_drawdown'))} drawdown (Calmar {_f(ho.get('calmar'))})"
                         + (f"; on the holdout {_pct(hh.get('total_return'))} with a {_share(hh.get('max_drawdown'))} drawdown." if hh else "."))
        holdout_text = ""
        if best.get("holdout"):
            h = best["holdout"]
            holdout_text = (f" On the untouched holdout it made {_pct(h.get('total_return'))} with a {_share(h.get('max_drawdown'))} drawdown "
                            f"(PF {_f(h.get('profit_factor'))}, {h.get('n_trades')} trades) — "
                            + ("consistent with the walk-forward." if best.get("holdout_confirmed") else "NOT consistent with the walk-forward."))
        bullets.append(
            f"**Best so far.** {best['candidate']} on {best['instrument']} {best['timeframe']} with `{best['regime']}` and exit `{best['bracket']}`: "
            f"out-of-sample {_pct(best['cagr'])} per year with a worst drawdown of {_share(best['max_drawdown'])} (Sharpe {_f(best['sharpe'])}, "
            f"Calmar {_f(best['calmar'])}, {best['n_trades']} trades, {_share(best['rolling_12m_positive_share'])} of rolling 12-month windows positive).{holdout_text} "
            f"Plain buy-and-hold over the same months made {_pct(bh.get('cagr'))} per year with a {_share(bh.get('max_drawdown'))} drawdown "
            f"(Calmar {_f(bh.get('calmar'))}).{hold_text}"
            + ("" if best["passed"] else f" It still misses: {', '.join(GATE_LABELS.get(g, g) for g in best['failed_gates'])}.")
        )
    else:
        bullets.append("**Best so far.** No configuration had a profit factor above 1.0 with at least 30 trades, so there is no lead candidate.")

    if study.get("n"):
        verdict = study.get("verdict", "")
        bullets.append(
            f"**What the regime gate bought us.** Across the {study['n']} rules run with and without the gate, blocking entries in the bear state "
            f"moved the median 2022 return from {_pct(study.get('none_2022_median'))} to {_pct(study.get('gate_2022_median'))}, the median worst "
            f"drawdown from {_share(study.get('none_dd_median'))} to {_share(study.get('gate_dd_median'))}, the median yearly return from "
            f"{_pct(study.get('none_cagr_median'))} to {_pct(study.get('gate_cagr_median'))} and the median Calmar from {_f(study.get('none_calmar_median'))} "
            f"to {_f(study.get('gate_calmar_median'))}; quarter-sizing in the bear state gave Calmar {_f(study.get('scale_calmar_median'))}. {verdict}"
        )
    else:
        bullets.append("**What the regime gate bought us.** The regime comparison could not be computed for this run.")

    ports = run.get("portfolios") or []
    turnover = run.get("turnover_study") or {}
    next_step = run.get("next_step", "See the recommendations at the end of this report.")
    port_text = ""
    if ports:
        best_p = max(ports, key=lambda p: _num((p.get("metrics") or {}).get("calmar")))
        m = best_p.get("metrics") or {}
        port_text = (f"The best portfolio ({best_p.get('name')}) made {_pct(m.get('cagr'))} per year with a {_share(m.get('max_drawdown'))} drawdown "
                     f"(Sharpe {_f(m.get('sharpe'))}, Calmar {_f(m.get('calmar'))}). ")
    turn_text = ""
    if turnover.get("n"):
        turn_text = (f"The lower-turnover clocks cut the median fee drag from {_share(turnover.get('base_fees_median'))} to "
                     f"{_share(turnover.get('variant_fees_median'))} per year and moved the median Calmar from {_f(turnover.get('base_calmar_median'))} "
                     f"to {_f(turnover.get('variant_calmar_median'))}. ")
    bullets.append(f"**Portfolio, turnover and next step.** {port_text}{turn_text}{next_step}")
    return bullets


# -- aggregate studies (computed by the runner, rendered here) -----------------------

def regime_study(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Same rule with regime mode none / gate / scale: 2022, drawdown, CAGR, Calmar medians."""
    by_key: Dict[Any, Dict[str, Mapping[str, Any]]] = {}
    for r in results:
        if r.get("candidate") in REFERENCE_CANDIDATES:
            continue
        mode = (r.get("regime") or {}).get("mode", "none")
        by_key.setdefault((r["candidate"], r["instrument"], r["timeframe"]), {})[mode] = r
    rows = []
    for (cand, inst, tf), modes in by_key.items():
        if "none" not in modes or "gate" not in modes:
            continue
        def pick(m: str, key: str, src: str = "oos"):
            r = modes.get(m)
            if r is None:
                return None
            return (r.get(src) or {}).get(key)
        rows.append({
            "candidate": cand, "instrument": inst, "timeframe": tf,
            "none_2022": (modes["none"].get("yearly") or {}).get("2022", (modes["none"].get("yearly") or {}).get(2022)),
            "gate_2022": (modes["gate"].get("yearly") or {}).get("2022", (modes["gate"].get("yearly") or {}).get(2022)),
            "scale_2022": None if "scale" not in modes else (modes["scale"].get("yearly") or {}).get("2022", (modes["scale"].get("yearly") or {}).get(2022)),
            "none_cagr": pick("none", "cagr"), "gate_cagr": pick("gate", "cagr"), "scale_cagr": pick("scale", "cagr"),
            "none_dd": pick("none", "max_drawdown"), "gate_dd": pick("gate", "max_drawdown"), "scale_dd": pick("scale", "max_drawdown"),
            "none_calmar": pick("none", "calmar"), "gate_calmar": pick("gate", "calmar"), "scale_calmar": pick("scale", "calmar"),
            "none_sharpe": pick("none", "sharpe"), "gate_sharpe": pick("gate", "sharpe"), "scale_sharpe": pick("scale", "sharpe"),
            "none_trades": pick("none", "n_trades"), "gate_trades": pick("gate", "n_trades"), "scale_trades": pick("scale", "n_trades"),
            "gate_blocked_share": pick("gate", "gate_blocked_share"),
            "none_passed": bool((modes["none"].get("acceptance") or {}).get("passed")),
            "gate_passed": bool((modes["gate"].get("acceptance") or {}).get("passed")),
            "scale_passed": bool((modes.get("scale", {}).get("acceptance") or {}).get("passed")) if "scale" in modes else None,
        })
    if not rows:
        return {"n": 0, "rows": []}

    def med(key: str) -> Optional[float]:
        return _median([row.get(key) for row in rows])

    out = {
        "n": len(rows), "rows": rows,
        "none_2022_median": med("none_2022"), "gate_2022_median": med("gate_2022"), "scale_2022_median": med("scale_2022"),
        "none_cagr_median": med("none_cagr"), "gate_cagr_median": med("gate_cagr"), "scale_cagr_median": med("scale_cagr"),
        "none_dd_median": med("none_dd"), "gate_dd_median": med("gate_dd"), "scale_dd_median": med("scale_dd"),
        "none_calmar_median": med("none_calmar"), "gate_calmar_median": med("gate_calmar"), "scale_calmar_median": med("scale_calmar"),
        "gate_wins_calmar": sum(1 for row in rows if _num(row.get("gate_calmar"), -9) > _num(row.get("none_calmar"), -9)),
    }
    delta = _num(out["gate_calmar_median"]) - _num(out["none_calmar_median"])
    if delta > 0.1:
        out["verdict"] = "In other words, standing aside in the bear state improved the risk-adjusted result, not only the drawdown."
    elif delta < -0.1:
        out["verdict"] = "In other words, the gate cost more return than it saved: the bear state also contains the recoveries these rules need."
    else:
        out["verdict"] = "In other words, the gate changed the shape of the losses but not the risk-adjusted result; it is not where the missing edge is."
    return out


def turnover_study(results: Sequence[Mapping[str, Any]], variants: Mapping[str, str]) -> Dict[str, Any]:
    """Variant vs its base rule (same instrument, timeframe, regime mode): fees/yr, trades/yr, Calmar."""
    index: Dict[Any, Mapping[str, Any]] = {}
    for r in results:
        index[(r["candidate"], r["instrument"], r["timeframe"], (r.get("regime") or {}).get("mode", "none"))] = r
    rows = []
    for variant, base_key in variants.items():
        for (cand, inst, tf, mode), r in index.items():
            if cand != variant:
                continue
            base = index.get((base_key, inst, tf, mode))
            if base is None:
                continue
            bo, vo = base.get("oos") or {}, r.get("oos") or {}
            rows.append({"variant": variant, "base": base_key, "instrument": inst, "timeframe": tf, "regime": mode,
                         "base_fees": bo.get("fees_pct_per_year"), "variant_fees": vo.get("fees_pct_per_year"),
                         "base_trades": bo.get("trades_per_year"), "variant_trades": vo.get("trades_per_year"),
                         "base_cagr": bo.get("cagr"), "variant_cagr": vo.get("cagr"),
                         "base_dd": bo.get("max_drawdown"), "variant_dd": vo.get("max_drawdown"),
                         "base_sharpe": bo.get("sharpe"), "variant_sharpe": vo.get("sharpe"),
                         "base_calmar": bo.get("calmar"), "variant_calmar": vo.get("calmar"),
                         "variant_passed": bool((r.get("acceptance") or {}).get("passed"))})
    if not rows:
        return {"n": 0, "rows": []}
    return {
        "n": len(rows), "rows": rows,
        "base_fees_median": _median([x["base_fees"] for x in rows]), "variant_fees_median": _median([x["variant_fees"] for x in rows]),
        "base_calmar_median": _median([x["base_calmar"] for x in rows]), "variant_calmar_median": _median([x["variant_calmar"] for x in rows]),
        "variant_wins_calmar": sum(1 for x in rows if _num(x["variant_calmar"], -9) > _num(x["base_calmar"], -9)),
    }


def s5_study(results: Sequence[Mapping[str, Any]], variants: Mapping[str, str]) -> List[Dict[str, Any]]:
    index: Dict[Any, Mapping[str, Any]] = {}
    for r in results:
        index[(r["candidate"], r["instrument"], r["timeframe"], (r.get("regime") or {}).get("mode", "none"))] = r
    rows = []
    for variant, base_key in variants.items():
        for (cand, inst, tf, mode), r in index.items():
            if cand != variant:
                continue
            base = index.get((base_key, inst, tf, mode))
            long_window = index.get((base_key + "+S5", inst, tf, mode))
            rows.append({"variant": variant, "base": base_key, "instrument": inst, "timeframe": tf, "regime": mode,
                         "base": None if base is None else base.get("oos"), "s5_long": None if long_window is None else long_window.get("oos"),
                         "s5_short": r.get("oos"), "params": r.get("selected_params"), "coverage": r.get("positioning_coverage")})
    return rows


# -- Markdown -----------------------------------------------------------------------

def _holdout_cell(r: Mapping[str, Any]) -> str:
    h = r.get("holdout")
    if not h:
        return "untouched"
    verdict = holdout_verdict(r)
    mark = "✓" if verdict else "✗"
    return f"{_pct(h.get('total_return'))} / PF {_f(h.get('profit_factor'))} / {h.get('n_trades')} tr {mark}"


def _summary_row(r: Mapping[str, Any]) -> str:
    oos, acc = r["oos"], r["acceptance"]
    return (f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {(r.get('regime') or {}).get('label', '-')} | "
            f"{(r.get('selected_params') or {}).get('bracket', '-')} | {_pct(oos.get('total_return'))} | {_pct(oos.get('cagr'))} | "
            f"{_f(oos.get('sharpe'))} | {_f(oos.get('profit_factor'))} | {_share(oos.get('max_drawdown'))} | {_f(oos.get('calmar'))} | "
            f"{oos.get('n_trades', 0)} | {_share(oos.get('avg_allocation'))} | {_share(oos.get('fees_pct_per_year'))} | "
            f"{_share(acc.get('rolling_positive_share'))} | {_pct(acc.get('worst_calendar_year_return'))} | "
            f"{_share((r.get('robustness') or {}).get('share_above_threshold'))} | {_f((r.get('dsr') or {}).get('dsr'))} | "
            f"{'**PASS**' if acc.get('passed') else 'fail'} | {_holdout_cell(r)} |")


def render_report_v1c(run: Mapping[str, Any]) -> str:
    meta = run["meta"]
    results = list(run["results"])
    cands = [r for r in results if r["candidate"] not in REFERENCE_CANDIDATES]
    lines: List[str] = []
    lines += [
        "# Ensemble v1c — regime gates, portfolio sizing and turnover (walk-forward, SIMULATION ONLY)",
        "",
        f"Generated {meta['generated_at']} by `scripts/run_research_v1c.py`. Data: PUBLIC OKX spot candles from the Parquet lake "
        f"({meta['data_span']}); 6H bars resampled from 1H (UTC-aligned). Positioning features: {meta.get('positioning_source', 'none')} "
        f"(public, research only). Costs: fee {meta['fee_rate'] * 100:.2f}% per side + slippage {meta['slippage_rate'] * 100:.3f}% per side. "
        f"Long-only spot, no leverage. Walk-forward: train {meta['train_days']}d → purge {meta['purge_days']}d → test {meta['test_days']}d, rolling; "
        f"the trading rule (entries × exit bracket) is selected on the train slice by {meta['select_by']} with ≥{meta['min_trades']} train trades at "
        f"full size, exactly as in Sprint 2b; the regime model (`{meta['regime']['label']}`, {meta['regime']['n_states']} states on log return + log "
        f"{meta['regime']['vol_window_days']:g}-day realized vol) is fitted on the train slice of every window and applied forward as an ENTRY gate only; "
        f"sizing is the fixed a-priori policy `{meta['policy_sizing']['label']}` for every candidate (planner decision 2; the train-selected sizing of "
        f"Sprint 2b is shown only as a comparison). S0 no-trade filter: {meta.get('no_trade_label', 'default')}. Brackets tried: {meta.get('bracket_variants')}. "
        f"Holdout: last {meta['holdout_months']} months ({meta['holdout_span']}), evaluated once and only for candidates that passed walk-forward.",
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
        "## Gates (Sprint 2b item 8 + planner decision 1, at the fixed policy sizing)",
        "",
        f"- Out-of-sample profit factor > {GATES['profit_factor_min']} after costs",
        f"- Max drawdown < {GATES['max_drawdown_max'] * 100:.0f}%",
        f"- Sharpe > {GATES['sharpe_min']}; Calmar (CAGR / max drawdown) > {GATES['calmar_min']}",
        f"- Yearly consistency v2: ≥ {GATES['rolling_12m_positive_min'] * 100:.0f}% of rolling 12-month windows (sampled every 30 days) positive AND no "
        f"calendar year (≥ {GATES['min_year_days']} days of data) worse than {GATES['worst_calendar_year_min'] * 100:+.0f}%",
        f"- At least {GATES['min_trades']} out-of-sample trades",
        f"- ≥ {GATES['robust_share_min'] * 100:.0f}% of ±30% parameter neighbours stay profitable (replayed with the same regime gate and sizing)",
        "- Deflated Sharpe reported (no threshold)",
        "",
        "## Summary (fixed policy sizing; one row per candidate × series × regime mode)",
        "",
        "| Candidate | Series | Regime | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Alloc. | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Verdict | Holdout (12m) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in results:
        lines.append(_summary_row(r))
    passed = [r for r in cands if r["acceptance"]["passed"]]
    confirmed = [r for r in passed if holdout_verdict(r) is True]
    contradicted = [r for r in passed if holdout_verdict(r) is False]
    lines += ["", f"Configurations passing all walk-forward gates: **{len(passed)}** of {len(cands)}; confirmed by the untouched holdout: "
              f"**{len(confirmed)}**; contradicted by it: **{len(contradicted)}** (the `hold` rows are passive always-long controls with the "
              "same sizing machinery — planner decision 6 — not candidates; their holdout is shown for comparison only). Holdout ✓ = positive "
              f"return, PF > 1 and ≥ {HOLDOUT_MIN_TRADES} trades.", ""]
    if run.get("failures"):
        lines += ["Runs that failed with an error (not evaluated):", ""]
        for f in run["failures"]:
            lines.append(f"- {f['candidate']} on {f['instrument']} {f['timeframe']} ({f.get('regime', '-')}): `{f['error']}`")
        lines.append("")
    if run.get("benchmark"):
        lines += ["Buy-and-hold over the same out-of-sample span (after costs, all-in):", "",
                  "| Series | Total | CAGR | Sharpe | Max DD | Calmar |", "|---|---:|---:|---:|---:|---:|"]
        for b in run["benchmark"]:
            lines.append(f"| {b['instrument']} {b['timeframe']} | {_pct(b['total_return'])} | {_pct(b.get('cagr'))} | {_f(b.get('sharpe'))} | "
                         f"{_share(b['max_drawdown'])} | {_f(b.get('calmar'))} |")
        lines.append("")

    # Regime study.
    study = run.get("regime_study") or {}
    if study.get("rows"):
        lines += ["## Regime v2 as an entry gate — same rule without / with the gate / with quarter-size in the bear state", "",
                  "2022 is the bear year that broke the Sprint 2b yearly gate; it is shown explicitly (planner item 2). `blocked` = share of the "
                  "selected rule's desired entry bars removed by the gate in the test windows.", "",
                  "| Candidate | Series | 2022 none → gate → scale | CAGR none → gate → scale | Max DD none → gate → scale | Calmar none → gate → scale | Trades none → gate | Blocked | Pass none / gate / scale |",
                  "|---|---|---|---|---|---|---|---:|---|"]
        for s in study["rows"]:
            lines.append(f"| {s['candidate']} | {s['instrument']} {s['timeframe']} | {_pct(s.get('none_2022'))} → {_pct(s.get('gate_2022'))} → {_pct(s.get('scale_2022'))} | "
                         f"{_pct(s.get('none_cagr'))} → {_pct(s.get('gate_cagr'))} → {_pct(s.get('scale_cagr'))} | "
                         f"{_share(s.get('none_dd'))} → {_share(s.get('gate_dd'))} → {_share(s.get('scale_dd'))} | "
                         f"{_f(s.get('none_calmar'))} → {_f(s.get('gate_calmar'))} → {_f(s.get('scale_calmar'))} | "
                         f"{s.get('none_trades')} → {s.get('gate_trades')} | {_share(s.get('gate_blocked_share'))} | "
                         f"{'yes' if s.get('none_passed') else 'no'} / {'yes' if s.get('gate_passed') else 'no'} / "
                         f"{'-' if s.get('scale_passed') is None else ('yes' if s.get('scale_passed') else 'no')} |")
        lines += ["", f"Medians over {study['n']} rules: 2022 {_pct(study.get('none_2022_median'))} → {_pct(study.get('gate_2022_median'))} (gate) / "
                  f"{_pct(study.get('scale_2022_median'))} (scale); max DD {_share(study.get('none_dd_median'))} → {_share(study.get('gate_dd_median'))} / "
                  f"{_share(study.get('scale_dd_median'))}; CAGR {_pct(study.get('none_cagr_median'))} → {_pct(study.get('gate_cagr_median'))} / "
                  f"{_pct(study.get('scale_cagr_median'))}; Calmar {_f(study.get('none_calmar_median'))} → {_f(study.get('gate_calmar_median'))} / "
                  f"{_f(study.get('scale_calmar_median'))}. The gate had the higher Calmar in {study.get('gate_wins_calmar')} of {study['n']} rules. "
                  f"{study.get('verdict', '')}", ""]
    sens = run.get("regime_sensitivity") or []
    if sens:
        lines += ["Gate-threshold sensitivity (one rule, fixed replay of the most-selected parameters with the policy sizing):", "",
                  "| Rule | Series | bear_prob_max | CAGR | Max DD | Calmar | Trades | 2022 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for s in sens:
            lines.append(f"| {s['candidate']} | {s['instrument']} {s['timeframe']} | {s['bear_prob_max']:g} | {_pct(s.get('cagr'))} | {_share(s.get('max_drawdown'))} | "
                         f"{_f(s.get('calmar'))} | {s.get('n_trades')} | {_pct(s.get('y2022'))} |")
        lines.append("")

    # Sizing comparison.
    comp_rows = [r for r in results if r.get("comparison")]
    if comp_rows:
        lines += ["## Sizing: fixed policy (the proposal) vs train-selected sizing (comparison only)", "",
                  "| Candidate | Series | Regime | Policy CAGR / max DD / Calmar | Train-selected CAGR / max DD / Calmar | Most-selected comparison sizing |",
                  "|---|---|---|---|---|---|"]
        for r in comp_rows:
            o, c = r["oos"], r["comparison"]
            freq = r.get("comparison_frequency") or {}
            most = max(freq, key=freq.get) if freq else "-"
            lines.append(f"| {r['candidate']} | {r['instrument']} {r['timeframe']} | {(r.get('regime') or {}).get('mode', '-')} | "
                         f"{_pct(o.get('cagr'))} / {_share(o.get('max_drawdown'))} / {_f(o.get('calmar'))} | "
                         f"{_pct(c.get('cagr'))} / {_share(c.get('max_drawdown'))} / {_f(c.get('calmar'))} | {most} |")
        lines.append("")

    # Portfolios.
    if run.get("portfolios"):
        lines += ["## Portfolio-level sizing (BTC+ETH × S1/S2/S4 sleeves, one drawdown budget)", "",
                  "Two constructions of the same sleeves (per family and instrument the timeframe with the higher OOS Calmar — a mild selection "
                  "on OOS data): *sleeve-sized* = each sleeve already carries the policy sizing, equal-risk weights on full-sample vol, bucket "
                  "compounding, portfolio ladder (Sprint 2b); *jointly sized* = sleeves at FULL size, trailing inverse-vol weights, one portfolio "
                  "vol target and one 15 % drawdown ladder (Sprint 2c item 3). Gates on a portfolio use its daily curve and the pooled sleeve trades.", "",
                  "| Portfolio | Sleeves | Regime | CAGR | Sharpe | Max DD | Calmar | Rolling 12m + | Worst year | Avg scale | Trades (pooled) | PF (pooled) | Gates missed |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for p in run["portfolios"]:
            m = p.get("metrics") or {}
            acc = p.get("acceptance") or {}
            missed = ", ".join(GATE_LABELS.get(g, g) for g in acc.get("failed", [])) or ("none — PASS" if acc else "-")
            lines.append(f"| {p['name']} | {len(p.get('weights') or {})} | {p.get('regime', '-')} | {_pct(m.get('cagr'))} | {_f(m.get('sharpe'))} | "
                         f"{_share(m.get('max_drawdown'))} | {_f(m.get('calmar'))} | {_share(acc.get('rolling_positive_share'))} | "
                         f"{_pct(acc.get('worst_calendar_year_return'))} | {_share(p.get('avg_scale'))} | {p.get('pooled_trades', '-')} | "
                         f"{_f(p.get('pooled_profit_factor'))} | {missed} |")
        lines.append("")
        corr = run.get("portfolio_correlation")
        if corr:
            names = list(corr)
            lines += ["Correlation of daily sleeve returns (full-size sleeves, no regime gate):", "", "| | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
            for a in names:
                lines.append(f"| {a} | " + " | ".join(_f(corr[a].get(b_)) for b_ in names) + " |")
            lines.append("")

    # Turnover.
    turnover = run.get("turnover_study") or {}
    if turnover.get("rows"):
        lines += ["## Lower-turnover variants — fee drag per variant (same regime mode and series as the base rule)", "",
                  "| Variant | Base | Series | Regime | Fees/yr base → variant | Trades/yr base → variant | CAGR base → variant | Max DD base → variant | Calmar base → variant | Variant passes |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for t in turnover["rows"]:
            lines.append(f"| {t['variant']} | {t['base']} | {t['instrument']} {t['timeframe']} | {t['regime']} | {_share(t.get('base_fees'))} → {_share(t.get('variant_fees'))} | "
                         f"{_f(t.get('base_trades'), '{:.0f}')} → {_f(t.get('variant_trades'), '{:.0f}')} | {_pct(t.get('base_cagr'))} → {_pct(t.get('variant_cagr'))} | "
                         f"{_share(t.get('base_dd'))} → {_share(t.get('variant_dd'))} | {_f(t.get('base_calmar'))} → {_f(t.get('variant_calmar'))} | "
                         f"{'yes' if t.get('variant_passed') else 'no'} |")
        lines += ["", f"Medians over {turnover['n']} pairs: fees/yr {_share(turnover.get('base_fees_median'))} → {_share(turnover.get('variant_fees_median'))}, "
                  f"Calmar {_f(turnover.get('base_calmar_median'))} → {_f(turnover.get('variant_calmar_median'))}; the variant had the higher Calmar in "
                  f"{turnover.get('variant_wins_calmar')} of {turnover['n']} pairs.", ""]

    # S5 re-test.
    s5 = run.get("s5_study") or []
    if s5:
        lines += ["## Positioning filter re-test (S5) — base vs 30-day funding window vs 7–14-day window + OI change", "",
                  "| Variant | Series | Regime | Base Sharpe / Calmar / DD / trades | S5 (30d) Sharpe / Calmar / DD / trades | S5 short Sharpe / Calmar / DD / trades | Most-selected S5 params | Data coverage |",
                  "|---|---|---|---|---|---|---|---:|"]
        for s in s5:
            def trip(o):
                return "-" if not o else f"{_f(o.get('sharpe'))} / {_f(o.get('calmar'))} / {_share(o.get('max_drawdown'))} / {o.get('n_trades')}"
            p = s.get("params") or {}
            pp = {k: p[k] for k in ("funding_z_window", "funding_z_max", "oi_change_max", "oi_change_window_days") if k in p}
            lines.append(f"| {s['variant']} | {s['instrument']} {s['timeframe']} | {s['regime']} | {trip(s.get('base'))} | {trip(s.get('s5_long'))} | "
                         f"{trip(s.get('s5_short'))} | `{pp}` | {_share(s.get('coverage'))} |")
        lines.append("")

    # Shortlist.
    lines += ["## Paper-fleet shortlist (ranked) — forward evidence only; nothing approved", "",
              f"Ranked by: passed all gates first, then Calmar, then Sharpe; only configurations with OOS profit factor > 1 and ≥ 30 trades. "
              f"Machine-readable copy with the controls: `{meta.get('shortlist_path', 'docs/research/paper_fleet_shortlist_v1c.json')}`.", ""]
    sl = run.get("shortlist") or shortlist(results)
    if sl:
        lines += ["| # | Candidate | Series | Regime | Bracket | CAGR | Sharpe | Calmar | Max DD | PF | Trades | Rolling 12m + | Worst year | DSR | Gates missed | Holdout |",
                  "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for row in sl:
            missed = ", ".join(GATE_LABELS.get(g, g) for g in row["failed_gates"]) or "none — PASS"
            lines.append(f"| {row['rank']} | {row['candidate']} | {row['instrument']} {row['timeframe']} | {row['regime']} | {row['bracket']} | "
                         f"{_pct(row['cagr'])} | {_f(row['sharpe'])} | {_f(row['calmar'])} | {_share(row['max_drawdown'])} | {_f(row['profit_factor'])} | "
                         f"{row['n_trades']} | {_share(row['rolling_12m_positive_share'])} | {_pct(row.get('worst_calendar_year_return'))} | {_f(row['dsr'])} | {missed} | {_holdout_cell(row)} |")
    else:
        lines.append("No configuration qualifies for the shortlist (profit factor ≤ 1 or fewer than 30 trades everywhere).")
    ctrl = run.get("controls") or []
    if ctrl:
        lines += ["", "Controls the fleet must run next to the shortlist (planner decision 6):", "",
                  "| Role | Series | Regime | CAGR | Sharpe | Calmar | Max DD | Holdout |", "|---|---|---|---:|---:|---:|---:|---|"]
        for c in ctrl:
            lines.append(f"| {c.get('role')} | {c['instrument']} {c['timeframe']} | {c.get('regime', '-')} | {_pct(c.get('cagr'))} | {_f(c.get('sharpe'))} | "
                         f"{_f(c.get('calmar'))} | {_share(c.get('max_drawdown'))} | {_holdout_cell(c) if c.get('holdout') else '-'} |")
    lines.append("")

    # Per-candidate details.
    for r in results:
        oos = r["oos"]
        lines += [f"## {r['candidate']} — {r['label']} ({r['instrument']} {r['timeframe']}, {(r.get('regime') or {}).get('label', '-')})", ""]
        lines += [f"Rule grid: {r['grid_size']} combinations (entries × exit brackets). Windows: {oos.get('windows')} ({oos.get('windows_traded')} traded, "
                  f"{oos.get('windows_positive')} positive). Most-selected rule: `{r.get('selected_params')}`. Policy sizing: `{(r.get('policy_sizing') or {}).get('label')}`. "
                  f"Regime: train bear share median {_share(r.get('regime_train_bear_share_median'))}, test bear share median {_share(r.get('regime_test_bear_share_median'))}, "
                  f"entries blocked by the gate {_share(oos.get('gate_blocked_share'))}.", ""]
        if r.get("yearly"):
            lines += ["| Year | OOS return |", "|---|---:|"]
            for year, value in r["yearly"].items():
                lines.append(f"| {year} | {_pct(value)} |")
            lines.append("")
        yg = r.get("yearly_gate") or {}
        lines += [f"Rolling 12-month windows: {yg.get('rolling_windows')} sampled, {_share(yg.get('rolling_positive_share'))} positive, min {_pct(yg.get('rolling_min'))}, "
                  f"median {_pct(yg.get('rolling_median'))}; worst calendar year {yg.get('worst_calendar_year')} at {_pct(yg.get('worst_calendar_year_return'))}.", ""]
        rb = r.get("robustness") or {}
        lines += [f"Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime "
                  f"gate and the policy sizing over every test window): selected set {_pct(rb.get('best'))}, neighbours median {_pct(rb.get('median'))}, "
                  f"min {_pct(rb.get('min'))}, share profitable {_share(rb.get('share_above_threshold'))} over {rb.get('n_neighbours')} neighbours.", ""]
        if r.get("full_size"):
            fs = r["full_size"]
            lines += [f"Same rule at full size (no sizing, same gate): return {_pct(fs.get('total_return'))}, max DD {_share(fs.get('max_drawdown'))}, Calmar {_f(fs.get('calmar'))}.", ""]
        mc = r.get("montecarlo", {})
        if mc.get("n_trades"):
            lines += [f"Monte Carlo (trade-order bootstrap of equity-level trade returns, {mc['paths']} paths over {mc['n_trades']} OOS trades): terminal growth "
                      f"p05 {_f(mc['terminal_p05'])}× / p50 {_f(mc['terminal_p50'])}× / p95 {_f(mc['terminal_p95'])}×, P(loss) {_share(mc['prob_loss'])}, "
                      f"max DD p50 {_share(mc['max_dd_p50'])}, p95 {_share(mc['max_dd_p95'])}.", ""]
        ss = r.get("slippage_stress", {})
        if ss:
            lines += ["Slippage stress (OOS total return with slippage ×1/×2/×3): " + ", ".join(f"{k}: {_pct(v)}" for k, v in ss.items()), ""]
        d = r.get("dsr") or {}
        lines += [f"Deflated Sharpe: {d.get('n_trials')} rule trials in the last train window (× {meta.get('n_regime_modes', 1)} regime modes tried a priori), "
                  f"expected max SR (zero skill) {_f(d.get('expected_max_sr'), '{:.3f}')} per bar vs observed OOS {_f(d.get('observed_sr'), '{:.3f}')} → DSR {_f(d.get('dsr'))}.", ""]
        acc = r["acceptance"]
        lines += ["Checks: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in acc.items() if isinstance(v, bool) and k != "passed"), ""]
        if r.get("holdout"):
            h = r["holdout"]
            lines += [f"**Holdout ({meta['holdout_span']}), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole "
                      f"in-sample span:** return {_pct(h.get('total_return'))}, CAGR {_pct(h.get('cagr'))}, Sharpe {_f(h.get('sharpe'))}, PF {_f(h.get('profit_factor'))}, "
                      f"max DD {_share(h.get('max_drawdown'))}, Calmar {_f(h.get('calmar'))}, trades {h.get('n_trades')}.", ""]
        elif acc["passed"]:
            lines += ["Holdout: not evaluated in this run (`--evaluate-holdout` not set).", ""]
        else:
            lines += ["Holdout: untouched (candidate did not pass walk-forward).", ""]
        for note in r.get("notes", []):
            lines.append(f"- {note}")
        if r.get("notes"):
            lines.append("")

    lines += ["## Owner decisions (nothing below is decided by this report)", ""]
    for item in run.get("owner_decisions") or []:
        lines.append(f"- {item}")
    lines += [
        "",
        "## Method notes and caveats",
        "",
        "- Engine, sizing overlays, brackets, staged rule selection and the stitched out-of-sample construction are the Sprint 2b ones "
        "(`docs/RESEARCH_LAB.md`); the only new element inside a window is the regime gate, which is fitted on the train slice and applied "
        "forward (filtered probabilities, never smoothed), to entries only.",
        "- The regime model is a diagonal-Gaussian HMM written for this repository (`research/hmm.py`), not `hmmlearn`: the lockfile stays "
        "audited and the filter exposes the forward-only posterior a trading decision needs. Tests check that the filtered probability of a bar does "
        "not change when later bars are appended.",
        "- The yearly gate v2 samples trailing 12-month returns every 30 days along the stitched curve (overlapping windows, so the share is a "
        "smoothed statistic, not independent trials) and judges calendar years with at least 60 days of data.",
        "- The fixed policy sizing was declared before the run (Sprint 2b's `vt10/30 crash15/90dh ladder`); the train-selected sizing is a "
        "comparison, not a proposal. The regime modes (none / gate / scale), the gate threshold and the turnover clocks were also fixed before the "
        "run; they still multiply the number of things tried, which is why the deflated Sharpe stays low.",
        "- The FOMC calendar inside the S0 filter was written from memory of the published schedules; the owner should verify it before it "
        "matters (it blocks a few bars per meeting at 4H/6H, so its effect on these numbers is small).",
        "- Portfolio-level sizing uses only past days for weights and the vol scale; the sleeve choice (timeframe per family and instrument) is a "
        "mild selection on OOS data, so portfolio numbers are slightly optimistic.",
        "- Every number is a simulation on historical public data and proves nothing about the future.",
        "",
    ]
    return "\n".join(lines)
