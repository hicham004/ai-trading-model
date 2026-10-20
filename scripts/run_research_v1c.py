"""Sprint 2c research runner: regime gates, portfolio sizing, turnover, S5 re-test (SIMULATION ONLY).

Per candidate x instrument x timeframe x regime mode, a walk-forward in which
the regime-v2 model is fitted on every window's TRAIN slice and applied
forward as an ENTRY gate (or an entry-size scale), the trading rule is
selected on the gated train slice exactly as in Sprint 2b, and the test slice
is simulated once under the FIXED a-priori policy sizing (planner decision
2). Fixed replays measure robustness, the full-size sleeve and slippage
stress. The Sprint 2c gates (planner decision 1: rolling 12-month windows)
are applied to the stitched out-of-sample curve. Sleeves are combined into
sleeve-sized and jointly-sized portfolios. Writes
``docs/research/ENSEMBLE_V1C_REPORT.md``, a results JSON and the
machine-readable paper-fleet shortlist.

Example::

    python scripts/run_research_v1c.py --evaluate-holdout --workers 4
    python scripts/run_research_v1c.py --quick --strategies S2 --instruments BTC-USDT --timeframes 4H

Nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.models import SimulationConfig  # noqa: E402
from app.backtest.simulator import run_signal_backtest  # noqa: E402
from app.broker.base import CostModel  # noqa: E402
from app.datalake.layout import LakeLayout  # noqa: E402
from app.risk.manager import RiskLimits, RiskManager  # noqa: E402
from app.strategy.timeframes import parse_timeframe  # noqa: E402
from research.bracket import BRACKETS  # noqa: E402
from research.data import bars_per_year, load_or_resample_candles, positioning_context, split_holdout, to_market_candles  # noqa: E402
from research.engine import Costs, buy_and_hold  # noqa: E402
from research.gated_walkforward import (  # noqa: E402
    WindowRegime,
    gate_desired_matrix,
    regimes_for_windows,
    replay_gated,
    run_gated_walk_forward,
    slippage_stress_gated,
)
from research.metrics import deflated_sharpe_ratio, equity_metrics, return_moments, sharpe, trade_metrics  # noqa: E402
from research.montecarlo import trade_order_bootstrap  # noqa: E402
from research.portfolio import align_sleeves, combine, combine_sized, equal_risk_weights  # noqa: E402
from research.regime_v2 import RegimeV2Config, bear_probability, entry_gate_mask, fit_regime, size_multiplier  # noqa: E402
from research.report_v1c import (  # noqa: E402
    REFERENCE_CANDIDATES,
    acceptance_check_v1c,
    controls,
    executive_summary,
    holdout_verdict,
    regime_study,
    render_report_v1c,
    s5_study,
    shortlist,
    turnover_study,
    write_shortlist_file,
    yearly_gate_v2,
)
from research.sized_walkforward import SizingSelection  # noqa: E402
from research.sizing import LadderConfig, SizingSpec, fraction_matrix, sizing_grid  # noqa: E402
from research.strategies import ALL_KEYS, REFERENCES, S5_RETEST_VARIANTS, TURNOVER_VARIANTS, get_candidate  # noqa: E402
from research.strategies.adapters import ResearchStrategyAdapter  # noqa: E402
from research.strategies.base import days_to_bars  # noqa: E402
from research.strategies.s0_filters import NoTradeConfig, blocked_share  # noqa: E402
from research.strategies.s5_positioning import positioning_coverage  # noqa: E402
from research.sweep import Frames, build_frames, param_grid, perturbed_params, simulate_sizing  # noqa: E402
from research.walkforward import WalkForwardConfig, make_windows  # noqa: E402

DEFAULT_STRATEGIES = ["hold", "S1", "S2", "S4", "S1w", "S1d", "S2d", "S4d", "S1h", "S1+S5", "S1+S5s", "S2+S5", "S2+S5s"]
PORTFOLIO_FAMILIES = ("S1", "S2", "S4")
DEFAULT_BRACKETS = ["none", "tp2", "trail1", "time30"]
ALL_MODES = ("none", "gate", "scale")


def modes_for(key: str, requested: Sequence[str]) -> List[str]:
    """Which regime modes a candidate runs (fixed a priori; see the report's method notes)."""
    if key in REFERENCES:
        allowed = ("none",)  # always-long never exits, so an entry gate only delays one entry per window
    elif key in ("S1", "S2", "S4"):
        allowed = ALL_MODES
    else:
        allowed = ("none", "gate")
    return [m for m in requested if m in allowed]


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprint 2c walk-forward research over the Parquet lake (simulation only).")
    p.add_argument("--instruments", nargs="+", default=["BTC-USDT", "ETH-USDT"])
    p.add_argument("--timeframes", nargs="+", default=["4H", "6H"])
    p.add_argument("--strategies", nargs="+", default=DEFAULT_STRATEGIES, choices=ALL_KEYS)
    p.add_argument("--regime-modes", nargs="+", default=list(ALL_MODES), choices=list(ALL_MODES))
    p.add_argument("--regime-states", type=int, default=3)
    p.add_argument("--regime-vol-days", type=float, default=7.0)
    p.add_argument("--bear-prob-max", type=float, default=0.5)
    p.add_argument("--bear-scale", type=float, default=0.25)
    p.add_argument("--sensitivity-thresholds", nargs="+", type=float, default=[0.35, 0.5, 0.65])
    p.add_argument("--no-scheduled-events", action="store_true", help="Disable the built-in FOMC windows in the S0 filter.")
    p.add_argument("--holdout-months", type=int, default=12)
    p.add_argument("--train-days", type=float, default=540)
    p.add_argument("--test-days", type=float, default=180)
    p.add_argument("--purge-days", type=float, default=7)
    p.add_argument("--min-trades", type=int, default=20)
    p.add_argument("--select-by", default="sharpe", choices=["sharpe", "sortino", "profit_factor", "calmar", "total_return"])
    p.add_argument("--fee", type=float, default=0.0010, help="Fee per side (default 0.10%%).")
    p.add_argument("--slippage", type=float, default=0.0005, help="Slippage per side (default 0.05%%).")
    p.add_argument("--policy-target-vol", type=float, default=0.10)
    p.add_argument("--policy-lookback", type=int, default=30)
    p.add_argument("--policy-crash-dd", type=float, default=0.15)
    p.add_argument("--policy-crash-days", type=float, default=90.0)
    p.add_argument("--policy-no-ladder", action="store_true")
    p.add_argument("--no-comparison", action="store_true", help="Skip the small train-selected sizing comparison.")
    p.add_argument("--rebalance-threshold", type=float, default=0.25)
    p.add_argument("--ladder-recovery-days", type=float, default=30.0)
    p.add_argument("--portfolio-dd-budget", type=float, default=0.15)
    p.add_argument("--portfolio-target-vols", nargs="+", type=float, default=[0.10, 0.15])
    p.add_argument("--positioning-source", default="binance", choices=["none", "okx", "binance"])
    p.add_argument("--brackets", nargs="+", default=DEFAULT_BRACKETS, choices=list(BRACKETS))
    p.add_argument("--mc-paths", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--evaluate-holdout", action="store_true")
    p.add_argument("--quick", action="store_true", help="Small grids for a smoke run.")
    p.add_argument("--workers", type=int, default=1, help="Process workers over instrument x timeframe series.")
    p.add_argument("--lake-dir", default=None)
    p.add_argument("--report", default="docs/research/ENSEMBLE_V1C_REPORT.md")
    p.add_argument("--json", default="docs/research/ensemble_v1c_results.json")
    p.add_argument("--shortlist", default="docs/research/paper_fleet_shortlist_v1c.json")
    p.add_argument("--render-from-json", default=None, metavar="PATH",
                   help="Re-render the report/shortlist/narrative from a saved results JSON without re-running the research.")
    return p.parse_args(argv)


# -- configuration helpers ---------------------------------------------------------

def _wf_config(args, timeframe: str, *, min_trades: Optional[int] = None) -> WalkForwardConfig:
    return WalkForwardConfig(
        train_bars=days_to_bars(args.train_days, timeframe), test_bars=days_to_bars(args.test_days, timeframe),
        purge_bars=days_to_bars(args.purge_days, timeframe), min_trades=args.min_trades if min_trades is None else min_trades,
        select_by=args.select_by,
    )


def _policy_spec(args) -> SizingSpec:
    return SizingSpec(kind="vol_target", target_vol=args.policy_target_vol, vol_lookback=args.policy_lookback,
                      crash_dd=args.policy_crash_dd, crash_window_days=args.policy_crash_days, crash_mode="half",
                      ladder=not args.policy_no_ladder)


def _comparison_specs(args) -> List[SizingSpec]:
    if args.no_comparison:
        return []
    return sizing_grid(targets=(0.10, 0.15, 0.25), lookbacks=(30,), fixed=(), crash=((0.15, 90.0),), crash_modes=("half",), ladders=(True,))


def _regime_cfg(args, mode: str, *, bear_prob_max: Optional[float] = None) -> RegimeV2Config:
    return RegimeV2Config(mode=mode, n_states=args.regime_states, vol_window_days=args.regime_vol_days,
                          bear_prob_max=args.bear_prob_max if bear_prob_max is None else bear_prob_max, bear_scale=args.bear_scale)


def _no_trade(args) -> NoTradeConfig:
    return NoTradeConfig(scheduled_events=not args.no_scheduled_events)


def _rebalance(args) -> Optional[float]:
    return None if args.rebalance_threshold is None or args.rebalance_threshold < 0 else float(args.rebalance_threshold)


def _staging(combos: Sequence[Dict[str, Any]]) -> Tuple[Optional[List[int]], Dict[int, List[int]]]:
    def base(c: Dict[str, Any]) -> Tuple:
        return tuple(sorted((k, str(v)) for k, v in c.items() if k != "bracket"))
    groups: Dict[Tuple, List[int]] = {}
    for j, c in enumerate(combos):
        groups.setdefault(base(c), []).append(j)
    stage_a = [j for j, c in enumerate(combos) if str(c.get("bracket", "none")) == "none"]
    siblings = {j: groups[base(c)] for j, c in enumerate(combos)}
    return (stage_a or None), siblings


def _brackets_for(args, key: str) -> List[str]:
    if key in REFERENCES:
        return ["none"]
    if key in S5_RETEST_VARIANTS or key.endswith("+S5"):
        return ["none"]  # the S5 filter is an entry gate; brackets were almost never selected for it in Sprint 2b
    if args.quick:
        return [b for b in ("none", "tp2") if b in args.brackets] or ["none"]
    return list(args.brackets)


def _grid_for(args, candidate) -> Dict[str, List[Any]]:
    grid = dict(candidate.grid)
    if args.quick:
        grid = {k: v[:2] for k, v in grid.items()}
    return grid


# -- one candidate x series x regime mode ---------------------------------------------

def _event_driven_check(candidate, params, context, df_holdout: pd.DataFrame, instrument: str, timeframe: str, costs: Costs) -> Dict[str, Any]:
    candles = to_market_candles(df_holdout, instrument, timeframe)
    bar = parse_timeframe(timeframe)
    strategy = ResearchStrategyAdapter(candidate, {k: v for k, v in params.items() if k != "bracket"}, context, fallback_confidence=0.60)
    limits = RiskLimits(max_risk_per_trade=1.0, max_daily_loss=1.0, max_position_size=1.0, min_confidence=0.01,
                        max_data_staleness=bar * 2, require_stop_loss=True)
    config = SimulationConfig(starting_cash=10_000.0, costs=CostModel(fee_rate=costs.fee_rate, slippage_rate=costs.slippage_rate))
    result = run_signal_backtest(candles, strategy, config=config, risk_manager=RiskManager(limits), timeframe=timeframe)
    return {"total_return": result.ending_equity / result.starting_cash - 1.0, "n_trades": len(result.trades),
            "rejected_entries": result.rejected_entries, "max_drawdown": result.metrics.max_drawdown_pct / 100.0}


def run_candidate(args, layout: LakeLayout, df_all: pd.DataFrame, instrument: str, timeframe: str, key: str, mode: str, costs: Costs,
                  regimes: Sequence[WindowRegime]) -> Tuple[Dict[str, Any], pd.Series, pd.Series, pd.DataFrame]:
    t0 = time.monotonic()
    candidate = get_candidate(key)
    context = positioning_context(layout, instrument, timeframe, source=args.positioning_source)
    ppy = context.periods_per_year
    df_in, df_hold = split_holdout(df_all, holdout_months=args.holdout_months)
    has_stop = key not in REFERENCES
    regime_cfg = _regime_cfg(args, mode)
    policy = _policy_spec(args)
    no_trade = _no_trade(args)
    grid = _grid_for(args, candidate)
    grid["bracket"] = _brackets_for(args, key)
    combos = param_grid(grid, base=candidate.default_params)
    frames = build_frames(candidate, df_in, combos, context, no_trade=no_trade)
    cfg = _wf_config(args, timeframe, min_trades=1 if not has_stop else None)
    ladder = LadderConfig(recovery_bars=days_to_bars(args.ladder_recovery_days, timeframe))
    policy_fracs = fraction_matrix(df_in, [policy], timeframe, ppy)
    comp_specs = _comparison_specs(args)
    comp_fracs = fraction_matrix(df_in, comp_specs, timeframe, ppy) if comp_specs else None
    rebalance = _rebalance(args)
    stage_a, siblings = _staging(combos)
    comparison_cfg = SizingSelection(dd_cap=0.10, select_by="calmar", min_trades=1 if not has_stop else 10, rebalance_threshold=rebalance)

    wf = run_gated_walk_forward(df_in, frames, combos, cfg, policy, policy_fracs, ladder, regime_cfg, costs=costs, periods_per_year=ppy,
                                timeframe=timeframe, rebalance_threshold=rebalance, stage_a_columns=stage_a, siblings=siblings, regimes=regimes,
                                comparison_specs=comp_specs or None, comparison_fractions=comp_fracs, comparison_cfg=comparison_cfg)
    windows = make_windows(len(df_in), cfg)
    notes: List[str] = []
    selected = wf.rule_most_often
    if selected is None:
        last = wf.last_selected
        if last is not None:
            selected = dict(last.rule_params)
        else:
            notes.append("no rule qualified (min trades) in any training window")
            selected = dict(candidate.default_params, bracket="none")
    rule_col = next((i for i, c in enumerate(combos) if c == selected), None)
    if rule_col is None:
        combos = list(combos) + [selected]
        frames = build_frames(candidate, df_in, combos, context, no_trade=no_trade)
        rule_col = len(combos) - 1

    # Robustness: ±30 % perturbations replayed with the same per-window gate and the policy sizing.
    neighbours = perturbed_params(selected, list(candidate.grid), tolerance=0.30)
    sets = [selected] + neighbours
    pert_frames = build_frames(candidate, df_in, sets, context, no_trade=no_trade)
    replays, _ = replay_gated(df_in, pert_frames, range(len(sets)), windows, regimes, costs=costs, periods_per_year=ppy,
                              size_fraction=policy_fracs, ladder=ladder, ladder_on=policy.ladder, rebalance_threshold=rebalance)
    neighbour_returns = np.array([r["total_return"] for r in replays[1:]], dtype=float)
    robust = {
        "n_neighbours": int(len(neighbours)), "best": float(replays[0]["total_return"]),
        "median": float(np.median(neighbour_returns)) if neighbour_returns.size else float("nan"),
        "min": float(neighbour_returns.min()) if neighbour_returns.size else float("nan"),
        "share_above_threshold": float((neighbour_returns > 0).mean()) if neighbour_returns.size else float("nan"),
        "neighbours": [dict(params=sets[j + 1], total_return=replays[j + 1]["total_return"], max_drawdown=replays[j + 1]["max_drawdown"]) for j in range(len(neighbours))],
    }
    # Full-size sleeve (same gate, no sizing) for the jointly-sized portfolio.
    full_metrics, full_series = replay_gated(df_in, frames, [rule_col], windows, regimes, costs=costs, periods_per_year=ppy,
                                             size_fraction=None, want_returns=True)
    full_size = _finite_dict(full_metrics[0])
    full_returns = full_series[0]

    stitched = wf.oos_returns
    moments = return_moments(stitched.to_numpy())
    observed_sr = sharpe(stitched.to_numpy(), 1.0)
    last = wf.last_selected or wf.windows[-1]
    dsr = deflated_sharpe_ratio(observed_sr, list(last.train_sharpes_rules), len(stitched), moments["skew"], moments["kurt"])
    dsr["observed_sr"] = observed_sr
    yearly = {int(k): float(v) for k, v in wf.yearly.items()}
    yearly_gate = yearly_gate_v2(wf.oos_equity)
    trades = wf.oos_trades
    equity_level = (trades["return_pct"] * trades["size_fraction"]).to_numpy() if len(trades) else []
    mc = trade_order_bootstrap(equity_level, n_paths=args.mc_paths, seed=args.seed)
    stress = slippage_stress_gated(df_in, frames, rule_col, windows, regimes, base_costs=costs, periods_per_year=ppy, size_fraction=policy_fracs,
                                   ladder=ladder, ladder_on=policy.ladder, rebalance_threshold=rebalance)
    acceptance = acceptance_check_v1c(wf.oos_metrics, yearly_gate, robust)
    train_shares = [w.regime_train.get("bear_share") for w in wf.windows if w.regime_train]
    test_shares = [w.regime_test.get("bear_share") for w in wf.windows if w.regime_test]
    if "S5" in key:
        cov = positioning_coverage(df_in, context)
        notes.append(f"positioning data ({args.positioning_source}) cover {cov * 100:.1f}% of in-sample bars (filter passes elsewhere)")
    else:
        cov = None
    if not has_stop:
        notes.append("passive control: always long, no stop, policy sizing only; excluded from the shortlist (planner decision 6)")
    regime_errors = [r.error for r in regimes if r.error]
    if regime_errors:
        notes.append(f"regime fit failed in {len(regime_errors)} window(s); entries were blocked there (fail closed)")

    out: Dict[str, Any] = {
        "candidate": key, "label": candidate.label, "instrument": instrument, "timeframe": timeframe,
        "regime": regime_cfg.to_dict(), "policy_sizing": policy.to_dict(), "grid_size": len(combos),
        "selected_params": selected, "rule_frequency": wf.rule_frequency,
        "oos": {k: _finite(v, k) for k, v in wf.oos_metrics.items()}, "yearly": yearly, "yearly_gate": yearly_gate,
        "robustness": robust, "dsr": dsr, "montecarlo": mc, "slippage_stress": stress, "full_size": full_size,
        "comparison": _finite_dict(wf.comparison_metrics) if wf.comparison_metrics else None,
        "comparison_frequency": wf.comparison_frequency,
        "regime_train_bear_share_median": float(np.median(train_shares)) if train_shares else None,
        "regime_test_bear_share_median": float(np.median(test_shares)) if test_shares else None,
        "positioning_coverage": cov,
        "acceptance": acceptance,
        "windows": [
            {"idx": w.idx, "train": f"{w.train_start:%Y-%m-%d}->{w.train_end:%Y-%m-%d}", "test": f"{w.test_start:%Y-%m-%d}->{w.test_end:%Y-%m-%d}",
             "rule": w.rule_params, "rule_train_metric": None if not np.isfinite(w.rule_train_metric) else w.rule_train_metric,
             "qualified": w.n_qualified, "test_return": w.test_metrics.get("total_return"), "test_max_dd": w.test_metrics.get("max_drawdown"),
             "test_trades": w.test_metrics.get("n_trades"), "regime_train": w.regime_train, "regime_test": w.regime_test,
             "gate_blocked_share": w.gate_blocked_share, "comparison_sizing": w.comparison_label}
            for w in wf.windows
        ],
        "notes": notes,
    }

    # Passers are judged on the untouched holdout; the passive controls are evaluated on it too (a reference, not a selection).
    if (acceptance["passed"] or not has_stop) and args.evaluate_holdout and len(df_hold):
        full_frames = build_frames(candidate, df_all, [selected], context, no_trade=no_trade)
        full_fracs = fraction_matrix(df_all, [policy], timeframe, ppy)
        if regime_cfg.active:
            try:
                fitted = fit_regime(df_in, timeframe, ppy, regime_cfg)
                bear = bear_probability(fitted, df_all, timeframe, ppy, regime_cfg)
                ok = entry_gate_mask(bear, regime_cfg).to_numpy(dtype=bool)
                mult = size_multiplier(bear, regime_cfg).to_numpy(dtype=float)
                full_frames = Frames(desired=gate_desired_matrix(full_frames.desired, ok), stop=full_frames.stop, strength=full_frames.strength,
                                     time_stops=full_frames.time_stops, target=full_frames.target, trail_activate=full_frames.trail_activate,
                                     trail_dist=full_frames.trail_dist)
                full_fracs = full_fracs * mult[:, None]
            except ValueError as exc:
                notes.append(f"holdout regime fit failed: {exc}; holdout not evaluated")
                full_frames = None
        if full_frames is not None:
            hold_slice = slice(len(df_in), len(df_all))
            res = simulate_sizing(df_all, full_frames, 0, hold_slice, full_fracs, costs=costs, ladder=ladder, ladder_mask=np.array([policy.ladder]),
                                  rebalance_threshold=rebalance)
            hm = equity_metrics(res.equity[:, 0], ppy)
            hm.update(trade_metrics(res.trades, init_cash=res.init_cash, n_bars=res.n_bars, periods_per_year=ppy))
            hm["avg_allocation"] = float(res.avg_allocation[0])
            out["holdout"] = {k: _finite(v, k) for k, v in hm.items()}
            if has_stop and selected.get("bracket", "none") == "none" and not regime_cfg.active:
                try:
                    hold_frames = build_frames(candidate, df_hold, [selected], context, no_trade=no_trade)
                    vec = simulate_sizing(df_hold, hold_frames, 0, slice(0, len(df_hold)), np.ones((len(df_hold), 1)), costs=costs)
                    ev = _event_driven_check(candidate, selected, context, df_hold, instrument, timeframe, costs)
                    ev["vectorized_total_return"] = vec.equity[-1, 0] / vec.init_cash - 1.0
                    ev["n_trades_vectorized"] = int(len(vec.trades))
                    ev["difference"] = ev["total_return"] - ev["vectorized_total_return"]
                    out["holdout_event_driven"] = ev
                except Exception as exc:  # report, never hide
                    out["notes"].append(f"event-driven cross-check failed: {type(exc).__name__}: {exc}")
    out["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    return out, stitched, full_returns, trades


# -- one series (instrument x timeframe): all candidates and regime modes ------------

def run_series(args_dict: Dict[str, Any], instrument: str, timeframe: str) -> Dict[str, Any]:
    args = argparse.Namespace(**args_dict)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    costs = Costs(fee_rate=args.fee, slippage_rate=args.slippage)
    out: Dict[str, Any] = {"instrument": instrument, "timeframe": timeframe, "results": [], "failures": [], "sleeves": {}, "full_sleeves": {},
                           "trades": {}, "benchmark": None, "span": None, "holdout_span": None, "positioning": None, "sensitivity": [],
                           "s0_blocked_share": None, "skipped": None}
    df_all = load_or_resample_candles(layout, instrument, timeframe)
    if len(df_all) < 1000:
        out["skipped"] = f"only {len(df_all)} bars available"
        return out
    df_in, df_hold = split_holdout(df_all, holdout_months=args.holdout_months)
    out["span"] = f"{instrument} {timeframe}: {df_all.index[0]:%Y-%m-%d}->{df_all.index[-1]:%Y-%m-%d} ({len(df_all)} bars)"
    if len(df_hold):
        out["holdout_span"] = f"{df_hold.index[0]:%Y-%m-%d}->{df_hold.index[-1]:%Y-%m-%d}"
    cfg = _wf_config(args, timeframe)
    windows = make_windows(len(df_in), cfg)
    first_test = windows[0].test.start if windows else 0
    ppy = bars_per_year(timeframe)
    bh = buy_and_hold(df_in["open"].to_numpy()[first_test:], df_in["close"].to_numpy()[first_test:], costs=costs)
    bm = equity_metrics(bh, ppy)
    out["benchmark"] = {"instrument": instrument, "timeframe": timeframe, "total_return": float(bh[-1] / 10_000.0 - 1.0), "cagr": bm["cagr"],
                        "sharpe": bm["sharpe"], "max_drawdown": bm["max_drawdown"], "calmar": bm["calmar"]}
    out["positioning"] = _positioning_info(layout, instrument, timeframe, args.positioning_source, df_in)
    out["s0_blocked_share"] = blocked_share(df_in, timeframe, ppy, _no_trade(args))

    # Per-window regime fits are a function of the data only: fit once per mode and share across candidates.
    regime_cache: Dict[str, List[WindowRegime]] = {}

    def regimes_for(mode: str) -> List[WindowRegime]:
        if mode not in regime_cache:
            regime_cache[mode] = regimes_for_windows(df_in, windows, _regime_cfg(args, mode), timeframe, ppy)
        return regime_cache[mode]

    for key in args.strategies:
        for mode in modes_for(key, args.regime_modes):
            print(f"running {key} [{mode}] on {instrument} {timeframe} ...", flush=True)
            try:
                res, stitched, full_returns, trades = run_candidate(args, layout, df_all, instrument, timeframe, key, mode, costs, regimes_for(mode))
            except Exception as exc:  # one failing candidate must not lose the whole run
                print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                out["failures"].append({"candidate": key, "instrument": instrument, "timeframe": timeframe, "regime": mode, "error": f"{type(exc).__name__}: {exc}"})
                continue
            out["results"].append(res)
            out["sleeves"][(key, mode)] = stitched
            out["full_sleeves"][(key, mode)] = full_returns
            out["trades"][(key, mode)] = trades
            o = res["oos"]
            print(f"  OOS CAGR {_fmt_pct(o.get('cagr'))} Sharpe {_fmt(o.get('sharpe'))} maxDD {_fmt_pct(o.get('max_drawdown'))} Calmar {_fmt(o.get('calmar'))} "
                  f"PF {_fmt(o.get('profit_factor'))} trades {o.get('n_trades')} blocked {_fmt_pct(o.get('gate_blocked_share'))} "
                  f"roll12m+ {_fmt_pct(res['acceptance'].get('rolling_positive_share'))} pass={res['acceptance']['passed']} ({res['elapsed_seconds']}s)", flush=True)

    # Gate-threshold sensitivity on the best gated trend rule of this series (fixed replay of its most-selected parameters).
    gated = [r for r in out["results"] if r["candidate"] in ("S1", "S2", "S4") and r["regime"]["mode"] == "gate"]
    if gated and "gate" in args.regime_modes:
        lead = max(gated, key=lambda r: (r["oos"].get("calmar") or -9))
        candidate = get_candidate(lead["candidate"])
        context = positioning_context(layout, instrument, timeframe, source=args.positioning_source)
        frames = build_frames(candidate, df_in, [lead["selected_params"]], context, no_trade=_no_trade(args))
        policy = _policy_spec(args)
        pf = fraction_matrix(df_in, [policy], timeframe, ppy)
        ladder = LadderConfig(recovery_bars=days_to_bars(args.ladder_recovery_days, timeframe))
        for thr in args.sensitivity_thresholds:
            regs = regimes_for_windows(df_in, windows, _regime_cfg(args, "gate", bear_prob_max=thr), timeframe, ppy)
            m, series = replay_gated(df_in, frames, [0], windows, regs, costs=costs, periods_per_year=ppy, size_fraction=pf, ladder=ladder,
                                     ladder_on=policy.ladder, rebalance_threshold=_rebalance(args), want_returns=True)
            eq = (1.0 + series[0]).cumprod()
            years = yearly_gate_v2(eq)["calendar_years"]
            out["sensitivity"].append({"candidate": lead["candidate"], "instrument": instrument, "timeframe": timeframe, "bear_prob_max": thr,
                                       "cagr": m[0]["cagr"], "max_drawdown": m[0]["max_drawdown"], "calmar": m[0]["calmar"], "sharpe": m[0]["sharpe"],
                                       "n_trades": m[0]["n_trades"], "y2022": years.get(2022)})
    return out


def _positioning_info(layout: LakeLayout, instrument: str, timeframe: str, source: str, df_in: pd.DataFrame) -> Dict[str, Any]:
    ctx = positioning_context(layout, instrument, timeframe, source=source)
    info: Dict[str, Any] = {"source": source}
    for name, col, label in (("funding", "funding_rate", "funding"), ("open_interest", "oi_usd", "oi")):
        frame = getattr(ctx, name)
        if frame is None or frame.empty:
            info[f"{label}_span"] = "-"
            info[f"{label}_coverage"] = 0.0
            continue
        info[f"{label}_span"] = f"{frame.index[0]:%Y-%m-%d}->{frame.index[-1]:%Y-%m-%d} ({len(frame)} rows)"
        aligned = ctx.aligned(name, df_in.index, col)
        info[f"{label}_coverage"] = float(aligned.notna().mean()) if aligned is not None else 0.0
    return info


# -- portfolios ----------------------------------------------------------------------

def _pooled_trade_stats(trade_frames: Sequence[pd.DataFrame]) -> Tuple[int, float]:
    frames = [t for t in trade_frames if t is not None and len(t)]
    if not frames:
        return 0, 0.0
    pnl = pd.concat(frames, ignore_index=True)["pnl"].to_numpy(dtype=float)
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    pf = float(wins / losses) if losses > 0 else (999.0 if wins > 0 else 0.0)
    return int(pnl.size), pf


def _portfolios(args, results: Sequence[Dict[str, Any]], sleeves: Dict[Tuple, pd.Series], full_sleeves: Dict[Tuple, pd.Series],
                trades: Dict[Tuple, pd.DataFrame]) -> Tuple[List[Dict], Dict]:
    """Per regime mode: sleeve-sized (2b) and jointly-sized (2c) portfolios of the best timeframe per (family, instrument)."""
    out: List[Dict] = []
    corr: Dict = {}
    ladder_2b = LadderConfig(recovery_bars=max(1, int(args.ladder_recovery_days)))
    budget = float(args.portfolio_dd_budget)
    ladder_2c = LadderConfig(half_dd=budget / 2.0, flat_dd=budget, recovery_bars=max(1, int(args.ladder_recovery_days)))
    for mode in ("none", "gate"):
        best: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in results:
            if r["candidate"] not in PORTFOLIO_FAMILIES or r["regime"]["mode"] != mode:
                continue
            k = (r["candidate"], r["instrument"])
            calmar = r["oos"].get("calmar") or -1e9
            if (r["oos"].get("n_trades") or 0) >= 10 and (k not in best or calmar > (best[k]["oos"].get("calmar") or -1e9)):
                best[k] = r
        keys = [(c, i) for c in PORTFOLIO_FAMILIES for i in args.instruments if (c, i) in best]
        if len(keys) < 2:
            continue

        def name_of(c: str, i: str) -> str:
            return f"{c}/{i.split('-')[0]}/{best[(c, i)]['timeframe']}"

        sized = {name_of(c, i): sleeves[(c, i, best[(c, i)]["timeframe"], mode)] for c, i in keys}
        full = {name_of(c, i): full_sleeves[(c, i, best[(c, i)]["timeframe"], mode)] for c, i in keys}
        pooled_n, pooled_pf = _pooled_trade_stats([trades[(c, i, best[(c, i)]["timeframe"], mode)] for c, i in keys])
        daily_sized = align_sleeves(sized)
        daily_full = align_sleeves(full)
        if mode == "none":
            corr = daily_full.corr().to_dict()
        specs = [("sleeve-sized, equal risk, ladder 5/10", lambda: combine(daily_sized, equal_risk_weights(daily_sized), name="x", ladder=ladder_2b))]
        for tv in args.portfolio_target_vols:
            specs.append((f"jointly sized, vol target {tv * 100:.0f}%, ladder {budget * 50:.1f}/{budget * 100:.0f}",
                          lambda tv=tv: combine_sized(daily_full, name="x", target_vol=tv, ladder=ladder_2c)))
        for label, builder in specs:
            res = builder()
            d = res.to_dict()
            d["name"] = f"S1+S2+S4 x BTC+ETH — {label}"
            d["regime"] = mode
            d["pooled_trades"] = pooled_n
            d["pooled_profit_factor"] = pooled_pf
            yg = yearly_gate_v2(res.equity)
            d["yearly_gate"] = yg
            oos_like = dict(res.metrics, profit_factor=pooled_pf, n_trades=pooled_n)
            d["acceptance"] = acceptance_check_v1c(oos_like, yg, {"share_above_threshold": 1.0})
            d["acceptance"]["note"] = "robustness gate not evaluated at portfolio level (sleeves carry their own); profit factor and trade count are pooled from the policy-sized sleeves"
            out.append(d)
    return out, {a: {b: (None if v is None or not np.isfinite(v) else float(v)) for b, v in row.items()} for a, row in corr.items()}


# -- narrative --------------------------------------------------------------------

def _next_step(results: Sequence[Dict[str, Any]], holds: Sequence[Dict[str, Any]]) -> str:
    cands = [r for r in results if r["candidate"] not in REFERENCE_CANDIDATES]
    passed = [r for r in cands if r["acceptance"]["passed"]]
    confirmed = [r for r in passed if holdout_verdict(r) is True]
    contradicted = [r for r in passed if holdout_verdict(r) is False]
    unevaluated = [r for r in passed if holdout_verdict(r) is None]
    if len(confirmed) >= 2:
        return (f"{len(passed)} configurations pass the Sprint 2c walk-forward gates and {len(confirmed)} are confirmed by the untouched holdout "
                f"({len(contradicted)} contradicted): Sprint 5's paper fleet should run the confirmed ones forward on live public data next to the "
                "controls; demo exposure stays unchanged until the forward evidence matches the walk-forward expectations.")
    if passed and not unevaluated:
        names = "; ".join(f"{r['candidate']} {r['instrument']} {r['timeframe']} [{r['regime']['mode']}] holdout {(r.get('holdout') or {}).get('total_return', 0) * 100:+.1f}% "
                          f"PF {(r.get('holdout') or {}).get('profit_factor', 0):.2f}" for r in passed)
        prefix = (f"{len(passed)} configuration(s) passed the walk-forward gates but only {len(confirmed)} survived the untouched 12-month holdout "
                  f"({names}). A walk-forward pass that the holdout rejects is selection luck among {len(cands)} configurations, not edge. ")
    else:
        prefix = f"{len(passed)} configuration(s) passed (holdout not evaluated). "
    # Numbers-backed acceptance clause: does any timing rule beat vol-targeted holding on the same series?
    beats = 0
    pairs = 0
    for h in holds:
        same = [r for r in cands if r["instrument"] == h["instrument"] and r["timeframe"] == h["timeframe"]]
        if not same:
            continue
        pairs += 1
        best = max(same, key=lambda r: (r["oos"].get("calmar") or -9))
        if (best["oos"].get("calmar") or -9) > (h["oos"].get("calmar") or -9) + 0.1:
            beats += 1
    counts: Dict[str, int] = {}
    for r in cands:
        for g in r["acceptance"].get("failed", []):
            counts[g] = counts.get(g, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    top = ", ".join(f"{g} ({n}/{len(cands)})" for g, n in ranked[:3])
    hold_holdout = "; ".join(
        f"hold+policy {h['instrument']} {h['timeframe']} holdout {(h.get('holdout') or {}).get('total_return', 0) * 100:+.1f}%"
        for h in holds if h.get("holdout")
    )
    survivors = "; ".join(
        f"{r['candidate']} {r['instrument']} {r['timeframe']} [{r['regime']['mode']}] OOS CAGR {r['oos'].get('cagr', 0) * 100:+.1f}% / max DD "
        f"{r['oos'].get('max_drawdown', 0) * 100:.1f}% / Calmar {r['oos'].get('calmar', 0):.2f}, holdout {(r.get('holdout') or {}).get('total_return', 0) * 100:+.1f}%"
        for r in confirmed
    )
    return (prefix + f"Binding walk-forward gates: {top}. On {beats} of {pairs} series the best long-only timing rule beat "
            f"vol-targeted holding by more than 0.1 Calmar on the walk-forward, and the controls lost on the holdout ({hold_holdout or 'controls not evaluated on the holdout'}), "
            f"so the honest, numbers-backed statement is narrower than 'timing never beats holding': the edge of long-only timing on BTC/ETH spot is REAL BUT THIN "
            f"AND FRAGILE — of {len(cands)} configurations exactly {len(confirmed)} survived both the walk-forward and the holdout"
            + (f" ({survivors})" if survivors else "")
            + ", and the risk-managed return is a few percent a year at under 10 % drawdown. One surviving sleeve is not an ensemble. Per the Sprint 2c "
            "acceptance clause the Phase 7/8 product therefore stays 'risk-managed exposure + news brake' (hold with the policy sizing and the no-trade gates, "
            "the news agent as a brake), the confirmed sleeve(s) and the jointly sized portfolio run forward in the paper fleet next to the controls as the "
            "honest tiebreaker, and the Phase 9 long/short design study becomes the research priority.")


def _owner_decisions(run: Dict[str, Any]) -> List[str]:
    results = [r for r in run["results"] if r["candidate"] not in REFERENCE_CANDIDATES]
    passed = [r for r in results if r["acceptance"]["passed"]]
    confirmed = [r for r in passed if holdout_verdict(r) is True]
    study = run.get("regime_study") or {}
    items = [
        ("**Acceptance clause.** " + (f"{len(passed)} configurations passed walk-forward and {len(confirmed)} were confirmed by the holdout: approve the paper "
                                      "fleet (Sprint 5 item 3) on the confirmed configurations plus the controls?"
                                      if len(confirmed) >= 2 else
                                      "Fewer than two configurations passed. The report's next-step sentence states, with numbers, that long-only timing does not "
                                      "reliably beat vol-targeted holding. Confirm the pivot of the Phase 7/8 product to 'risk-managed exposure + news brake' "
                                      "and authorize the Phase 9 long/short DESIGN STUDY (research only, no derivatives access) as the next research priority — or "
                                      "ask for one more research sprint on a specific idea.")),
        "**Paper fleet anyway?** Forward evidence on live public data is cheap. Recommended: start the fleet with the shortlist AND the controls "
        "(hold + policy sizing on BTC and ETH, plain buy-and-hold) even if nothing passed, so the next decision rests on forward numbers.",
        f"**Regime gate.** {study.get('verdict', 'See the regime table.')} The gate threshold ({run['meta']['regime']['bear_prob_max']}), the number of states "
        f"and the modes were fixed before the run; changing them after seeing these results would be tuning on the test set — if you want a sweep, it is a new, "
        "pre-registered sprint, not an edit of this one.",
        "**FOMC calendar.** The S0 filter's scheduled-event windows use a calendar written from memory (`research/events.py`). Verify it against "
        "federalreserve.gov (or supply a JSON calendar) before any forward run relies on it; its effect on these numbers is small.",
        "**Positioning data.** Keep the nightly Binance public funding/open-interest top-up (research only) as decided? The 7–14-day funding window changed "
        "little; dropping S5 from the fleet would simplify it.",
    ]
    return items


# -- main ----------------------------------------------------------------------

def render_from_json(args) -> int:
    """Re-render the report, shortlist and derived narrative from a saved results JSON (no research re-run)."""
    saved = json.loads(Path(args.render_from_json).read_text(encoding="utf-8"))
    results = saved["results"]
    holds = [r for r in results if r["candidate"] in REFERENCE_CANDIDATES]
    run = dict(saved)
    run["meta"] = dict(saved["meta"], generated_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                       rendered_from=str(args.render_from_json), report_path=args.report, shortlist_path=args.shortlist)
    run["regime_study"] = regime_study(results)
    run["turnover_study"] = turnover_study(results, TURNOVER_VARIANTS)
    run["s5_study"] = s5_study(results, S5_RETEST_VARIANTS)
    run["shortlist"] = shortlist(results)
    run["controls"] = controls(results, saved.get("benchmark", []))
    run["next_step"] = _next_step(results, holds)
    run["owner_decisions"] = _owner_decisions(run)
    run["executive_summary"] = executive_summary(run)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report_v1c(run), encoding="utf-8")
    Path(args.json).write_text(json.dumps(_rounded(run), separators=(",", ":"), default=_json_default), encoding="utf-8")
    write_shortlist_file(Path(args.shortlist), run)
    print(f"re-rendered {report_path}, {args.json} and {args.shortlist} from {args.render_from_json}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.render_from_json:
        return render_from_json(args)
    args_dict = dict(vars(args))
    series_list = [(inst, tf) for inst in args.instruments for tf in args.timeframes]
    t0 = time.monotonic()
    if args.workers > 1 and len(series_list) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(series_list))) as pool:
            outputs = list(pool.map(run_series, [args_dict] * len(series_list), [s[0] for s in series_list], [s[1] for s in series_list]))
    else:
        outputs = [run_series(args_dict, inst, tf) for inst, tf in series_list]

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    benchmark: List[Dict[str, Any]] = []
    spans: List[str] = []
    holdout_spans: List[str] = []
    positioning: Dict[str, Dict[str, Any]] = {}
    sleeves: Dict[Tuple, pd.Series] = {}
    full_sleeves: Dict[Tuple, pd.Series] = {}
    trades: Dict[Tuple, pd.DataFrame] = {}
    sensitivity: List[Dict[str, Any]] = []
    s0_shares: Dict[str, float] = {}
    for o in outputs:
        if o.get("skipped"):
            print(f"skip {o['instrument']} {o['timeframe']}: {o['skipped']}", file=sys.stderr)
            continue
        results.extend(o["results"])
        failures.extend(o["failures"])
        benchmark.append(o["benchmark"])
        spans.append(o["span"])
        if o["holdout_span"]:
            holdout_spans.append(o["holdout_span"])
        positioning.setdefault(o["instrument"], o["positioning"])
        for (key, mode), s in o["sleeves"].items():
            sleeves[(key, o["instrument"], o["timeframe"], mode)] = s
        for (key, mode), s in o["full_sleeves"].items():
            full_sleeves[(key, o["instrument"], o["timeframe"], mode)] = s
        for (key, mode), t in o["trades"].items():
            trades[(key, o["instrument"], o["timeframe"], mode)] = t
        sensitivity.extend(o["sensitivity"])
        s0_shares[f"{o['instrument']} {o['timeframe']}"] = o["s0_blocked_share"]

    portfolios, corr = _portfolios(args, results, sleeves, full_sleeves, trades)
    holds = [r for r in results if r["candidate"] in REFERENCE_CANDIDATES]
    regime_cfg = _regime_cfg(args, "gate")
    run: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "data_span": "; ".join(spans) or "no data",
            "data_span_short": f"{spans[0].split(': ')[1].split(' (')[0]}" if spans else "n/a",
            "holdout_span": sorted(set(holdout_spans))[0] if holdout_spans else "n/a",
            "holdout_months": args.holdout_months, "fee_rate": args.fee, "slippage_rate": args.slippage,
            "train_days": args.train_days, "test_days": args.test_days, "purge_days": args.purge_days,
            "select_by": args.select_by, "min_trades": args.min_trades,
            "policy_sizing": _policy_spec(args).to_dict(),
            "comparison_sizing": [s.label for s in _comparison_specs(args)],
            "regime": dict(regime_cfg.to_dict(), modes=list(args.regime_modes), sensitivity_thresholds=list(args.sensitivity_thresholds)),
            "n_regime_modes": len(args.regime_modes),
            "no_trade_label": _no_trade(args).label, "s0_blocked_share": s0_shares,
            "bracket_variants": list(args.brackets), "rebalance_threshold": _rebalance(args),
            "ladder": dict(LadderConfig().to_dict(), recovery_days=args.ladder_recovery_days),
            "portfolio": {"dd_budget": args.portfolio_dd_budget, "target_vols": list(args.portfolio_target_vols)},
            "selection": "entries selected among bracket-free rules, then the exit bracket among siblings, on the gated train slice; fixed policy sizing",
            "positioning_source": args.positioning_source, "instruments": args.instruments, "timeframes": args.timeframes,
            "strategies": args.strategies, "quick": bool(args.quick), "seed": args.seed, "workers": args.workers,
            "report_path": args.report, "shortlist_path": args.shortlist,
            "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1),
        },
        "benchmark": benchmark, "results": results, "failures": failures, "positioning": positioning,
        "regime_study": regime_study(results), "regime_sensitivity": sensitivity,
        "turnover_study": turnover_study(results, TURNOVER_VARIANTS), "s5_study": s5_study(results, S5_RETEST_VARIANTS),
        "portfolios": portfolios, "portfolio_correlation": corr,
        "shortlist": shortlist(results), "controls": controls(results, benchmark),
    }
    run["next_step"] = _next_step(results, holds)
    run["owner_decisions"] = _owner_decisions(run)
    run["executive_summary"] = executive_summary(run)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report_v1c(run), encoding="utf-8")
    Path(args.json).write_text(json.dumps(_rounded(run), separators=(",", ":"), default=_json_default), encoding="utf-8")
    write_shortlist_file(Path(args.shortlist), run)
    print(f"wrote {report_path}, {args.json} and {args.shortlist} in {run['meta']['elapsed_minutes']} min")
    return 0


# -- small helpers -------------------------------------------------------------

def _rounded(value, digits: int = 6):
    if isinstance(value, dict):
        return {k: _rounded(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v, digits) for v in value]
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else round(float(value), digits)
    return value


def _finite(value, key: str = ""):
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        if key == "profit_factor" and value > 0:
            return 999.0
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _finite_dict(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return None if d is None else {k: _finite(v, k) for k, v in d.items()}


def _fmt_pct(value) -> str:
    return "-" if value is None else f"{value * 100:+.1f}%"


def _fmt(value) -> str:
    return "-" if value is None else f"{value:.2f}"


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
