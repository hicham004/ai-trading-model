"""Core types for the strategy engine: market candles, signals, and the base.

The whole engine is built around three small ideas:

* :class:`MarketCandle` - one OHLCV bar of PUBLIC market data.
* :class:`Signal` - a strategy's recommendation for a single bar.
* :class:`Strategy` - the interface every strategy implements.

A strategy turns a list of candles into a list of signals of the same length,
using only information available up to and including each bar (no look-ahead).
The backtest simulator then acts on ``signals[i-1]`` when processing bar ``i``,
so a signal can never "see" the bar it is executed on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import List, Optional, Sequence


class SignalAction(str, Enum):
    """What a strategy recommends for a bar.

    * ``LONG`` - be in the market (enter if currently flat).
    * ``FLAT`` - be out of the market (exit if currently long).
    * ``HOLD`` - make no change; keep whatever position is currently open.

    Short selling is intentionally NOT supported in this research phase
    (it implies borrowing/leverage, which is out of scope).
    """

    LONG = "long"
    FLAT = "flat"
    HOLD = "hold"


@dataclass(frozen=True)
class MarketCandle:
    """One OHLCV candle of public market data (timestamp in UTC).

    ``timeframe`` is optional metadata (e.g. ``"1H"``). It defaults to ``None``
    for backward compatibility; the database-backed runner populates it so the
    simulator can validate that a run uses a single, expected timeframe.
    """

    instrument: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: Optional[str] = None


@dataclass(frozen=True)
class Signal:
    """A strategy's recommendation for one bar.

    Attributes:
        timestamp: the bar this signal belongs to (UTC).
        instrument: e.g. ``"BTC-USDT"``.
        action: :class:`SignalAction`.
        confidence: 0.0-1.0. The risk manager rejects entries below a floor.
        reason: short human-readable explanation (great for logs/audits).
        stop_loss: required price for LONG entries. The risk manager refuses
            to open a position without a valid stop-loss below the entry price.
        timeframe: optional metadata (e.g. ``"1H"``) identifying the source
            candle's timeframe. Defaults to ``None`` for backward compatibility;
            it is stamped from the source candle by :meth:`Strategy._validate_output`.

    Note: ``timestamp`` is the source-candle (data) time. The simulator treats
    it as the signal's data time, distinct from the later execution time, when
    enforcing staleness.
    """

    timestamp: datetime
    instrument: str
    action: SignalAction
    confidence: float = 0.0
    reason: str = ""
    stop_loss: Optional[float] = None
    timeframe: Optional[str] = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise ValueError("stop_loss must be a positive price when provided")


class Strategy(ABC):
    """Base class for every strategy.

    Subclasses set ``name`` and implement :meth:`generate_signals`. The method
    must return exactly one :class:`Signal` per input candle, in order.
    """

    name: str = "unnamed"

    @abstractmethod
    def generate_signals(self, candles: Sequence[MarketCandle]) -> List[Signal]:
        """Return one signal per candle (no look-ahead)."""
        raise NotImplementedError

    # -- helpers shared by concrete strategies ------------------------------

    @staticmethod
    def _flat(candle: MarketCandle, reason: str = "warmup") -> Signal:
        """A neutral FLAT signal (used during indicator warm-up)."""
        return Signal(
            timestamp=candle.timestamp,
            instrument=candle.instrument,
            action=SignalAction.FLAT,
            confidence=0.0,
            reason=reason,
        )

    def _validate_output(
        self, candles: Sequence[MarketCandle], signals: List[Signal]
    ) -> List[Signal]:
        """Guard against a misaligned signal list and stamp timeframe metadata.

        Every concrete strategy returns through here, so this is the single
        place that propagates each source candle's ``timeframe`` onto its
        signal. It only fills the value in when the candle carries one and the
        signal does not already specify it, keeping things backward compatible.
        """
        if len(signals) != len(candles):
            raise ValueError(
                f"{self.name}: produced {len(signals)} signals for "
                f"{len(candles)} candles (must match)"
            )
        stamped: List[Signal] = []
        for candle, signal in zip(candles, signals):
            if signal.timeframe is None and candle.timeframe is not None:
                signal = replace(signal, timeframe=candle.timeframe)
            stamped.append(signal)
        return stamped
