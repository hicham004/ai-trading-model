"""Parse OKX-style timeframe strings into durations.

This is used to derive an appropriate *signal staleness* limit for a backtest,
so that exactly one immediately-previous completed candle counts as fresh. A
fixed two-hour limit is wrong for 4H or 1D candles (it would reject every valid
previous-bar signal), so the limit must scale with the timeframe.

Only the timeframe formats this project documents/uses are supported:

    minutes -> "m"  (e.g. 1m, 5m, 15m, 30m)
    hours   -> "H"  (e.g. 1H, 4H)
    days    -> "D"  (e.g. 1D)
    weeks   -> "W"  (e.g. 1W)

Anything else (unknown unit, non-integer count, month "M", empty) is rejected
with a clear error rather than silently assuming an unsafe value (fail-closed).
"""

from __future__ import annotations

from datetime import timedelta
from math import isfinite
from typing import Optional

# OKX bar units used by this project. Lowercase ``m`` is minutes; uppercase
# ``H``/``D``/``W`` are hours/days/weeks (matching OKX's casing). Month ("M")
# is intentionally unsupported to avoid the m/M ambiguity and because this
# project does not use it.
_UNIT_TO_SECONDS = {"m": 60, "H": 3_600, "D": 86_400, "W": 604_800}

_SUPPORTED_EXAMPLES = "1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W"


def parse_timeframe(timeframe: str) -> timedelta:
    """Convert an OKX-style timeframe string into a :class:`timedelta`.

    Raises:
        ValueError: if the timeframe is empty, malformed, or uses an
            unsupported unit.
    """
    raw = (timeframe or "").strip()
    if len(raw) < 2:
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}. Supported examples: "
            f"{_SUPPORTED_EXAMPLES}."
        )

    number_part, unit = raw[:-1], raw[-1]
    if unit not in _UNIT_TO_SECONDS or not number_part.isdigit():
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}. Supported examples: "
            f"{_SUPPORTED_EXAMPLES}."
        )

    count = int(number_part)
    if count <= 0:
        raise ValueError(f"Timeframe {timeframe!r} must be a positive multiple.")
    return timedelta(seconds=count * _UNIT_TO_SECONDS[unit])


def resolve_max_signal_age(
    timeframe: str, override_seconds: Optional[float] = None
) -> timedelta:
    """Resolve the maximum allowed signal age for a backtest.

    The ``timeframe`` is ALWAYS validated when present, even if an override is
    supplied, so an unsupported timeframe (e.g. ``"1Q"``) is never silently
    accepted just because ``--max-signal-age-seconds`` was passed. If
    ``override_seconds`` is given it then wins (and must be a positive finite
    number). Otherwise the limit is derived from the timeframe as exactly one
    bar interval, so the immediately-previous completed candle is fresh while a
    signal two or more bars old is rejected.

    Raises:
        ValueError: on an unsupported timeframe, an invalid override, or when
            neither a timeframe nor an override is provided.
    """
    # Validate the timeframe up front so it cannot be bypassed by an override.
    derived = parse_timeframe(timeframe) if timeframe else None

    if override_seconds is not None:
        if not isfinite(override_seconds) or override_seconds <= 0:
            raise ValueError(
                "max signal age (seconds) must be a positive finite number"
            )
        return timedelta(seconds=override_seconds)

    if derived is None:
        raise ValueError(
            "a timeframe is required to derive the maximum signal age"
        )
    return derived
