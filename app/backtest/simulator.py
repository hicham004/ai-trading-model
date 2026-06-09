"""Signal-driven backtest simulator (long/flat, SIMULATION ONLY).

This is the heart of Phase 2. It connects the three layers exactly the way a
future automated system would:

    strategy.generate_signals()  ->  risk_manager.evaluate_entry()  ->  broker.submit()

Walking bar by bar at bar ``i``, it:

1. Checks the stop-loss FIRST for any pre-existing position (exit if the bar's
   low pierces it), modelling gap-throughs conservatively (see below). If a
   stop exits the position on a bar, no new entry is taken on that same bar.
   A position OPENED on this bar (at its open) is also stop-checked against the
   same bar's low, so an entry can be stopped out on its own bar.
2. Acts on the PREVIOUS bar's signal (``signals[i-1]``) using THIS bar's OPEN
   as the execution price. This avoids look-ahead: the bar's close is unknown
   when the bar begins, so a previous-bar signal must execute at the next bar's
   open, not its close.
3. Asks the risk manager to approve and size every entry (final veto), passing
   the distinct signal-data time and execution time. Risk checks, position
   sizing, and the order all use the execution OPEN.
4. Routes every fill through a SIMULATION broker, so fees and slippage are
   applied consistently. It refuses a broker that is not explicitly marked as a
   simulation, and refuses any fill that is not marked simulated or does not
   match the submitted order.
5. Charges the funding placeholder per bar a position is held.
6. Tracks an equity curve (marked at each bar's close) and produces completed
   trades + metrics.

It never places real orders. Sizing is risk-based and all-in/all-out; there is
no martingale, no averaging down, and no loss-chasing.

OHLC execution assumptions
--------------------------
Candles are OHLC bars, so the exact intrabar price path is unknown.

* Normal signal execution (enter on a LONG, exit on a FLAT) uses the execution
  bar's OPEN price. This is the first price available once the previous-bar
  signal is known, and removes the look-ahead of executing at the (then-unknown)
  close.
* Stop-loss execution for a long position:
  - If the bar OPENS at or above the stop and its low later pierces the stop,
    the stop is assumed to fill at the stop price (the standard, slightly
    optimistic intrabar assumption).
  - If the bar GAPS open BELOW the stop, the stop price was never available, so
    the first achievable price is the (worse) open. We fill at the open, never
    at the unavailable stop. This avoids overstating equity / understating
    drawdown on gap-downs.
* End-of-data liquidation closes any still-open position at the FINAL bar's
  close (there is no following open to use). This is a terminal bookkeeping
  step so metrics are complete; it is not a tradable signal.

In all cases the chosen reference price is routed through the simulation broker,
so slippage and fees still apply on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isclose, isfinite
from typing import List, Optional, Sequence

from app.backtest.metrics import compute_metrics
from app.backtest.models import (
    SimulationConfig,
    StrategyBacktestResult,
    Trade,
)
from app.backtest.validation import validate_candles, validate_signals
from app.broker.base import Broker, Fill, Order, OrderSide
from app.broker.paper import PaperBroker
from app.logging_config import get_logger
from app.risk.manager import RiskContext, RiskLimits, RiskManager
from app.strategy.base import MarketCandle, SignalAction, Strategy
from app.strategy.timeframes import resolve_max_signal_age

logger = get_logger(__name__)


# Relative/absolute tolerances for matching a fill's quantity to the order's.
# Tight enough to catch real mismatches (e.g. a doubled quantity) while
# tolerating only floating-point rounding.
_QTY_REL_TOL = 1e-9
_QTY_ABS_TOL = 1e-12


def _execute_simulated(broker: Broker, order: Order) -> Fill:
    """Submit ``order`` and validate the fill BEFORE the caller accounts for it.

    Raises ``ValueError`` (before any cash/position mutation by the caller) if
    the broker returns a non-simulated fill, a fill that does not match the
    order's instrument, side, quantity, or timestamp, or one containing
    invalid/non-finite values. This keeps the backtest fail-closed and prevents
    partial state mutation on a bad fill.
    """
    fill = broker.submit(order)
    if not getattr(fill, "is_simulated", False):
        raise ValueError(
            "Backtest refused a non-simulated fill (fill.is_simulated is False)."
        )
    if fill.instrument != order.instrument:
        raise ValueError("Broker fill instrument does not match the submitted order.")
    if fill.side != order.side:
        raise ValueError("Broker fill side does not match the submitted order.")
    if not (isfinite(fill.price) and fill.price > 0):
        raise ValueError("Broker fill price must be positive and finite.")
    if not (isfinite(fill.quantity) and fill.quantity > 0):
        raise ValueError("Broker fill quantity must be positive and finite.")
    # Strict quantity match (tolerating only float rounding).
    if not isclose(
        fill.quantity, order.quantity, rel_tol=_QTY_REL_TOL, abs_tol=_QTY_ABS_TOL
    ):
        raise ValueError("Broker fill quantity does not match the submitted order.")
    if fill.timestamp != order.timestamp:
        raise ValueError("Broker fill timestamp does not match the submitted order.")
    if not (isfinite(fill.fee) and fill.fee >= 0):
        raise ValueError("Broker fill fee must be a non-negative finite number.")
    if not (isfinite(fill.slippage_cost) and fill.slippage_cost >= 0):
        raise ValueError("Broker fill slippage must be a non-negative finite number.")
    return fill


@dataclass
class _OpenPosition:
    entry_time: datetime
    entry_price: float
    quantity: float
    stop_loss: Optional[float]
    entry_fee: float
    entry_slippage: float
    funding_cost: float = 0.0


def _empty_result(
    strategy_name: str, instrument: str, timeframe: str, config: SimulationConfig, bars: int
) -> StrategyBacktestResult:
    curve = [config.starting_cash] * bars
    return StrategyBacktestResult(
        strategy_name=strategy_name,
        instrument=instrument,
        timeframe=timeframe,
        bars=bars,
        starting_cash=config.starting_cash,
        ending_equity=config.starting_cash,
        trades=[],
        metrics=compute_metrics([], curve, config.starting_cash),
        equity_curve=curve,
        rejected_entries=0,
    )


def run_signal_backtest(
    candles: Sequence[MarketCandle],
    strategy: Strategy,
    config: Optional[SimulationConfig] = None,
    risk_manager: Optional[RiskManager] = None,
    broker: Optional[Broker] = None,
    timeframe: str = "",
    max_signal_age_seconds: Optional[float] = None,
) -> StrategyBacktestResult:
    """Run ``strategy`` over ``candles`` and return a SIMULATED result.

    When ``risk_manager`` is not supplied, a default one is built whose signal
    staleness is derived from ``timeframe`` (or ``max_signal_age_seconds`` if
    given), so direct callers and the database runner are timeframe-aware
    instead of stuck on a fixed two-hour default. Passing both an explicit
    ``risk_manager`` and ``max_signal_age_seconds`` is contradictory and refused.
    """
    config = config or SimulationConfig()
    broker = broker or PaperBroker(config.costs)
    funding_rate = config.costs.funding_rate
    expected_timeframe = timeframe or None

    if risk_manager is None:
        if timeframe or max_signal_age_seconds is not None:
            # Derive (or override) staleness so a valid previous-bar signal is
            # accepted on this timeframe. Unknown timeframes fail closed.
            risk_manager = RiskManager(
                RiskLimits(
                    max_data_staleness=resolve_max_signal_age(
                        timeframe, max_signal_age_seconds
                    )
                )
            )
        else:
            risk_manager = RiskManager()
    elif max_signal_age_seconds is not None:
        raise ValueError(
            "Pass max_signal_age_seconds OR a risk_manager, not both. Set the "
            "staleness on the supplied RiskManager's RiskLimits instead."
        )

    # Fail closed: a backtest may only use an explicitly simulated broker.
    if not getattr(broker, "is_simulation", False):
        raise ValueError(
            "run_signal_backtest requires a simulation broker "
            "(broker.is_simulation must be True). Refusing to run."
        )

    instrument = candles[0].instrument if candles else "?"

    # Validate market-data invariants up front (single instrument, ordering,
    # OHLC coherence, finite values, tz-aware timestamps).
    validate_candles(
        candles,
        expected_instrument=instrument,
        expected_timeframe=expected_timeframe,
    )

    if len(candles) < 2:
        return _empty_result(strategy.name, instrument, timeframe, config, len(candles))

    signals = strategy.generate_signals(candles)
    # Validate signal identity/alignment BEFORE processing any orders.
    validate_signals(
        signals,
        candles,
        expected_instrument=instrument,
        expected_timeframe=expected_timeframe,
    )

    cash = config.starting_cash
    position: Optional[_OpenPosition] = None
    trades: List[Trade] = []
    equity_curve: List[float] = []
    rejected_entries = 0

    # Daily-loss tracking (UTC days).
    current_day = candles[0].timestamp.date()
    day_start_equity = config.starting_cash
    day_realized_pnl = 0.0

    def equity_now(price: float) -> float:
        return cash + (position.quantity * price if position else 0.0)

    def close_position(
        exit_price_ref: float, when: datetime, reason: str
    ) -> float:
        """Sell the whole position through the broker. Returns realised pnl."""
        nonlocal cash, position
        assert position is not None
        order = Order(
            instrument=instrument,
            side=OrderSide.SELL,
            quantity=position.quantity,
            reference_price=exit_price_ref,
            timestamp=when,
        )
        # Validate the fill before mutating cash (fail-closed, no partial state).
        fill = _execute_simulated(broker, order)
        cash += fill.price * fill.quantity - fill.fee
        trade = Trade(
            instrument=instrument,
            entry_time=position.entry_time,
            exit_time=when,
            entry_price=position.entry_price,
            exit_price=fill.price,
            quantity=position.quantity,
            fees=position.entry_fee + fill.fee,
            slippage_cost=position.entry_slippage + fill.slippage_cost,
            funding_cost=position.funding_cost,
            exit_reason=reason,
        )
        trades.append(trade)
        position = None
        return trade.pnl

    def apply_stop_loss(candle: MarketCandle) -> bool:
        """Exit if this bar's low pierces the open position's stop.

        Returns True if the position was stopped out. Uses the conservative
        gap model: a bar that gaps open below the stop fills at the (worse)
        open; otherwise it fills at the stop price. Called both for a
        pre-existing position and for one just opened on this same bar.
        """
        nonlocal day_realized_pnl
        if position is None or position.stop_loss is None:
            return False
        if candle.low > position.stop_loss:
            return False
        if candle.open < position.stop_loss:
            # Gapped open below the stop: the stop price was never available;
            # the first achievable price is the worse open.
            stop_reference = candle.open
        else:
            # Opened at/above the stop and traded down through it: assume a
            # fill at the stop price.
            stop_reference = position.stop_loss
        day_realized_pnl += close_position(stop_reference, candle.timestamp, "stop_loss")
        return True

    for i, candle in enumerate(candles):
        close_price = candle.close
        # Normal signal execution happens at THIS bar's open (next-bar-open
        # execution relative to the previous-bar signal). The close is only
        # used for mark-to-market valuation and the funding placeholder.
        execution_price = candle.open

        # Roll the daily-loss window at UTC midnight (marked at the close).
        if candle.timestamp.date() != current_day:
            current_day = candle.timestamp.date()
            day_start_equity = equity_now(close_price)
            day_realized_pnl = 0.0

        # 1) Stop-loss check FIRST for a pre-existing position (intrabar low
        #    pierces the stop), modelling gap-throughs conservatively.
        exited_this_bar = apply_stop_loss(candle)

        # 2) Act on the PREVIOUS bar's signal at THIS bar's OPEN (no look-ahead).
        #    Skipped if a stop already exited on this bar (no same-bar re-entry).
        signal = signals[i - 1] if i > 0 else None

        if signal is not None and not exited_this_bar:
            if signal.action == SignalAction.LONG and position is None:
                equity = equity_now(execution_price)  # flat, so == cash
                context = RiskContext(
                    equity=equity,
                    reference_price=execution_price,
                    day_start_equity=day_start_equity,
                    day_realized_pnl=day_realized_pnl,
                    # Execution time is THIS bar; the signal's data time is the
                    # PREVIOUS bar it was generated from. These are distinct so
                    # the staleness gate actually sees the signal's age.
                    now=candle.timestamp,
                    data_time=signal.timestamp,
                )
                decision = risk_manager.evaluate_entry(signal, context)
                if not decision.allowed:
                    rejected_entries += 1
                else:
                    fraction = risk_manager.position_fraction(signal, context)
                    notional = equity * fraction
                    fill_price_est = execution_price * (1.0 + config.costs.slippage_rate)
                    denom = fill_price_est * (1.0 + config.costs.fee_rate)
                    quantity = notional / denom if denom > 0 else 0.0
                    if quantity > 0:
                        order = Order(
                            instrument=instrument,
                            side=OrderSide.BUY,
                            quantity=quantity,
                            reference_price=execution_price,
                            timestamp=candle.timestamp,
                        )
                        # Validate the fill before mutating cash/position.
                        fill = _execute_simulated(broker, order)
                        cash -= fill.price * fill.quantity + fill.fee
                        position = _OpenPosition(
                            entry_time=candle.timestamp,
                            entry_price=fill.price,
                            quantity=fill.quantity,
                            stop_loss=signal.stop_loss,
                            entry_fee=fill.fee,
                            entry_slippage=fill.slippage_cost,
                        )
                        # A position opened at THIS bar's open can still be
                        # stopped out by the SAME bar's low (e.g. enter at 100,
                        # bar trades down to 80 through a 90 stop). The entry
                        # open is above the stop, so this fills at the stop.
                        apply_stop_loss(candle)
            elif signal.action == SignalAction.FLAT and position is not None:
                day_realized_pnl += close_position(
                    execution_price, candle.timestamp, "signal"
                )
            # HOLD: leave the position unchanged.

        # 3) Funding placeholder for any position still open at the bar close.
        if position is not None and funding_rate > 0:
            funding = position.quantity * close_price * funding_rate
            cash -= funding
            position.funding_cost += funding

        equity_curve.append(equity_now(close_price))

    # Close any position left open at the end so metrics are complete. There is
    # no following bar's open to use, so this terminal bookkeeping step uses the
    # final bar's close (see the module docstring). It is not a tradable signal.
    if position is not None:
        close_position(candles[-1].close, candles[-1].timestamp, "end_of_data")
        equity_curve[-1] = cash

    ending_equity = equity_curve[-1]

    # Invariant: every monetary result must be finite.
    if not (isfinite(cash) and isfinite(ending_equity)):
        raise ValueError("backtest produced non-finite cash/equity")
    if any(not isfinite(value) for value in equity_curve):
        raise ValueError("backtest produced a non-finite equity-curve value")
    for trade in trades:
        if any(
            not isfinite(value)
            for value in (
                trade.entry_price,
                trade.exit_price,
                trade.quantity,
                trade.fees,
                trade.slippage_cost,
                trade.funding_cost,
                trade.pnl,
            )
        ):
            raise ValueError("backtest produced a non-finite trade value")

    metrics = compute_metrics(trades, equity_curve, config.starting_cash)

    result = StrategyBacktestResult(
        strategy_name=strategy.name,
        instrument=instrument,
        timeframe=timeframe,
        bars=len(candles),
        starting_cash=config.starting_cash,
        ending_equity=ending_equity,
        trades=trades,
        metrics=metrics,
        equity_curve=equity_curve,
        rejected_entries=rejected_entries,
    )
    logger.info(
        "Signal backtest finished (SIMULATION ONLY)",
        extra={
            "strategy": result.strategy_name,
            "instrument": instrument,
            "timeframe": timeframe,
            "bars": result.bars,
            "num_trades": metrics.num_trades,
            "total_return_pct": round(metrics.total_return_pct, 4),
            "rejected_entries": rejected_entries,
        },
    )
    return result
