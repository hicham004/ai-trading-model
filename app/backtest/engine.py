"""A minimal, long/flat backtest engine (research skeleton).

What it does
------------
- Walks through historical closing prices bar by bar.
- Asks a :class:`~app.backtest.strategy.Strategy` for a target position
  (1.0 = long, 0.0 = flat) for the next bar, using past data only.
- Tracks a simulated equity curve.
- Applies FEE and SLIPPAGE placeholders whenever the position changes.

What it deliberately does NOT do (Phase 1 safety)
-------------------------------------------------
- It never places real or simulated exchange orders.
- It uses fixed, all-in/all-out sizing only. There is NO martingale, NO
  doubling down, and NO loss-chasing position sizing.
- Its output is a SIMULATION on historical data and proves nothing about the
  future. A passing backtest never authorizes paper or live trading.

The fee and slippage values are PLACEHOLDERS so the structure is ready for a
more realistic cost model later. They default to zero unless you set them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import List, Sequence

from app.backtest.strategy import Strategy
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    """Tunable inputs for a backtest run.

    Attributes:
        starting_cash: simulated starting capital.
        fee_rate: PLACEHOLDER per-trade fee as a fraction of traded value
            (e.g. 0.001 = 0.1%). Defaults to 0.0.
        slippage_rate: PLACEHOLDER price slippage as a fraction of price applied
            when entering/exiting (e.g. 0.0005 = 0.05%). Defaults to 0.0.
    """

    starting_cash: float = 10_000.0
    fee_rate: float = 0.0  # placeholder; wire in a real model later
    slippage_rate: float = 0.0  # placeholder; wire in a real model later

    def __post_init__(self) -> None:
        if not isfinite(self.starting_cash) or self.starting_cash <= 0:
            raise ValueError("starting_cash must be a positive finite number")
        if not isfinite(self.fee_rate) or not 0.0 <= self.fee_rate < 1.0:
            raise ValueError("fee_rate must be between 0.0 (inclusive) and 1.0")
        if (
            not isfinite(self.slippage_rate)
            or not 0.0 <= self.slippage_rate < 1.0
        ):
            raise ValueError(
                "slippage_rate must be between 0.0 (inclusive) and 1.0"
            )


@dataclass
class BacktestResult:
    """Outcome of a backtest run. All figures are SIMULATED."""

    strategy_name: str
    bars: int
    starting_cash: float
    ending_equity: float
    total_return_pct: float
    num_trades: int
    total_fees_paid: float
    total_slippage_cost: float
    equity_curve: List[float] = field(default_factory=list)
    is_simulation: bool = True  # always True; never real trading

    def summary(self) -> str:
        return (
            f"[SIMULATION] strategy={self.strategy_name} bars={self.bars} "
            f"start={self.starting_cash:.2f} end={self.ending_equity:.2f} "
            f"return={self.total_return_pct:.2f}% trades={self.num_trades} "
            f"fees={self.total_fees_paid:.2f} slippage={self.total_slippage_cost:.2f}"
        )


def run_backtest(
    closes: Sequence[float],
    strategy: Strategy,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run a long/flat backtest over ``closes`` using ``strategy``.

    Args:
        closes: closing prices, oldest first.
        strategy: produces a target position per bar (1.0 long / 0.0 flat).
        config: starting cash and fee/slippage placeholders.

    Returns:
        A :class:`BacktestResult` describing the SIMULATED outcome.
    """
    config = config or BacktestConfig()

    if any(not isfinite(price) or price <= 0 for price in closes):
        raise ValueError("all closing prices must be positive finite numbers")

    if len(closes) < 2:
        # Not enough data to simulate any movement.
        return BacktestResult(
            strategy_name=getattr(strategy, "name", "unknown"),
            bars=len(closes),
            starting_cash=config.starting_cash,
            ending_equity=config.starting_cash,
            total_return_pct=0.0,
            num_trades=0,
            total_fees_paid=0.0,
            total_slippage_cost=0.0,
            equity_curve=[config.starting_cash] * len(closes),
        )

    positions = strategy.generate_positions(closes)
    if len(positions) != len(closes):
        raise ValueError("strategy returned the wrong number of positions")
    if any(position not in (0.0, 1.0) for position in positions):
        raise ValueError("strategy positions must be either 0.0 (flat) or 1.0 (long)")

    cash = config.starting_cash
    units = 0.0  # units of the asset currently held
    current_position = 0.0  # 0.0 flat, 1.0 long
    num_trades = 0
    total_fees = 0.0
    total_slippage = 0.0
    equity_curve: List[float] = []

    for i, price in enumerate(closes):
        # Decide the target position using data up to the PREVIOUS bar to avoid
        # look-ahead bias. On the first bar we start flat.
        target_position = positions[i - 1] if i > 0 else 0.0

        if target_position != current_position:
            # Execute the position change at this bar's price, applying the
            # slippage and fee PLACEHOLDERS. Sizing is all-in / all-out only.
            if target_position == 1.0:
                # Enter long: buy slightly higher because of slippage.
                exec_price = price * (1.0 + config.slippage_rate)
                # Reserve the entry fee from starting cash so the simulation
                # never creates a negative cash balance.
                units = cash / (exec_price * (1.0 + config.fee_rate))
                trade_value = units * exec_price
                slippage_cost = units * price * config.slippage_rate
                fee = trade_value * config.fee_rate
                cash = 0.0
            else:
                # Exit to flat: sell slightly lower because of slippage.
                exec_price = price * (1.0 - config.slippage_rate)
                trade_value = units * exec_price
                slippage_cost = units * price * config.slippage_rate
                fee = trade_value * config.fee_rate
                cash = trade_value - fee
                units = 0.0

            total_fees += fee
            total_slippage += slippage_cost
            num_trades += 1
            current_position = target_position

        # Mark-to-market equity at this bar's close.
        equity = cash + units * price
        equity_curve.append(equity)

    ending_equity = equity_curve[-1]
    total_return_pct = (
        (ending_equity - config.starting_cash) / config.starting_cash * 100.0
    )

    result = BacktestResult(
        strategy_name=getattr(strategy, "name", "unknown"),
        bars=len(closes),
        starting_cash=config.starting_cash,
        ending_equity=ending_equity,
        total_return_pct=total_return_pct,
        num_trades=num_trades,
        total_fees_paid=total_fees,
        total_slippage_cost=total_slippage,
        equity_curve=equity_curve,
    )
    logger.info(
        "Backtest finished (SIMULATION ONLY)",
        extra={
            "strategy": result.strategy_name,
            "bars": result.bars,
            "num_trades": result.num_trades,
            "total_return_pct": round(result.total_return_pct, 4),
        },
    )
    return result
