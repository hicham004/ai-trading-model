"""Tests for timeframe-aware signal staleness (offline).

Covers Codex issue 3: the fixed two-hour staleness wrongly rejected valid
previous-bar signals on 4H / 1D candles. Staleness is now derived from the
timeframe (or an explicit override).
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from app.backtest.simulator import run_signal_backtest
from app.risk.manager import RiskLimits, RiskManager
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy
from app.strategy.timeframes import parse_timeframe, resolve_max_signal_age

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --- parse_timeframe -------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("1m", timedelta(minutes=1)),
        ("15m", timedelta(minutes=15)),
        ("30m", timedelta(minutes=30)),
        ("1H", timedelta(hours=1)),
        ("4H", timedelta(hours=4)),
        ("1D", timedelta(days=1)),
        ("1W", timedelta(weeks=1)),
    ],
)
def test_parse_timeframe_valid(text, expected):
    assert parse_timeframe(text) == expected


@pytest.mark.parametrize("text", ["", "1", "H", "1M", "1.5H", "abc", "H1", "0H", "-1H", "1h"])
def test_parse_timeframe_rejects_unknown(text):
    with pytest.raises(ValueError):
        parse_timeframe(text)


# --- resolve_max_signal_age ------------------------------------------------

def test_resolve_uses_override_when_given():
    assert resolve_max_signal_age("1H", 60.0) == timedelta(seconds=60)


def test_resolve_derives_from_timeframe_when_no_override():
    assert resolve_max_signal_age("4H", None) == timedelta(hours=4)
    assert resolve_max_signal_age("1D", None) == timedelta(days=1)


@pytest.mark.parametrize("bad", [0.0, -5.0, float("inf"), float("nan")])
def test_resolve_rejects_invalid_override(bad):
    with pytest.raises(ValueError):
        resolve_max_signal_age("1H", bad)


def test_resolve_rejects_unknown_timeframe_without_override():
    with pytest.raises(ValueError):
        resolve_max_signal_age("1M", None)


@pytest.mark.parametrize("bad_tf", ["1Q", "1M", "abc", "H1"])
def test_resolve_validates_timeframe_even_with_override(bad_tf):
    # Regression: an invalid timeframe must NOT be accepted just because an
    # explicit override is supplied.
    with pytest.raises(ValueError):
        resolve_max_signal_age(bad_tf, 60.0)


# --- simulator wiring at different timeframes ------------------------------

class _AlwaysLong(Strategy):
    name = "always_long"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp,
                instrument=c.instrument,
                action=SignalAction.LONG,
                confidence=1.0,
                stop_loss=c.close * 0.5,
            )
            for c in candles
        ]


def _candles(interval: timedelta, n: int = 4) -> List[MarketCandle]:
    return [
        MarketCandle(
            instrument="BTC-USDT",
            timestamp=START + interval * i,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=1.0,
        )
        for i in range(n)
    ]


def _risk(max_age: timedelta) -> RiskManager:
    return RiskManager(
        RiskLimits(
            max_risk_per_trade=0.5,
            max_position_size=1.0,
            max_data_staleness=max_age,
        )
    )


def test_1h_previous_bar_signal_works_with_normal_default():
    # Default RiskLimits staleness (2h) already accepts 1H previous-bar signals.
    result = run_signal_backtest(
        _candles(timedelta(hours=1)),
        _AlwaysLong(),
        risk_manager=RiskManager(RiskLimits(max_risk_per_trade=0.5, max_position_size=1.0)),
    )
    assert result.metrics.num_trades >= 1
    assert result.rejected_entries == 0


def test_4h_previous_bar_signal_works_with_derived_default():
    max_age = resolve_max_signal_age("4H", None)
    result = run_signal_backtest(
        _candles(timedelta(hours=4)), _AlwaysLong(), risk_manager=_risk(max_age)
    )
    assert result.metrics.num_trades >= 1
    assert result.rejected_entries == 0


def test_1d_previous_bar_signal_works_with_derived_default():
    max_age = resolve_max_signal_age("1D", None)
    result = run_signal_backtest(
        _candles(timedelta(days=1)), _AlwaysLong(), risk_manager=_risk(max_age)
    )
    assert result.metrics.num_trades >= 1
    assert result.rejected_entries == 0


def test_explicit_one_minute_limit_rejects_one_hour_old_signal():
    # The override must still be able to reject a stale (1h-old) signal.
    max_age = resolve_max_signal_age("1H", 60.0)  # one minute
    result = run_signal_backtest(
        _candles(timedelta(hours=1)), _AlwaysLong(), risk_manager=_risk(max_age)
    )
    assert result.metrics.num_trades == 0
    assert result.rejected_entries >= 1


# --- CLI wiring ------------------------------------------------------------

def _load_cli_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_strategy_backtest.py"
    spec = importlib.util.spec_from_file_location("run_strategy_backtest_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_accepts_and_resolves_signal_age_override():
    cli = _load_cli_module()
    args = cli.parse_args(["--timeframe", "4H", "--max-signal-age-seconds", "60"])
    assert args.max_signal_age_seconds == 60.0
    # This mirrors exactly what main() feeds into RiskLimits.
    max_age = resolve_max_signal_age(args.timeframe, args.max_signal_age_seconds)
    assert max_age == timedelta(seconds=60)
    limits = RiskLimits(max_data_staleness=max_age)
    assert limits.max_data_staleness == timedelta(seconds=60)


def test_cli_default_signal_age_is_derived_from_timeframe():
    cli = _load_cli_module()
    args = cli.parse_args(["--timeframe", "1D"])
    assert args.max_signal_age_seconds is None
    assert resolve_max_signal_age(args.timeframe, args.max_signal_age_seconds) == timedelta(days=1)
