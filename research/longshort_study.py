"""Phase 9 design study: long and short through perpetual swaps without leverage (plan row R9, SIMULATION ONLY).

The question (master plan, strategic note after Sprint 2b; v1c acceptance
clause): would the trend rules of Sprint 2c earn their keep if they could also
be SHORT — through USDT-margined perpetual swaps with collateral at least
equal to the position (no leverage) — after fees, slippage and funding?

Everything that defines the answer was fixed before the first run and is
recorded in :data:`PREREGISTRATION` (its hash goes into the results). In brief:

- **Families**: S1, S2, S4 (the trend families of the v1c portfolio) and
  S1+S5 (the holdout-confirmed sleeve's family), entry rules and grids exactly
  as Sprint 2c ran them; their mirror images are the short rules
  (:mod:`research.strategies.shorts`).
- **Designs** (both judged): ``hybrid`` — long on spot (0.10 % fee, no
  funding), short on the perpetual swap (0.05 % fee + funding); ``perp`` —
  both legs on the perpetual swap (0.05 % + funding). Slippage 0.05 % per
  side. ``long_only`` is Sprint 2c's spot rule, run through the same code as
  a reproduction check: the study stops unless it gives Sprint 2c's stored
  numbers.
- **Protocol**: Sprint 2c's walk-forward (train 540 d, purge 7 d, test 180 d;
  the rule selected on the train slice at full size by Sharpe with >= 20
  trades among bracket-free rules, then the bracket among siblings), the fixed
  policy sizing (``vt10/30 crash15/90dh ladder``, the same fraction for both
  sides) on the test slice, the v1c gates unchanged.
- **Evidence rule for Phase 9** (pre-registered, stricter than the gates
  alone, after R5b's lesson that portfolio gates were too easy): a
  configuration counts only if (1) it passes the v1c gates on the
  walk-forward, (2) its short leg alone has a profit factor above 1 after
  costs and funding, (3) its walk-forward Calmar beats Sprint 2c's long-only
  result for the same family and series, and (4) the untouched 12-month
  holdout confirms it (v1c verdict). The holdout is opened only for
  configurations that meet (1)-(3).
- **Known about the holdout before it is opened**: Sprint 2c and R5b reported
  BTC -26 % and ETH -39 % over these 12 months, so a rule that can be short is
  expected to look better there than a long-only rule: a confirmation is weak
  evidence, a contradiction strong evidence.

Diagnostics (reported, never gates): leg attribution, funding paid and
received, stress replays (slippage x2/x3, funding x2), the short leg replayed
on the perpetual swap's own OKX candles, the fixed default-parameter rules
over 2020-01-01 -> holdout start without any selection, funding by year,
spot-perp basis, and the largest price rises a short would have faced.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.datalake.layout import LakeLayout
from research.data import bars_per_year, load_candles, load_or_resample_candles, positioning_context, split_holdout
from research.engine import Costs
from research.gated_walkforward import _stitch, _window_returns
from research.longshort import DEFAULT_MMR, NO_LOSS_PROFIT_FACTOR, LongShortResult, run_long_short, side_metrics
from research.longshort_data import (
    align_perp,
    basis_stats,
    funding_by_year,
    funding_coverage,
    funding_overlap,
    funding_per_bar,
    load_funding,
    load_perp_candles,
)
from research.metrics import bar_returns, deflated_sharpe_ratio, equity_metrics, return_moments, sharpe, trade_metrics
from research.montecarlo import trade_order_bootstrap
from research.report_v1c import acceptance_check_v1c, calendar_year_returns, holdout_verdict, yearly_gate_v2
from research.sizing import LadderConfig, SizingSpec, fraction_matrix
from research.strategies import get_candidate
from research.strategies.base import days_to_bars
from research.strategies.s0_filters import NoTradeConfig
from research.strategies.shorts import LSFrames, build_ls_frames
from research.sweep import _slice_fraction, metrics_table, param_grid, perturbed_params
from research.walkforward import WINDOW_INIT_CASH, WalkForwardConfig, Window, _params_key, _select, make_windows

STUDY_FAMILIES = ("S1", "S2", "S4", "S1+S5")
STUDY_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
STUDY_TIMEFRAMES = ("4H", "6H")
DEFAULT_BRACKETS = ("none", "tp2", "trail1", "time30")


class StudyError(RuntimeError):
    """The study cannot be trusted (the long-only path does not reproduce Sprint 2c, the data is missing)."""


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    shorts: bool
    long_on_perp: bool


VARIANTS: Dict[str, Variant] = {
    "long_only": Variant("long_only", "long-only on spot (Sprint 2c, reproduced)", shorts=False, long_on_perp=False),
    "hybrid": Variant("hybrid", "long on spot, short on the perpetual swap", shorts=True, long_on_perp=False),
    "perp": Variant("perp", "long and short on the perpetual swap", shorts=True, long_on_perp=True),
}
JUDGED_VARIANTS = ("hybrid", "perp")


@dataclass(frozen=True)
class StudyConfig:
    spot_fee: float = 0.0010  # OKX regular spot taker (Sprint 2c's cost)
    perp_fee: float = 0.0005  # OKX regular USDT-margined swap taker
    slippage: float = 0.0005
    train_days: float = 540.0
    test_days: float = 180.0
    purge_days: float = 7.0
    min_trades: int = 20
    select_by: str = "sharpe"
    policy_target_vol: float = 0.10
    policy_lookback: int = 30
    policy_crash_dd: float = 0.15
    policy_crash_days: float = 90.0
    policy_ladder: bool = True
    rebalance_threshold: float = 0.25
    ladder_recovery_days: float = 30.0
    holdout_months: int = 12
    brackets: Tuple[str, ...] = DEFAULT_BRACKETS
    funding_source: str = "binance"
    positioning_source: str = "binance"
    mmr: float = DEFAULT_MMR
    scheduled_events: bool = True
    descriptive_start: str = "2020-01-01"
    funding_stress: float = 2.0
    slippage_stress: Tuple[float, ...] = (1.0, 2.0, 3.0)
    mc_paths: int = 2000
    seed: int = 0
    quick: bool = False

    def costs(self, variant: Variant, *, slippage_mult: float = 1.0) -> Tuple[Costs, Costs]:
        slip = min(0.0999, self.slippage * slippage_mult)
        long_costs = Costs(fee_rate=self.perp_fee if variant.long_on_perp else self.spot_fee, slippage_rate=slip)
        short_costs = Costs(fee_rate=self.perp_fee, slippage_rate=slip)
        return long_costs, short_costs

    def policy(self) -> SizingSpec:
        return SizingSpec(kind="vol_target", target_vol=self.policy_target_vol, vol_lookback=self.policy_lookback,
                          crash_dd=self.policy_crash_dd, crash_window_days=self.policy_crash_days, crash_mode="half",
                          ladder=self.policy_ladder)

    def no_trade(self) -> NoTradeConfig:
        return NoTradeConfig(scheduled_events=self.scheduled_events)

    def wf(self, timeframe: str, *, min_trades: Optional[int] = None) -> WalkForwardConfig:
        return WalkForwardConfig(train_bars=days_to_bars(self.train_days, timeframe), test_bars=days_to_bars(self.test_days, timeframe),
                                 purge_bars=days_to_bars(self.purge_days, timeframe),
                                 min_trades=self.min_trades if min_trades is None else min_trades, select_by=self.select_by)

    def ladder(self, timeframe: str) -> LadderConfig:
        return LadderConfig(recovery_bars=days_to_bars(self.ladder_recovery_days, timeframe))

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["brackets"] = list(self.brackets)
        out["slippage_stress"] = list(self.slippage_stress)
        out["policy_sizing"] = self.policy().label
        return out


PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-10-22, before the first full run (plan row R9)",
    "question": ("Does a short leg through USDT-margined perpetual swaps at no leverage (collateral >= position) improve the Sprint 2c "
                 "trend rules out of sample on BTC-USDT and ETH-USDT, after fees, slippage and funding?"),
    "families": list(STUDY_FAMILIES),
    "series": [f"{i} {t}" for i in STUDY_INSTRUMENTS for t in STUDY_TIMEFRAMES],
    "entry_rules_and_grids": "exactly Sprint 2c's (research/strategies), brackets none/tp2/trail1/time30 (none only for S1+S5)",
    "short_rules": ("mirror images with the same parameters: S1 >= vote lookbacks negative; S2 close below the prior entry_days low with "
                    "the same volume/ATR filters, cover above the prior exit_days high; S4 close below the lower band after a squeeze, "
                    "cover above the mid band; S5 mirror: no new short while the funding z-score < -funding_z_max or open interest "
                    "surges; ATR stop above the entry; a short needs a finite stop"),
    "priority": ("the long side is the long-only rule unchanged; a short may only start while it is flat and the S0 filter (and the S5 "
                 "mirror) allow a new entry; one position at a time; the long side wins a tie"),
    "designs": {"hybrid": "long on spot (fee 0.10 %, no funding), short on the perpetual swap (fee 0.05 % + funding)",
                "perp": "long and short on the perpetual swap (fee 0.05 % + funding)",
                "slippage": "0.05 % per side everywhere"},
    "funding": ("Binance BTCUSDT/ETHUSDT public funding history as the proxy for OKX's swaps (OKX keeps months); each settlement "
                "charged on the position open at the close of the bar it settles in, on |quantity| x that close; longs pay positive "
                "rates, shorts receive them; OKX's own funding compared with the proxy where both exist"),
    "sizing": ("Sprint 2c's fixed policy vt10/30 crash15/90dh ladder (rebalance threshold 0.25, ladder re-arm 30 days), the same "
               "fraction for both sides, fraction <= 1 so a short's notional at entry never exceeds the equity behind it"),
    "walk_forward": "train 540 d -> purge 7 d -> test 180 d; Sharpe with >= 20 train trades; entries first, then the bracket",
    "gates": "the v1c gates unchanged (research/report_v1c.py GATES)",
    "phase9_evidence_rule": ["(1) passes the v1c gates on the walk-forward",
                             "(2) the short leg alone has a walk-forward profit factor > 1 after costs and funding",
                             "(3) walk-forward Calmar above Sprint 2c's long-only result for the same family and series",
                             "(4) the untouched holdout confirms (positive return, profit factor > 1, >= 10 trades)"],
    "holdout": ("last 12 months (2025-10-20 -> 2026-10-20), opened once and only for configurations meeting (1)-(3); known in advance: "
                "BTC -26 %, ETH -39 % over these months (Sprint 2c, R5b), so a confirmation is weak and a contradiction strong evidence"),
    "configurations_judged": 32,
    "diagnostics_not_gates": ["leg attribution and funding", "slippage x2/x3 and funding x2 replays",
                              "the short leg replayed on OKX perpetual-swap candles", "fixed default parameters 2020-01-01 -> holdout start",
                              "funding by year, spot-perp basis, the largest rises against a short"],
}


#: Added AFTER the pipeline smoke run (S1 on BTC-USDT 4H, both designs, walk-forward only) and before the full run;
#: diagnostics only — no verdict, gate, configuration or holdout decision depends on them.
POST_HOC: List[Dict[str, str]] = [
    {"added": "2026-10-22, after the smoke run of S1 on BTC-USDT 4H and before the full run",
     "what": ("the shorts of every configuration replayed with the policy sizing minus its crash filter (vol target and ladder only), "
              "on the walk-forward's own per-window selections"),
     "why": ("the pre-registered policy applies Sprint 2b's crash filter to both sides; it halves exposure while the price is more than "
             "15 % below its 90-day peak, which is the market state in which a short leg is expected to earn — the Phase 9 design has to "
             "know what that rule costs the shorts")},
]


#: Fixed AFTER the first full run, from the independent code review; no gate, rule, configuration, parameter or
#: pre-registered choice changed (the pre-registration hash is the same). The first run's holdout openings are in the ledger.
REVIEW_FIXES: List[Dict[str, str]] = [
    {"what": ("flips: a short that the long side needs now closes at the open before that bar's stops are checked, so the long enters "
              "where the long-only rule enters; before, a short whose stop also fired in the flip bar was booked at its stop and the long "
              "entered one bar late, against the pre-registered 'long side unchanged'"),
     "effect": "changes numbers of configurations with flips (mostly S1 and S1+S5); tested: the long side now trades exactly like the long-only rule"},
    {"what": "the S5 mirror and the S0 filter gate a short's start one after the other, in the long side's order (they were combined on one bar)",
     "effect": "S1+S5 only, a fraction of a percent of short bars"},
    {"what": "a leg without a losing trade has profit factor 999 (Sprint 2c's convention) instead of an empty value",
     "effect": "reporting only"},
    {"what": "the holdout can only be opened by the full pre-registered study (never in quick mode or on a subset), and every opening "
             "is appended to a ledger the report shows",
     "effect": "protocol only"},
]


def preregistration_hash(cfg: StudyConfig) -> str:
    payload = json.dumps({"preregistration": PREREGISTRATION, "config": cfg.to_dict()}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -- simulation helpers ------------------------------------------------------------------------

def simulate_ls(
    df: pd.DataFrame,
    frames: LSFrames,
    sl: slice,
    *,
    variant: Variant,
    costs: Tuple[Costs, Costs],
    fund: Optional[np.ndarray],
    size_fraction: Any = 1.0,
    columns: Optional[Sequence[int]] = None,
    ladder: Optional[LadderConfig] = None,
    ladder_mask: Optional[np.ndarray] = None,
    rebalance_threshold: Optional[float] = None,
    perp: Optional[Mapping[str, np.ndarray]] = None,
    funding_mult: float = 1.0,
    mmr: float = DEFAULT_MMR,
    short_size_fraction: Optional[np.ndarray] = None,
) -> LongShortResult:
    """Simulate (a subset of) columns on ``df[sl]`` from a flat start under one design."""
    cols = np.arange(frames.n_combos) if columns is None else np.asarray(list(columns), dtype=int)
    sub = df.iloc[sl]
    dl = frames.desired[sl][:, cols]
    ds = frames.short_matrix()[sl][:, cols] if variant.shorts else None
    stop = frames.stop[sl][:, cols]
    target = None if frames.target is None else frames.target[sl][:, cols]
    act = None if frames.trail_activate is None else frames.trail_activate[cols]
    dist = None if frames.trail_dist is None else frames.trail_dist[cols]
    f = None if fund is None else np.asarray(fund, dtype=float)[sl] * float(funding_mult)
    perp_ohlc = None if perp is None else tuple(np.asarray(perp[k], dtype=float)[sl] for k in ("open", "high", "low", "close"))
    return run_long_short(
        sub["open"].to_numpy(), sub["high"].to_numpy(), sub["low"].to_numpy(), sub["close"].to_numpy(), dl, ds, stop,
        costs_long=costs[0], costs_short=costs[1],
        funding_long=f if variant.long_on_perp else None, funding_short=f if variant.shorts else None,
        long_ohlc=perp_ohlc if variant.long_on_perp else None, short_ohlc=perp_ohlc if variant.shorts else None,
        time_stop_bars=[frames.time_stops[c] for c in cols], target_distance=target,
        size_fraction=_slice_fraction(size_fraction, sl, len(df), len(cols)),
        short_size_fraction=None if short_size_fraction is None else _slice_fraction(short_size_fraction, sl, len(df), len(cols)),
        trail_activate_r=act, trail_r=dist,
        ladder=ladder, ladder_mask=ladder_mask, rebalance_threshold=rebalance_threshold, maintenance_margin_rate=mmr,
    )


@dataclass
class LSWindow:
    idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    rule: Optional[int]
    params: Dict[str, Any]
    train_metric: float
    n_qualified: int
    test_metrics: Dict[str, float]
    test_returns: pd.Series
    train_sharpes: List[float] = field(default_factory=list)


@dataclass
class LSWalkForward:
    windows: List[LSWindow]
    oos_returns: pd.Series
    oos_equity: pd.Series
    oos_trades: pd.DataFrame
    oos_metrics: Dict[str, float]
    rule_frequency: Dict[str, int]
    short_share: float = 0.0
    max_leverage: float = 0.0
    funding_total_pct: float = 0.0  # sum over windows of funding / window capital

    @property
    def rule_most_often(self) -> Optional[Dict[str, Any]]:
        if not self.rule_frequency:
            return None
        key = max(self.rule_frequency, key=self.rule_frequency.get)
        for w in self.windows:
            if w.rule is not None and _params_key(w.params) == key:
                return dict(w.params)
        return None

    @property
    def last_selected(self) -> Optional[LSWindow]:
        return next((w for w in reversed(self.windows) if w.rule is not None), None)


@dataclass(frozen=True)
class SeriesInputs:
    df: pd.DataFrame  # in-sample spot bars
    fund: Optional[np.ndarray]  # per-bar funding sums over df (None = no funding at all)
    policy_fracs: np.ndarray  # (n, 1)
    ladder: LadderConfig
    ppy: float
    perp: Optional[Mapping[str, np.ndarray]] = None  # perp OHLC aligned onto df (for the perp-priced replay)
    short_fracs_no_crash: Optional[np.ndarray] = None  # (n, 1) policy without the crash filter (post-hoc diagnostic for shorts)


def run_ls_walk_forward(
    inp: SeriesInputs,
    frames: LSFrames,
    combos: Sequence[Mapping[str, Any]],
    wf_cfg: WalkForwardConfig,
    cfg: StudyConfig,
    variant: Variant,
    *,
    stage_a: Optional[Sequence[int]] = None,
    siblings: Optional[Mapping[int, Sequence[int]]] = None,
) -> LSWalkForward:
    """Sprint 2c's walk-forward (regime mode ``none``) with the long/short engine under one design."""
    df = inp.df
    windows = make_windows(len(df), wf_cfg)
    if not windows:
        raise ValueError(f"not enough bars ({len(df)}) for the walk-forward")
    costs = cfg.costs(variant)
    rebalance = cfg.rebalance_threshold
    policy_ladder = np.array([cfg.policy_ladder])
    results: List[LSWindow] = []
    oos_returns: List[pd.Series] = []
    oos_trades: List[pd.DataFrame] = []
    traded: List[Dict[str, float]] = []
    freq: Dict[str, int] = {}
    short_bars = 0
    total_bars = 0
    max_lev = 0.0
    funding_pct = 0.0
    for w in windows:
        train_res = simulate_ls(df, frames, w.train, variant=variant, costs=costs, fund=inp.fund, mmr=cfg.mmr)
        table = metrics_table(train_res, combos, periods_per_year=inp.ppy)
        rule_sharpes = [sharpe(bar_returns(train_res.equity[:, k]), 1.0) for k in range(train_res.n_combos)]
        stage_table = table if stage_a is None else table[table["combo"].isin(list(stage_a))]
        best = _select(stage_table, wf_cfg)
        if best is not None and siblings is not None and int(best["combo"]) in siblings:
            sib = table[table["combo"].isin(list(siblings[int(best["combo"])]))]
            best_sibling = _select(sib, wf_cfg)
            if best_sibling is not None:
                best = best_sibling
        test_index = df.index[w.test]
        total_bars += len(test_index)
        if best is None:
            flat = pd.Series(0.0, index=test_index)
            results.append(LSWindow(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1], None, {},
                                    float("nan"), 0, {}, flat, rule_sharpes))
            oos_returns.append(flat)
            continue
        rule = int(best["combo"])
        params = dict(combos[rule])
        freq[_params_key(params)] = freq.get(_params_key(params), 0) + 1
        test_res = simulate_ls(df, frames, w.test, variant=variant, costs=costs, fund=inp.fund, size_fraction=inp.policy_fracs,
                               columns=[rule], ladder=inp.ladder, ladder_mask=policy_ladder, rebalance_threshold=rebalance, mmr=cfg.mmr)
        test_returns = _window_returns(test_res, 0, test_index)
        tm = equity_metrics(test_res.equity[:, 0], inp.ppy)
        tm.update(trade_metrics(test_res.trades, init_cash=test_res.init_cash, n_bars=test_res.n_bars, periods_per_year=inp.ppy))
        tm["exposure"] = float(test_res.exposure[0])
        tm["avg_allocation"] = float(test_res.avg_allocation[0])
        tm["short_share"] = float(test_res.short_share()[0])
        trades = test_res.trades.copy()
        trades["window"] = w.idx
        trades["entry_time"] = test_index[trades["entry_i"].to_numpy(dtype=int)] if len(trades) else pd.Series(dtype="datetime64[ns, UTC]")
        oos_trades.append(trades)
        traded.append({"exposure": tm["exposure"], "avg_allocation": tm["avg_allocation"], "bars": len(test_returns)})
        short_bars += int((test_res.side[:, 0] == -1).sum())
        max_lev = max(max_lev, float(test_res.max_leverage[0]))
        funding_pct += float(test_res.funding_total[0]) / test_res.init_cash
        results.append(LSWindow(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1], rule, params,
                                float(best[wf_cfg.select_by]), int((stage_table["n_trades"] >= wf_cfg.min_trades).sum()), tm, test_returns,
                                rule_sharpes))
        oos_returns.append(test_returns)
    stitched, oos_equity, trades_df, metrics = _stitch(oos_returns, oos_trades, traded, inp.ppy)
    metrics["windows"] = len(results)
    metrics["windows_traded"] = sum(1 for r in results if r.rule is not None)
    metrics["windows_positive"] = sum(1 for r in results if r.rule is not None and r.test_metrics.get("total_return", 0) > 0)
    return LSWalkForward(results, stitched, oos_equity, trades_df, metrics, freq, short_share=short_bars / total_bars if total_bars else 0.0,
                         max_leverage=max_lev, funding_total_pct=funding_pct)


def replay_fixed(
    inp: SeriesInputs,
    frames: LSFrames,
    columns: Sequence[int],
    windows: Sequence[Window],
    cfg: StudyConfig,
    variant: Variant,
    *,
    sized: bool = True,
    slippage_mult: float = 1.0,
    funding_mult: float = 1.0,
    perp_priced: bool = False,
    per_window: Optional[Sequence[Optional[int]]] = None,
    short_no_crash: bool = False,
) -> List[Dict[str, Any]]:
    """Replay FIXED rule columns over every test window (or one column per window, ``per_window``); stitched metrics per column.

    ``per_window`` replays the walk-forward's own per-window selections (None = flat window) as one column;
    ``short_no_crash`` sizes the shorts with the policy minus its crash filter (a post-hoc diagnostic)."""
    costs = cfg.costs(variant, slippage_mult=slippage_mult)
    perp = inp.perp if perp_priced else None
    if perp_priced and perp is None:
        raise ValueError("no perpetual-swap candles for a perp-priced replay")
    if short_no_crash and (inp.short_fracs_no_crash is None or not sized):
        raise ValueError("the no-crash-filter short sizing needs the policy sizing and its fractions")
    if per_window is not None:
        col_sets: List[List[Optional[int]]] = [[c] for c in per_window]
        n_cols = 1
    else:
        col_sets = [list(columns) for _ in windows]
        n_cols = len(columns)
    returns: List[List[pd.Series]] = [[] for _ in range(n_cols)]
    trades: List[List[pd.DataFrame]] = [[] for _ in range(n_cols)]
    traded: List[List[Dict[str, float]]] = [[] for _ in range(n_cols)]
    funding = np.zeros(n_cols)
    for w, cols in zip(windows, col_sets):
        test_index = inp.df.index[w.test]
        if any(c is None for c in cols):
            for k in range(n_cols):
                returns[k].append(pd.Series(0.0, index=test_index))
            continue
        res = simulate_ls(inp.df, frames, w.test, variant=variant, costs=costs, fund=inp.fund,
                          size_fraction=inp.policy_fracs if sized else 1.0, columns=cols,
                          ladder=inp.ladder if sized else None, ladder_mask=np.full(len(cols), cfg.policy_ladder) if sized else None,
                          rebalance_threshold=cfg.rebalance_threshold if sized else None, perp=perp, funding_mult=funding_mult, mmr=cfg.mmr,
                          short_size_fraction=inp.short_fracs_no_crash if short_no_crash else None)
        for k in range(n_cols):
            returns[k].append(_window_returns(res, k, test_index))
            t = res.trades_for(k)
            trades[k].append(t)
            traded[k].append({"exposure": float(res.exposure[k]), "avg_allocation": float(res.avg_allocation[k]), "bars": res.n_bars})
            funding[k] += float(res.funding_total[k]) / res.init_cash
    out = []
    for k in range(n_cols):
        stitched, equity, trades_df, metrics = _stitch(returns[k], trades[k], traded[k], inp.ppy)
        metrics["funding_total_pct"] = float(funding[k])
        metrics["legs"] = side_metrics(trades_df, init_cash=WINDOW_INIT_CASH) if len(trades_df) else side_metrics(_no_trades(), init_cash=WINDOW_INIT_CASH)
        metrics["yearly"] = {int(y): float(v) for y, v in calendar_year_returns(equity).items()}
        out.append(metrics)
    return out


def _no_trades() -> pd.DataFrame:
    return pd.DataFrame({"side": pd.Series(dtype=np.int64), "pnl": pd.Series(dtype=float), "funding": pd.Series(dtype=float),
                         "fees": pd.Series(dtype=float), "bars_held": pd.Series(dtype=float), "return_pct": pd.Series(dtype=float),
                         "mae_pct": pd.Series(dtype=float), "max_leverage": pd.Series(dtype=float), "exit_reason": pd.Series(dtype=object)})


# -- grids (Sprint 2c's) ------------------------------------------------------------------------

def study_grid(key: str, cfg: StudyConfig) -> Tuple[List[Dict[str, Any]], Optional[List[int]], Dict[int, List[int]]]:
    """The candidate's Sprint 2c grid x brackets (S5 families: no bracket), with the staging of the selection."""
    candidate = get_candidate(key)
    grid = dict(candidate.grid)
    if cfg.quick:
        grid = {k: v[:2] for k, v in grid.items()}
    if "+S5" in key:
        brackets = ["none"]
    elif cfg.quick:
        brackets = [b for b in ("none", "tp2") if b in cfg.brackets] or ["none"]
    else:
        brackets = list(cfg.brackets)
    grid["bracket"] = brackets
    combos = param_grid(grid, base=candidate.default_params)

    def base(c: Mapping[str, Any]) -> Tuple:
        return tuple(sorted((k, str(v)) for k, v in c.items() if k != "bracket"))

    groups: Dict[Tuple, List[int]] = {}
    for j, c in enumerate(combos):
        groups.setdefault(base(c), []).append(j)
    stage_a = [j for j, c in enumerate(combos) if str(c.get("bracket", "none")) == "none"]
    siblings = {j: groups[base(c)] for j, c in enumerate(combos)}
    return combos, (stage_a or None), siblings


# -- verdicts ---------------------------------------------------------------------------------

def phase9_rule(acceptance: Mapping[str, Any], legs: Mapping[str, Any], calmar: Optional[float], long_only_calmar: Optional[float]) -> Dict[str, Any]:
    """The pre-registered walk-forward part (1)-(3) of the Phase 9 evidence rule."""
    short_pf = (legs.get("short") or {}).get("profit_factor")
    short_n = int((legs.get("short") or {}).get("n_trades") or 0)
    checks = {
        "v1c_gates": bool(acceptance.get("passed")),
        "short_leg_pf_gt_1": bool(short_n > 0 and short_pf is not None and _num(short_pf) > 1.0),
        "beats_long_only_calmar": bool(calmar is not None and long_only_calmar is not None and _num(calmar) > _num(long_only_calmar)),
    }
    checks["walk_forward_passed"] = all(checks.values())
    return checks


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else x


def _finite(v: Any, key: str = "") -> Any:
    """JSON-safe values: non-finite -> None, except an infinite profit factor -> 999 (Sprint 2c's convention)."""
    if isinstance(v, (np.floating, float)):
        f = float(v)
        if not math.isfinite(f):
            return NO_LOSS_PROFIT_FACTOR if (key == "profit_factor" and f > 0) else None
        return f
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, dict):
        return {k: _finite(x, str(k)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_finite(x) for x in v]
    return v


def stored_long_only(v1c: Mapping[str, Any], key: str, instrument: str, timeframe: str) -> Optional[Mapping[str, Any]]:
    for r in v1c.get("results", []):
        if r["candidate"] == key and r["instrument"] == instrument and r["timeframe"] == timeframe and (r.get("regime") or {}).get("mode") == "none":
            return r
    return None


REPRO_KEYS = ("total_return", "cagr", "sharpe", "max_drawdown", "calmar", "profit_factor")
STORED_DECIMALS = 6  # scripts/run_research_v1c.py rounds every float of its results JSON to 6 decimals
REPRO_TOLERANCE = 0.5 * 10 ** -STORED_DECIMALS + 1e-12


def reproduction_check(wf: LSWalkForward, stored: Mapping[str, Any]) -> Dict[str, Any]:
    """The long-only path against Sprint 2c's stored walk-forward numbers (same rules, same windows).

    The stored numbers carry 6 decimals, so agreement means every metric is within half a unit of the
    6th decimal (and normally rounds to exactly the stored value), the same trade count and the same
    most-selected rule."""
    got = wf.oos_metrics
    exp = stored["oos"]
    diffs: Dict[str, float] = {}
    exact = True
    for k in REPRO_KEYS:
        a, b = _num(got.get(k)), _num(exp.get(k))
        if k == "profit_factor" and not math.isfinite(a):
            a = 999.0
        diffs[k] = abs(a - b)
        exact &= round(a, STORED_DECIMALS) == b
    trades_ok = int(_num(got.get("n_trades"))) == int(_num(exp.get("n_trades")))
    selected_ok = _params_key(_canon(wf.rule_most_often or {})) == _params_key(_canon(stored.get("selected_params") or {}))
    worst = max(diffs.values()) if diffs else 0.0
    return {"max_abs_difference": worst, "max_abs_difference_text": f"{worst:.1e}", "rounds_to_stored": bool(exact),
            "n_trades": int(_num(got.get("n_trades"))),
            "n_trades_stored": int(_num(exp.get("n_trades"))), "selected_matches": bool(selected_ok),
            "ok": bool(worst <= REPRO_TOLERANCE and trades_ok and selected_ok),
            "reproduced": {k: _finite(got.get(k), k) for k in REPRO_KEYS}, "stored": {k: _finite(exp.get(k), k) for k in REPRO_KEYS}}


def _canon(params: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items()}


def _as_params(raw: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items()}


# -- one configuration -------------------------------------------------------------------------------

def run_configuration(
    inp: SeriesInputs,
    frames: LSFrames,
    combos: Sequence[Mapping[str, Any]],
    stage_a: Optional[Sequence[int]],
    siblings: Mapping[int, Sequence[int]],
    key: str,
    variant: Variant,
    instrument: str,
    timeframe: str,
    cfg: StudyConfig,
    context,
    long_only_ref: Optional[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], LSWalkForward]:
    t0 = time.monotonic()
    wf_cfg = cfg.wf(timeframe)
    wf = run_ls_walk_forward(inp, frames, combos, wf_cfg, cfg, variant, stage_a=stage_a, siblings=siblings)
    windows = make_windows(len(inp.df), wf_cfg)
    candidate = get_candidate(key)
    notes: List[str] = []
    selected = wf.rule_most_often
    if selected is None:
        last = wf.last_selected
        selected = dict(last.params) if last is not None else dict(candidate.default_params, bracket="none")
        if last is None:
            notes.append("no rule qualified (min trades) in any training window")
    # Robustness: the selected set and its ±30 % neighbours replayed with the policy sizing over every test window.
    neighbours = perturbed_params(selected, list(candidate.grid), tolerance=0.30)
    sets = [selected] + neighbours
    pert = build_ls_frames(key, inp.df, sets, context, no_trade=cfg.no_trade(), shorts=variant.shorts)
    replays = replay_fixed(inp, pert, range(len(sets)), windows, cfg, variant)
    neighbour_returns = np.array([r["total_return"] for r in replays[1:]], dtype=float)
    robust = {
        "n_neighbours": int(len(neighbours)), "best": float(replays[0]["total_return"]),
        "median": float(np.median(neighbour_returns)) if neighbour_returns.size else float("nan"),
        "min": float(neighbour_returns.min()) if neighbour_returns.size else float("nan"),
        "share_above_threshold": float((neighbour_returns > 0).mean()) if neighbour_returns.size else float("nan"),
    }
    sel_frames = build_ls_frames(key, inp.df, [selected], context, no_trade=cfg.no_trade(), shorts=variant.shorts)
    stress = {f"slippage_x{m:g}": float(replay_fixed(inp, sel_frames, [0], windows, cfg, variant, slippage_mult=m)[0]["total_return"])
              for m in cfg.slippage_stress}
    if variant.shorts:
        fs = replay_fixed(inp, sel_frames, [0], windows, cfg, variant, funding_mult=cfg.funding_stress)[0]
        stress[f"funding_x{cfg.funding_stress:g}"] = float(fs["total_return"])
        stress[f"funding_x{cfg.funding_stress:g}_calmar"] = _finite(fs["calmar"])
        f0 = replay_fixed(inp, sel_frames, [0], windows, cfg, variant, funding_mult=0.0)[0]
        stress["funding_x0"] = float(f0["total_return"])
    stitched = wf.oos_returns
    moments = return_moments(stitched.to_numpy())
    observed_sr = sharpe(stitched.to_numpy(), 1.0)
    last = wf.last_selected or wf.windows[-1]
    dsr = deflated_sharpe_ratio(observed_sr, list(last.train_sharpes), len(stitched), moments["skew"], moments["kurt"])
    dsr["observed_sr"] = observed_sr
    yearly_gate = yearly_gate_v2(wf.oos_equity)
    trades = wf.oos_trades
    equity_level = (trades["return_pct"] * trades["size_fraction"]).to_numpy() if len(trades) else []
    mc = trade_order_bootstrap(equity_level, n_paths=cfg.mc_paths, seed=cfg.seed)
    acceptance = acceptance_check_v1c(wf.oos_metrics, yearly_gate, robust)
    legs = side_metrics(trades, init_cash=WINDOW_INIT_CASH) if len(trades) else side_metrics(_no_trades(), init_cash=WINDOW_INIT_CASH)
    lo_oos = (long_only_ref or {}).get("oos") or {}
    rule = phase9_rule(acceptance, legs, wf.oos_metrics.get("calmar"), lo_oos.get("calmar")) if variant.shorts else None
    perp_priced = None
    short_no_crash = None
    per_window = [w.rule for w in wf.windows]
    summary_keys = ("total_return", "cagr", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades", "funding_total_pct")
    if variant.shorts and inp.perp is not None:
        pp = replay_fixed(inp, frames, [], windows, cfg, variant, perp_priced=True, per_window=per_window)[0]
        perp_priced = {k: _finite(pp.get(k), k) for k in summary_keys}
        perp_priced["legs"] = _finite(pp["legs"])
    if variant.shorts and inp.short_fracs_no_crash is not None:
        nc = replay_fixed(inp, frames, [], windows, cfg, variant, per_window=per_window, short_no_crash=True)[0]
        short_no_crash = {k: _finite(nc.get(k), k) for k in summary_keys}
        short_no_crash["legs"] = _finite(nc["legs"])
        short_no_crash["yearly"] = nc["yearly"]
    out: Dict[str, Any] = {
        "candidate": key, "label": candidate.label, "variant": variant.key, "variant_label": variant.label,
        "instrument": instrument, "timeframe": timeframe, "grid_size": len(combos),
        "selected_params": _canon(selected), "rule_frequency": wf.rule_frequency,
        "oos": {k: _finite(v, k) for k, v in wf.oos_metrics.items()},
        "yearly": {int(k): float(v) for k, v in yearly_gate["calendar_years"].items()},
        "yearly_gate": _finite(yearly_gate), "robustness": _finite(robust), "dsr": _finite(dsr), "montecarlo": _finite(mc),
        "stress": _finite(stress), "legs": _finite(legs), "short_share": wf.short_share, "max_leverage": wf.max_leverage,
        "funding_total_pct": wf.funding_total_pct, "acceptance": acceptance, "phase9_rule": rule,
        "long_only": None if long_only_ref is None else {
            "oos": {k: _finite(lo_oos.get(k), k) for k in ("total_return", "cagr", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades")},
            "yearly": (long_only_ref.get("yearly_gate") or {}).get("calendar_years"),
            "passed": bool((long_only_ref.get("acceptance") or {}).get("passed")),
            "holdout": long_only_ref.get("holdout"),
        },
        "perp_priced": perp_priced,
        "diagnostic_short_no_crash_filter": short_no_crash,
        "windows": [
            {"idx": w.idx, "train": f"{w.train_start:%Y-%m-%d}->{w.train_end:%Y-%m-%d}", "test": f"{w.test_start:%Y-%m-%d}->{w.test_end:%Y-%m-%d}",
             "rule": _canon(w.params), "test_return": _finite(w.test_metrics.get("total_return")),
             "test_max_dd": _finite(w.test_metrics.get("max_drawdown")), "test_trades": w.test_metrics.get("n_trades"),
             "short_share": _finite(w.test_metrics.get("short_share"))}
            for w in wf.windows
        ],
        "notes": notes,
        "holdout": None,
    }
    out["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    return out, wf


def evaluate_holdout(
    df_all: pd.DataFrame,
    n_in: int,
    key: str,
    selected: Mapping[str, Any],
    context,
    cfg: StudyConfig,
    variant: Variant,
    timeframe: str,
    settlements: pd.Series,
) -> Dict[str, Any]:
    """The untouched 12 months, once: the most-selected rule, policy sizing, a flat start (Sprint 2c's construction)."""
    ppy = bars_per_year(timeframe)
    frames = build_ls_frames(key, df_all, [_as_params(selected)], context, no_trade=cfg.no_trade(), shorts=variant.shorts)
    fracs = fraction_matrix(df_all, [cfg.policy()], timeframe, ppy)
    fund_all = funding_per_bar(df_all.index, settlements)
    hold = slice(n_in, len(df_all))
    res = simulate_ls(df_all, frames, hold, variant=variant, costs=cfg.costs(variant), fund=fund_all, size_fraction=fracs, columns=[0],
                      ladder=cfg.ladder(timeframe), ladder_mask=np.array([cfg.policy_ladder]), rebalance_threshold=cfg.rebalance_threshold,
                      mmr=cfg.mmr)
    hm = equity_metrics(res.equity[:, 0], ppy)
    hm.update(trade_metrics(res.trades, init_cash=res.init_cash, n_bars=res.n_bars, periods_per_year=ppy))
    hm["avg_allocation"] = float(res.avg_allocation[0])
    hm["short_share"] = float(res.short_share()[0])
    hm["funding_total_pct"] = float(res.funding_total[0]) / res.init_cash
    hm["max_leverage"] = float(res.max_leverage[0])
    hm["funding_coverage"] = funding_coverage(df_all.index[hold], settlements)
    out = {k: _finite(v, k) for k, v in hm.items()}
    out["legs"] = _finite(side_metrics(res.trades, init_cash=res.init_cash) if len(res.trades) else side_metrics(_no_trades(), init_cash=res.init_cash))
    out["span"] = f"{df_all.index[n_in]:%Y-%m-%d}->{df_all.index[-1]:%Y-%m-%d}"
    return out


def holdout_step(res: Dict[str, Any], *, evaluate: bool, opener) -> None:
    """Open the holdout ONLY for a configuration that met the walk-forward part (1)-(3) of the evidence rule, and only once."""
    rule = res.get("phase9_rule") or {}
    if not rule.get("walk_forward_passed"):
        res["holdout"] = None
        res["holdout_confirmed"] = None
        res["holdout_note"] = "untouched: the walk-forward part of the evidence rule was not met"
        return
    if not evaluate:
        res["holdout"] = None
        res["holdout_confirmed"] = None
        res["holdout_note"] = "met the walk-forward part of the rule; holdout not requested in this run"
        return
    if res.get("holdout") is not None:
        raise StudyError("the holdout of this configuration was already opened")
    res["holdout"] = opener()
    res["holdout_confirmed"] = holdout_verdict(res)
    res["holdout_note"] = "opened once (met the walk-forward part of the rule)"


def holdout_openings(series: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The holdout openings of one run, for the append-only ledger (every opening is recorded, re-runs included)."""
    out: List[Dict[str, Any]] = []
    for s in series:
        for r in s.get("results", []):
            h = r.get("holdout")
            if not h:
                continue
            out.append({"configuration": f"{r['candidate']} {r['instrument']} {r['timeframe']} {r['variant']}",
                        "selected_params": r.get("selected_params"), "span": h.get("span"),
                        "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"),
                        "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades"),
                        "confirmed": r.get("holdout_confirmed")})
    return out


def default_params_runs(df_in: pd.DataFrame, key: str, context, cfg: StudyConfig, timeframe: str, fund: np.ndarray) -> Dict[str, Any]:
    """The family's DEFAULT parameters (fixed in Sprint 2, no bracket, no selection) over descriptive_start -> holdout start."""
    ppy = bars_per_year(timeframe)
    params = dict(get_candidate(key).default_params, bracket="none")
    frames = build_ls_frames(key, df_in, [params], context, no_trade=cfg.no_trade())
    fracs = fraction_matrix(df_in, [cfg.policy()], timeframe, ppy)
    start = int(df_in.index.searchsorted(pd.Timestamp(cfg.descriptive_start, tz="UTC"), side="left"))
    if start >= len(df_in):
        raise StudyError(f"no in-sample bars after {cfg.descriptive_start}")
    sl = slice(start, len(df_in))
    out: Dict[str, Any] = {"params": _canon(params), "span": f"{df_in.index[start]:%Y-%m-%d}->{df_in.index[-1]:%Y-%m-%d}"}
    for vkey, variant in VARIANTS.items():
        res = simulate_ls(df_in, frames, sl, variant=variant, costs=cfg.costs(variant), fund=fund, size_fraction=fracs, columns=[0],
                          ladder=cfg.ladder(timeframe), ladder_mask=np.array([cfg.policy_ladder]), rebalance_threshold=cfg.rebalance_threshold,
                          mmr=cfg.mmr)
        eq = pd.Series(res.equity[:, 0], index=df_in.index[sl])
        m = equity_metrics(res.equity[:, 0], ppy)
        m.update(trade_metrics(res.trades, init_cash=res.init_cash, n_bars=res.n_bars, periods_per_year=ppy))
        m["short_share"] = float(res.short_share()[0])
        m["funding_total_pct"] = float(res.funding_total[0]) / res.init_cash
        m["max_leverage"] = float(res.max_leverage[0])
        out[vkey] = {k: _finite(v, k) for k, v in m.items()}
        out[vkey]["yearly"] = {int(y): float(v) for y, v in calendar_year_returns(eq).items()}
        out[vkey]["legs"] = _finite(side_metrics(res.trades, init_cash=res.init_cash) if len(res.trades) else side_metrics(_no_trades(), init_cash=res.init_cash))
    return out


# -- one series -------------------------------------------------------------------------------------

def series_inputs(layout: LakeLayout, instrument: str, timeframe: str, cfg: StudyConfig) -> Dict[str, Any]:
    df_all = load_or_resample_candles(layout, instrument, timeframe)
    if len(df_all) < 1000:
        raise StudyError(f"{instrument} {timeframe}: only {len(df_all)} bars in the lake")
    df_in, df_hold = split_holdout(df_all, holdout_months=cfg.holdout_months)
    settlements = load_funding(layout, instrument, source=cfg.funding_source)
    if settlements.empty:
        raise StudyError(f"{instrument}: no {cfg.funding_source} funding history in the lake")
    fund = funding_per_bar(df_in.index, settlements)
    ppy = bars_per_year(timeframe)
    perp_df = load_perp_candles(layout, instrument, timeframe)
    perp = None
    perp_info: Dict[str, Any] = {"available": False}
    if not perp_df.empty:
        aligned = align_perp(df_in, perp_df)
        perp_info = {"available": True, "coverage": aligned["coverage"], "missing_bars": aligned["missing"],
                     "span": f"{perp_df.index[0]:%Y-%m-%d}->{perp_df.index[-1]:%Y-%m-%d}"}
        if aligned["coverage"] > 0.99:
            perp = {k: aligned[k] for k in ("open", "high", "low", "close")}
        else:
            perp_info["note"] = "perpetual-swap candles cover too little of the in-sample bars; the perp-priced replay is skipped"
    no_crash = SizingSpec(kind="vol_target", target_vol=cfg.policy_target_vol, vol_lookback=cfg.policy_lookback, ladder=cfg.policy_ladder)
    inp = SeriesInputs(df=df_in, fund=fund, policy_fracs=fraction_matrix(df_in, [cfg.policy()], timeframe, ppy), ladder=cfg.ladder(timeframe),
                       ppy=ppy, perp=perp, short_fracs_no_crash=fraction_matrix(df_in, [no_crash], timeframe, ppy))
    return {"df_all": df_all, "df_in": df_in, "df_hold": df_hold, "settlements": settlements, "inp": inp, "perp_info": perp_info,
            "funding_coverage": funding_coverage(df_in.index, settlements)}


def run_series(layout: LakeLayout, instrument: str, timeframe: str, cfg: StudyConfig, v1c: Mapping[str, Any], *,
               families: Sequence[str] = STUDY_FAMILIES, variants: Sequence[str] = JUDGED_VARIANTS, evaluate_holdout_: bool = False,
               log=print) -> Dict[str, Any]:
    """Every family x design on one series; the long-only reproduction first, then the judged designs."""
    if evaluate_holdout_ and cfg.quick:
        raise StudyError("quick mode (cut grids, no reproduction check) never opens the holdout")
    data = series_inputs(layout, instrument, timeframe, cfg)
    df_all, df_in, inp = data["df_all"], data["df_in"], data["inp"]
    context = positioning_context(layout, instrument, timeframe, source=cfg.positioning_source)
    out: Dict[str, Any] = {
        "instrument": instrument, "timeframe": timeframe,
        "span": f"{instrument} {timeframe}: {df_all.index[0]:%Y-%m-%d}->{df_all.index[-1]:%Y-%m-%d} ({len(df_all)} bars)",
        "holdout_span": f"{data['df_hold'].index[0]:%Y-%m-%d}->{data['df_hold'].index[-1]:%Y-%m-%d}" if len(data["df_hold"]) else None,
        "in_sample_end": f"{df_in.index[-1]:%Y-%m-%d %H:%M}", "funding_coverage": data["funding_coverage"], "perp": data["perp_info"],
        "reproduction": [], "results": [], "defaults": {},
    }
    for key in families:
        combos, stage_a, siblings = study_grid(key, cfg)
        log(f"[{instrument} {timeframe}] {key}: building frames for {len(combos)} rules ...")
        frames = build_ls_frames(key, df_in, combos, context, no_trade=cfg.no_trade())
        stored = stored_long_only(v1c, key, instrument, timeframe)
        if stored is not None and not cfg.quick:
            wf_lo = run_ls_walk_forward(inp, frames, combos, cfg.wf(timeframe), cfg, VARIANTS["long_only"], stage_a=stage_a, siblings=siblings)
            check = reproduction_check(wf_lo, stored)
            check.update({"candidate": key, "instrument": instrument, "timeframe": timeframe})
            out["reproduction"].append(check)
            log(f"  reproduction of Sprint 2c long-only: ok={check['ok']} max abs. diff {check['max_abs_difference']:.1e} "
                f"rounds to stored={check['rounds_to_stored']}")
            if not check["ok"]:
                raise StudyError(f"{key} {instrument} {timeframe}: the long-only path does not reproduce Sprint 2c's stored numbers: {check}")
        for vkey in variants:
            variant = VARIANTS[vkey]
            res, wf = run_configuration(inp, frames, combos, stage_a, siblings, key, variant, instrument, timeframe, cfg, context, stored)
            rule = res.get("phase9_rule") or {}
            holdout_step(res, evaluate=evaluate_holdout_,
                         opener=lambda res=res, variant=variant, key=key: evaluate_holdout(df_all, len(df_in), key, res["selected_params"], context,
                                                                                           cfg, variant, timeframe, data["settlements"]))
            out["results"].append(res)
            o = res["oos"]
            log(f"  {key} {vkey}: CAGR {_pct(o.get('cagr'))} Sharpe {_f2(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} "
                f"Calmar {_f2(o.get('calmar'))} PF {_f2(o.get('profit_factor'))} trades {o.get('n_trades')} short {res['short_share'] * 100:.0f}% "
                f"short-PF {_f2((res['legs'].get('short') or {}).get('profit_factor'))} gates={res['acceptance']['passed']} "
                f"rule={rule.get('walk_forward_passed')} ({res['elapsed_seconds']}s)")
        out["defaults"][key] = default_params_runs(df_in, key, context, cfg, timeframe, inp.fund)
    return out


def _pct(v: Any) -> str:
    return "-" if v is None else f"{_num(v) * 100:+.1f}%"


def _f2(v: Any) -> str:
    return "-" if v is None else f"{_num(v):.2f}"


# -- descriptive analyses (2020-01-01 -> holdout start) ------------------------------------------------

def adverse_moves(df_1h: pd.DataFrame, *, horizons_hours: Sequence[int] = (4, 24, 168, 720), mmr: float = DEFAULT_MMR) -> Dict[str, Any]:
    """The largest rises a short opened at an hourly close would have faced within each horizon (high over the next H hours / close - 1)."""
    if df_1h.empty:
        return {}
    close = df_1h["close"].astype(float)
    high = df_1h["high"].astype(float)
    out: Dict[str, Any] = {"bars": int(len(df_1h)), "span": f"{df_1h.index[0]:%Y-%m-%d}->{df_1h.index[-1]:%Y-%m-%d}"}
    liq_rise = 2.0 / (1.0 + mmr) - 1.0
    for hours in horizons_hours:
        fwd = high[::-1].rolling(int(hours), min_periods=int(hours)).max()[::-1].shift(-1)
        rise = (fwd / close - 1.0).dropna()
        if rise.empty:
            continue
        t = rise.idxmax()
        out[f"{hours}h"] = {"max": float(rise.max()), "at": f"{t:%Y-%m-%d %H:%M}", "p99": float(rise.quantile(0.99)),
                            "p999": float(rise.quantile(0.999)), "share_ge_20pct": float((rise >= 0.20).mean()),
                            "share_ge_liquidation": float((rise >= liq_rise).mean())}
    gap = (df_1h["open"] / close.shift(1) - 1.0).dropna()
    spike = (high / close.shift(1) - 1.0).dropna()
    out["largest_open_gap_up"] = float(gap.max()) if len(gap) else None
    out["largest_one_hour_spike"] = float(spike.max()) if len(spike) else None
    out["largest_one_hour_spike_at"] = f"{spike.idxmax():%Y-%m-%d %H:%M}" if len(spike) else None
    out["isolated_1x_liquidation_rise"] = liq_rise
    return out


def descriptive(layout: LakeLayout, cfg: StudyConfig, holdout_start: pd.Timestamp, instruments: Sequence[str] = STUDY_INSTRUMENTS) -> Dict[str, Any]:
    start = pd.Timestamp(cfg.descriptive_start, tz="UTC")
    out: Dict[str, Any] = {"span": f"{start:%Y-%m-%d}->{holdout_start:%Y-%m-%d}"}
    for inst in instruments:
        settle = load_funding(layout, inst, source=cfg.funding_source)
        spot = load_candles(layout, inst, "1H")
        spot = spot[(spot.index >= start) & (spot.index < holdout_start)]
        perp = load_perp_candles(layout, inst, "1H")
        perp_in = perp[(perp.index >= start) & (perp.index < holdout_start)] if not perp.empty else perp
        entry: Dict[str, Any] = {
            "funding_by_year": funding_by_year(settle, start=start, end=holdout_start),
            "okx_vs_binance_funding": funding_overlap(layout, inst),
            "adverse_moves_spot": adverse_moves(spot, mmr=cfg.mmr),
            "adverse_moves_perp": adverse_moves(perp_in, mmr=cfg.mmr) if not perp_in.empty else {},
            "basis_1h": basis_stats(spot, perp_in) if not perp_in.empty else {"n": 0},
        }
        s = settle[(settle.index >= start) & (settle.index < holdout_start)]
        days = max(1.0, (s.index[-1] - s.index[0]).total_seconds() / 86_400.0) if len(s) else 1.0
        entry["funding_span_summary"] = {
            "settlements": int(len(s)), "annualized_mean": float(s.mean() * len(s) / days * 365.25) if len(s) else None,
            "summed": float(s.sum()) if len(s) else None, "share_negative": float((s < 0).mean()) if len(s) else None,
        }
        out[inst] = _finite(entry)
    return out
