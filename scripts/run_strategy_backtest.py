"""Command-line script: run a Phase 2 strategy backtest over stored candles.

Examples
--------
List available strategies::

    python scripts/run_strategy_backtest.py --list

Run the moving-average crossover on stored BTC-USDT 1H candles, with
placeholder fees and slippage::

    python scripts/run_strategy_backtest.py --strategy ma_crossover \
        --instrument BTC-USDT --timeframe 1H --fee-rate 0.001 --slippage-rate 0.0005

Execution model: a strategy signal generated on one bar executes at the NEXT
bar's OPEN (not its close), so there is no look-ahead. Signal staleness is
derived from ``--timeframe`` by default (one bar interval) and can be overridden
with ``--max-signal-age-seconds``.

WARNING: Output is a SIMULATION on historical data only. The baseline
strategies are not predictive and make no profitability claim. The risk
manager vets every entry, and the paper broker produces simulated fills only.
A passing backtest does NOT authorize paper or live trading (PROJECT_RULES.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.models import SimulationConfig  # noqa: E402
from app.backtest.runner import run_backtest_on_stored_candles  # noqa: E402
from app.broker.base import CostModel  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.database import init_db, session_scope  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402
from app.risk.manager import RiskLimits, RiskManager  # noqa: E402
from app.strategy.registry import available_strategies, build_strategy  # noqa: E402
from app.strategy.timeframes import resolve_max_signal_age  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Phase 2 strategy backtest.")
    parser.add_argument(
        "--list", action="store_true", help="List available strategies and exit."
    )
    parser.add_argument(
        "--strategy", default="ma_crossover", help="Strategy name (see --list)."
    )
    parser.add_argument(
        "--instrument", default="BTC-USDT", choices=list(ALLOWED_INSTRUMENTS)
    )
    parser.add_argument("--timeframe", default="1H")
    parser.add_argument("--starting-cash", type=float, default=10_000.0)
    parser.add_argument(
        "--fee-rate", type=float, default=0.0, help="Placeholder fee fraction."
    )
    parser.add_argument(
        "--slippage-rate", type=float, default=0.0, help="Placeholder slippage fraction."
    )
    parser.add_argument(
        "--funding-rate",
        type=float,
        default=0.0,
        help="Placeholder per-bar funding fraction (spot research: keep 0).",
    )
    parser.add_argument(
        "--max-risk-per-trade",
        type=float,
        default=0.01,
        help="Risk-manager cap: fraction of equity risked per trade.",
    )
    parser.add_argument(
        "--max-position-size",
        type=float,
        default=0.25,
        help="Risk-manager cap: max fraction of equity in one position.",
    )
    parser.add_argument(
        "--max-signal-age-seconds",
        type=float,
        default=None,
        help=(
            "Risk-manager cap: maximum signal age (seconds). If omitted, it is "
            "derived from --timeframe so the immediately-previous completed "
            "candle is fresh (e.g. 1H -> 3600s, 4H -> 14400s, 1D -> 86400s)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list:
        print("Available strategies:")
        for name in available_strategies():
            print(f"  - {name}")
        return 0

    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()

    try:
        strategy = build_strategy(args.strategy)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    config = SimulationConfig(
        starting_cash=args.starting_cash,
        costs=CostModel(
            fee_rate=args.fee_rate,
            slippage_rate=args.slippage_rate,
            funding_rate=args.funding_rate,
        ),
    )

    # Derive (or override) the signal-staleness limit for this timeframe. An
    # unknown timeframe or invalid override fails closed before any work.
    try:
        max_signal_age = resolve_max_signal_age(
            args.timeframe, args.max_signal_age_seconds
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    risk_manager = RiskManager(
        RiskLimits(
            max_risk_per_trade=args.max_risk_per_trade,
            max_position_size=args.max_position_size,
            max_data_staleness=max_signal_age,
        )
    )

    try:
        with session_scope() as session:
            result = run_backtest_on_stored_candles(
                session,
                strategy,
                args.instrument,
                timeframe=args.timeframe,
                config=config,
                risk_manager=risk_manager,
            )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    m = result.metrics
    print("=" * 78)
    print("PHASE 2 STRATEGY BACKTEST  (SIMULATION ONLY - NOT A PROFITABILITY CLAIM)")
    print("=" * 78)
    print(result.summary())
    print("-" * 78)
    print(f"  strategy           : {result.strategy_name}")
    print(f"  instrument / tf    : {result.instrument} / {result.timeframe}")
    print(f"  bars               : {result.bars}")
    print(f"  starting cash      : {result.starting_cash:,.2f}")
    print(f"  ending equity      : {result.ending_equity:,.2f}")
    print(f"  total return       : {m.total_return_pct:.2f}%")
    print(f"  number of trades   : {m.num_trades}")
    print(f"  win rate           : {m.win_rate_pct:.1f}%")
    print(f"  profit factor      : {m.profit_factor:.2f}")
    print(f"  max drawdown       : {m.max_drawdown_pct:.2f}%")
    print(f"  average win        : {m.average_win:,.2f}")
    print(f"  average loss       : {m.average_loss:,.2f}")
    print(f"  fees paid          : {m.total_fees_paid:,.2f}")
    print(f"  slippage cost      : {m.total_slippage_cost:,.2f}")
    print(f"  funding cost       : {m.total_funding_cost:,.2f}")
    print(f"  risk-rejected entries: {result.rejected_entries}")
    print("-" * 78)
    print(
        "Reminder: historical simulation only. The risk manager vetoes entries "
        "and the paper broker simulates fills. This does NOT authorize paper or "
        "live trading. See PROJECT_RULES.md and docs/PHASES.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
