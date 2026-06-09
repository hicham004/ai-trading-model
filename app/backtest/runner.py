"""Backtest runner: load stored candles and run a strategy over them.

This bridges the Phase 1 data foundation (candles in the database) and the
Phase 2 strategy engine. It loads candles for an instrument/timeframe, converts
the ORM rows into neutral :class:`MarketCandle` objects, and runs the
signal-driven simulator.
"""

from __future__ import annotations

from datetime import timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.models import SimulationConfig, StrategyBacktestResult
from app.backtest.simulator import run_signal_backtest
from app.db.models import Candle as CandleRow
from app.risk.manager import RiskManager
from app.strategy.base import MarketCandle, Strategy


def load_market_candles(
    session: Session, instrument: str, timeframe: str
) -> List[MarketCandle]:
    """Load stored candles for one instrument/timeframe, oldest-first."""
    rows = session.scalars(
        select(CandleRow)
        .where(CandleRow.instrument == instrument, CandleRow.timeframe == timeframe)
        .order_by(CandleRow.open_time.asc())
    ).all()

    candles: List[MarketCandle] = []
    for row in rows:
        open_time = row.open_time
        # SQLite returns naive datetimes; treat stored times as UTC.
        if open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=timezone.utc)
        candles.append(
            MarketCandle(
                instrument=row.instrument,
                timestamp=open_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                timeframe=row.timeframe,
            )
        )
    return candles


def run_backtest_on_stored_candles(
    session: Session,
    strategy: Strategy,
    instrument: str,
    timeframe: str = "1H",
    config: Optional[SimulationConfig] = None,
    risk_manager: Optional[RiskManager] = None,
    max_signal_age_seconds: Optional[float] = None,
) -> StrategyBacktestResult:
    """Load stored candles and run ``strategy`` over them (SIMULATION ONLY).

    When ``risk_manager`` is not supplied, the simulator derives the signal
    staleness from ``timeframe`` (or ``max_signal_age_seconds`` if given), so
    calling this runner directly is timeframe-aware (a valid previous-bar 4H or
    1D signal is accepted) rather than stuck on a fixed two-hour default.

    Raises:
        ValueError: if there are fewer than two stored candles to simulate, or
            if both ``risk_manager`` and ``max_signal_age_seconds`` are given.
    """
    candles = load_market_candles(session, instrument, timeframe)
    if len(candles) < 2:
        raise ValueError(
            f"Not enough stored candles for {instrument} {timeframe}. "
            "Fetch some first with scripts/fetch_candles.py."
        )
    return run_signal_backtest(
        candles,
        strategy,
        config=config,
        risk_manager=risk_manager,
        timeframe=timeframe,
        max_signal_age_seconds=max_signal_age_seconds,
    )
