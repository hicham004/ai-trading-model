"""Defensive invariant checks for the signal-driven backtest.

These guards make the backtest fail CLOSED on malformed or misaligned inputs
instead of silently producing misleading results. They cover the Phase 2B
review findings on signal identity/alignment and basic market-data integrity.

What is validated here (static, before any orders are processed):

* one instrument per simulation;
* timezone-aware, strictly increasing (no duplicate, no out-of-order) candle
  and signal timestamps;
* positive, finite OHLC values and non-negative finite volume;
* coherent OHLC relationships (high is the max, low is the min);
* signal/candle alignment: equal counts, matching instrument and timestamp,
  and matching timeframe wherever that metadata is present.

What is intentionally NOT validated here: *future* and *stale* signals relative
to a decision clock. Those are time-relative and are enforced per entry by the
risk manager (``future_signal`` / ``stale_data``), which receives the distinct
signal-data time and execution time.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Optional, Sequence

from app.strategy.base import MarketCandle, Signal


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def validate_candles(
    candles: Sequence[MarketCandle],
    *,
    expected_instrument: Optional[str] = None,
    expected_timeframe: Optional[str] = None,
) -> None:
    """Validate market-data invariants. Raises ``ValueError`` on any violation."""
    previous_ts: Optional[datetime] = None
    for idx, candle in enumerate(candles):
        if expected_instrument is not None and candle.instrument != expected_instrument:
            raise ValueError(
                f"candle {idx} instrument {candle.instrument!r} does not match "
                f"the simulation instrument {expected_instrument!r}"
            )
        if (
            expected_timeframe
            and candle.timeframe is not None
            and candle.timeframe != expected_timeframe
        ):
            raise ValueError(
                f"candle {idx} timeframe {candle.timeframe!r} does not match "
                f"the requested timeframe {expected_timeframe!r}"
            )

        if not _is_timezone_aware(candle.timestamp):
            raise ValueError(f"candle {idx} timestamp must be timezone-aware (UTC)")
        if previous_ts is not None and not candle.timestamp > previous_ts:
            raise ValueError(
                "candles must be in strictly increasing chronological order "
                "(no duplicate or out-of-order timestamps)"
            )
        previous_ts = candle.timestamp

        for label, value in (
            ("open", candle.open),
            ("high", candle.high),
            ("low", candle.low),
            ("close", candle.close),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(
                    f"candle {idx} {label} must be a positive finite number"
                )
        if not isfinite(candle.volume) or candle.volume < 0:
            raise ValueError(
                f"candle {idx} volume must be a non-negative finite number"
            )

        # Coherent OHLC: high is the period max, low is the period min.
        if candle.high < candle.low:
            raise ValueError(f"candle {idx} has high < low")
        if candle.high < max(candle.open, candle.close):
            raise ValueError(f"candle {idx} high is below open/close")
        if candle.low > min(candle.open, candle.close):
            raise ValueError(f"candle {idx} low is above open/close")


def validate_signals(
    signals: Sequence[Signal],
    candles: Sequence[MarketCandle],
    *,
    expected_instrument: Optional[str] = None,
    expected_timeframe: Optional[str] = None,
) -> None:
    """Validate signal/candle identity and alignment. Raises ``ValueError``."""
    if len(signals) != len(candles):
        raise ValueError(
            f"signal count {len(signals)} does not equal candle count "
            f"{len(candles)}"
        )

    previous_ts: Optional[datetime] = None
    for idx, (signal, candle) in enumerate(zip(signals, candles)):
        if not _is_timezone_aware(signal.timestamp):
            raise ValueError(f"signal {idx} timestamp must be timezone-aware (UTC)")
        if signal.instrument != candle.instrument:
            raise ValueError(
                f"signal {idx} instrument {signal.instrument!r} does not match "
                f"its source candle {candle.instrument!r}"
            )
        if expected_instrument is not None and signal.instrument != expected_instrument:
            raise ValueError(
                f"signal {idx} instrument {signal.instrument!r} does not match "
                f"the simulation instrument {expected_instrument!r}"
            )
        if signal.timestamp != candle.timestamp:
            raise ValueError(
                f"signal {idx} timestamp does not match its source candle "
                "(misaligned signal)"
            )
        if (
            expected_timeframe
            and signal.timeframe is not None
            and signal.timeframe != expected_timeframe
        ):
            raise ValueError(
                f"signal {idx} timeframe {signal.timeframe!r} does not match "
                f"the requested timeframe {expected_timeframe!r}"
            )
        if previous_ts is not None and not signal.timestamp > previous_ts:
            raise ValueError(
                "signals must be in strictly increasing chronological order "
                "(no duplicate or out-of-order timestamps)"
            )
        previous_ts = signal.timestamp
