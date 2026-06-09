"""Strategy interface and a demo (non-predictive) strategy.

A strategy turns a price history into a sequence of target positions, where:
    1.0  = fully long (hold the asset)
    0.0  = flat (hold cash)

Phase 1 only ships a DEMO strategy. It exists to exercise the backtest
skeleton end-to-end. It is intentionally simple, is NOT predictive, and makes
NO claim of profitability.
"""

from __future__ import annotations

from typing import List, Protocol, Sequence


class Strategy(Protocol):
    """A strategy maps a list of closing prices to target positions.

    The returned list must be the same length as ``closes``. Each value is the
    desired position for the NEXT bar, decided using only information available
    up to and including the current bar (no look-ahead).
    """

    name: str

    def generate_positions(self, closes: Sequence[float]) -> List[float]:
        ...


class DemoMovingAverageStrategy:
    """A demo moving-average crossover strategy.

    Goes "long" (position 1.0) when the short moving average is above the long
    moving average, otherwise stays flat (0.0). This is a textbook teaching
    example used here ONLY to demonstrate the backtest mechanics.

    WARNING: This is not investment advice and is not expected to be
    profitable. It exists purely to make the skeleton runnable.
    """

    def __init__(self, short_window: int = 3, long_window: int = 8) -> None:
        if short_window < 1 or long_window < 1:
            raise ValueError("windows must be >= 1")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.name = f"demo_ma_{short_window}_{long_window}"

    @staticmethod
    def _moving_average(values: Sequence[float], window: int, end: int) -> float:
        """Average of the ``window`` values ending at index ``end`` (inclusive)."""
        start = end - window + 1
        chunk = values[start : end + 1]
        return sum(chunk) / len(chunk)

    def generate_positions(self, closes: Sequence[float]) -> List[float]:
        positions: List[float] = []
        for i in range(len(closes)):
            # Not enough history yet to compute the long average: stay flat.
            if i + 1 < self.long_window:
                positions.append(0.0)
                continue

            short_ma = self._moving_average(closes, self.short_window, i)
            long_ma = self._moving_average(closes, self.long_window, i)
            positions.append(1.0 if short_ma > long_ma else 0.0)
        return positions
