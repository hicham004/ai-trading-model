"""Sprint 2b research runner: sizing, risk, timeframe and positioning (SIMULATION ONLY).

Two-stage walk-forward per candidate x instrument x timeframe: the trading
rule (entries x exit bracket) is selected on the train slice at full size,
then the sizing rule (vol target / fixed fraction x crash filter x drawdown
ladder) is selected on the same train slice under a drawdown cap; the test
slice is simulated once. Fixed replays measure robustness, the sizing sweep,
the ladder and bracket effects and slippage stress. Passing candidates are
evaluated once on the untouched 12-month holdout. Sleeves are combined into
portfolios. Writes ``docs/research/ENSEMBLE_V1B_REPORT.md`` plus JSON.

Example::

    python scripts/run_research_v1b.py --instruments BTC-USDT ETH-USDT --timeframes 4H 6H --evaluate-holdout
    python scripts/run_research_v1b.py --quick --strategies S2 --instruments BTC-USDT --timeframes 4H

Nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
from research.metrics import deflated_sharpe_ratio, equity_metrics, return_moments, sharpe, trade_metrics  # noqa: E402
from research.montecarlo import trade_order_bootstrap  # noqa: E402
from research.portfolio import align_sleeves, combine, equal_risk_weights, equal_weights  # noqa: E402
from research.regime import metrics_by_regime, regime_labels  # noqa: E402
from research.report_v1b import REFERENCE_CANDIDATES, acceptance_check_v1b, executive_summary, render_report_v1b, shortlist  # noqa: E402
from research.sized_walkforward import SizingSelection, replay_columns, replay_sizing_sweep, run_sized_walk_forward  # noqa: E402
from research.sizing import LadderConfig, SizingSpec, find_spec, fraction_matrix, sizing_grid  # noqa: E402
from research.strategies import ALL_KEYS, REFERENCES, get_candidate  # noqa: E402
from research.strategies.adapters import ResearchStrategyAdapter  # noqa: E402
from research.strategies.base import days_to_bars  # noqa: E402
from research.strategies.s5_positioning import positioning_coverage  # noqa: E402
from research.sweep import build_frames, param_grid, perturbed_params, simulate_sizing  # noqa: E402
from research.walkforward import WalkForwardConfig, make_windows  # noqa: E402

DEFAULT_STRATEGIES = ["hold", "baseline", "S1", "S2", "S3", "S4", "S1+S5", "S2+S5"]
PORTFOLIO_FAMILIES = ("S1", "S2", "S4")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprint 2b walk-forward research over the Parquet lake (simulation only).")
    p.add_argument("--instruments", nargs="+", default=["BTC-USDT", "ETH-USDT"])
    p.add_argument("--timeframes", nargs="+", default=["4H", "6H"])
    p.add_argument("--strategies", nargs="+", default=DEFAULT_STRATEGIES, choices=ALL_KEYS)
    p.add_argument("--holdout-months", type=int, default=12)
    p.add_argument("--train-days", type=float, default=540)
    p.add_argument("--test-days", type=float, default=180)
    p.add_argument("--purge-days", type=float, default=7)
    p.add_argument("--min-trades", type=int, default=20)
    p.add_argument("--select-by", default="sharpe", choices=["sharpe", "sortino", "profit_factor", "calmar", "total_return"])
    p.add_argument("--fee", type=float, default=0.0010, help="Fee per side (default 0.10%%).")
    p.add_argument("--slippage", type=float, default=0.0005, help="Slippage per side (default 0.05%%).")
    p.add_argument("--sizing-dd-cap", type=float, default=0.15, help="Train max drawdown a sizing variant may show to qualify.")
    p.add_argument("--sizing-select-by", default="calmar", choices=["calmar", "sharpe", "sortino", "total_return"])
    p.add_argument("--sizing-min-trades", type=int, default=10)
    p.add_argument("--rebalance-threshold", type=float, default=0.25, help="Reduce-only mid-trade threshold; negative = entry-sized only.")
    p.add_argument("--ladder-recovery-days", type=float, default=30.0)
    p.add_argument("--positioning-source", default="binance", choices=["none", "okx", "binance"])
    p.add_argument("--brackets", nargs="+", default=list(BRACKETS), choices=list(BRACKETS))
    p.add_argument("--mc-paths", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--evaluate-holdout", action="store_true", help="Evaluate the holdout for candidates that passed walk-forward.")
    p.add_argument("--quick", action="store_true", help="Small sizing/bracket grids for a smoke run.")
    p.add_argument("--lake-dir", default=None)
    p.add_argument("--report", default="docs/research/ENSEMBLE_V1B_REPORT.md")
    p.add_argument("--json", default="docs/research/ensemble_v1b_results.json")
    return p.parse_args(argv)


def _specs(args: argparse.Namespace) -> Tuple[List[SizingSpec], Dict[str, Any]]:
    if args.quick:
        grid = dict(targets=(0.15,), lookbacks=(30,), fixed=(0.5, 1.0), crash=((0.15, 90.0),), crash_modes=("half",), ladders=(False, True))
    else:
        grid = dict(targets=(0.10, 0.15, 0.20, 0.25), lookbacks=(20, 30, 60), fixed=(0.25, 0.50, 1.0),
                    crash=((0.10, 90.0), (0.10, 180.0), (0.15, 90.0), (0.15, 180.0), (0.20, 90.0), (0.20, 180.0)),
                    crash_modes=("half", "zero"), ladders=(False, True))
    specs = sizing_grid(**grid)
    meta = {k: list(v) if isinstance(v, tuple) else v for k, v in grid.items()}
    return specs, meta


def _wf_config(args: argparse.Namespace, timeframe: str) -> WalkForwardConfig:
    return WalkForwardConfig(
        train_bars=days_to_bars(args.train_days, timeframe),
        test_bars=days_to_bars(args.test_days, timeframe),
        purge_bars=days_to_bars(args.purge_days, timeframe),
        min_trades=args.min_trades,
        select_by=args.select_by,
    )


def _rebalance(args: argparse.Namespace) -> Optional[float]:
    return None if args.rebalance_threshold is None or args.rebalance_threshold < 0 else float(args.rebalance_threshold)


def _event_driven_check(candidate, params, context, df_holdout: pd.DataFrame, instrument: str, timeframe: str, costs: Costs) -> Dict[str, Any]:
    """Reviewed event-driven simulator on the holdout at full size (trade-sequence check; the contract carries a fixed stop only)."""
    candles = to_market_candles(df_holdout, instrument, timeframe)
    bar = parse_timeframe(timeframe)
    strategy = ResearchStrategyAdapter(candidate, {k: v for k, v in params.items() if k != "bracket"}, context, fallback_confidence=0.60)
    limits = RiskLimits(max_risk_per_trade=1.0, max_daily_loss=1.0, max_position_size=1.0, min_confidence=0.01,
                        max_data_staleness=bar * 2, require_stop_loss=True)
    config = SimulationConfig(starting_cash=10_000.0, costs=CostModel(fee_rate=costs.fee_rate, slippage_rate=costs.slippage_rate))
    result = run_signal_backtest(candles, strategy, config=config, risk_manager=RiskManager(limits), timeframe=timeframe)
    return {
        "total_return": result.ending_equity / result.starting_cash - 1.0,
        "n_trades": len(result.trades),
        "rejected_entries": result.rejected_entries,
        "max_drawdown": result.metrics.max_drawdown_pct / 100.0,
    }


def _sweep_row(sweep: pd.DataFrame, label: Optional[str]) -> Optional[Dict[str, Any]]:
    if label is None:
        return None
    rows = sweep[sweep["sizing"] == label]
    if rows.empty:
        return None
    row = rows.iloc[0].to_dict()
    return {k: _finite(v, k) for k, v in row.items() if k in ("sizing", "total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar",
                                                               "profit_factor", "n_trades", "avg_allocation", "exposure", "fees_pct_per_year",
                                                               "giveback_share_reached", "giveback_share_reached_closed_negative", "giveback_avg_giveback_pct",
                                                               "giveback_n_reached", "worst_window_drawdown")}


def _toggle_ladder_label(spec: SizingSpec) -> str:
    return SizingSpec(**{**{k: v for k, v in spec.to_dict().items() if k != "label"}, "ladder": not spec.ladder}).label


def run_candidate(args, layout: LakeLayout, df_all: pd.DataFrame, instrument: str, timeframe: str, key: str, costs: Costs,
                  specs: Sequence[SizingSpec]) -> Tuple[Dict[str, Any], pd.Series]:
    t0 = time.monotonic()
    candidate = get_candidate(key)
    context = positioning_context(layout, instrument, timeframe, source=args.positioning_source)
    ppy = context.periods_per_year
    df_in, df_hold = split_holdout(df_all, holdout_months=args.holdout_months)
    has_stop = key not in REFERENCES
    brackets = list(args.brackets) if has_stop else ["none"]
    if args.quick and has_stop:
        brackets = [b for b in ("none", "trail1") if b in brackets] or brackets[:1]
    grid = dict(candidate.grid)
    grid["bracket"] = brackets
    combos = param_grid(grid, base=candidate.default_params)
    frames = build_frames(candidate, df_in, combos, context)
    cfg = _wf_config(args, timeframe)
    ladder = LadderConfig(recovery_bars=days_to_bars(args.ladder_recovery_days, timeframe))
    fractions = fraction_matrix(df_in, specs, timeframe, ppy)
    rebalance = _rebalance(args)
    sizing_cfg = SizingSelection(dd_cap=args.sizing_dd_cap, select_by=args.sizing_select_by, min_trades=args.sizing_min_trades,
                                 rebalance_threshold=rebalance)
    if not has_stop:  # a passive always-long reference has one trade per window: no trade-count qualification
        cfg = WalkForwardConfig(train_bars=cfg.train_bars, test_bars=cfg.test_bars, purge_bars=cfg.purge_bars, min_trades=1, select_by=cfg.select_by)
        sizing_cfg = SizingSelection(dd_cap=sizing_cfg.dd_cap, select_by=sizing_cfg.select_by, min_trades=1, rebalance_threshold=rebalance)
    wf = run_sized_walk_forward(df_in, frames, combos, cfg, specs, fractions, ladder, costs=costs, periods_per_year=ppy, sizing_cfg=sizing_cfg)

    notes: List[str] = []
    selected = wf.rule_most_often
    if selected is None:
        last = wf.last_selected
        if last is not None:
            selected = dict(last.rule_params)
        else:
            notes.append("no rule qualified (min trades) in any training window")
            selected = dict(candidate.default_params, bracket="none")
    s_idx = wf.sizing_most_often
    if s_idx is None:
        s_idx = wf.last_selected.sizing_index if wf.last_selected is not None else (find_spec(specs, "fixed25") or 0)
    spec = specs[s_idx]
    frac_col = fractions[:, [s_idx]]
    windows = make_windows(len(df_in), cfg)
    rule_col = next((i for i, c in enumerate(combos) if c == selected), None)
    if rule_col is None:  # the selected rule is not in the grid (defaults fallback): add it
        combos = list(combos) + [selected]
        frames = build_frames(candidate, df_in, combos, context)
        rule_col = len(combos) - 1

    # Robustness: ±30 % perturbations of the numeric rule parameters, replayed with the chosen sizing.
    neighbours = perturbed_params(selected, list(candidate.grid), tolerance=0.30)
    sets = [selected] + neighbours
    pert_frames = build_frames(candidate, df_in, sets, context)
    replays = replay_columns(df_in, pert_frames, range(len(sets)), windows, costs=costs, periods_per_year=ppy, size_fraction=frac_col,
                             ladder=ladder, ladder_on=spec.ladder, rebalance_threshold=rebalance)
    neighbour_returns = np.array([r["total_return"] for r in replays[1:]], dtype=float)
    robust = {
        "n_neighbours": int(len(neighbours)),
        "best": float(replays[0]["total_return"]),
        "median": float(np.median(neighbour_returns)) if neighbour_returns.size else float("nan"),
        "min": float(neighbour_returns.min()) if neighbour_returns.size else float("nan"),
        "share_above_threshold": float((neighbour_returns > 0).mean()) if neighbour_returns.size else float("nan"),
        "neighbours": [dict(params=sets[j + 1], total_return=replays[j + 1]["total_return"], max_drawdown=replays[j + 1]["max_drawdown"]) for j in range(len(neighbours))],
    }

    # Sizing sweep: the selected rule under every sizing spec (informational, fixed replay).
    sweep = replay_sizing_sweep(df_in, frames, rule_col, windows, specs, fractions, ladder, costs=costs, periods_per_year=ppy,
                                rebalance_threshold=rebalance)
    sweep_rows = [{k: _finite(v, k) for k, v in row.items() if k in ("sizing", "total_return", "cagr", "sharpe", "max_drawdown", "calmar",
                                                                       "profit_factor", "n_trades", "avg_allocation")} for row in sweep.to_dict(orient="records")]
    qualified = sweep[(sweep["n_trades"] >= 30)].replace([np.inf, -np.inf], np.nan).dropna(subset=["calmar"])
    sweep_best = qualified.sort_values(["calmar", "sharpe"], ascending=[False, False]).iloc[0]["sizing"] if len(qualified) else None
    full_label = find_spec(specs, "fixed100")
    full_row = _sweep_row(sweep, "fixed100") if full_label is not None else None
    chosen_row = _sweep_row(sweep, spec.label)
    ladder_effect = {"with": _sweep_row(sweep, spec.label if spec.ladder else _toggle_ladder_label(spec)),
                     "without": _sweep_row(sweep, _toggle_ladder_label(spec) if spec.ladder else spec.label)}

    # Exit bracket effect: the selected rule with vs without its bracket (give-back before/after).
    bracket_effect: Dict[str, Any] = {}
    if has_stop:
        sel_bracket = selected.get("bracket", "none")
        other = dict(selected, bracket="none" if sel_bracket != "none" else "trail1")
        be_frames = build_frames(candidate, df_in, [selected, other], context)
        be = replay_columns(df_in, be_frames, [0, 1], windows, costs=costs, periods_per_year=ppy, size_fraction=frac_col, ladder=ladder,
                            ladder_on=spec.ladder, rebalance_threshold=rebalance)
        if sel_bracket != "none":
            bracket_effect = {"bracket": sel_bracket, "selected": _finite_dict(be[0]), "none": _finite_dict(be[1])}
        else:
            bracket_effect = {"bracket": "none (selected); comparison shows trail1", "selected": _finite_dict(be[1]), "none": _finite_dict(be[0])}

    # Entry-sized only (no mid-trade reductions) for comparison.
    eso = replay_columns(df_in, frames, [rule_col], windows, costs=costs, periods_per_year=ppy, size_fraction=frac_col, ladder=ladder,
                         ladder_on=spec.ladder, rebalance_threshold=None)[0] if rebalance is not None else None

    stitched = pd.concat([w.test_returns for w in wf.windows]).sort_index()
    moments = return_moments(stitched.to_numpy())
    observed_sr = sharpe(stitched.to_numpy(), 1.0)
    last = wf.last_selected or wf.windows[-1]
    trials = list(last.train_sharpes_rules) + list(last.train_sharpes_sizing)
    dsr = deflated_sharpe_ratio(observed_sr, trials, len(stitched), moments["skew"], moments["kurt"])
    dsr["observed_sr"] = observed_sr

    regimes = regime_labels(df_in, timeframe, ppy)
    by_regime = metrics_by_regime(stitched, regimes, ppy).to_dict(orient="records")
    yearly = {int(k): float(v) for k, v in wf.yearly.items()}
    trades = wf.oos_trades
    equity_level = (trades["return_pct"] * trades["size_fraction"]).to_numpy() if len(trades) else []
    mc = trade_order_bootstrap(equity_level, n_paths=args.mc_paths, seed=args.seed)

    stress: Dict[str, float] = {}
    for mult in (1.0, 2.0, 3.0):
        sc = Costs(fee_rate=costs.fee_rate, slippage_rate=min(0.0999, costs.slippage_rate * mult))
        growth = 1.0
        for w in wf.windows:
            if w.rule_combo is None:
                continue
            res = simulate_sizing(df_in, frames, rule_col, windows[w.idx].test, frac_col, costs=sc, ladder=ladder,
                                  ladder_mask=np.array([spec.ladder]), rebalance_threshold=rebalance)
            growth *= res.equity[-1, 0] / res.init_cash
        stress[f"x{mult:g}"] = growth - 1.0

    acceptance = acceptance_check_v1b(wf.oos_metrics, yearly, robust)
    if "S5" in key:
        cov = positioning_coverage(df_in, context)
        notes.append(f"positioning data ({args.positioning_source}) cover {cov * 100:.1f}% of in-sample bars (filter passes elsewhere)")
    if not has_stop:
        notes.append("passive reference: always long, no stop, sizing overlays only; excluded from the shortlist")

    out: Dict[str, Any] = {
        "candidate": key,
        "label": candidate.label,
        "instrument": instrument,
        "timeframe": timeframe,
        "grid_size": len(combos),
        "selected_params": selected,
        "selected_sizing": spec.to_dict(),
        "rule_frequency": wf.rule_frequency,
        "sizing_frequency": wf.sizing_frequency,
        "oos": {k: _finite(v, k) for k, v in wf.oos_metrics.items()},
        "yearly": yearly,
        "by_regime": by_regime,
        "robustness": robust,
        "dsr": dsr,
        "montecarlo": mc,
        "slippage_stress": stress,
        "sizing_sweep": {"rows": sweep_rows, "best_by_calmar": sweep_best, "all_in": full_row, "chosen": chosen_row},
        "ladder_effect": ladder_effect,
        "bracket_effect": bracket_effect,
        "entry_sized_only": _finite_dict(eso) if eso else None,
        "acceptance": acceptance,
        "windows": [
            {"idx": w.idx, "train": f"{w.train_start:%Y-%m-%d}->{w.train_end:%Y-%m-%d}", "test": f"{w.test_start:%Y-%m-%d}->{w.test_end:%Y-%m-%d}",
             "rule": w.rule_params, "sizing": w.sizing_label, "rule_train_metric": None if not np.isfinite(w.rule_train_metric) else w.rule_train_metric,
             "sizing_train": w.sizing_train, "qualified": w.n_qualified, "test_return": w.test_metrics.get("total_return"),
             "test_max_dd": w.test_metrics.get("max_drawdown"), "test_trades": w.test_metrics.get("n_trades")}
            for w in wf.windows
        ],
        "notes": notes,
    }

    if acceptance["passed"] and args.evaluate_holdout and len(df_hold):
        full_frames = build_frames(candidate, df_all, [selected], context)
        full_fracs = fraction_matrix(df_all, [spec], timeframe, ppy)
        hold_slice = slice(len(df_in), len(df_all))
        res = simulate_sizing(df_all, full_frames, 0, hold_slice, full_fracs, costs=costs, ladder=ladder, ladder_mask=np.array([spec.ladder]),
                              rebalance_threshold=rebalance)
        hm = equity_metrics(res.equity[:, 0], ppy)
        hm.update(trade_metrics(res.trades, init_cash=res.init_cash, n_bars=res.n_bars, periods_per_year=ppy))
        hm["avg_allocation"] = float(res.avg_allocation[0])
        out["holdout"] = {k: _finite(v, k) for k, v in hm.items()}
        if has_stop and selected.get("bracket", "none") == "none":
            try:
                hold_frames = build_frames(candidate, df_hold, [selected], context)
                vec = simulate_sizing(df_hold, hold_frames, 0, slice(0, len(df_hold)), np.ones((len(df_hold), 1)), costs=costs)
                ev = _event_driven_check(candidate, selected, context, df_hold, instrument, timeframe, costs)
                ev["vectorized_total_return"] = vec.equity[-1, 0] / vec.init_cash - 1.0
                ev["n_trades_vectorized"] = int(len(vec.trades))
                ev["difference"] = ev["total_return"] - ev["vectorized_total_return"]
                out["holdout_event_driven"] = ev
            except Exception as exc:  # report, never hide
                out["notes"].append(f"event-driven cross-check failed: {type(exc).__name__}: {exc}")
        elif has_stop:
            out["notes"].append("event-driven cross-check skipped: the reviewed contract carries a fixed stop only (brackets are Sprint 3 scope)")
    out["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    return out, stitched


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


def _sizing_study(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for r in results:
        if r["candidate"] in REFERENCE_CANDIDATES:
            continue
        sw = r.get("sizing_sweep") or {}
        full, chosen = sw.get("all_in"), sw.get("chosen")
        if not full or not chosen:
            continue
        rows.append({
            "candidate": r["candidate"], "instrument": r["instrument"], "timeframe": r["timeframe"],
            "bracket": (r.get("selected_params") or {}).get("bracket", "-"), "sizing": chosen.get("sizing"),
            "full_cagr": full.get("cagr"), "full_dd": full.get("max_drawdown"), "full_calmar": full.get("calmar"),
            "sized_cagr": chosen.get("cagr"), "sized_dd": chosen.get("max_drawdown"), "sized_calmar": chosen.get("calmar"),
            "sweep_best": sw.get("best_by_calmar"),
        })
    if not rows:
        return {"n": 0, "rows": []}

    def med(key: str) -> Optional[float]:
        vals = [row[key] for row in rows if row.get(key) is not None]
        return float(np.median(vals)) if vals else None

    return {
        "n": len(rows), "rows": rows,
        "full_dd_median": med("full_dd"), "sized_dd_median": med("sized_dd"),
        "full_cagr_median": med("full_cagr"), "sized_cagr_median": med("sized_cagr"),
        "full_calmar_median": med("full_calmar"), "sized_calmar_median": med("sized_calmar"),
        "note": "Both columns replay the most-selected rule with FIXED parameters over every test window (no re-selection), so they differ "
                "from the walk-forward numbers in the summary table, which re-select the rule and sizing every window. All-in = 100% of equity, "
                "no crash filter, no ladder (the Sprint 2 convention); chosen = the most-selected sizing of the walk-forward.",
    }


def _portfolios(results: Sequence[Dict[str, Any]], sleeves: Dict[Tuple[str, str, str], pd.Series], ladder_days: int) -> Tuple[List[Dict], Dict, str]:
    """Combine the best timeframe per (family, instrument) sleeve; equal capital / equal risk; with and without a ladder."""
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in results:
        if r["candidate"] not in PORTFOLIO_FAMILIES:
            continue
        k = (r["candidate"], r["instrument"])
        calmar = r["oos"].get("calmar") or -1e9
        if (r["oos"].get("n_trades") or 0) >= 10 and (k not in best or calmar > (best[k]["oos"].get("calmar") or -1e9)):
            best[k] = r
    note = ("Sleeves use, for every (strategy family, instrument), the timeframe with the higher out-of-sample Calmar — a mild selection on "
            "out-of-sample data, so treat portfolio numbers as slightly optimistic. Each sleeve compounds its own capital bucket.")
    if not best:
        return [], {}, note + " No sleeve qualified (fewer than 10 OOS trades everywhere)."
    ladder = LadderConfig(recovery_bars=max(1, int(ladder_days)))
    out: List[Dict] = []
    corr: Dict = {}

    def build(name: str, keys: Sequence[Tuple[str, str]], *, risk: bool, with_ladder: bool) -> Optional[Dict]:
        chosen = {f"{c}/{i.split('-')[0]}/{best[(c, i)]['timeframe']}": sleeves[(c, i, best[(c, i)]["timeframe"])] for c, i in keys if (c, i) in best}
        if len(chosen) < 2:
            return None
        daily = align_sleeves(chosen)
        w = equal_risk_weights(daily) if risk else equal_weights(daily.columns)
        res = combine(daily, w, name=name, ladder=ladder if with_ladder else None)
        d = res.to_dict()
        return d

    families = {
        "S2+S4 x BTC+ETH": [(c, i) for c in ("S2", "S4") for i in ("BTC-USDT", "ETH-USDT")],
        "S1+S2+S4 x BTC+ETH": [(c, i) for c in ("S1", "S2", "S4") for i in ("BTC-USDT", "ETH-USDT")],
    }
    for fname, keys in families.items():
        for risk in (False, True):
            for with_ladder in (False, True):
                label = f"{fname}, {'equal risk' if risk else 'equal capital'}{', ladder' if with_ladder else ''}"
                d = build(label, keys, risk=risk, with_ladder=with_ladder)
                if d:
                    out.append(d)
                    if fname.startswith("S1+S2+S4") and not risk and not with_ladder:
                        corr = d["correlation"]
    return out, corr, note


def _next_step(results: Sequence[Dict[str, Any]], sl: List[Dict[str, Any]]) -> str:
    cands = [r for r in results if r["candidate"] not in REFERENCE_CANDIDATES]
    passed = [r for r in cands if r["acceptance"]["passed"]]
    if len(passed) >= 2:
        return (f"Sprint 5's paper fleet should run the {len(passed)} passing configurations (and the rest of the shortlist as controls) forward "
                "on live public data; demo exposure stays unchanged until the forward evidence matches the walk-forward expectations.")
    counts: Dict[str, int] = {}
    for r in cands:
        for g in r["acceptance"].get("failed", []):
            counts[g] = counts.get(g, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    top = ", ".join(f"{g} ({n}/{len(cands)})" for g, n in ranked[:3])
    return (f"Proposed Sprint 2c (research only): {len(passed)} configuration(s) passed, so the ensemble is not ready for the paper fleet. "
            f"Binding gates: {top}. Proposed work: (1) regime v2 (HMM on returns+vol) and the S0 filter as entry gates so the trend rules stand aside "
            "in 2022-style bear markets, which drive the failed yearly-consistency and Calmar gates; (2) portfolio-level sizing — size the "
            "BTC+ETH, S1/S2/S4 sleeves jointly against one drawdown budget instead of per sleeve; (3) lower-turnover variants (weekly rebalanced "
            "TSMOM, 1D entries with 4H exits) to cut fee drag; (4) keep collecting Binance/OKX positioning for an S5 re-test with a shorter funding "
            "z-window; (5) no entry-rule retuning beyond that — the evidence says the edge is small and the risk side is where the gates are won.")


def main(argv=None) -> int:
    args = parse_args(argv)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    costs = Costs(fee_rate=args.fee, slippage_rate=args.slippage)
    specs, sizing_meta = _specs(args)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    benchmark: List[Dict[str, Any]] = []
    spans: List[str] = []
    holdout_spans: List[str] = []
    positioning: Dict[str, Dict[str, Any]] = {}
    sleeves: Dict[Tuple[str, str, str], pd.Series] = {}
    for instrument in args.instruments:
        for timeframe in args.timeframes:
            df_all = load_or_resample_candles(layout, instrument, timeframe)
            if len(df_all) < 1000:
                print(f"skip {instrument} {timeframe}: only {len(df_all)} bars available", file=sys.stderr)
                continue
            df_in, df_hold = split_holdout(df_all, holdout_months=args.holdout_months)
            spans.append(f"{instrument} {timeframe}: {df_all.index[0]:%Y-%m-%d}->{df_all.index[-1]:%Y-%m-%d} ({len(df_all)} bars)")
            if len(df_hold):
                holdout_spans.append(f"{df_hold.index[0]:%Y-%m-%d}->{df_hold.index[-1]:%Y-%m-%d}")
            cfg = _wf_config(args, timeframe)
            wins = make_windows(len(df_in), cfg)
            first_test = wins[0].test.start if wins else 0
            ppy = bars_per_year(timeframe)
            bh = buy_and_hold(df_in["open"].to_numpy()[first_test:], df_in["close"].to_numpy()[first_test:], costs=costs)
            bm = equity_metrics(bh, ppy)
            benchmark.append({"instrument": instrument, "timeframe": timeframe, "total_return": float(bh[-1] / 10_000.0 - 1.0),
                              "cagr": bm["cagr"], "sharpe": bm["sharpe"], "max_drawdown": bm["max_drawdown"], "calmar": bm["calmar"]})
            if instrument not in positioning:
                positioning[instrument] = _positioning_info(layout, instrument, timeframe, args.positioning_source, df_in)
            for key in args.strategies:
                print(f"running {key} on {instrument} {timeframe} ...", flush=True)
                try:
                    res, stitched = run_candidate(args, layout, df_all, instrument, timeframe, key, costs, specs)
                except Exception as exc:  # one failing candidate must not lose the whole run
                    print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                    failures.append({"candidate": key, "instrument": instrument, "timeframe": timeframe, "error": f"{type(exc).__name__}: {exc}"})
                    continue
                results.append(res)
                sleeves[(key, instrument, timeframe)] = stitched
                o = res["oos"]
                print(f"  OOS CAGR {_fmt_pct(o.get('cagr'))} Sharpe {_fmt(o.get('sharpe'))} maxDD {_fmt_pct(o.get('max_drawdown'))} "
                      f"Calmar {_fmt(o.get('calmar'))} PF {_fmt(o.get('profit_factor'))} trades {o.get('n_trades')} sizing "
                      f"{res['selected_sizing']['label']} bracket {res['selected_params'].get('bracket')} pass={res['acceptance']['passed']} "
                      f"({res['elapsed_seconds']}s)", flush=True)

    portfolios, corr, portfolio_note = _portfolios(results, sleeves, int(args.ladder_recovery_days))
    sl = shortlist(results)
    run = {
        "meta": {
            "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "data_span": "; ".join(spans) or "no data",
            "data_span_short": f"{spans[0].split(': ')[1].split(' (')[0]}" if spans else "n/a",
            "holdout_span": sorted(set(holdout_spans))[0] if holdout_spans else "n/a",
            "holdout_months": args.holdout_months,
            "fee_rate": args.fee,
            "slippage_rate": args.slippage,
            "train_days": args.train_days,
            "test_days": args.test_days,
            "purge_days": args.purge_days,
            "select_by": args.select_by,
            "min_trades": args.min_trades,
            "sizing": {
                "grid_size": len(specs), "dd_cap": args.sizing_dd_cap, "select_by": args.sizing_select_by, "min_trades": args.sizing_min_trades,
                "rebalance_threshold": _rebalance(args), "ladder": dict(LadderConfig().to_dict(), recovery_days=args.ladder_recovery_days),
                **sizing_meta,
            },
            "bracket_variants": list(args.brackets),
            "positioning_source": args.positioning_source,
            "instruments": args.instruments,
            "timeframes": args.timeframes,
            "strategies": args.strategies,
            "quick": bool(args.quick),
            "seed": args.seed,
        },
        "benchmark": benchmark,
        "results": results,
        "failures": failures,
        "positioning": positioning,
        "positioning_note": ("Binance public history is the long-history source (funding since 2019-09/2019-11, 5-minute open interest reduced to "
                             "hourly since 2020-09 for BTC and 2021-12 for ETH); OKX's own series (months of history) keep being collected for the "
                             "forward period. Features only — this project never trades on Binance."),
        "sizing_study": _sizing_study(results),
        "portfolios": portfolios,
        "portfolio_correlation": corr,
        "portfolio_note": portfolio_note,
        "shortlist": sl,
    }
    run["next_step"] = _next_step(results, sl)
    run["executive_summary"] = executive_summary(run)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report_v1b(run), encoding="utf-8")
    Path(args.json).write_text(json.dumps(run, indent=1, default=_json_default), encoding="utf-8")
    print(f"wrote {report_path} and {args.json}")
    return 0


def _finite(value, key: str = ""):
    """JSON-safe metric: NaN -> None; an infinite profit factor (no losing trade) -> 999.0."""
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
