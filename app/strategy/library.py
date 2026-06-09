"""Baseline research strategies.

Three classic, well-documented strategies, implemented as teaching/research
examples. They are deliberately simple, are NOT predictive, and make NO claim
of profitability. Each one:

* uses only past/current data (no look-ahead),
* emits LONG / FLAT / HOLD signals with a confidence in 0-1,
* attaches a required stop-loss price to every LONG entry.

None of them use martingale, doubling-down, or loss-chasing logic; position
sizing is decided later by the risk manager, not by the strategy.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from app.strategy import indicators
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class MovingAverageCrossover(Strategy):
    """Go LONG when a short SMA is above a long SMA, otherwise stay FLAT.

    Confidence grows with the relative gap between the two averages.
    """

    def __init__(
        self,
        short_window: int = 10,
        long_window: int = 30,
        stop_loss_pct: float = 0.02,
    ) -> None:
        if short_window < 1 or long_window < 1:
            raise ValueError("windows must be >= 1")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        if not 0.0 < stop_loss_pct < 1.0:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        self.short_window = short_window
        self.long_window = long_window
        self.stop_loss_pct = stop_loss_pct
        self.name = f"ma_crossover_{short_window}_{long_window}"

    def generate_signals(self, candles: Sequence[MarketCandle]) -> List[Signal]:
        closes = [c.close for c in candles]
        short = indicators.simple_moving_average(closes, self.short_window)
        long = indicators.simple_moving_average(closes, self.long_window)

        signals: List[Signal] = []
        for i, candle in enumerate(candles):
            s, l = short[i], long[i]
            if s is None or l is None or l <= 0:
                signals.append(self._flat(candle))
                continue

            if s > l:
                gap = (s - l) / l
                confidence = _clamp(0.55 + gap * 10.0, 0.55, 1.0)
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.LONG,
                        confidence=confidence,
                        reason=f"short MA {s:.2f} > long MA {l:.2f}",
                        stop_loss=candle.close * (1.0 - self.stop_loss_pct),
                    )
                )
            else:
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.FLAT,
                        confidence=0.0,
                        reason=f"short MA {s:.2f} <= long MA {l:.2f}",
                    )
                )
        return self._validate_output(candles, signals)


class RsiVwapMeanReversion(Strategy):
    """Mean-reversion: buy when oversold and stretched below VWAP.

    * Enter LONG when RSI < ``oversold`` AND price is below the rolling VWAP
      (the market looks stretched to the downside).
    * Exit to FLAT when RSI recovers above ``exit_level`` OR price climbs back
      above VWAP.
    * Otherwise HOLD the current position.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        vwap_window: int = 20,
        oversold: float = 30.0,
        exit_level: float = 50.0,
        stop_loss_pct: float = 0.03,
    ) -> None:
        if not 0.0 < oversold < exit_level < 100.0:
            raise ValueError("require 0 < oversold < exit_level < 100")
        if not 0.0 < stop_loss_pct < 1.0:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        self.rsi_period = rsi_period
        self.vwap_window = vwap_window
        self.oversold = oversold
        self.exit_level = exit_level
        self.stop_loss_pct = stop_loss_pct
        self.name = f"rsi_vwap_meanrev_{rsi_period}_{vwap_window}"

    def generate_signals(self, candles: Sequence[MarketCandle]) -> List[Signal]:
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]

        rsi_values = indicators.rsi(closes, self.rsi_period)
        vwap_values = indicators.rolling_vwap(
            highs, lows, closes, volumes, self.vwap_window
        )

        signals: List[Signal] = []
        for i, candle in enumerate(candles):
            r: Optional[float] = rsi_values[i]
            v: Optional[float] = vwap_values[i]
            if r is None or v is None:
                signals.append(self._flat(candle))
                continue

            if r < self.oversold and candle.close < v:
                # How far below the oversold line we are -> confidence.
                confidence = _clamp(0.55 + (self.oversold - r) / self.oversold, 0.55, 1.0)
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.LONG,
                        confidence=confidence,
                        reason=f"RSI {r:.1f} < {self.oversold} and price < VWAP {v:.2f}",
                        stop_loss=candle.close * (1.0 - self.stop_loss_pct),
                    )
                )
            elif r > self.exit_level or candle.close > v:
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.FLAT,
                        confidence=0.0,
                        reason=f"RSI {r:.1f} or price recovered above VWAP {v:.2f}",
                    )
                )
            else:
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.HOLD,
                        confidence=0.0,
                        reason="between entry and exit thresholds",
                    )
                )
        return self._validate_output(candles, signals)


class Breakout(Strategy):
    """Channel breakout.

    * Enter LONG when the close breaks ABOVE the highest high of the prior
      ``entry_window`` bars.
    * Exit to FLAT when the close breaks BELOW the lowest low of the prior
      ``exit_window`` bars.
    * Otherwise HOLD.
    """

    def __init__(
        self,
        entry_window: int = 20,
        exit_window: int = 10,
        stop_loss_pct: float = 0.04,
    ) -> None:
        if entry_window < 1 or exit_window < 1:
            raise ValueError("windows must be >= 1")
        if not 0.0 < stop_loss_pct < 1.0:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.stop_loss_pct = stop_loss_pct
        self.name = f"breakout_{entry_window}_{exit_window}"

    def generate_signals(self, candles: Sequence[MarketCandle]) -> List[Signal]:
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # Highest high / lowest low of the PRIOR bars (exclude the current bar
        # so a break is measured against history, not itself).
        prior_high = indicators.rolling_max(highs, self.entry_window)
        prior_low = indicators.rolling_min(lows, self.exit_window)

        signals: List[Signal] = []
        for i, candle in enumerate(candles):
            hi = prior_high[i - 1] if i >= 1 else None
            lo = prior_low[i - 1] if i >= 1 else None

            if hi is not None and candle.close > hi:
                breakout_size = (candle.close - hi) / hi if hi > 0 else 0.0
                confidence = _clamp(0.55 + breakout_size * 20.0, 0.55, 1.0)
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.LONG,
                        confidence=confidence,
                        reason=f"close {candle.close:.2f} broke above prior high {hi:.2f}",
                        stop_loss=candle.close * (1.0 - self.stop_loss_pct),
                    )
                )
            elif lo is not None and candle.close < lo:
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.FLAT,
                        confidence=0.0,
                        reason=f"close {candle.close:.2f} broke below prior low {lo:.2f}",
                    )
                )
            else:
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.HOLD,
                        confidence=0.0,
                        reason="inside the breakout channel",
                    )
                )
        return self._validate_output(candles, signals)
