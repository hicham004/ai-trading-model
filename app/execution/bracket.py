"""Mechanical exit bracket levels (Sprint 3; pure, deterministic, Decimal).

The protective stop is mandatory and comes from the reviewed signal
(``Signal.stop_loss``). The bracket adds OPTIONAL legs, all OFF by default
(Sprint 2b showed brackets cost profit factor on rules that already have
exits):

- **take-profit** at ``entry + take_profit_r x R`` where ``R = entry - stop``
  (placed as the TP leg of an OCO exchange-side stop);
- **trailing stop** once the running high since the entry fill is at least
  ``trail_activate_r x R`` above the entry: the stop follows the running high
  at ``trail_r x R`` below it and only ever moves up (applied by amending the
  exchange-side stop on confirmed candle closes);
- **time stop** after ``time_stop_bars`` confirmed candles since the entry
  fill (a normal protective exit through the reviewed exit path).

No function here talks to a venue or a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from app.config import Settings


@dataclass(frozen=True)
class BracketLevels:
    stop: Decimal  # effective protective stop (original or trailed; never below the original)
    take_profit: Optional[Decimal]  # None when the take-profit leg is off
    time_stop_due: bool  # True when the time stop has elapsed


def risk_unit(entry_price: Decimal, stop_price: Decimal) -> Optional[Decimal]:
    """``R = entry - stop``; None when the stop is not below the entry."""
    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return None
    return entry_price - stop_price


def bracket_levels(
    *,
    entry_price: Decimal,
    stop_price: Decimal,
    highs_since_entry: Iterable[Decimal],
    bars_since_entry: int,
    settings: Settings,
) -> BracketLevels:
    """Compute the effective stop, the optional take-profit and the time-stop flag."""
    r = risk_unit(entry_price, stop_price)
    stop = stop_price
    take_profit: Optional[Decimal] = None
    if r is not None:
        tp_r = Decimal(str(settings.demo_bracket_take_profit_r))
        if tp_r > 0:
            take_profit = entry_price + tp_r * r
        activate_r = Decimal(str(settings.demo_bracket_trail_activate_r))
        trail_r = Decimal(str(settings.demo_bracket_trail_r))
        if trail_r > 0:
            running_high = max(list(highs_since_entry) or [entry_price])
            if running_high - entry_price >= activate_r * r:
                trailed = running_high - trail_r * r
                if trailed > stop:
                    stop = trailed
    bars_limit = int(settings.demo_bracket_time_stop_bars)
    time_due = bars_limit > 0 and int(bars_since_entry) >= bars_limit
    return BracketLevels(stop=stop, take_profit=take_profit, time_stop_due=time_due)
