"""Allocator v2 study (plan row R5b): v1 and v2 on the Sprint 2c portfolio's six full-size sleeves (SIMULATION ONLY).

Nothing is re-selected. The six sleeves of the jointly sized BTC+ETH x S1/S2/S4
portfolio (``docs/research/ensemble_v1c_results.json``: per family and coin the
timeframe Sprint 2c chose, the rule parameters its walk-forward selected most
often) are replayed at FULL size over the same walk-forward test windows, now
also recording whether each sleeve was long at every day's close. Then:

1. **Reproduction check** — allocator v1 (:func:`research.portfolio.combine_sized`)
   on the rebuilt sleeves must give Sprint 2c's stored portfolio numbers, or
   the study stops: the comparison is only fair on the very same sleeves.
2. **Allocator v2** with the configuration fixed before the first run
   (:data:`research.allocator.DEFAULT_ALLOCATOR_V2`), plus two ablations (each
   new brake alone) that explain the result and are never candidates.
3. **The Sprint 2c portfolio gates**, unchanged (``acceptance_check_v1c`` with the
   pooled sleeve trades, exactly as Sprint 2c judged v1).
4. **The 12-month holdout** — opened only when v2 passed the walk-forward gates
   (and only with ``evaluate_holdout``): the six sleeves start flat at the
   holdout and run on it with the same parameters, the estimators are warmed up
   on the walk-forward history, and v1 runs beside v2 as the paired reference
   (a reference, not a selection).

Coin correlations use one close per UTC day from the 1H candles (the close of
the 23:00 candle, the same price the 4H/6H bars close at). Public data from the
research lake only; nothing here can reach an order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.datalake.layout import LakeLayout
from research.allocator import (
    DEFAULT_ALLOCATOR_V2,
    AllocatorRun,
    AllocatorV2Config,
    allocate_v2,
    brake_stats,
    curve_metrics,
    daily_closes_to_returns,
    reference_stats,
)
from research.data import load_candles, load_or_resample_candles, positioning_context, split_holdout
from research.engine import Costs
from research.gated_walkforward import _window_returns, window_frames
from research.portfolio import align_sleeves, combine_sized, to_daily_returns
from research.report_v1c import acceptance_check_v1c, yearly_gate_v2
from research.sizing import LadderConfig
from research.strategies import get_candidate
from research.strategies.base import days_to_bars
from research.strategies.s0_filters import NoTradeConfig
from research.sweep import build_frames, simulate_slice
from research.walkforward import WalkForwardConfig, make_windows

PORTFOLIO_NAME = "S1+S2+S4 x BTC+ETH — jointly sized, vol target 15%, ladder 7.5/15"
TARGET_VOL = 0.15
PARITY_TOLERANCE = 2e-6  # the results file rounds to 6 decimals
STATUS = "SIMULATION ONLY - research evidence for the paper fleet; nothing approved"
ABLATIONS: Tuple[Tuple[str, AllocatorV2Config], ...] = (
    ("correlation cap only", AllocatorV2Config(loss_limit=None)),
    ("weekly loss limit and cooldown only", AllocatorV2Config(group_cap=None)),
)


class StudyError(RuntimeError):
    """The study cannot be trusted (the rebuilt sleeves do not reproduce Sprint 2c, the data is missing)."""


@dataclass(frozen=True)
class SleeveDef:
    name: str  # "S1/BTC/6H"
    candidate: str
    instrument: str
    timeframe: str
    params: Mapping[str, Any]


@dataclass
class SleeveHistory:
    """One full-size sleeve: bar returns, long/flat after every bar, its trades."""

    sleeve: SleeveDef
    returns: pd.Series
    allocation: pd.Series
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)

    def daily(self) -> pd.Series:
        return to_daily_returns(self.returns)

    def positions(self) -> pd.Series:
        return end_of_day_positions(self.allocation)


def end_of_day_positions(allocation: pd.Series) -> pd.Series:
    """Long at each UTC day's close = allocated after the last bar that opened that day (bars belong to the day they open in)."""
    if allocation.empty:
        return pd.Series(dtype=bool)
    days = allocation.index.tz_convert("UTC").floor("D")
    last = allocation.astype(float).groupby(days).last()
    last.index.name = "day"
    return last > 0.0


def daily_coin_closes(layout: LakeLayout, instruments: Sequence[str]) -> pd.DataFrame:
    """One close per UTC day per coin from the 1H candles (the last candle that opened that day)."""
    out = {}
    for inst in instruments:
        df = load_candles(layout, inst, "1H")
        if df.empty:
            raise StudyError(f"no 1H candles for {inst} in the lake")
        close = df["close"].astype(float)
        out[inst] = close.groupby(close.index.floor("D")).last()
    frame = pd.DataFrame(out).sort_index()
    frame.index.name = "day"
    full = pd.date_range(frame.index[0], frame.index[-1], freq="D", tz="UTC", name="day")
    return frame.reindex(full)


def _params(raw: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items()}


def portfolio_entry(results_doc: Mapping[str, Any]) -> Mapping[str, Any]:
    found = [p for p in results_doc.get("portfolios", []) if p.get("regime") == "none" and (p.get("sizing") or {}).get("target_vol") == TARGET_VOL]
    if len(found) != 1:
        raise StudyError(f"expected one jointly sized {TARGET_VOL:.0%} portfolio without a regime gate in the results, found {len(found)}")
    return found[0]


def sleeve_defs(results_doc: Mapping[str, Any]) -> List[SleeveDef]:
    entry = portfolio_entry(results_doc)
    coins = {"BTC": "BTC-USDT", "ETH": "ETH-USDT"}
    out = []
    for name in sorted(entry["weights"]):
        family, short, tf = name.split("/")
        inst = coins[short]
        rows = [r for r in results_doc["results"] if r["candidate"] == family and r["instrument"] == inst and r["timeframe"] == tf
                and r["regime"]["mode"] == "none"]
        if len(rows) != 1:
            raise StudyError(f"expected one research result for {name}, found {len(rows)}")
        out.append(SleeveDef(name, family, inst, tf, _params(rows[0]["selected_params"])))
    return out


@dataclass(frozen=True)
class StudySettings:
    train_days: float = 540.0
    test_days: float = 180.0
    purge_days: float = 7.0
    holdout_months: int = 12
    fee_rate: float = 0.0010
    slippage_rate: float = 0.0005
    positioning_source: str = "binance"
    no_trade: NoTradeConfig = NoTradeConfig(scheduled_events=True)
    ladder: LadderConfig = LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30)
    vol_lookback_days: int = 30
    weight_lookback_days: int = 60

    @property
    def costs(self) -> Costs:
        return Costs(fee_rate=self.fee_rate, slippage_rate=self.slippage_rate)

    @classmethod
    def from_results(cls, results_doc: Mapping[str, Any]) -> "StudySettings":
        """The Sprint 2c settings as recorded in its results file (checked, never re-chosen)."""
        meta = results_doc.get("meta") or {}
        out = cls(train_days=float(meta["train_days"]), test_days=float(meta["test_days"]), purge_days=float(meta["purge_days"]),
                  holdout_months=int(meta["holdout_months"]), fee_rate=float(meta["fee_rate"]), slippage_rate=float(meta["slippage_rate"]),
                  positioning_source=str(meta["positioning_source"]))
        if meta.get("no_trade_label") not in (None, out.no_trade.label):
            raise StudyError(f"Sprint 2c used the no-trade filter {meta.get('no_trade_label')!r}, not {out.no_trade.label!r}")
        sizing = portfolio_entry(results_doc).get("sizing") or {}
        lad = sizing.get("ladder") or {}
        if (sizing.get("vol_lookback_days"), sizing.get("weight_lookback_days")) != (out.vol_lookback_days, out.weight_lookback_days) or not (
                math.isclose(lad.get("half_dd", -1), out.ladder.half_dd) and math.isclose(lad.get("flat_dd", -1), out.ladder.flat_dd)
                and int(lad.get("recovery_bars", -1)) == out.ladder.recovery_bars):
            raise StudyError("the Sprint 2c portfolio sizing differs from the study's")
        return out


def replay_full_size(df: pd.DataFrame, frames, windows, costs: Costs) -> Tuple[pd.Series, pd.Series, pd.DataFrame]:
    """The fixed rule over every test window at full size, starting flat in each (as ``replay_gated`` without a gate):
    stitched bar returns, the allocation after every bar, and the trades."""
    rets, alloc, trades = [], [], []
    for w in windows:
        lo, hi = w.train.start, w.test.stop
        sub = df.iloc[lo:hi]
        test_rel = slice(w.test.start - lo, hi - lo)
        res = simulate_slice(sub, window_frames(frames, lo, hi, None), test_rel, costs=costs, size_fraction=1.0, columns=[0])
        index = df.index[w.test]
        rets.append(_window_returns(res, 0, index))
        alloc.append(pd.Series(res.allocation[:, 0], index=index))
        trades.append(res.trades_for(0))
    frame = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    return pd.concat(rets).sort_index(), pd.concat(alloc).sort_index(), frame


def rebuild_sleeves(layout: LakeLayout, defs: Sequence[SleeveDef], settings: StudySettings, *, holdout: bool = False
                    ) -> Tuple[Dict[str, SleeveHistory], Dict[str, SleeveHistory]]:
    """Walk-forward (and, if asked, holdout) histories of every sleeve."""
    oos: Dict[str, SleeveHistory] = {}
    hold: Dict[str, SleeveHistory] = {}
    for sd in defs:
        df_all = load_or_resample_candles(layout, sd.instrument, sd.timeframe)
        if len(df_all) < 1000:
            raise StudyError(f"only {len(df_all)} {sd.timeframe} bars for {sd.instrument} in the lake")
        df_in, df_hold = split_holdout(df_all, holdout_months=settings.holdout_months)
        cfg = WalkForwardConfig(train_bars=days_to_bars(settings.train_days, sd.timeframe), test_bars=days_to_bars(settings.test_days, sd.timeframe),
                                purge_bars=days_to_bars(settings.purge_days, sd.timeframe))
        windows = make_windows(len(df_in), cfg)
        candidate = get_candidate(sd.candidate)
        ctx = positioning_context(layout, sd.instrument, sd.timeframe, source=settings.positioning_source)
        frames = build_frames(candidate, df_in, [dict(sd.params)], ctx, no_trade=settings.no_trade)
        r, a, t = replay_full_size(df_in, frames, windows, settings.costs)
        oos[sd.name] = SleeveHistory(sd, r, a, t)
        if holdout and len(df_hold):
            frames_all = build_frames(candidate, df_all, [dict(sd.params)], ctx, no_trade=settings.no_trade)
            sl = slice(len(df_in), len(df_all))
            res = simulate_slice(df_all, frames_all, sl, costs=settings.costs, size_fraction=1.0, columns=[0])
            index = df_all.index[sl]
            hold[sd.name] = SleeveHistory(sd, _window_returns(res, 0, index), pd.Series(res.allocation[:, 0], index=index), res.trades_for(0))
    return oos, hold


def frames_for(histories: Mapping[str, SleeveHistory]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Aligned daily returns (``align_sleeves``: the union of days, 0 = cash) and end-of-day positions."""
    daily = align_sleeves({n: h.returns for n, h in histories.items()})
    positions = pd.DataFrame({n: h.positions() for n, h in histories.items()}).reindex(columns=daily.columns)
    return daily, positions


def pooled_trades(histories: Mapping[str, SleeveHistory]) -> Tuple[int, float]:
    """Trade count and profit factor pooled over sleeves, as Sprint 2c pooled them (999 when nothing lost, 0 without trades)."""
    frames = [h.trades for h in histories.values() if h.trades is not None and len(h.trades)]
    if not frames:
        return 0, 0.0
    pnl = pd.concat(frames, ignore_index=True)["pnl"].to_numpy(dtype=float)
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    return int(pnl.size), (float(wins / losses) if losses > 0 else (999.0 if wins > 0 else 0.0))


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def summarize(equity: pd.Series, *, pooled_n: int, pooled_pf: Optional[float]) -> Dict[str, Any]:
    """Metrics, the yearly gate and the Sprint 2c portfolio acceptance of one daily curve."""
    metrics = curve_metrics(equity)
    yg = yearly_gate_v2(equity)
    acc = acceptance_check_v1c(dict(metrics, profit_factor=pooled_pf, n_trades=pooled_n), yg, {"share_above_threshold": 1.0})
    acc["note"] = ("robustness gate not evaluated at portfolio level (sleeves carry their own); profit factor and trade count are pooled "
                   "from the policy-sized sleeves of Sprint 2c (the same sleeves for v1 and v2)")
    days = len(equity)
    return {"metrics": metrics, "yearly_gate": yg, "acceptance": acc, "days": days, "years": days / 365.25,
            "first_day": str(equity.index[0].date()) if days else None, "last_day": str(equity.index[-1].date()) if days else None}


def run_study(layout: LakeLayout, results_doc: Mapping[str, Any], *, cfg: AllocatorV2Config = DEFAULT_ALLOCATOR_V2,
              evaluate_holdout: bool = False) -> Dict[str, Any]:
    settings = StudySettings.from_results(results_doc)
    entry = portfolio_entry(results_doc)
    defs = sleeve_defs(results_doc)
    assets = {sd.name: sd.instrument for sd in defs}
    oos, _ = rebuild_sleeves(layout, defs, settings)
    daily, positions = frames_for(oos)
    closes = daily_coin_closes(layout, sorted(set(assets.values())))
    coin_returns = daily_closes_to_returns(closes)
    kw = dict(target_vol=TARGET_VOL, vol_lookback_days=settings.vol_lookback_days, weight_lookback_days=settings.weight_lookback_days,
              ladder=settings.ladder)

    # 1. Reproduction: v1 on the rebuilt sleeves is Sprint 2c's portfolio, or nothing below is comparable.
    v1 = combine_sized(daily, name=PORTFOLIO_NAME, ladder=settings.ladder, target_vol=TARGET_VOL, vol_lookback_days=settings.vol_lookback_days,
                       weight_lookback_days=settings.weight_lookback_days)
    stored = entry["metrics"]
    parity = {k: {"stored": stored.get(k), "rebuilt": float(v1.metrics[k])} for k in ("cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "total_return")}
    parity["days"] = {"stored": entry.get("days"), "rebuilt": int(len(daily))}
    bad = [k for k, v in parity.items() if k != "days" and (v["stored"] is None or abs(float(v["stored"]) - v["rebuilt"]) > PARITY_TOLERANCE)]
    if bad or parity["days"]["stored"] != parity["days"]["rebuilt"]:
        raise StudyError(f"the rebuilt sleeves do not reproduce Sprint 2c's portfolio ({bad or 'days'}): {parity}")

    pooled_n, pooled_pf = int(entry.get("pooled_trades") or 0), entry.get("pooled_profit_factor")
    v2 = allocate_v2(daily, positions, coin_returns, assets, cfg=cfg, name="allocator v2", **kw)
    if not np.allclose(v2.reference_equity.to_numpy(), v1.equity.to_numpy(), rtol=1e-12, atol=0.0):
        raise StudyError("the paired v1 reference inside allocator v2 differs from combine_sized")
    stats = brake_stats(v2)
    out: Dict[str, Any] = {
        "status": STATUS,
        "meta": {"portfolio": PORTFOLIO_NAME, "sleeves": [{"name": sd.name, "candidate": sd.candidate, "instrument": sd.instrument, "timeframe": sd.timeframe,
                                                           "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in sd.params.items()}} for sd in defs],
                 "settings": {"train_days": settings.train_days, "test_days": settings.test_days, "purge_days": settings.purge_days,
                              "holdout_months": settings.holdout_months, "fee_rate": settings.fee_rate, "slippage_rate": settings.slippage_rate,
                              "positioning_source": settings.positioning_source, "no_trade": settings.no_trade.label,
                              "target_vol": TARGET_VOL, "vol_lookback_days": settings.vol_lookback_days,
                              "weight_lookback_days": settings.weight_lookback_days, "ladder": settings.ladder.to_dict()},
                 "allocator_v2": cfg.to_dict(), "default_configuration": cfg == DEFAULT_ALLOCATOR_V2,
                 "configuration_source": "research.allocator.DEFAULT_ALLOCATOR_V2",
                 "walk_forward_last_bar": {name: h.returns.index[-1].isoformat() for name, h in sorted(oos.items())},
                 "sleeves_passed_on_their_own": _sleeves_passed(results_doc, defs),
                 "calendar_complete": bool(len(daily) == (daily.index[-1] - daily.index[0]).days + 1),
                 "coin_correlation_source": "one close per UTC day from the 1H candles"},
        "reproduction": parity,
        "walk_forward": {
            "v1": dict(summarize(v1.equity, pooled_n=pooled_n, pooled_pf=pooled_pf), brakes=reference_stats(stats)),
            "v2": dict(summarize(v2.equity, pooled_n=pooled_n, pooled_pf=pooled_pf), brakes=stats),
            "ablations": [],
            "pooled_trades": pooled_n, "pooled_profit_factor": pooled_pf,
            "coin_correlation": _correlation_summary(v2),
        },
        "holdout": None,
    }
    for label, acfg in ABLATIONS:
        run = allocate_v2(daily, positions, coin_returns, assets, cfg=acfg, name=label, **kw)
        out["walk_forward"]["ablations"].append(dict(summarize(run.equity, pooled_n=pooled_n, pooled_pf=pooled_pf),
                                                     label=label, allocator=acfg.to_dict(), brakes=brake_stats(run)))
    passed = bool(out["walk_forward"]["v2"]["acceptance"]["passed"])
    if not passed:
        out["holdout"] = {"evaluated": False, "reason": "allocator v2 did not pass the walk-forward gates: the holdout stays untouched"}
    elif not evaluate_holdout:
        out["holdout"] = {"evaluated": False, "reason": "not requested (run with --evaluate-holdout)"}
    else:
        out["holdout"] = _holdout(layout, defs, settings, cfg, assets, oos, coin_returns, kw)
    out["sprint_2c_holdout_context"] = holdout_context(results_doc)
    out["daily"] = {"v1": _series(v1.equity), "v2": _series(v2.equity)}
    return _finite(out)


def _sleeves_passed(results_doc: Mapping[str, Any], defs: Sequence[SleeveDef]) -> Dict[str, bool]:
    """Did each sleeve pass the Sprint 2c walk-forward gates on its own (its own policy-sized row in the results)?"""
    out = {}
    for sd in defs:
        rows = [r for r in results_doc["results"] if r["candidate"] == sd.candidate and r["instrument"] == sd.instrument
                and r["timeframe"] == sd.timeframe and r["regime"]["mode"] == "none"]
        out[sd.name] = bool(rows and (rows[0].get("acceptance") or {}).get("passed"))
    return out


def holdout_context(results_doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """What Sprint 2c's own holdout said about the controls and the configurations it opened it for (for reading this study's holdout)."""
    out = []
    for r in results_doc.get("results", []):
        h = r.get("holdout")
        if not h:
            continue
        out.append({"candidate": r["candidate"], "instrument": r["instrument"], "timeframe": r["timeframe"], "regime": (r.get("regime") or {}).get("mode"),
                    "control": r["candidate"] in ("hold", "buy_and_hold"), "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"),
                    "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades")})
    return sorted(out, key=lambda x: (not x["control"], x["candidate"], x["instrument"], x["timeframe"]))


def _correlation_summary(run: AllocatorRun) -> Dict[str, Any]:
    values = [v for r in run.records for v in r["correlations"].values() if v is not None]
    if not values:
        return {}
    arr = np.array(values)
    return {"median": float(np.median(arr)), "p10": float(np.quantile(arr, 0.10)), "p90": float(np.quantile(arr, 0.90)),
            "share_at_or_above_threshold": float((arr >= run.config["allocator"]["corr_threshold"]).mean())}


def _series(equity: pd.Series) -> Dict[str, float]:
    return {str(d.date()): round(float(v), 8) for d, v in equity.items()}


def _holdout(layout, defs, settings: StudySettings, cfg: AllocatorV2Config, assets, oos: Mapping[str, SleeveHistory], coin_returns: pd.DataFrame,
             kw: Mapping[str, Any]) -> Dict[str, Any]:
    """v2 and the paired v1 reference on the untouched last months, the estimators warmed up on the walk-forward history."""
    _, hold = rebuild_sleeves(layout, defs, settings, holdout=True)
    if len(hold) != len(defs):
        return {"evaluated": False, "reason": "no holdout bars for every sleeve"}
    # Book full UTC days only: from the first day on which EVERY sleeve is in its holdout from midnight, to the last day on
    # which every sleeve's final bar closed (a day that also holds walk-forward bars of a sleeve, or a cut-off last day, is left out).
    latest_first = max(h.returns.index[0] for h in hold.values())
    start = latest_first.floor("D") if latest_first == latest_first.floor("D") else latest_first.floor("D") + pd.Timedelta(days=1)
    end = min((h.returns.index[-1] + pd.Timedelta(hours=int(h.sleeve.timeframe[:-1]))).floor("D") - pd.Timedelta(days=1) for h in hold.values())
    first = min(h.returns.index[0] for h in oos.values()).floor("D")
    last = max(h.returns.index[-1] for h in hold.values()).floor("D")  # the frames hold every bar; only full days are booked
    calendar = pd.date_range(first, last, freq="D", tz="UTC", name="day")
    daily = pd.DataFrame(0.0, index=calendar, columns=sorted(assets))
    positions = pd.DataFrame(False, index=calendar, columns=sorted(assets))
    for name in sorted(assets):
        # One bar history per sleeve (walk-forward windows, then the holdout from a flat start): the day the holdout begins compounds both.
        bars = pd.concat([oos[name].returns, hold[name].returns]).sort_index()
        alloc = pd.concat([oos[name].allocation, hold[name].allocation]).sort_index()
        d = to_daily_returns(bars)
        daily.loc[d.index, name] = d.to_numpy()
        p = end_of_day_positions(alloc).astype(float).reindex(calendar).ffill().fillna(0.0)
        positions[name] = (p > 0.5).to_numpy()
    if end < start:
        return {"evaluated": False, "reason": "the holdout holds no full day for every sleeve"}
    run = allocate_v2(daily.loc[:end], positions.loc[:end], coin_returns, assets, cfg=cfg, start=start, name="allocator v2 (holdout)", **kw)
    n_trades, pf = pooled_trades(hold)
    stats = brake_stats(run)
    sleeves = {}
    for name, h in sorted(hold.items()):
        n_s, pf_s = pooled_trades({name: h})
        sleeves[name] = {"total_return": float((1.0 + h.returns).prod() - 1.0), "n_trades": n_s, "profit_factor": pf_s,
                         "exposure": float(h.allocation.mean())}
    growth = (1.0 + coin_returns.reindex(run.days).fillna(0.0)).prod() - 1.0
    coins = {inst: float(growth[inst]) for inst in sorted(set(assets.values()))}
    out: Dict[str, Any] = {"evaluated": True, "first_day": str(run.days[0].date()), "last_day": str(run.days[-1].date()), "days": int(len(run.days)),
                           "pooled_trades": n_trades, "pooled_profit_factor": pf, "sleeves": sleeves, "coins_buy_and_hold": coins,
                           "holdout_first_bar": {name: h.returns.index[0].isoformat() for name, h in sorted(hold.items())},
                           "holdout_last_bar": {name: h.returns.index[-1].isoformat() for name, h in sorted(hold.items())},
                           "note": "Full-size sleeves start flat at the holdout; full UTC days only are booked (from the first day every sleeve is "
                                   "in its holdout from midnight to the last day every sleeve's final bar closed); weights, vol scale and "
                                   "correlations are warmed up on the walk-forward history; v1 is the paired reference on the same sleeves "
                                   "(a reference, not a selection)"}
    for key, equity, metrics, brakes in (("v2", run.equity, run.metrics, stats), ("v1", run.reference_equity, run.reference_metrics, reference_stats(stats))):
        confirmed = bool(metrics["total_return"] > 0 and (pf or 0.0) > 1.0 and n_trades >= 10)
        out[key] = {"metrics": metrics, "confirmed": confirmed, "brakes": brakes, "daily": _series(equity)}
    return out


# -- report ----------------------------------------------------------------------------


def _pct(v: Any, signed: bool = True) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return f"{float(v) * 100:+.1f}%" if signed else f"{float(v) * 100:.1f}%"


def _num(v: Any, fmt: str = "{:.2f}") -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return fmt.format(float(v))


def _times(n: Any) -> str:
    n = int(n or 0)
    return "never" if n == 0 else ("once" if n == 1 else f"{n} times")


GATE_WORDS = {
    "pf_gt_1_2": "profit factor above 1.2", "max_dd_lt_20pct": "max drawdown below 20%", "sharpe_gt_0_7": "Sharpe above 0.7",
    "calmar_gt_0_5": "Calmar above 0.5", "rolling_12m_75pct_positive": "75% of rolling 12-month windows positive",
    "no_calendar_year_below_minus_10pct": "no calendar year below -10%", "enough_trades": "at least 30 trades", "robust_pm30pct": "robust to ±30% parameters",
}


def _gates(acc: Mapping[str, Any]) -> str:
    failed = acc.get("failed") or []
    return "none — PASS" if not failed else ", ".join(GATE_WORDS.get(g, g) for g in failed)


def _row(label: str, s: Mapping[str, Any]) -> str:
    m, yg, b = s["metrics"], s["yearly_gate"], s.get("brakes") or {}
    return (f"| {label} | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'), False)} | {_num(m.get('sharpe'))} | {_pct(m.get('max_drawdown'), False)} | "
            f"{_num(m.get('calmar'))} | {_pct(yg.get('rolling_positive_share'), False)} | {_pct(yg.get('worst_calendar_year_return'))} | "
            f"{_pct(b.get('invested_share_mean'), False)} | {_gates(s['acceptance'])} |")


def _growth_share_of_best_years(yearly: Mapping[Any, float], n: int = 2) -> Tuple[Optional[float], List[str]]:
    """Share of the total log growth that came from the ``n`` best calendar years (and which years)."""
    logs = {str(y): math.log1p(float(r)) for y, r in yearly.items() if r is not None and float(r) > -1.0}
    total = sum(logs.values())
    if not logs or total <= 0:
        return None, []
    best = sorted(logs, key=logs.get, reverse=True)[:n]
    return sum(logs[y] for y in best) / total, sorted(best)


def _holdout_facts(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The holdout's plain-English facts, each one derived from the numbers, so a re-run on other data cannot print a false sentence."""
    hold = result.get("holdout") or {}
    if not hold.get("evaluated"):
        return {}
    r1, r2 = float(hold["v1"]["metrics"]["total_return"]), float(hold["v2"]["metrics"]["total_return"])
    coins = hold.get("coins_buy_and_hold") or {}
    ctx = result.get("sprint_2c_holdout_context") or []
    controls = [float(c["total_return"]) for c in ctx if c.get("control") and c.get("total_return") is not None]
    passes = [c for c in ctx if not c.get("control")]
    contradicted = [c for c in passes if not ((c.get("total_return") or 0.0) > 0 and (c.get("profit_factor") or 0.0) > 1.0
                                             and int(c.get("n_trades") or 0) >= 10)]
    if coins and all(v < 0 for v in coins.values()):
        market = "a falling market"
    elif coins and all(v > 0 for v in coins.values()):
        market = "a rising market"
    else:
        market = "a mixed market"
    if r2 > r1 + 1e-12:
        effect = ("The brakes cut the loss but did not turn it into a gain." if r2 < 0 else
                  "The brakes turned a loss into a gain." if r1 < 0 else "The brakes added return.")
    elif r2 < r1 - 1e-12:
        effect = "The brakes cost return."
    else:
        effect = "The brakes made no difference."
    return {"r1": r1, "r2": r2, "coins": coins, "market": market, "effect": effect, "both_lost": r1 < 0 and r2 < 0,
            "both_gained": r1 > 0 and r2 > 0, "v2_confirmed": bool(hold["v2"]["confirmed"]), "v1_confirmed": bool(hold["v1"]["confirmed"]),
            "controls": controls, "passes": len(passes), "contradicted": len(contradicted),
            "worse_than_every_control": bool(controls) and max(r1, r2) < min(controls)}


def render_report(result: Mapping[str, Any]) -> str:
    wf = result["walk_forward"]
    v1, v2 = wf["v1"], wf["v2"]
    b1, b2 = v1["brakes"], v2["brakes"]
    m1, m2 = v1["metrics"], v2["metrics"]
    cfg = result["meta"]["allocator_v2"]
    hold = result.get("holdout") or {}
    facts = _holdout_facts(result)
    passed = bool(v2["acceptance"]["passed"])
    cap_pct = f"{cfg['group_cap'] * 100:.0f} %"
    lines: List[str] = []
    lines.append("# Allocator v2 — the jointly sized portfolio with extra brakes (walk-forward, SIMULATION ONLY)")
    lines.append("")
    lines.append(f"Plan row R5b (master plan Sprint 5, item 2). {result['status']}. Generated by `scripts/run_allocator_v2.py` from the Sprint 2c "
                 "results (`docs/research/ensemble_v1c_results.json`) and the research data lake; numbers in "
                 "`docs/research/allocator_v2_results.json`.")
    lines.append("")
    lines.append("## In short (plain English)")
    lines.append("")
    lines.append(f"- **What we tested.** The best Sprint 2c construction — six trend sleeves (S1, S2, S4 on BTC and ETH) sized together as one "
                 f"portfolio, with its volatility target and drawdown ladder — plus new brakes, each a multiplier between 0 and 1 on its own sizing: at "
                 f"most {cap_pct} of the money in one bet (BTC and ETH count as one bet while they move together; checked at each day's close), and "
                 f"{cfg['cooldown_days']} days out of the market after losing {cfg['loss_limit'] * 100:.0f} % in a week. The brake values were set "
                 "before the study first ran and were not changed afterwards.")
    lines.append(f"- **Same sleeves, same days.** Rebuilt from scratch, the old allocator reproduces Sprint 2c exactly ({_pct(m1['cagr'])} a year, "
                 f"{_pct(m1['max_drawdown'], False)} worst fall), so the difference below is the brakes and nothing else.")
    lines.append(f"- **Result, {v2['years']:.1f} years of walk-forward ({v2['first_day']} to {v2['last_day']}).** Allocator v2 made {_pct(m2['cagr'])} a year "
                 f"with a {_pct(m2['max_drawdown'], False)} worst fall (Sharpe {_num(m2['sharpe'])}, Calmar {_num(m2['calmar'])}), against "
                 f"{_pct(m1['cagr'])} / {_pct(m1['max_drawdown'], False)} (Sharpe {_num(m1['sharpe'])}, Calmar {_num(m1['calmar'])}) for v1. "
                 + ("It passes every Sprint 2c gate." if passed else f"It misses: {_gates(v2['acceptance'])}."))
    lines.append(f"- **How often the brakes acted.** The correlation cap trimmed the book on {_pct(b2.get('correlation_cap_days_share'), False)} of days; the "
                 f"weekly loss limit tripped {_times(b2.get('loss_limit_trips', 0))} ({_num(b2.get('loss_limit_trips_per_year'))} a year), leaving the book "
                 f"in cash {_pct(b2.get('cooldown_days_share'), False)} of days; on average {_pct(b2.get('invested_share_mean'), False)} of the money was "
                 f"invested (v1: {_pct(b1.get('invested_share_mean'), False)}).")
    if facts:
        h1, h2 = hold["v1"]["metrics"], hold["v2"]["metrics"]
        head = "**Both lost.** " if facts["both_lost"] else ("**Both gained.** " if facts["both_gained"] else "")
        verdict = ("The holdout confirms v2's walk-forward result." if facts["v2_confirmed"] else
                   "The holdout does not confirm v2's walk-forward pass"
                   + (f", just as it did not confirm {facts['contradicted']} of the {facts['passes']} configurations Sprint 2c opened it for"
                      if facts["passes"] else "") + ".")
        lines.append(f"- **Untouched last 12 months** (opened because v2 passed, {hold['first_day']} to {hold['last_day']}): {head}v2 {_pct(h2['total_return'])} "
                     f"(worst fall {_pct(h2['max_drawdown'], False)}), v1 on the same sleeves {_pct(h1['total_return'])} ({_pct(h1['max_drawdown'], False)}), "
                     f"in {facts['market']} (" + ", ".join(f"{k.split('-')[0]} {_pct(v)}" for k, v in facts["coins"].items())
                     + f" for plain buy-and-hold). {facts['effect']} {verdict}")
        if not facts["v2_confirmed"]:
            sentences = []
            sleeves = hold.get("sleeves") or {}
            losers = sum(1 for sl in sleeves.values() if (sl.get("total_return") or 0.0) < 0)
            if facts["both_lost"]:
                sentences.append(f"{losers} of the {len(sleeves)} long-only trend sleeves lost at full size on these months, and both portfolio "
                                 "constructions lost with them" + (f", more than every always-long control with the policy sizing "
                                                                   f"({_pct(min(facts['controls']))} to {_pct(max(facts['controls']))})"
                                                                   if facts["worse_than_every_control"] else "") + ".")
            elif facts["r2"] < 0 <= facts["r1"]:
                sentences.append("v2 lost on these months while v1 on the same sleeves did not: here the brakes cost more than they saved.")
            elif facts["r1"] < 0 <= facts["r2"]:
                sentences.append("v1 lost on these months and v2 did not, but v2's gain is not enough to confirm it.")
            lead = ("v1, which its holdout confirms, is the stronger of the two" if facts["v1_confirmed"] else
                    "neither is a lead candidate")
            sentences.append(f"Both portfolio accounts keep running in the paper fleet (it costs nothing); on this evidence {lead}, and the "
                             "forward record decides.")
            lines.append("- **What it means.** " + " ".join(sentences))
    else:
        lines.append(f"- **Untouched last 12 months:** not opened — {hold.get('reason', 'not evaluated')}. The paper fleet runs v2 next to v1 anyway: forward "
                     "evidence on the same sleeves is the cheap, honest test of the brakes.")
    lines.append("")
    lines.append("## What allocator v2 adds")
    lines.append("")
    lines.append("Allocator v1 (Sprint 2c, `research.portfolio.combine_sized`) is kept unchanged: the six sleeves run at FULL size; every day each gets a weight "
                 "∝ 1 / its trailing 60-day volatility; one portfolio volatility target of 15 % (trailing 30 days, never above 100 % = no leverage) scales "
                 "the whole book; one drawdown ladder (half size at −7.5 %, flat at −15 %, 30 days flat then the peak is reset) acts on the portfolio's own "
                 "equity. Allocator v2 (`research/allocator.py`) multiplies that sizing by brakes that are each between 0 and 1:")
    lines.append("")
    lines.append("| Brake | Rule | Why this value |")
    lines.append("|---|---|---|")
    lines.append(f"| Correlation cap | Sleeves on the same coin are one bet; BTC and ETH are one bet while the correlation of their daily returns over the last "
                 f"{cfg['corr_lookback_days']} days is {cfg['corr_threshold']:.2f} or more (unknown = one bet). The money invested in one bet — the sleeves of "
                 f"the bet that were long at the previous close — is capped at {cap_pct} of equity: above it the bet is scaled back to the cap. Sleeves "
                 "that enter during a day count from the next close, so after several entries a bet can stand above the cap until then. | "
                 f"The {cfg['corr_lookback_days']}-day window is v1's weight window; {cfg['corr_threshold']:.2f} is the conventional \"highly correlated\" "
                 "line; one bet may hold at most half the book. |")
    lines.append(f"| Weekly loss limit | A loss of {cfg['loss_limit'] * 100:.0f} % or more over the last {cfg['loss_window_days']} days sends the book to cash. | "
                 f"A third of the 15 % annual volatility target, about 2.5 to 3 weekly standard deviations: a circuit breaker for bad weeks, not a routine brake. |")
    lines.append(f"| Cooldown | After a trip, {cfg['cooldown_days']} days in cash, then the limit re-arms with a fresh {cfg['loss_window_days']}-day window. The ladder "
                 "keeps its own 30-day cooling-off. | Sit out the week after a bad week instead of jumping straight back in. |")
    lines.append("| Vol target and ladder | Same rules as v1. The vol target is measured on the base weights, so a brake never raises the scale; the ladder "
                 "follows v2's own equity. | The difference between v1 and v2 is then the new brakes and their effect on v2's own drawdown path. |")
    lines.append("")
    lines.append(f"The values are `DEFAULT_ALLOCATOR_V2` in `research/allocator.py`. They were written before the study first ran in plan row R5b and were "
                 "not changed after any result, but they were committed together with the results, so the repository itself cannot prove that order: "
                 "the paper fleet's forward record is the test that cannot be tuned. \"Only lowers\" means relative to v2's own sizing: because v2's "
                 f"ladder follows v2's equity, it held v2 at a larger size than v1's ladder held v1 on {b2.get('ladder_v2_above_v1_days', 0)} days "
                 f"(and the reverse on {b2.get('ladder_v1_above_v2_days', 0)}); v2 had more money invested than v1 on "
                 f"{b2.get('invested_above_reference_days', 0)} days.")
    lines.append("")
    lines.append("Everything a day's size depends on is known at the previous close (tests prove that changing a day cannot change its own size). "
                 "Moving money between sleeves is assumed free, as in Sprint 2c; the cost of that re-weighting is estimated below.")
    lines.append("")
    lines.append("## Reproduction check")
    lines.append("")
    lines.append("| | Sprint 2c (stored) | Rebuilt now |")
    lines.append("|---|---:|---:|")
    rep = result["reproduction"]
    for k in ("cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "total_return"):
        lines.append(f"| {k} | {_num(rep[k]['stored'], '{:.6f}')} | {_num(rep[k]['rebuilt'], '{:.6f}')} |")
    lines.append(f"| days | {rep['days']['stored']} | {rep['days']['rebuilt']} |")
    lines.append("")
    lines.append(f"Sleeves: " + "; ".join(f"`{s['name']}` {s['candidate']} {s['instrument']} {s['timeframe']} `{s['params']}`" for s in result["meta"]["sleeves"]) + ".")
    lines.append("")
    lines.append(f"## Walk-forward ({v2['first_day']} to {v2['last_day']}, {v2['days']} days, after fees and slippage)")
    lines.append("")
    lines.append("| Allocator | CAGR | Vol | Sharpe | Max DD | Calmar | Rolling 12m + | Worst year | Avg invested | Gates missed |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    lines.append(_row("v1 (Sprint 2c)", v1))
    lines.append(_row("**v2 (the fixed configuration)**", v2))
    for ab in wf["ablations"]:
        lines.append(_row(f"ablation: {ab['label']}", ab))
    lines.append("")
    lines.append(f"Profit factor {_num(wf['pooled_profit_factor'])} and {wf['pooled_trades']} trades are pooled from the sleeves (the same for every row). "
                 "The ablations switch one new brake off to show where the difference comes from; they are diagnostics, never candidates.")
    lines.append("")
    years = sorted(set(v1["yearly_gate"]["calendar_years"]) | set(v2["yearly_gate"]["calendar_years"]))
    lines.append("| Calendar year | " + " | ".join(str(y) for y in years) + " |")
    lines.append("|---|" + "---:|" * len(years))
    for label, s in (("v1", v1), ("v2", v2)):
        lines.append(f"| {label} | " + " | ".join(_pct(s["yearly_gate"]["calendar_years"].get(str(y), s["yearly_gate"]["calendar_years"].get(y))) for y in years) + " |")
    lines.append("")
    lines.append("## How often each brake acted (walk-forward)")
    lines.append("")
    corr = wf.get("coin_correlation") or {}
    lines.append(f"- BTC/ETH correlation (trailing {cfg['corr_lookback_days']} days): median {_num(corr.get('median'))} (10th–90th percentile "
                 f"{_num(corr.get('p10'))}–{_num(corr.get('p90'))}); the coins counted as one bet on {_pct(b2.get('coins_one_bet_days_share'), False)} of days.")
    by_year = b2.get("correlation_cap_days_by_year") or {}
    lines.append(f"- Correlation cap: trimmed the book on {_pct(b2.get('correlation_cap_days_share'), False)} of days ("
                 + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())) + f" days), by {_pct(b2.get('correlation_cap_average_cut'), False)} "
                 f"on average when it did. v1 had more than {cap_pct} of its equity in one bet at the previous close on "
                 f"{_pct(b2.get('reference_above_cap_days_share'), False)} of days (at most {_pct(b2.get('reference_bet_max'), False)}). On the days the cap "
                 f"acted, {_num(b2.get('cap_days_sleeves_long_mean'), '{:.1f}')} of the six sleeves were long on average "
                 f"({_num(b2.get('other_days_sleeves_long_mean'), '{:.1f}')} on the other days, {_num(b2.get('cap_days_sleeves_long_10d_before_mean'), '{:.1f}')} "
                 f"ten days earlier) and the vol scale was {_num(b2.get('cap_days_vol_scale_mean'))} ({_num(b2.get('other_days_vol_scale_mean'))} otherwise): "
                 "it acted when many sleeves had just entered together, before the trailing volatility had caught up.")
    lines.append(f"- The cap is checked at the previous close, so it trims a bet one day after several sleeves entered together: a bet stood above {cap_pct} "
                 f"at a day's close on {b2.get('bet_above_cap_at_close_days', 0)} of {b2.get('days', 0)} days (at most "
                 f"{_pct(b2.get('bet_at_close_max'), False)}), and the next day's cap brought it back.")
    lines.append(f"- Weekly loss limit: tripped {_times(b2.get('loss_limit_trips', 0))} (" + (", ".join(b2.get("trip_days") or []) or "never") +
                 f"); in cash after a trip on {_pct(b2.get('cooldown_days_share'), False)} of days.")
    lines.append(f"- Drawdown ladder: v2 at half size on {_pct(b2.get('ladder_half_days_share'), False)} and flat on {_pct(b2.get('ladder_flat_days_share'), False)} of "
                 f"days (v1: {_pct(b1.get('ladder_half_days_share'), False)} / {_pct(b1.get('ladder_flat_days_share'), False)}).")
    lines.append(f"- Invested money (start of each day): v2 {_pct(b2.get('invested_share_mean'), False)} on average, at most "
                 f"{_pct(b2.get('invested_share_max'), False)} (above {cap_pct} only on days the coins counted as two bets); v1 "
                 f"{_pct(b1.get('invested_share_mean'), False)}, at most {_pct(b1.get('invested_share_max'), False)}. Both are low on average because the "
                 "sleeves are flat much of the time and the ladder halves the book on about half of the days.")
    lines.append(f"- Re-weighting between sleeves (assumed free, as in Sprint 2c): about {_num(b2.get('reweighting_turnover_per_year'), '{:.1f}')} times the "
                 f"equity a year for v2 and {_num(b1.get('reweighting_turnover_per_year'), '{:.1f}')} for v1, i.e. roughly "
                 f"{_pct(b2.get('reweighting_cost_per_year'), False)} and {_pct(b1.get('reweighting_cost_per_year'), False)} a year at 0.15 % per side if "
                 "it were charged. A real book would re-weight only on larger changes.")
    lines.append("")
    lines.append("## Gates (Sprint 2c portfolio gates, unchanged)")
    lines.append("")
    lines.append("Profit factor above 1.2 (pooled), max drawdown below 20 %, Sharpe above 0.7, Calmar above 0.5, at least 75 % of rolling 12-month windows "
                 "positive and no calendar year below −10 %, at least 30 trades (pooled); the ±30 % robustness gate is carried by the sleeves, as in Sprint 2c. "
                 f"Verdict for v2: **{_gates(v2['acceptance'])}**. No gate was changed after the results were in.")
    lines.append("")
    if facts and passed and not facts["v2_confirmed"]:
        own = result["meta"].get("sleeves_passed_on_their_own") or {}
        n_own = sum(1 for v in own.values() if v)
        share, best = _growth_share_of_best_years(v1["yearly_gate"]["calendar_years"])
        reasons = ["at the portfolio level the ±30 % robustness gate is skipped",
                   f"the profit factor and trade count are pooled from sleeves of which {n_own} of {len(own)} passed on their own",
                   "the sleeves' timeframes were picked on out-of-sample numbers"]
        if share is not None:
            reasons.append(f"{share * 100:.0f} % of v1's walk-forward growth came from its two best calendar years ({' and '.join(best)})")
        lines.append("**Do the gates look wrong?** Not one by one, but they are too easy for a portfolio, and that is worth fixing before the next "
                     "portfolio study (as a new, pre-registered rule, not as an edit of this one): " + "; ".join(reasons) + ". A portfolio cleared every "
                     "gate and was not confirmed by its holdout. Recommendation for future studies: count a portfolio as a candidate only when its "
                     "sleeves pass on their own or its holdout confirms it.")
        lines.append("")
    lines.append("## The untouched 12 months (holdout)")
    lines.append("")
    if hold.get("evaluated"):
        h1, h2 = hold["v1"], hold["v2"]
        lines.append(f"Opened because v2 passed the walk-forward gates: {hold['first_day']} to {hold['last_day']} ({hold['days']} days). {hold['note']}.")
        lines.append("")
        lines.append("| Allocator | Return | Vol | Sharpe | Max DD | Avg invested | Brakes | Confirms (return > 0, pooled PF > 1, ≥ 10 trades) |")
        lines.append("|---|---:|---:|---:|---:|---:|---|---|")
        for label, h in (("v1 (reference)", h1), ("v2", h2)):
            m, b = h["metrics"], h["brakes"]
            ladder = f"ladder half {_pct(b.get('ladder_half_days_share'), False)} / flat {_pct(b.get('ladder_flat_days_share'), False)} of days"
            brakes = (f"cap on {_pct(b.get('correlation_cap_days_share'), False)} of days, loss limit tripped {_times(b.get('loss_limit_trips', 0))}, {ladder}"
                      if label == "v2" else ladder)
            lines.append(f"| {label} | {_pct(m.get('total_return'))} | {_pct(m.get('ann_vol'), False)} | {_num(m.get('sharpe'))} | {_pct(m.get('max_drawdown'), False)} | "
                         f"{_pct(b.get('invested_share_mean'), False)} | {brakes} | {'yes' if h['confirmed'] else 'no'} |")
        lines.append("")
        lines.append(f"Pooled over the six sleeves on the holdout: {hold['pooled_trades']} trades, profit factor {_num(hold['pooled_profit_factor'])} (full-size "
                     "sleeves; the walk-forward gate pooled Sprint 2c's policy-sized sleeves instead).")
        lines.append("")
        first_bars, last_bars = hold.get("holdout_first_bar") or {}, hold.get("holdout_last_bar") or {}
        if first_bars and last_bars:
            lines.append(f"The sleeve rows and the pooled numbers cover each sleeve's whole holdout ({min(first_bars.values())[:16]} to "
                         f"{max(last_bars.values())[:16]} UTC bar opens), a part-day more at each end than the portfolio's booked days.")
            lines.append("")
        lines.append("| Sleeve on the holdout (full size) | Return | Trades | Profit factor | Time long |")
        lines.append("|---|---:|---:|---:|---:|")
        for name, sl in (hold.get("sleeves") or {}).items():
            lines.append(f"| {name} | {_pct(sl.get('total_return'))} | {sl.get('n_trades')} | {_num(sl.get('profit_factor'))} | {_pct(sl.get('exposure'), False)} |")
        lines.append("")
        lines.append("The same 12 months for comparison (plain buy-and-hold over the booked days; the other rows are Sprint 2c's own holdout evaluation "
                     "in `ensemble_v1c_results.json`, with the policy sizing):")
        lines.append("")
        lines.append("| | Return | Max DD |")
        lines.append("|---|---:|---:|")
        for coin, ret in (hold.get("coins_buy_and_hold") or {}).items():
            lines.append(f"| plain buy-and-hold {coin} | {_pct(ret)} | - |")
        for c in result.get("sprint_2c_holdout_context") or []:
            kind = "control: always long, policy sizing" if c["control"] else f"{c['candidate']} [{c['regime']}]"
            lines.append(f"| {kind} — {c['instrument']} {c['timeframe']} | {_pct(c.get('total_return'))} | {_pct(c.get('max_drawdown'), False)} |")
    else:
        lines.append(f"Not opened: {hold.get('reason', 'not evaluated')}.")
    lines.append("")
    lines.append("## What happens next")
    lines.append("")
    lines.append("- The paper fleet runs allocator v2 as its own account, `pf-s1s2s4-btceth-vt15-alloc2`, on the same six sleeves as the v1 portfolio account "
                 "`pf-s1s2s4-btceth-vt15` (which is unchanged). Its journal also carries the v1 rules on its own sleeves, so the weekly report shows the "
                 "brakes' own effect day by day even if the two accounts started at different times. The walk-forward numbers above are its "
                 "expectations, and its holdout result is a second reference, as for the shortlist accounts.")
    lines.append("- The weekly report's allocator section compares the two and lists every brake that acted. A good forward record is evidence for "
                 "plan row G7, not an approval.")
    lines.append("- Allocator v2 is research code (`research/`). The demo and live risk manager (`app/risk`) stays the reviewed core; moving any of these "
                 "brakes there is a separate, reviewed owner decision.")
    lines.append("")
    lines.append("## Method notes and caveats")
    lines.append("")
    lines.append("- The sleeves are Sprint 2c's: per family and coin the timeframe with the higher walk-forward Calmar (a mild selection on out-of-sample data, "
                 "already flagged in Sprint 2c), the rule each sleeve's walk-forward selected most often, replayed at full size in the same 180-day test "
                 "windows, each window starting flat. Portfolio numbers inherit that mild optimism, for v1 and v2 alike.")
    lines.append("- A sleeve counts as invested when it was long at the previous day's close (its last bar of the day); a sleeve that enters during the day "
                 "joins at the weight it was given that morning (see the cap's numbers above).")
    lines.append("- Coin correlations use one close per UTC day from the 1H candles, from the start of the coin history (so the first walk-forward days "
                 "already have a 60-day correlation); a missing close leaves no return across the gap.")
    lines.append("- The holdout was computed more than once in this step: first to open it, then again each time statistics or fixes were added to the "
                 "study (one fix moved its first booked day to the first full holdout day). The brake configuration never changed, and every number "
                 "here is from the final code.")
    lines.append("- The study reproduces Sprint 2c only on the same data: the 12-month split follows the lake's last bar (the last bars used are recorded "
                 "in the results file). After the lake grows, the reproduction check stops a re-run instead of comparing different samples.")
    lines.append("- Every number is a simulation on historical public data and proves nothing about the future.")
    return "\n".join(lines) + "\n"


def expectations_from_results(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The paper-fleet expectations of the allocator-v2 account (the keys the weekly report reads)."""
    wf = result["walk_forward"]["v2"]
    m, yg, acc, b = wf["metrics"], wf["yearly_gate"], wf["acceptance"], wf["brakes"]
    years = float(wf["years"] or 0.0)
    pooled = result["walk_forward"]["pooled_trades"]
    out = {
        "walk_forward": {"cagr": m.get("cagr"), "ann_vol": m.get("ann_vol"), "sharpe": m.get("sharpe"), "sortino": m.get("sortino"),
                         "max_drawdown": m.get("max_drawdown"), "calmar": m.get("calmar"), "total_return": m.get("total_return"), "years": years,
                         "n_trades": pooled, "profit_factor": result["walk_forward"]["pooled_profit_factor"],
                         "trades_per_year": pooled / years if years else None,
                         "rolling_12m_positive_share": yg.get("rolling_positive_share"), "worst_calendar_year_return": yg.get("worst_calendar_year_return")},
        "passed_walk_forward": bool(acc.get("passed")), "failed_gates": list(acc.get("failed") or []),
        "brakes": {k: b.get(k) for k in ("correlation_cap_days_share", "loss_limit_trips_per_year", "cooldown_days_share", "ladder_half_days_share",
                                          "ladder_flat_days_share", "invested_share_mean")},
        "reference_v1": {"walk_forward": {k: result["walk_forward"]["v1"]["metrics"].get(k) for k in ("cagr", "ann_vol", "sharpe", "max_drawdown", "calmar")},
                         "brakes": {k: result["walk_forward"]["v1"]["brakes"].get(k) for k in ("ladder_half_days_share", "ladder_flat_days_share", "invested_share_mean")}},
        "holdout": None,
        "note": "allocator v2 on the six full-size sleeves of the jointly sized portfolio; walk-forward numbers from docs/research/ALLOCATOR_V2_REPORT.md",
    }
    hold = result.get("holdout") or {}
    if hold.get("evaluated"):
        hm = hold["v2"]["metrics"]
        ref = hold["v1"]["metrics"]
        out["holdout"] = {"total_return": hm.get("total_return"), "cagr": hm.get("cagr"), "ann_vol": hm.get("ann_vol"), "sharpe": hm.get("sharpe"),
                          "max_drawdown": hm.get("max_drawdown"), "calmar": hm.get("calmar"), "bars": hold.get("days"),
                          "n_trades": hold.get("pooled_trades"), "profit_factor": hold.get("pooled_profit_factor"), "confirmed": hold["v2"]["confirmed"],
                          "first_day": hold.get("first_day"), "last_day": hold.get("last_day"),
                          "reference_v1_total_return": ref.get("total_return"), "reference_v1_max_drawdown": ref.get("max_drawdown")}
    return out
