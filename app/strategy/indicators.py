"""Pure technical-indicator helpers.

Every function takes a sequence of numbers and returns a list of the SAME
length, using ``None`` for the leading bars where there is not yet enough data
("warm-up"). Keeping these as small, side-effect-free functions makes them
easy to read and easy to test.

These are standard descriptive indicators. They are NOT predictive and imply
no profitability.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def simple_moving_average(values: Sequence[float], window: int) -> List[Optional[float]]:
    """Simple moving average over ``window`` bars."""
    if window < 1:
        raise ValueError("window must be >= 1")

    out: List[Optional[float]] = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def rsi(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index using Wilder's smoothing.

    Returns values in the range 0-100. The first ``period`` bars are ``None``.
    """
    if period < 1:
        raise ValueError("period must be >= 1")

    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out

    # Seed averages from the first ``period`` price changes.
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period

    def to_rsi(avg_g: float, avg_l: float) -> float:
        if avg_l == 0.0:
            return 100.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = to_rsi(avg_gain, avg_loss)

    # Smooth the rest with Wilder's exponential averaging.
    for i in range(period + 1, n):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


def rolling_vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    window: int,
) -> List[Optional[float]]:
    """Volume-weighted average price of the typical price over ``window`` bars.

    Typical price = (high + low + close) / 3. Bars before the window fills, or
    where total volume is zero, are ``None``.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    n = len(closes)
    if not (len(highs) == len(lows) == len(volumes) == n):
        raise ValueError("highs, lows, closes and volumes must be the same length")

    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    out: List[Optional[float]] = [None] * n
    pv_sum = 0.0  # sum of price * volume
    vol_sum = 0.0
    for i in range(n):
        pv_sum += typical[i] * volumes[i]
        vol_sum += volumes[i]
        if i >= window:
            pv_sum -= typical[i - window] * volumes[i - window]
            vol_sum -= volumes[i - window]
        if i >= window - 1 and vol_sum > 0:
            out[i] = pv_sum / vol_sum
    return out


def rolling_max(values: Sequence[float], window: int) -> List[Optional[float]]:
    """Highest value over the trailing ``window`` bars (inclusive)."""
    return _rolling_extreme(values, window, want_max=True)


def rolling_min(values: Sequence[float], window: int) -> List[Optional[float]]:
    """Lowest value over the trailing ``window`` bars (inclusive)."""
    return _rolling_extreme(values, window, want_max=False)


def _rolling_extreme(
    values: Sequence[float], window: int, want_max: bool
) -> List[Optional[float]]:
    if window < 1:
        raise ValueError("window must be >= 1")
    out: List[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        if i >= window - 1:
            chunk = values[i - window + 1 : i + 1]
            out[i] = max(chunk) if want_max else min(chunk)
    return out
