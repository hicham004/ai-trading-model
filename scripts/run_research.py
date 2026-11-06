"""Sprint 2 research runner: sweeps + walk-forward + robustness + report (SIMULATION ONLY).

Reads PUBLIC candles from the Parquet lake, runs every candidate strategy
through the walk-forward harness with an untouched 12-month holdout, and
writes ``docs/research/ENSEMBLE_V1_REPORT.md`` plus a JSON results file.

Example::

    python scripts/run_research.py --instruments BTC-USDT ETH-USDT --timeframes 1H 4H \\
        --strategies baseline S1 S2 S3 S4 S1+S5 --evaluate-holdout

Nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.models import SimulationConfig  # noqa: E402
from app.backtest.simulator import run_signal_backtest  # noqa: E402
from app.broker.base import CostModel  # noqa: E402
from app.datalake.layout import LakeLayout  # noqa: E402
from app.datalake.parquet_store import coverage  # noqa: E402
from app.risk.manager import RiskLimits, RiskManager  # noqa: E402
from app.strategy.timeframes import parse_timeframe  # noqa: E402
from research.calibration import StrengthCalibrator, entry_outcomes  # noqa: E402
from research.data import bars_per_year, load_candles, split_holdout, to_market_candles  # noqa: E402
from research.engine import Costs, buy_and_hold  # noqa: E402
from research.metrics import deflated_sharpe_ratio, equity_metrics, max_drawdown, return_moments, sharpe, trade_metrics  # noqa: E402
from research.montecarlo import trade_order_bootstrap  # noqa: E402
from research.regime import metrics_by_regime, regime_labels  # noqa: E402
from research.report import acceptance_check, render_report  # noqa: E402
from research.strategies import CANDIDATES, get_candidate  # noqa: E402
from research.strategies.adapters import ResearchStrategyAdapter  # noqa: E402
from research.strategies.base import FeatureContext, days_to_bars  # noqa: E402
from research.strategies.s5_positioning import positioning_coverage  # noqa: E402
from research.sweep import build_frames, metrics_table, param_grid, perturbed_params, simulate_slice  # noqa: E402
from research.walkforward import WalkForwardConfig, make_windows, replay_fixed_params, run_walk_forward  # noqa: E402

import pyarrow.parquet as pq  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Walk-forward research over the Parquet lake (simulation only).")
    p.add_argument("--instruments", nargs="+", default=["BTC-USDT", "ETH-USDT"])
    p.add_argument("--timeframes", nargs="+", default=["1H", "4H"])
    p.add_argument("--strategies", nargs="+", default=list(CANDIDATES), choices=list(CANDIDATES))
    p.add_argument("--holdout-months", type=int, default=12)
    p.add_argument("--train-days", type=float, default=540)
    p.add_argument("--test-days", type=float, default=180)
    p.add_argument("--purge-days", type=float, default=7)
    p.add_argument("--min-trades", type=int, default=20)
    p.add_argument("--select-by", default="sharpe", choices=["sharpe", "sortino", "profit_factor", "calmar", "total_return"])
    p.add_argument("--fee", type=float, default=0.0010, help="Fee per side (default 0.10%%).")
    p.add_argument("--slippage", type=float, default=0.0005, help="Slippage per side (default 0.05%%).")
    p.add_argument("--size-fraction", type=float, default=1.0)
    p.add_argument("--mc-paths", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--evaluate-holdout", action="store_true", help="Evaluate the holdout for candidates that passed walk-forward.")
    p.add_argument("--lake-dir", default=None)
    p.add_argument("--report", default="docs/research/ENSEMBLE_V1_REPORT.md")
    p.add_argument("--json", default="docs/research/ensemble_v1_results.json")
    return p.parse_args(argv)


def _load_series(layout: LakeLayout, kind: str, instrument: str, period: str, column: str) -> Optional[pd.DataFrame]:
    directory = layout.series_dir(kind, instrument, period)
    files = sorted(directory.glob("*.parquet")) if directory.exists() else []
    if not files:
        return None
    frames = [pq.read_table(f, columns=["ts", column]).to_pandas() for f in files]
    df = pd.concat(frames).set_index("ts").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC") if df.index.tz is not None else pd.DatetimeIndex(df.index, tz="UTC")
    return df


def _context(layout: LakeLayout, instrument: str, timeframe: str) -> FeatureContext:
    swap = f"{instrument}-SWAP"
    return FeatureContext(
        timeframe=timeframe,
        periods_per_year=bars_per_year(timeframe),
        funding=_load_series(layout, "funding_rate", swap, "8H", "funding_rate"),
        open_interest=_load_series(layout, "open_interest", swap, "1H", "oi_usd"),
    )


def _wf_config(args: argparse.Namespace, timeframe: str) -> WalkForwardConfig:
    return WalkForwardConfig(
        train_bars=days_to_bars(args.train_days, timeframe),
        test_bars=days_to_bars(args.test_days, timeframe),
        purge_bars=days_to_bars(args.purge_days, timeframe),
        min_trades=args.min_trades,
        select_by=args.select_by,
    )


def _event_driven_check(candidate, params, context, df_holdout: pd.DataFrame, instrument: str, timeframe: str, costs: Costs, calibrator) -> Dict[str, Any]:
    """Run the reviewed event-driven simulator on the holdout with the same conventions."""
    candles = to_market_candles(df_holdout, instrument, timeframe)
    bar = parse_timeframe(timeframe)
    strategy = ResearchStrategyAdapter(candidate, params, context, calibrator=calibrator, fallback_confidence=0.60)
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


def run_candidate(args, layout: LakeLayout, df_all: pd.DataFrame, instrument: str, timeframe: str, key: str, costs: Costs) -> Dict[str, Any]:
    t0 = time.monotonic()
    candidate = get_candidate(key)
    context = _context(layout, instrument, timeframe)
    ppy = context.periods_per_year
    df_in, df_hold = split_holdout(df_all, holdout_months=args.holdout_months)
    combos = param_grid(candidate.grid, base=candidate.default_params)
    frames = build_frames(candidate, df_in, combos, context)
    cfg = _wf_config(args, timeframe)
    wf = run_walk_forward(df_in, frames, combos, cfg, costs=costs, periods_per_year=ppy, size_fraction=args.size_fraction)

    selected = wf.selected_most_often or next((w.selected_params for w in reversed(wf.windows) if w.selected_combo is not None), None)
    notes: List[str] = []
    if selected is None:
        notes.append("no parameter set qualified (min trades) in any training window")
        selected = dict(candidate.default_params)

    # Robustness: ±30% perturbations of the selected set, each replayed with fixed
    # parameters over every OOS test window (no re-selection).
    windows = make_windows(len(df_in), cfg)
    neighbours = perturbed_params(selected, list(candidate.grid), tolerance=0.30)
    sets = [selected] + neighbours
    pert_frames = build_frames(candidate, df_in, sets, context)
    replays = [replay_fixed_params(df_in, pert_frames, j, windows, costs=costs, size_fraction=args.size_fraction) for j in range(len(sets))]
    neighbour_returns = np.array([r["total_return"] for r in replays[1:]], dtype=float)
    robust = {
        "n_neighbours": int(len(neighbours)),
        "best": float(replays[0]["total_return"]),
        "median": float(np.median(neighbour_returns)) if neighbour_returns.size else float("nan"),
        "min": float(neighbour_returns.min()) if neighbour_returns.size else float("nan"),
        "share_above_threshold": float((neighbour_returns > 0).mean()) if neighbour_returns.size else float("nan"),
        "neighbours": [dict(params=sets[j + 1], **replays[j + 1]) for j in range(len(neighbours))],
    }
    stitched = pd.concat([w.test_returns for w in wf.windows]).sort_index()
    moments = return_moments(stitched.to_numpy())
    observed_sr = sharpe(stitched.to_numpy(), 1.0)
    dsr = deflated_sharpe_ratio(observed_sr, wf.windows[-1].train_sharpes, len(stitched), moments["skew"], moments["kurt"])
    dsr["observed_sr"] = observed_sr

    regimes = regime_labels(df_in, timeframe, ppy)
    by_regime = metrics_by_regime(stitched, regimes, ppy).to_dict(orient="records")
    yearly = {int(k): float(v) for k, v in wf.yearly.items()}
    mc = trade_order_bootstrap(wf.oos_trades["return_pct"].to_numpy() if len(wf.oos_trades) else [], n_paths=args.mc_paths, seed=args.seed)

    # Slippage stress: replay the selected combo per window under heavier slippage.
    stress: Dict[str, float] = {}
    for mult in (1.0, 2.0, 3.0):
        sc = Costs(fee_rate=costs.fee_rate, slippage_rate=min(0.0999, costs.slippage_rate * mult))
        growth = 1.0
        for w in wf.windows:
            if w.selected_combo is None:
                continue
            res = simulate_slice(df_in, frames, windows[w.idx].test, costs=sc, size_fraction=args.size_fraction, columns=[w.selected_combo])
            growth *= res.equity[-1, 0] / res.init_cash
        stress[f"x{mult:g}"] = growth - 1.0

    acceptance = acceptance_check(wf.oos_metrics, yearly, robust)
    if "S5" in key:
        notes.append(f"positioning data cover {positioning_coverage(df_in, context) * 100:.1f}% of in-sample bars (filter passes elsewhere)")

    out: Dict[str, Any] = {
        "candidate": key,
        "label": candidate.label,
        "instrument": instrument,
        "timeframe": timeframe,
        "grid_size": len(combos),
        "selected_params": selected,
        "params_frequency": wf.params_frequency,
        "oos": {k: _finite(v, k) for k, v in wf.oos_metrics.items()},
        "yearly": yearly,
        "by_regime": by_regime,
        "robustness": robust,
        "dsr": dsr,
        "montecarlo": mc,
        "slippage_stress": stress,
        "acceptance": acceptance,
        "windows": [
            {"idx": w.idx, "train": f"{w.train_start:%Y-%m-%d}→{w.train_end:%Y-%m-%d}", "test": f"{w.test_start:%Y-%m-%d}→{w.test_end:%Y-%m-%d}",
             "params": w.selected_params, "train_metric": None if not np.isfinite(w.train_metric) else w.train_metric,
             "qualified": w.n_qualified, "test_return": w.test_metrics.get("total_return"), "test_trades": w.test_metrics.get("n_trades")}
            for w in wf.windows
        ],
        "notes": notes,
    }

    if acceptance["passed"] and args.evaluate_holdout and len(df_hold):
        full_frames = build_frames(candidate, df_all, [selected], context)
        hold_slice = slice(len(df_in), len(df_all))
        res = simulate_slice(df_all, full_frames, hold_slice, costs=costs, size_fraction=args.size_fraction)
        hm = equity_metrics(res.equity[:, 0], ppy)
        hm.update(trade_metrics(res.trades, init_cash=res.init_cash, n_bars=res.n_bars, periods_per_year=ppy))
        out["holdout"] = hm
        # Calibrate confidence on in-sample entries of the selected combo, then cross-check engines on the holdout alone.
        sel_idx = next((i for i, c in enumerate(combos) if c == selected), None)
        calibrator = None
        if sel_idx is not None:
            in_res = simulate_slice(df_in, frames, slice(0, len(df_in)), costs=costs, size_fraction=args.size_fraction, columns=[sel_idx])
            strengths, wins = entry_outcomes(in_res.trades.assign(combo=sel_idx), frames.strength, sel_idx)
            calibrator = StrengthCalibrator().fit(strengths, wins)
            out["calibration"] = calibrator.table().to_dict(orient="records")
        try:
            hold_only_frames = build_frames(candidate, df_hold, [selected], context)
            hold_only = simulate_slice(df_hold, hold_only_frames, slice(0, len(df_hold)), costs=costs, size_fraction=args.size_fraction)
            vec_return = hold_only.equity[-1, 0] / hold_only.init_cash - 1.0
            ev = _event_driven_check(candidate, selected, context, df_hold, instrument, timeframe, costs, calibrator)
            ev["vectorized_total_return"] = vec_return
            ev["difference"] = ev["total_return"] - vec_return
            out["holdout_event_driven"] = ev
        except Exception as exc:  # report, never hide
            out["notes"].append(f"event-driven cross-check failed: {type(exc).__name__}: {exc}")
    out["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    return out


def main(argv=None) -> int:
    args = parse_args(argv)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    costs = Costs(fee_rate=args.fee, slippage_rate=args.slippage)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    benchmark: List[Dict[str, Any]] = []
    spans: List[str] = []
    holdout_spans: List[str] = []
    for instrument in args.instruments:
        for timeframe in args.timeframes:
            df_all = load_candles(layout, instrument, timeframe)
            if len(df_all) < 1000:
                print(f"skip {instrument} {timeframe}: only {len(df_all)} bars stored", file=sys.stderr)
                continue
            df_in, df_hold = split_holdout(df_all, holdout_months=args.holdout_months)
            spans.append(f"{instrument} {timeframe}: {df_all.index[0]:%Y-%m-%d}→{df_all.index[-1]:%Y-%m-%d} ({len(df_all)} bars)")
            if len(df_hold):
                holdout_spans.append(f"{df_hold.index[0]:%Y-%m-%d}→{df_hold.index[-1]:%Y-%m-%d}")
            cfg = _wf_config(args, timeframe)
            first_test = make_windows(len(df_in), cfg)[0].test.start if make_windows(len(df_in), cfg) else 0
            bh = buy_and_hold(df_in["open"].to_numpy()[first_test:], df_in["close"].to_numpy()[first_test:], costs=costs)
            benchmark.append({"instrument": instrument, "timeframe": timeframe, "total_return": float(bh[-1] / 10_000.0 - 1.0),
                              "max_drawdown": max_drawdown(bh)})
            for key in args.strategies:
                print(f"running {key} on {instrument} {timeframe} ...", flush=True)
                try:
                    res = run_candidate(args, layout, df_all, instrument, timeframe, key, costs)
                except Exception as exc:  # one failing candidate must not lose the whole run
                    print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                    failures.append({"candidate": key, "instrument": instrument, "timeframe": timeframe,
                                     "error": f"{type(exc).__name__}: {exc}"})
                    continue
                results.append(res)
                print(f"  OOS return {_fmt_pct(res['oos'].get('total_return'))} PF {_fmt(res['oos'].get('profit_factor'))} "
                      f"trades {res['oos'].get('n_trades')} pass={res['acceptance']['passed']} ({res['elapsed_seconds']}s)", flush=True)

    run = {
        "meta": {
            "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "data_span": "; ".join(spans) or "no data",
            "holdout_span": sorted(set(holdout_spans))[0] if holdout_spans else "n/a",
            "holdout_months": args.holdout_months,
            "fee_rate": args.fee,
            "slippage_rate": args.slippage,
            "size_fraction": args.size_fraction,
            "train_days": args.train_days,
            "test_days": args.test_days,
            "purge_days": args.purge_days,
            "select_by": args.select_by,
            "min_trades": args.min_trades,
            "seed": args.seed,
        },
        "benchmark": benchmark,
        "results": results,
        "failures": failures,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(run), encoding="utf-8")
    Path(args.json).write_text(json.dumps(run, indent=1, default=_json_default), encoding="utf-8")
    print(f"wrote {report_path} and {args.json}")
    return 0


def _finite(value, key: str = ""):
    """JSON-safe metric: NaN -> None; an infinite profit factor (no losing trade) -> 999.0."""
    if isinstance(value, float) and not np.isfinite(value):
        if key == "profit_factor" and value > 0:
            return 999.0
        return None
    return value


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
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
