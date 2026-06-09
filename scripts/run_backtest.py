"""Command-line script: run the DEMO backtest over stored candles.

This loads candles from the local database and runs the non-predictive demo
strategy through the backtest skeleton.

Example::

    python scripts/run_backtest.py --instrument BTC-USDT --timeframe 1H

WARNING: Output is a SIMULATION on historical data only. The demo strategy is
not predictive and makes no profitability claim. A passing backtest does not
authorize paper or live trading (see PROJECT_RULES.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.backtest.engine import BacktestConfig, run_backtest  # noqa: E402
from app.backtest.strategy import DemoMovingAverageStrategy  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.database import init_db, session_scope  # noqa: E402
from app.db.models import Candle  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the demo backtest skeleton.")
    parser.add_argument(
        "--instrument", default="BTC-USDT", choices=list(ALLOWED_INSTRUMENTS)
    )
    parser.add_argument("--timeframe", default="1H")
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.0,
        help="Placeholder per-trade fee fraction (e.g. 0.001 = 0.1%%).",
    )
    parser.add_argument(
        "--slippage-rate",
        type=float,
        default=0.0,
        help="Placeholder slippage fraction (e.g. 0.0005 = 0.05%%).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()

    with session_scope() as session:
        closes = list(
            session.scalars(
                select(Candle.close)
                .where(
                    Candle.instrument == args.instrument,
                    Candle.timeframe == args.timeframe,
                )
                .order_by(Candle.open_time.asc())
            ).all()
        )

    if len(closes) < 2:
        print(
            f"Not enough stored candles for {args.instrument} {args.timeframe}. "
            "Run scripts/fetch_candles.py first.",
            file=sys.stderr,
        )
        return 1

    strategy = DemoMovingAverageStrategy()
    config = BacktestConfig(fee_rate=args.fee_rate, slippage_rate=args.slippage_rate)
    result = run_backtest(closes, strategy, config)

    print("=" * 70)
    print("DEMO BACKTEST RESULT  (SIMULATION ONLY - NOT A PROFITABILITY CLAIM)")
    print("=" * 70)
    print(result.summary())
    print(
        "\nReminder: historical simulation only. Does not authorize paper or "
        "live trading. See PROJECT_RULES.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
