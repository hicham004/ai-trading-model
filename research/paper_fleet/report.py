"""The paper fleet's weekly ranking report (from the journals alone; SIMULATION ONLY).

``reports/weekly-YYYY-Www.md`` covers one ISO week (Monday to Sunday, UTC) and
everything since the fleet started. The current week's file is rewritten as
the week goes on ("week to date") and finalized once the week is over.

What it compares — every band below was fixed in this file before the fleet
produced a single forward number, and must not be changed after looking at
forward results (a changed band is a new, pre-registered study):

- **Return band**: the walk-forward CAGR compounded over the forward days,
  plus/minus 2 standard deviations of the walk-forward volatility over the same
  span (about 95 % of outcomes if the future looks like the backtest). Below
  the band = "worse than the backtest", above = "better".
- **Sharpe band** (from 90 days on): the walk-forward Sharpe plus/minus 2
  standard errors of a Sharpe ratio measured over the forward span
  (``sqrt((1 + SR^2 / 2) / years)``, Lo 2002).
- **Drawdown check**: the forward worst drawdown against the worst drawdown of
  the whole walk-forward (5+ years): above it = a warning, above 1.5 times it =
  an alarm.
- **Trade count band**: the walk-forward entries per year over the forward
  span, plus/minus 2 Poisson standard deviations.
- **Holdout pace**, where the configuration had a holdout: its 12-month holdout
  return compounded over the forward days, as a second reference.

Verdicts need at least 30 forward days ("too early" before that); the ranking
(by forward Sharpe, controls excluded) is labelled "not meaningful yet" before
90 days. Controls come first: a timing rule earns its place only by beating
them forward (planner decision 6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.data import bars_per_year
from research.events import FOMC_DECISION_DAYS

from research.paper_fleet.store import FleetPaths, Journal, read_state

BAND_Z = 2.0
MIN_DAYS_FOR_VERDICT = 30.0
MIN_DAYS_FOR_SHARPE = 90.0
DD_ALARM_MULTIPLE = 1.5
DAYS_PER_YEAR = 365.25
FOMC_WARNING_DAYS = 60.0  # warn this long before the built-in FOMC calendar runs out


# -- formatting ------------------------------------------------------------------


def _pct(v: Optional[float], signed: bool = True) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    v = float(v) + 0.0  # no "-0.00%"
    if abs(v) < 5e-7:
        v = 0.0
    return f"{v * 100:+.2f}%" if signed else f"{v * 100:.2f}%"


def _num(v: Optional[float], fmt: str = "{:.2f}") -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return fmt.format(v)


def _ts(text: str) -> pd.Timestamp:
    t = pd.Timestamp(text)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def iso_week(day: date) -> Tuple[int, int]:
    y, w, _ = day.isocalendar()
    return int(y), int(w)


def week_bounds(year: int, week: int) -> Tuple[pd.Timestamp, pd.Timestamp]:
    monday = date.fromisocalendar(year, week, 1)
    start = pd.Timestamp(monday, tz="UTC")
    return start, start + pd.Timedelta(days=7)


def week_label(year: int, week: int) -> str:
    return f"{year}-W{week:02d}"


# -- metrics -----------------------------------------------------------------------


@dataclass
class ForwardMetrics:
    days: float
    start: Optional[str]
    end: Optional[str]
    equity: float
    total_return: float
    ann_vol: Optional[float]
    sharpe: Optional[float]
    max_drawdown: float
    entries: int
    closed_trades: int
    wins: int
    profit_factor: Optional[float]
    fees: float
    exposure: Optional[float]
    avg_allocation: Optional[float]
    in_position: bool
    allocation_now: float
    bars: int

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _max_dd(equity: Sequence[float]) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(eq)
    return float(-(eq / peaks - 1.0).min())


def _sharpe(returns: np.ndarray, periods_per_year: float) -> Tuple[Optional[float], Optional[float]]:
    if returns.size < 2:
        return None, None
    sd = float(returns.std(ddof=1))
    vol = sd * math.sqrt(periods_per_year)
    return (float(returns.mean() / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0), vol


def _trade_stats(bar_records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    entries = exits = wins = 0
    gross_win = gross_loss = fees = 0.0
    for r in bar_records:
        for ev in r.get("events") or []:
            kind = ev.get("kind")
            if kind == "entry":
                entries += 1
                fees += float(ev.get("fee") or 0.0)
            elif kind == "reduce":
                fees += float(ev.get("fee") or 0.0)
            elif kind == "exit":
                exits += 1
                fees += float(ev.get("fee") or 0.0)
                pnl = float(ev.get("pnl") or 0.0)
                if pnl > 0:
                    wins += 1
                    gross_win += pnl
                else:
                    gross_loss += -pnl
    pf = (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    return {"entries": entries, "closed_trades": exits, "wins": wins, "profit_factor": pf, "fees": fees}


def sleeve_metrics(records: Sequence[Mapping[str, Any]], timeframe: str, init_cash: float, *, until: Optional[pd.Timestamp] = None) -> ForwardMetrics:
    bars = [r for r in records if r.get("type") == "bar" and "sleeve" not in r and (until is None or _ts(r["close_time"]) <= until)]
    if not bars:
        return ForwardMetrics(0.0, None, None, init_cash, 0.0, None, None, 0.0, 0, 0, 0, None, 0.0, None, None, False, 0.0, 0)
    eq = np.array([float(r["equity"]) for r in bars])
    rets = eq[1:] / eq[:-1] - 1.0 if eq.size > 1 else np.zeros(0)
    sharpe, vol = _sharpe(rets, bars_per_year(timeframe))
    start, end = _ts(bars[0]["close_time"]), _ts(bars[-1]["close_time"])
    ts = _trade_stats(bars[1:])
    live = bars[1:]
    exposure = float(np.mean([1.0 if r.get("in_position") else 0.0 for r in live])) if live else None
    alloc = float(np.mean([float(r.get("allocation") or 0.0) for r in live])) if live else None
    last = bars[-1]
    return ForwardMetrics(
        days=(end - start).total_seconds() / 86400.0, start=start.isoformat(), end=end.isoformat(), equity=float(eq[-1]),
        total_return=float(eq[-1] / init_cash - 1.0), ann_vol=vol, sharpe=sharpe, max_drawdown=_max_dd(np.concatenate([[init_cash], eq])),
        entries=ts["entries"], closed_trades=ts["closed_trades"], wins=ts["wins"], profit_factor=ts["profit_factor"], fees=ts["fees"],
        exposure=exposure, avg_allocation=alloc, in_position=bool(last.get("in_position")), allocation_now=float(last.get("allocation") or 0.0),
        bars=len(live),
    )


def portfolio_metrics(records: Sequence[Mapping[str, Any]], init_cash: float, *, until: Optional[pd.Timestamp] = None) -> ForwardMetrics:
    days = [r for r in records if r.get("type") == "portfolio_day" and (until is None or _ts(r["day"]) + pd.Timedelta(days=1) <= until)]
    sleeve_bars = [r for r in records if r.get("type") == "bar" and "sleeve" in r and (until is None or _ts(r["close_time"]) <= until)]
    start_day = None
    for r in records:
        if r.get("type") == "portfolio_warmup":
            start_day = r.get("forward_start_day")
    ts = _trade_stats([r for r in sleeve_bars if start_day is None or _ts(r["bar"]) >= _ts(start_day)])
    if not days:
        return ForwardMetrics(0.0, start_day, None, init_cash, 0.0, None, None, 0.0, ts["entries"], ts["closed_trades"], ts["wins"],
                              ts["profit_factor"], 0.0, None, None, False, 0.0, 0)
    idx = np.array([1.0] + [float(r["equity_index"]) for r in days])
    rets = np.array([float(r["portfolio_return"]) for r in days])
    sharpe, vol = _sharpe(rets, DAYS_PER_YEAR)
    gross = [float(r.get("gross_exposure_end_of_day") or 0.0) for r in days]
    return ForwardMetrics(
        days=float(len(days)), start=days[0]["day"], end=days[-1]["day"], equity=init_cash * float(idx[-1]), total_return=float(idx[-1] - 1.0),
        ann_vol=vol, sharpe=sharpe, max_drawdown=_max_dd(idx), entries=ts["entries"], closed_trades=ts["closed_trades"], wins=ts["wins"],
        profit_factor=ts["profit_factor"], fees=ts["fees"], exposure=float(np.mean([g > 0 for g in gross])), avg_allocation=float(np.mean(gross)),
        in_position=gross[-1] > 0, allocation_now=gross[-1], bars=len(days),
    )


# -- expectations and verdicts ---------------------------------------------------------


def _f(v: Any) -> Optional[float]:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def return_band(cagr: Optional[float], ann_vol: Optional[float], days: float) -> Optional[Tuple[float, float, float]]:
    if cagr is None or ann_vol is None or days <= 0:
        return None
    years = days / DAYS_PER_YEAR
    expected = (1.0 + cagr) ** years - 1.0
    width = BAND_Z * ann_vol * math.sqrt(years)
    return expected, expected - width, expected + width


def sharpe_band(sharpe: Optional[float], days: float, periods_per_year: float) -> Optional[Tuple[float, float, float]]:
    """Annualized Sharpe +- 2 standard errors over ``days``: Lo (2002) for i.i.d. returns measured ``periods_per_year`` times a year,
    ``SE = sqrt((1 + SR^2 / (2 q)) / years)``."""
    if sharpe is None or days <= 0 or periods_per_year <= 0:
        return None
    years = days / DAYS_PER_YEAR
    se = math.sqrt((1.0 + sharpe * sharpe / (2.0 * periods_per_year)) / years)
    return sharpe, sharpe - BAND_Z * se, sharpe + BAND_Z * se


def count_band(per_year: Optional[float], days: float) -> Optional[Tuple[float, float, float]]:
    if per_year is None or days <= 0:
        return None
    lam = per_year * days / DAYS_PER_YEAR
    return lam, max(0.0, lam - BAND_Z * math.sqrt(lam)), lam + BAND_Z * math.sqrt(lam)


def _side(value: Optional[float], band: Optional[Tuple[float, float, float]], low: str = "below", high: str = "above") -> str:
    if value is None or band is None:
        return "n/a"
    if value < band[1]:
        return low
    if value > band[2]:
        return high
    return "within"


def verdicts(account: Mapping[str, Any], m: ForwardMetrics) -> Dict[str, Any]:
    exp = account.get("expectations") or {}
    wf = exp.get("walk_forward") or {}
    hold = exp.get("holdout") or None
    benchmark = bool(exp.get("benchmark"))
    out: Dict[str, Any] = {}
    early = m.days < MIN_DAYS_FOR_VERDICT
    rb = None if benchmark else return_band(_f(wf.get("cagr")), _f(wf.get("ann_vol")), m.days)
    out["return_band"] = rb
    out["return"] = "too early" if early else ("benchmark" if benchmark else _side(m.total_return, rb))
    q = DAYS_PER_YEAR if account.get("kind") == "portfolio" else bars_per_year(account.get("timeframe") or "1D")
    sb = None if benchmark else sharpe_band(_f(wf.get("sharpe")), m.days, q)
    out["sharpe_band"] = sb
    out["sharpe"] = ("benchmark" if benchmark else "too early") if (m.days < MIN_DAYS_FOR_SHARPE or benchmark) else _side(m.sharpe, sb)
    wf_dd = _f(wf.get("max_drawdown"))
    if wf_dd is None:
        out["drawdown"] = "n/a"
    elif m.max_drawdown > DD_ALARM_MULTIPLE * wf_dd:
        out["drawdown"] = "ALARM"
    elif m.max_drawdown > wf_dd:
        out["drawdown"] = "above backtest worst"
    else:
        out["drawdown"] = "ok"
    always_long = account.get("kind") == "buy_and_hold" or ((account.get("sleeve") or {}).get("candidate") == "hold")
    cb = None if always_long else count_band(_f(wf.get("trades_per_year")), m.days)
    out["count_band"] = cb
    out["entries"] = "n/a (always long)" if always_long else ("too early" if early else _side(float(m.entries), cb, "fewer", "more"))
    if hold and _f(hold.get("total_return")) is not None and _f(hold.get("bars")):
        tf = account.get("timeframe") or "1D"
        hold_days = float(hold["bars"]) / bars_per_year(tf) * DAYS_PER_YEAR
        g = (1.0 + float(hold["total_return"])) ** (DAYS_PER_YEAR / hold_days) - 1.0 if hold_days > 0 else None
        hb = return_band(g, _f(hold.get("ann_vol")), m.days)
        out["holdout_band"] = hb
        out["holdout"] = "too early" if early else _side(m.total_return, hb)
    else:
        out["holdout_band"] = None
        out["holdout"] = "n/a"
    if early:
        status = "too early"
    elif benchmark:
        status = "benchmark"
    elif out["return"] == "below" or out["drawdown"] == "ALARM":
        status = "worse than backtest"
    elif out["return"] == "above":
        status = "better than backtest"
    elif out["return"] == "within":
        status = "consistent with backtest"
    else:
        status = "n/a"
    out["status"] = status
    return out


# -- assembling ----------------------------------------------------------------------


def load_journals(paths: FleetPaths, account_ids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    return {aid: list(Journal(paths.journal(aid)).read()) for aid in account_ids}


def fleet_log(paths: FleetPaths) -> List[Dict[str, Any]]:
    return list(Journal(paths.fleet_log).read())


def build_report_data(paths: FleetPaths, now: datetime, *, year: Optional[int] = None, week: Optional[int] = None) -> Dict[str, Any]:
    state = read_state(paths.state_file)
    if state is None:
        raise FileNotFoundError(f"no fleet state in {paths.state_file}")
    manifest = state.get("manifest") or {}
    accounts = manifest.get("accounts") or []
    init_cash = float(manifest.get("init_cash", 10_000.0))
    now_ts = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    if year is None or week is None:
        year, week = iso_week(now_ts.date())
    w_start, w_end = week_bounds(year, week)
    last_cycle = _ts(state["last_cycle"]) if state.get("last_cycle") else now_ts
    until = min(now_ts, w_end, max(last_cycle, w_start))
    final = until >= w_end
    journals = load_journals(paths, [a["account_id"] for a in accounts])
    rows: List[Dict[str, Any]] = []
    for acc in accounts:
        recs = journals.get(acc["account_id"], [])
        if acc["kind"] == "portfolio":
            m = portfolio_metrics(recs, init_cash, until=until)
            wk_start = portfolio_metrics(recs, init_cash, until=w_start)
            week_recs = [r for r in recs if r.get("type") == "bar" and "sleeve" in r and w_start < _ts(r["close_time"]) <= until]
        else:
            m = sleeve_metrics(recs, acc["timeframe"], init_cash, until=until)
            wk_start = sleeve_metrics(recs, acc["timeframe"], init_cash, until=w_start)
            week_recs = [r for r in recs if r.get("type") == "bar" and "sleeve" not in r and w_start < _ts(r["close_time"]) <= until]
        base = wk_start.equity if wk_start.bars or wk_start.days else init_cash
        week_stats = _trade_stats(week_recs)
        last_bar = next((r for r in reversed(recs) if r.get("type") == "bar" and "sleeve" not in r), None)
        rows.append({
            "account": acc, "metrics": m, "verdicts": verdicts(acc, m),
            "week": {"return": (m.equity / base - 1.0) if base else None, **week_stats},
            "last_decision": (last_bar or {}).get("decision"), "decision_error": (last_bar or {}).get("decision_error"),
            "notes": [r for r in recs if r.get("type") in ("gap", "regime_fit") and w_start <= _ts(r.get("bar") or r.get("next_bar") or r.get("missing_from")) < w_end],
        })
    controls = {(r["account"]["instrument"], r["account"]["timeframe"]): r for r in rows
                if r["account"]["role"] == "control" and (r["account"].get("sleeve") or {}).get("candidate") == "hold"}
    bh = {(r["account"]["instrument"], r["account"]["timeframe"]): r for r in rows if r["account"]["kind"] == "buy_and_hold"}
    for r in rows:
        key = (r["account"].get("instrument"), r["account"].get("timeframe"))
        ctl = controls.get(key)
        r["vs_control"] = None if ctl is None or r["account"]["role"] == "control" else r["metrics"].total_return - ctl["metrics"].total_return
        b = bh.get(key)
        r["vs_buy_and_hold"] = None if b is None or r["account"]["role"] == "control" else r["metrics"].total_return - b["metrics"].total_return
    log = fleet_log(paths)
    week_log = [r for r in log if "now" in r and w_start <= _ts(r["now"]) < w_end]
    return {
        "state": state, "rows": rows, "year": year, "week": week, "week_start": w_start, "week_end": w_end, "until": until, "final": final,
        "generated_at": now_ts, "created_at": state.get("created_at"), "init_cash": init_cash, "week_log": week_log,
    }


def _sharpe_text(m: ForwardMetrics) -> str:
    """Annualized Sharpe is noise over a few days: shown only once a verdict is possible."""
    return _num(m.sharpe) if m.days >= MIN_DAYS_FOR_VERDICT else "-"


def _status_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        if r["account"]["role"] == "control":
            continue
        s = r["verdicts"]["status"]
        out[s] = out.get(s, 0) + 1
    return out


def render(data: Mapping[str, Any]) -> str:
    rows = data["rows"]
    state = data["state"]
    label = week_label(data["year"], data["week"])
    ws, we = data["week_start"], data["week_end"]
    lines: List[str] = []
    kind = "final" if data["final"] else f"week to date, until {data['until']:%Y-%m-%d %H:%M} UTC"
    lines.append(f"# Paper fleet — weekly report {label} ({ws:%Y-%m-%d} to {(we - pd.Timedelta(days=1)):%Y-%m-%d}, {kind})")
    lines.append("")
    lines.append(f"Generated {data['generated_at']:%Y-%m-%d %H:%M} UTC from the fleet's journals (`journals/*.jsonl`). The forward record "
                 f"started {data['created_at']}. **SIMULATION ONLY**: virtual fills on public OKX market data, 10,000 virtual USDT per "
                 "account, costs 0.10 % fee + 0.05 % slippage per side. Nothing here is an order, and nothing here approves demo or live "
                 "trading for any configuration.")
    lines.append("")
    # -- in short
    ctl_rows = [r for r in rows if r["account"]["role"] == "control"]
    others = [r for r in rows if r["account"]["role"] != "control"]
    days = max((r["metrics"].days for r in rows), default=0.0)
    counts = _status_counts(rows)
    health = state.get("health") or {}
    lines.append("## In short (plain English)")
    lines.append("")
    lines.append(f"- The fleet has run forward for **{days:.1f} days** with {len(rows)} paper accounts: {len(others) - 1 if any(r['account']['kind'] == 'portfolio' for r in rows) else len(others)} "
                 f"shortlisted configurations, the jointly sized portfolio and {len(ctl_rows)} controls. Public data "
                 f"{'is STALE (no fresh candles)' if health.get('stale') else 'is fresh'} as of the last cycle ({state.get('last_cycle')}).")
    hold_ctl = [r for r in ctl_rows if r["account"]["kind"] == "sleeve"]
    bh_ctl = [r for r in ctl_rows if r["account"]["kind"] == "buy_and_hold"]
    if hold_ctl:
        lines.append("- Controls: always long with the policy sizing made " + ", ".join(
            f"{_pct(r['metrics'].total_return)} ({r['account']['instrument']} {r['account']['timeframe']})" for r in hold_ctl)
            + "; plain buy-and-hold made " + ", ".join(f"{_pct(r['metrics'].total_return)} ({r['account']['instrument']} {r['account']['timeframe']})" for r in bh_ctl) + ".")
    can_rank = days >= MIN_DAYS_FOR_VERDICT
    if can_rank:
        ranked = sorted([r for r in others if r["metrics"].sharpe is not None], key=lambda r: (r["metrics"].sharpe, r["metrics"].total_return), reverse=True)
        ranked += [r for r in others if r["metrics"].sharpe is None]
    else:
        ranked = sorted(others, key=lambda r: (r["account"].get("shortlist_rank") or 99))
    if can_rank and ranked and ranked[0]["metrics"].sharpe is not None:
        top = ranked[0]
        meaningful = days >= MIN_DAYS_FOR_SHARPE
        lines.append(f"- Best risk-adjusted so far: **{top['account']['label']}** ({_pct(top['metrics'].total_return)}, Sharpe "
                     f"{_num(top['metrics'].sharpe)})" + ("" if meaningful else f" — **not meaningful yet**: a ranking needs about {MIN_DAYS_FOR_SHARPE:.0f} days of data."))
    else:
        lines.append(f"- No ranking yet: the first {MIN_DAYS_FOR_VERDICT:.0f} days are mostly noise (the table below keeps the research's order).")
    if counts:
        lines.append("- Against their backtest: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) + ".")
    alarms = [r for r in rows if r["verdicts"]["drawdown"] == "ALARM"]
    if alarms:
        lines.append("- **Drawdown alarm**: " + ", ".join(r["account"]["account_id"] for r in alarms)
                     + " fell more than 1.5 times the worst drawdown of its whole backtest. Treat it as evidence against that configuration.")
    lines.append("- A good forward record is evidence for a later owner decision (plan row G7), not the decision itself.")
    lines.append("")
    # -- controls
    lines.append("## Controls (read these first)")
    lines.append("")
    lines.append("A timing rule earns its place only by beating these forward. *Always long, policy sizing* is the research's `hold` "
                 "with the same vol target, crash filter and drawdown ladder as every configuration; *plain buy-and-hold* is all-in, no stop.")
    lines.append("")
    lines.append("| Account | Series | Days | Return | Max DD | Sharpe | Exposure | Backtest CAGR / max DD | Holdout (12 m) | Status |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---|---|---|")
    for r in ctl_rows:
        m, acc = r["metrics"], r["account"]
        wf = (acc.get("expectations") or {}).get("walk_forward") or {}
        hold = (acc.get("expectations") or {}).get("holdout") or {}
        lines.append(f"| `{acc['account_id']}` | {acc['instrument']} {acc['timeframe']} | {m.days:.1f} | {_pct(m.total_return)} | {_pct(m.max_drawdown, False)} | "
                     f"{_sharpe_text(m)} | {_pct(m.exposure, False)} | {_pct(_f(wf.get('cagr')))} / {_pct(_f(wf.get('max_drawdown')), False)} | "
                     f"{_pct(_f(hold.get('total_return'))) if hold else '-'} | {r['verdicts']['status']} |")
    lines.append("")
    # -- ranking
    lines.append("## Ranking — configurations and the portfolio, by forward Sharpe")
    lines.append("")
    if not can_rank:
        lines.append(f"*No ranking yet* ({days:.0f} of {MIN_DAYS_FOR_VERDICT:.0f} days): listed in the research's shortlist order; Sharpe is shown from "
                     f"{MIN_DAYS_FOR_VERDICT:.0f} days on.")
        lines.append("")
    elif days < MIN_DAYS_FOR_SHARPE:
        lines.append(f"*Not meaningful yet* ({days:.0f} of {MIN_DAYS_FOR_SHARPE:.0f} days): read the status column, not the order.")
        lines.append("")
    lines.append("| # | Account | Return | vs its control | vs buy-and-hold | Sharpe | Max DD | Entries | Closed | Win/PF | Fees | Expected return (band) | Return | Sharpe band | Drawdown | Trade count | Holdout pace | Status |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---|---|---|---|---|---|")
    for i, r in enumerate(ranked, start=1):
        m, v, acc = r["metrics"], r["verdicts"], r["account"]
        rb = v.get("return_band")
        band = f"{_pct(rb[0])} ({_pct(rb[1])} to {_pct(rb[2])})" if rb else "-"
        pf = "∞" if m.profit_factor == float("inf") else _num(m.profit_factor)
        win = f"{m.wins}/{m.closed_trades} · {pf}" if m.closed_trades else "-"
        pooled = acc["kind"] == "portfolio"
        fees = "in returns" if pooled else _num(m.fees, "{:.2f}")
        entries = f"{m.entries} (pooled)" if pooled else str(m.entries)
        lines.append(f"| {i} | `{acc['account_id']}` | {_pct(m.total_return)} | {_pct(r['vs_control'])} | {_pct(r['vs_buy_and_hold'])} | "
                     f"{_sharpe_text(m)} | {_pct(m.max_drawdown, False)} | {entries} | {m.closed_trades} | {win} | {fees} | {band} | "
                     f"{v['return']} | {v['sharpe']} | {v['drawdown']} | {v['entries']} | {v['holdout']} | **{v['status']}** |")
    lines.append("")
    lines.append("The portfolio's entries, closed trades and win/PF are pooled over its six full-size sleeves (as the research pooled them); "
                 "its costs are inside its daily returns.")
    lines.append("")
    lines.append("Configurations (shortlist rank → account): " + "; ".join(f"`{r['account']['account_id']}` = {r['account']['label']}" for r in others) + ".")
    lines.append("")
    # -- this week
    lines.append(f"## This week ({ws:%Y-%m-%d} to {min(data['until'], we):%Y-%m-%d %H:%M} UTC)")
    lines.append("")
    lines.append("| Account | Week return | Entries | Exits | Fees | Position now | Last decision |")
    lines.append("|---|---:|---:|---:|---:|---|---|")
    for r in rows:
        m, acc, wk = r["metrics"], r["account"], r["week"]
        pos = f"long {_pct(m.allocation_now, False)} of equity" if m.in_position else "flat"
        dec = r.get("last_decision") or {}
        sig = (dec.get("signal") or {}).get("action")
        desired = (dec.get("diagnostics") or {}).get("desired")
        last = "error: " + str(r.get("decision_error")) if r.get("decision_error") else (f"{sig}{' (blocked by a filter)' if sig == 'long' and desired is False else ''}" if sig else "-")
        fees = "in returns" if acc["kind"] == "portfolio" else _num(wk["fees"])
        lines.append(f"| `{acc['account_id']}` | {_pct(wk['return'])} | {wk['entries']} | {wk['closed_trades']} | {fees} | {pos} | {last} |")
    lines.append("")
    # -- data and health
    lines.append("## Data and health")
    lines.append("")
    for key, s in sorted((state.get("series") or {}).items()):
        lines.append(f"- {key}: anchor bar {s.get('anchor') or 'not yet'}, last bar {s.get('last_bar') or '-'}, {s.get('bars', 0)} bars processed, "
                     f"{s.get('gaps', 0)} missing bars skipped.")
    newest = (health.get("newest_candle") or {})
    lines.append(f"- Newest 1H candle: " + ", ".join(f"{k} {v}" for k, v in newest.items()) + f"; last cycle {state.get('last_cycle')} "
                 f"({state.get('cycles')} cycles since the start).")
    for key, fit in sorted((state.get("fits") or {}).items()):
        f = fit.get("fitted") or {}
        lines.append(f"- Regime model {key}: trained {fit.get('train_start')} → {fit.get('train_end')}, active until {fit.get('active_until')}"
                     + (f", bear state share in training {f.get('train_bear_share', 0) * 100:.0f} %" if f else f", **fit failed ({fit.get('error')}): entries blocked**") + ".")
    lines.append(f"- Positioning data for the S5 filter: {state.get('positioning_source')} (OKX swap funding and open interest; the research used "
                 "Binance's history — see the method notes).")
    late = sorted((aid, m.get("created_at")) for aid, m in (state.get("accounts") or {}).items()
                  if m.get("created_at") and m.get("created_at") != state.get("created_at") and not m.get("retired_at"))
    if late:
        lines.append("- Accounts added after the fleet started (each counts from its own start): "
                     + ", ".join(f"`{aid}` since {when}" for aid, when in late) + ".")
    retired = sorted((aid, m.get("retired_at")) for aid, m in (state.get("accounts") or {}).items() if m.get("retired_at"))
    if retired:
        lines.append("- Retired accounts (no longer in the shortlist; their journals are kept): "
                     + ", ".join(f"`{aid}` on {when}" for aid, when in retired) + ".")
    last_fomc = max(FOMC_DECISION_DAYS)
    gen = data["generated_at"]
    if pd.Timestamp(last_fomc, tz="UTC") < gen + pd.Timedelta(days=FOMC_WARNING_DAYS):
        lines.append(f"- **FOMC calendar runs out**: the S0 filter's last built-in FOMC date is {last_fomc}; extend `research/events.py` "
                     "(plan row R7 verifies the dates) or the filter stops blocking FOMC windows after it.")
    stale = [r for r in data["week_log"] if r.get("type") in ("data_stale", "data_fresh")]
    if stale:
        lines.append("- Data freshness changes this week: " + "; ".join(f"{r['type']} at {r['now']}" for r in stale) + ".")
    errs = [e for r in data["week_log"] if r.get("type") == "cycle" for e in (r.get("errors") or [])]
    if errs:
        lines.append(f"- {len(errs)} cycle errors this week (first: {errs[0]}). Decisions that failed are listed in the journals as "
                     "`decision_error`; such an account keeps its stops but makes no new entry until the next good decision.")
    notes = [n for r in rows for n in r["notes"]]
    for n in notes[:20]:
        if n.get("type") == "gap":
            lines.append(f"- Gap: {n.get('series')} skipped {n.get('missing_bars')} bar(s) from {n.get('missing_from')} (a 1H candle never arrived).")
    seen = set()
    for n in notes:
        if n.get("type") == "regime_fit" and n.get("fit_id") not in seen:
            seen.add(n.get("fit_id"))
            lines.append(f"- Regime model refitted: {n.get('fit_id')} (train {n.get('train')}).")
    lines.append("")
    # -- reading the bands
    lines.append("## How to read the bands (fixed before the first forward bar)")
    lines.append("")
    lines.append(f"- **Return**: the backtest's yearly return (walk-forward CAGR) stretched over the forward days, ± {BAND_Z:.0f} standard deviations "
                 "of its yearly volatility over the same time. *within* means the forward result is the kind of number the backtest would produce; "
                 "*below* means worse than the backtest would plausibly give; *above* better.")
    lines.append(f"- **Sharpe** (from {MIN_DAYS_FOR_SHARPE:.0f} days): the backtest Sharpe ± {BAND_Z:.0f} standard errors of a Sharpe measured over the forward time.")
    lines.append(f"- **Drawdown**: *above backtest worst* when the forward fall from a peak is larger than the worst of the whole 5-year walk-forward; "
                 f"*ALARM* above {DD_ALARM_MULTIPLE:g} times it.")
    lines.append("- **Trade count**: the backtest's entries per year over the forward time, ± 2 Poisson deviations (*fewer*, *within*, *more*).")
    lines.append("- **Holdout pace**: the same return band built from the configuration's untouched 12-month holdout instead of the walk-forward "
                 "(only where the research evaluated one).")
    lines.append(f"- Nothing gets a verdict before {MIN_DAYS_FOR_VERDICT:.0f} days. Changing a band after seeing results would be tuning on the "
                 "forward test; a different band is a new, pre-registered study.")
    lines.append("")
    lines.append("## Method notes")
    lines.append("")
    lines.append("- Same rules as the research (`docs/research/ENSEMBLE_V1C_REPORT.md`): the research candidates through the reviewed "
                 "`Strategy` contract, the S0 no-trade filter with the FOMC calendar, the policy sizing `vt10/30 crash15/90dh ladder`, "
                 "the regime-v2 entry gate, the exit brackets, next-bar-open fills, stops checked on each bar's low. The bar-by-bar engine "
                 "is parity-tested against the research engine.")
    lines.append("- Known differences from the research: (1) the S5 positioning filter reads OKX's own swap funding and open interest, "
                 "which arrive in time, instead of Binance's history files, which arrive a day late; (2) at a regime refit the gate is "
                 "recomputed under the new model, which can close a position the new model would not have entered (the research started "
                 "every window flat there); (3) 4H bars are rebuilt from 1H candles on the UTC clock (identical "
                 "to OKX's 4H bars on 99.97 % of the history); (4) the portfolio's weights and vol estimate start from 120 days of simulated "
                 "sleeve history before the start (not counted), and moving money between its sleeves costs nothing, as in the research.")
    lines.append("- Every account starts flat at the first bar that closed after it was created, and — except plain buy-and-hold — "
                 "restarts flat every 180 days, as each walk-forward test window did (an open position is closed at the window's last "
                 "close, costs included): the research's numbers include those restarts, and without them a long-held, reduce-only "
                 "position could only ever shrink. A fill never uses a price from before its decision.")
    return "\n".join(lines) + "\n"


def write_week(paths: FleetPaths, now: datetime, *, year: Optional[int] = None, week: Optional[int] = None) -> Path:
    data = build_report_data(paths, now, year=year, week=week)
    paths.reports.mkdir(parents=True, exist_ok=True)
    out = paths.reports / f"weekly-{week_label(data['year'], data['week'])}.md"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(render(data), encoding="utf-8")
    tmp.replace(out)
    return out


class ReportScheduler:
    """Rewrite the current week's report at most every ``every_minutes`` and finalize the previous week once."""

    def __init__(self, paths: FleetPaths, *, every_minutes: float = 60.0) -> None:
        self.paths = paths
        self.every = timedelta(minutes=float(every_minutes))
        self._last: Optional[datetime] = None

    def __call__(self, now: datetime) -> List[str]:
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        written: List[str] = []
        if self._last is not None and now - self._last < self.every and now.date() == self._last.date():
            return written
        y, w = iso_week(now.date())
        prev = now.date() - timedelta(days=7)
        py, pw = iso_week(prev)
        prev_path = self.paths.reports / f"weekly-{week_label(py, pw)}.md"
        state = read_state(self.paths.state_file) or {}
        created = state.get("created_at")
        if created and _ts(created) < week_bounds(py, pw)[1]:
            if not prev_path.exists() or "week to date" in prev_path.read_text(encoding="utf-8").splitlines()[0]:
                written.append(str(write_week(self.paths, now, year=py, week=pw)))
        written.append(str(write_week(self.paths, now, year=y, week=w)))
        self._last = now
        return written
