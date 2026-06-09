"""Virtual account state for Phase 4 paper trading (SIMULATION ONLY).

The :class:`PaperAccount` holds virtual USDT cash plus zero-or-more long spot
positions and enforces hard, fail-closed invariants on every mutation:

* cash can never go negative (no borrowing, no leverage);
* a position is long-only with a positive finite quantity (no shorting);
* you can only ever sell a position you actually hold, in full (all-in /
  all-out; no partial oversell, no averaging down);
* no NaN / Infinity is ever allowed into cash, quantities, or prices.

The account is deliberately *not* coupled to the database. The engine mutates a
copy, the ledger persists the resulting state atomically, and only then does the
engine adopt the copy - so a failed write never leaves in-memory state ahead of
the journal. Daily realised-loss tracking lives here too, rolled at UTC
midnight by market (candle) time so the risk manager can enforce a daily-loss
lockout deterministically.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from math import isclose, isfinite
from typing import Dict, Optional


class AccountError(ValueError):
    """Raised when a mutation would violate an account invariant (fail closed)."""


def _check_finite_positive(value: float, label: str) -> None:
    if not isfinite(value) or value <= 0:
        raise AccountError(f"{label} must be a positive finite number (got {value!r})")


def _check_finite_nonneg(value: float, label: str) -> None:
    if not isfinite(value) or value < 0:
        raise AccountError(
            f"{label} must be a non-negative finite number (got {value!r})"
        )


@dataclass
class Position:
    """One open long spot position. All figures are virtual/simulated."""

    instrument: str
    quantity: float
    entry_price: float  # fill price, includes slippage
    stop_loss: Optional[float]
    entry_time: datetime
    entry_fee: float = 0.0
    entry_slippage: float = 0.0
    signal_id: str = ""

    def __post_init__(self) -> None:
        _check_finite_positive(self.quantity, "position quantity")
        _check_finite_positive(self.entry_price, "position entry_price")
        if self.stop_loss is not None:
            _check_finite_positive(self.stop_loss, "position stop_loss")
        _check_finite_nonneg(self.entry_fee, "position entry_fee")
        _check_finite_nonneg(self.entry_slippage, "position entry_slippage")

    def market_value(self, price: float) -> float:
        return self.quantity * price


@dataclass
class PaperAccount:
    """Virtual cash + long positions with fail-closed monetary invariants."""

    starting_cash: float
    # ``cash`` defaults to ``None`` to mean "fresh account": it is then set to
    # ``starting_cash``. A reconstructed account passes an explicit ``cash``
    # (even 0.0), so reconstruction is never mistaken for a fresh account.
    cash: Optional[float] = None
    positions: Dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    # Daily realised-loss tracking (UTC, market/candle time).
    current_day: Optional[date] = None
    day_start_equity: float = 0.0
    day_realized_pnl: float = 0.0

    def __post_init__(self) -> None:
        _check_finite_positive(self.starting_cash, "starting_cash")
        if self.cash is None:
            # Fresh account: cash starts at the configured starting balance.
            self.cash = self.starting_cash
            self.day_start_equity = self.starting_cash
        _check_finite_nonneg(self.cash, "cash")
        if not isfinite(self.realized_pnl):
            raise AccountError("realized_pnl must be finite")
        _check_finite_nonneg(self.total_fees, "total_fees")
        _check_finite_nonneg(self.total_slippage, "total_slippage")
        if not isfinite(self.day_start_equity) or self.day_start_equity < 0:
            raise AccountError("day_start_equity must be a non-negative finite number")
        if not isfinite(self.day_realized_pnl):
            raise AccountError("day_realized_pnl must be finite")
        for key, position in self.positions.items():
            if key != position.instrument:
                raise AccountError(
                    "position dictionary key must match the position instrument"
                )

    # -- read helpers -------------------------------------------------------

    def copy(self) -> "PaperAccount":
        """Return a deep copy so the engine can stage a candle's effects."""
        return copy.deepcopy(self)

    def has_position(self, instrument: str) -> bool:
        return instrument in self.positions

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def position_value(self, marks: Dict[str, float]) -> float:
        """Total value of open positions using ``marks`` (instrument -> price)."""
        total = 0.0
        for instrument, position in self.positions.items():
            mark = marks.get(instrument, position.entry_price)
            total += position.market_value(mark)
        return total

    def equity(self, marks: Dict[str, float]) -> float:
        """Cash plus the marked value of every open position."""
        return self.cash + self.position_value(marks)

    def unrealized_pnl(self, marks: Dict[str, float]) -> float:
        total = 0.0
        for instrument, position in self.positions.items():
            mark = marks.get(instrument, position.entry_price)
            total += (mark - position.entry_price) * position.quantity
        return total

    # -- daily-loss window --------------------------------------------------

    def roll_day_if_needed(self, market_day: date, equity_now: float) -> None:
        """Reset the daily realised-loss window at a new UTC market day."""
        if self.current_day is None or market_day != self.current_day:
            self.current_day = market_day
            self.day_start_equity = equity_now
            self.day_realized_pnl = 0.0

    # -- mutations (each enforces invariants) -------------------------------

    def apply_buy(
        self,
        *,
        instrument: str,
        quantity: float,
        fill_price: float,
        fee: float,
        slippage_cost: float,
        stop_loss: Optional[float],
        entry_time: datetime,
        signal_id: str,
    ) -> Position:
        """Open a long position, debiting cash. Fail closed on any violation."""
        _check_finite_positive(quantity, "buy quantity")
        _check_finite_positive(fill_price, "buy fill_price")
        _check_finite_nonneg(fee, "buy fee")
        _check_finite_nonneg(slippage_cost, "buy slippage_cost")
        if instrument in self.positions:
            # No averaging down / no second entry while already positioned.
            raise AccountError(
                f"cannot open {instrument}: a position is already open "
                "(no averaging down / no duplicate entry)"
            )
        cost = fill_price * quantity + fee
        if cost > self.cash + 1e-9:
            raise AccountError(
                "insufficient cash for buy "
                f"(need {cost!r}, have {self.cash!r}); no negative balances"
            )
        self.cash -= cost
        if self.cash < 0:  # defensive: never below zero after rounding
            self.cash = 0.0
        self.total_fees += fee
        self.total_slippage += slippage_cost
        position = Position(
            instrument=instrument,
            quantity=quantity,
            entry_price=fill_price,
            stop_loss=stop_loss,
            entry_time=entry_time,
            entry_fee=fee,
            entry_slippage=slippage_cost,
            signal_id=signal_id,
        )
        self.positions[instrument] = position
        return position

    def apply_sell(
        self,
        *,
        instrument: str,
        quantity: float,
        fill_price: float,
        fee: float,
        slippage_cost: float,
    ) -> float:
        """Close the full position, crediting cash. Returns realised PnL.

        Only a fully-held quantity may be sold (all-in / all-out). Selling more
        than is held, or selling an instrument with no position, fails closed.
        """
        _check_finite_positive(quantity, "sell quantity")
        _check_finite_positive(fill_price, "sell fill_price")
        _check_finite_nonneg(fee, "sell fee")
        _check_finite_nonneg(slippage_cost, "sell slippage_cost")
        position = self.positions.get(instrument)
        if position is None:
            raise AccountError(f"cannot sell {instrument}: no open position")
        if not isclose(quantity, position.quantity, rel_tol=1e-9, abs_tol=1e-12):
            raise AccountError(
                f"cannot sell {quantity!r} of {instrument}: the full held "
                f"quantity {position.quantity!r} is required"
            )
        proceeds = fill_price * quantity - fee
        self.cash += proceeds
        _check_finite_nonneg(self.cash, "cash after sell")
        self.total_fees += fee
        self.total_slippage += slippage_cost
        # Realised PnL on the closed round trip, net of both legs' fees.
        gross = (fill_price - position.entry_price) * quantity
        realized = gross - position.entry_fee - fee
        self.realized_pnl += realized
        self.day_realized_pnl += realized
        del self.positions[instrument]
        return realized
