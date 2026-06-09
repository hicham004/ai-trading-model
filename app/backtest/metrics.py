"""Compute performance metrics from a list of trades and an equity curve.

All metrics describe a SIMULATION on historical data. They never imply or
guarantee future results.
"""

from __future__ import annotations

from typing import List, Sequence

from app.backtest.models import PerformanceMetrics, Trade


def max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    """Largest peak-to-trough drop of the equity curve, as a percentage."""
    peak = float("-inf")
    max_dd = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (peak - equity) / peak
            max_dd = max(max_dd, drawdown)
    return max_dd * 100.0


def compute_metrics(
    trades: List[Trade],
    equity_curve: Sequence[float],
    starting_cash: float,
) -> PerformanceMetrics:
    """Build a :class:`PerformanceMetrics` from completed trades + equity."""
    ending_equity = equity_curve[-1] if equity_curve else starting_cash
    total_return_pct = (ending_equity - starting_cash) / starting_cash * 100.0

    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = sum(t.pnl for t in losses)  # <= 0

    num_trades = len(trades)
    win_rate_pct = (len(wins) / num_trades * 100.0) if num_trades else 0.0

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    else:
        # No losing trades: undefined ratio. Use +inf when there were profits,
        # otherwise 0.0 (no trades at all).
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    average_win = (gross_profit / len(wins)) if wins else 0.0
    average_loss = (gross_loss / len(losses)) if losses else 0.0

    return PerformanceMetrics(
        total_return_pct=total_return_pct,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct(equity_curve),
        average_win=average_win,
        average_loss=average_loss,
        num_trades=num_trades,
        total_fees_paid=sum(t.fees for t in trades),
        total_slippage_cost=sum(t.slippage_cost for t in trades),
        total_funding_cost=sum(t.funding_cost for t in trades),
    )
