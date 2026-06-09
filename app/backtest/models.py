"""Data models for signal-driven backtests: trades, metrics, and results.

These models describe SIMULATED outcomes only. A backtest result never proves
future performance and never authorises paper or live trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import List

from app.broker.base import CostModel


@dataclass(frozen=True)
class SimulationConfig:
    """Inputs for one backtest run."""

    starting_cash: float = 10_000.0
    costs: CostModel = field(default_factory=CostModel)

    def __post_init__(self) -> None:
        if not isfinite(self.starting_cash) or self.starting_cash <= 0:
            raise ValueError("starting_cash must be a positive finite number")


@dataclass(frozen=True)
class Trade:
    """One completed round-trip (entry then exit). All figures are SIMULATED."""

    instrument: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float  # fill price, includes slippage
    exit_price: float  # fill price, includes slippage
    quantity: float
    fees: float  # entry + exit fees
    slippage_cost: float  # entry + exit slippage magnitude
    funding_cost: float  # placeholder funding charged while held
    exit_reason: str  # e.g. "signal", "stop_loss", "end_of_data"

    @property
    def pnl(self) -> float:
        """Net profit/loss in cash, after fees and funding."""
        gross = (self.exit_price - self.entry_price) * self.quantity
        return gross - self.fees - self.funding_cost

    @property
    def return_pct(self) -> float:
        cost_basis = self.entry_price * self.quantity
        if cost_basis <= 0:
            return 0.0
        return self.pnl / cost_basis * 100.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0.0


@dataclass(frozen=True)
class PerformanceMetrics:
    """Summary statistics for a backtest. All SIMULATED, never a guarantee."""

    total_return_pct: float
    win_rate_pct: float
    profit_factor: float  # gross profit / gross loss; inf if there are no losses
    max_drawdown_pct: float
    average_win: float
    average_loss: float  # <= 0
    num_trades: int
    total_fees_paid: float
    total_slippage_cost: float
    total_funding_cost: float


@dataclass(frozen=True)
class StrategyBacktestResult:
    """Full result of a signal-driven backtest. SIMULATION ONLY."""

    strategy_name: str
    instrument: str
    timeframe: str
    bars: int
    starting_cash: float
    ending_equity: float
    trades: List[Trade]
    metrics: PerformanceMetrics
    equity_curve: List[float] = field(default_factory=list)
    rejected_entries: int = 0  # entries the risk manager vetoed
    is_simulation: bool = True  # always True

    def summary(self) -> str:
        m = self.metrics
        return (
            f"[SIMULATION] {self.strategy_name} {self.instrument} {self.timeframe} "
            f"bars={self.bars} start={self.starting_cash:.2f} "
            f"end={self.ending_equity:.2f} return={m.total_return_pct:.2f}% "
            f"trades={m.num_trades} win_rate={m.win_rate_pct:.1f}% "
            f"profit_factor={m.profit_factor:.2f} max_dd={m.max_drawdown_pct:.2f}% "
            f"fees={m.total_fees_paid:.2f} slippage={m.total_slippage_cost:.2f} "
            f"risk_rejected={self.rejected_entries}"
        )
