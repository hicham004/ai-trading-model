"""Integration tests for the signal-driven backtest simulator (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.backtest.models import SimulationConfig
from app.backtest.simulator import run_signal_backtest
from app.broker.base import CostModel
from app.risk.manager import RiskLimits, RiskManager
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy


def make_candles(closes, lows=None) -> List[MarketCandle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i, close in enumerate(closes):
        low = lows[i] if lows else close
        out.append(
            MarketCandle(
                instrument="BTC-USDT",
                timestamp=start + timedelta(hours=i),
                open=close,
                high=max(close, low),
                low=low,
                close=close,
                volume=1.0,
            )
        )
    return out


def make_ohlc_candles(ohlc) -> List[MarketCandle]:
    """Build candles from explicit (open, high, low, close) tuples."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        MarketCandle(
            instrument="BTC-USDT",
            timestamp=start + timedelta(hours=i),
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=1.0,
        )
        for i, (o, h, lo, c) in enumerate(ohlc)
    ]


class AlwaysLong(Strategy):
    """Emit a LONG signal every bar (for exercising the simulator)."""

    def __init__(self, stop_pct=0.5, confidence=1.0):
        self.stop_pct = stop_pct
        self.confidence = confidence
        self.name = "always_long"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp,
                instrument=c.instrument,
                action=SignalAction.LONG,
                confidence=self.confidence,
                reason="always",
                stop_loss=c.close * (1.0 - self.stop_pct),
            )
            for c in candles
        ]


def _all_in_risk() -> RiskManager:
    # Allow a full-equity position so outcomes are easy to reason about.
    return RiskManager(RiskLimits(max_risk_per_trade=0.5, max_position_size=1.0))


def test_rising_market_no_costs_profits_once():
    candles = make_candles([100.0, 100.0, 110.0, 121.0])
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.5), risk_manager=_all_in_risk(), timeframe="1H"
    )

    assert result.metrics.num_trades == 1
    assert result.ending_equity == pytest.approx(12_100.0)
    assert result.metrics.total_return_pct == pytest.approx(21.0)
    assert result.metrics.win_rate_pct == pytest.approx(100.0)
    assert result.is_simulation is True
    assert result.trades[0].exit_reason == "end_of_data"


def _five_pct_stop_risk() -> RiskManager:
    return RiskManager(RiskLimits(max_risk_per_trade=0.05, max_position_size=1.0))


def test_stop_loss_exit_is_recorded():
    # Enter at 100 with a 5% stop (95); a later bar opens AND trades at 90.
    # Because the bar opens below the stop, the stop price (95) was never
    # available, so the conservative fill is the worse open (90), not 95.
    candles = make_candles([100.0, 100.0, 90.0], lows=[100.0, 100.0, 90.0])
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.05), risk_manager=_five_pct_stop_risk()
    )

    assert result.metrics.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.is_win is False
    assert trade.exit_price == pytest.approx(90.0)  # filled at the gap open
    assert result.ending_equity == pytest.approx(9_000.0)


def test_stop_loss_gap_through_fills_at_open_not_stop():
    # Finding 1 regression: entry ~100, stop 95, next bar GAPS to 80 and trades
    # below 95. The exit reference must be 80, NOT the unavailable stop (95).
    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),  # bar 0: source for the entry signal
            (100.0, 100.0, 100.0, 100.0),  # bar 1: entry executes here at 100
            (80.0, 80.0, 78.0, 79.0),      # bar 2: gap down through the 95 stop
        ]
    )
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.05), risk_manager=_five_pct_stop_risk()
    )

    assert result.metrics.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.entry_price == pytest.approx(100.0)
    # Filled at the gap open (80), strictly worse than the stop (95).
    assert trade.exit_price == pytest.approx(80.0)
    assert trade.exit_price < 95.0
    # Gap loss is reflected: ~100 units * (80 - 100) = -2000.
    assert trade.pnl == pytest.approx(-2000.0)
    assert result.ending_equity == pytest.approx(8_000.0)


def test_stop_loss_intrabar_pierce_fills_at_stop():
    # When the bar OPENS above the stop and only later pierces it, the stop is
    # assumed available and used as the reference.
    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.0, 100.0, 100.0),  # entry at 100
            (98.0, 98.0, 90.0, 92.0),      # opens at 98 (>95), dips to 90
        ]
    )
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.05), risk_manager=_five_pct_stop_risk()
    )

    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(95.0)  # filled at the stop
    assert result.ending_equity == pytest.approx(9_500.0)


def test_stop_loss_gap_routes_through_broker_slippage():
    # The conservative gap reference (open=80) must still pass through the
    # broker, so sell slippage applies: 80 * (1 - 0.01) = 79.2.
    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.0, 100.0, 100.0),
            (80.0, 80.0, 78.0, 79.0),
        ]
    )
    result = run_signal_backtest(
        candles,
        AlwaysLong(stop_pct=0.05),
        config=SimulationConfig(costs=CostModel(slippage_rate=0.01)),
        risk_manager=_five_pct_stop_risk(),
    )
    trade = result.trades[0]
    assert trade.exit_price == pytest.approx(79.2)  # gap open routed via broker
    assert trade.slippage_cost > 0.0


def test_stop_loss_triggers_on_same_bar_as_entry():
    # Regression: a position opened at THIS bar's open must be stopped out by
    # the SAME bar's low. Enter at 100; the entry bar trades down to 80 through
    # a 90 stop -> the trade must NOT survive.
    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),  # bar 0: LONG signal -> stop 90
            (100.0, 100.0, 80.0, 85.0),    # bar 1: entry at open 100; low 80
        ]
    )
    risk = RiskManager(RiskLimits(max_risk_per_trade=0.10, max_position_size=1.0))
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.10), risk_manager=risk
    )

    assert result.metrics.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    # Entered and stopped out on the same bar.
    assert trade.entry_time == candles[1].timestamp
    assert trade.exit_time == candles[1].timestamp
    assert trade.entry_price == pytest.approx(100.0)
    assert trade.exit_price == pytest.approx(90.0)  # filled at the stop
    assert result.ending_equity == pytest.approx(9_000.0)


def test_risk_manager_can_reject_all_entries():
    candles = make_candles([100.0, 110.0, 120.0])
    # Confidence below the default floor -> every entry vetoed.
    result = run_signal_backtest(candles, AlwaysLong(confidence=0.4))

    assert result.metrics.num_trades == 0
    assert result.rejected_entries >= 1
    assert result.ending_equity == pytest.approx(10_000.0)


def test_fees_reduce_ending_equity():
    candles = make_candles([100.0, 100.0, 110.0, 121.0])
    no_fee = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.5), risk_manager=_all_in_risk()
    )
    with_fee = run_signal_backtest(
        candles,
        AlwaysLong(stop_pct=0.5),
        config=SimulationConfig(costs=CostModel(fee_rate=0.001, slippage_rate=0.0005)),
        risk_manager=_all_in_risk(),
    )
    assert with_fee.metrics.total_fees_paid > 0.0
    assert with_fee.metrics.total_slippage_cost > 0.0
    assert with_fee.ending_equity < no_fee.ending_equity


def test_funding_placeholder_charges_while_held():
    candles = make_candles([100.0, 100.0, 100.0, 100.0])
    flat_market = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.5), risk_manager=_all_in_risk()
    )
    with_funding = run_signal_backtest(
        candles,
        AlwaysLong(stop_pct=0.5),
        config=SimulationConfig(costs=CostModel(funding_rate=0.001)),
        risk_manager=_all_in_risk(),
    )
    # Funding is charged on each bar the position is held.
    assert flat_market.metrics.total_funding_cost == 0.0
    assert with_funding.metrics.total_funding_cost > 0.0
    assert with_funding.ending_equity < flat_market.ending_equity


def test_short_input_returns_empty_result():
    result = run_signal_backtest(make_candles([100.0]), AlwaysLong())
    assert result.metrics.num_trades == 0
    assert result.bars == 1
    assert len(result.equity_curve) == 1


def test_simulator_rejects_misaligned_strategy():
    class BadStrategy(Strategy):
        name = "bad"

        def generate_signals(self, candles):
            return []  # wrong length on purpose

    with pytest.raises(ValueError):
        run_signal_backtest(make_candles([100.0, 101.0]), BadStrategy())


def test_stale_signal_wiring_rejects_entries():
    # Finding 2 regression: the staleness gate must see the SIGNAL's data time
    # (the previous bar), not the execution bar. With hourly candles, every
    # signal is one hour old at execution, so a one-minute staleness limit must
    # reject every entry. (On the old wiring data_time == now, staleness == 0,
    # and these entries would wrongly be allowed.)
    candles = make_candles([100.0, 101.0, 102.0, 103.0])
    risk = RiskManager(
        RiskLimits(
            max_risk_per_trade=0.5,
            max_position_size=1.0,
            max_data_staleness=timedelta(minutes=1),
        )
    )
    result = run_signal_backtest(candles, AlwaysLong(stop_pct=0.5), risk_manager=risk)

    assert result.metrics.num_trades == 0
    assert result.rejected_entries >= 1
    assert result.ending_equity == pytest.approx(10_000.0)


def test_entry_executes_at_next_bar_open_not_close():
    # Finding 2 regression: a bar-0 LONG signal must execute at bar-1 OPEN, not
    # bar-1 close. bar 1 opens at 120 and closes at 90.
    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),  # bar 0: source of the LONG signal
            (120.0, 125.0, 85.0, 90.0),    # bar 1: open 120, close 90
        ]
    )
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.5), risk_manager=_all_in_risk()
    )

    assert result.metrics.num_trades == 1
    trade = result.trades[0]
    # Entered at the bar-1 OPEN (120), NOT the bar-1 close (90).
    assert trade.entry_price == pytest.approx(120.0)
    assert abs(trade.entry_price - 120.0) < abs(trade.entry_price - 90.0)
    # Position is liquidated at end-of-data on the final bar's close (90).
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_price == pytest.approx(90.0)


def test_flat_signal_exits_at_next_bar_open():
    # Finding 2 regression: a FLAT signal exits at the NEXT bar's open.
    class EnterThenExit(Strategy):
        name = "enter_then_exit"

        def generate_signals(self, candles):
            out = []
            for idx, c in enumerate(candles):
                if idx == 0:
                    action, stop = SignalAction.LONG, c.close * 0.5
                elif idx == 1:
                    action, stop = SignalAction.FLAT, None
                else:
                    action, stop = SignalAction.HOLD, None
                out.append(
                    Signal(
                        timestamp=c.timestamp,
                        instrument=c.instrument,
                        action=action,
                        confidence=1.0 if action == SignalAction.LONG else 0.0,
                        stop_loss=stop,
                    )
                )
            return out

    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),  # bar 0: LONG signal
            (100.0, 100.0, 100.0, 100.0),  # bar 1: entry at open 100; FLAT signal
            (130.0, 140.0, 120.0, 135.0),  # bar 2: FLAT executes at open 130
        ]
    )
    result = run_signal_backtest(candles, EnterThenExit(), risk_manager=_all_in_risk())

    assert result.metrics.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "signal"
    # Exited at the bar-2 OPEN (130), NOT the bar-2 close (135).
    assert trade.exit_price == pytest.approx(130.0)


def test_no_same_bar_reentry_after_stop():
    # Finding 2 regression: when a stop exits on a bar, no new entry is taken on
    # that same bar; re-entry happens on the FOLLOWING bar.
    candles = make_ohlc_candles(
        [
            (100.0, 100.0, 100.0, 100.0),  # bar 0: LONG signal
            (100.0, 100.0, 100.0, 100.0),  # bar 1: entry at 100, stop 95
            (96.0, 100.0, 90.0, 98.0),     # bar 2: low 90 -> stop hit; no re-entry
            (98.0, 100.0, 97.0, 99.0),     # bar 3: re-entry here at open 98
        ]
    )
    # Relax the daily-loss limit so the post-stop loss does not also trip the
    # kill-switch; this test isolates the same-bar re-entry rule.
    risk = RiskManager(
        RiskLimits(
            max_risk_per_trade=0.05, max_position_size=1.0, max_daily_loss=1.0
        )
    )
    result = run_signal_backtest(
        candles, AlwaysLong(stop_pct=0.05), risk_manager=risk
    )

    assert result.metrics.num_trades == 2
    first, second = result.trades
    assert first.exit_reason == "stop_loss"
    assert first.exit_time == candles[2].timestamp
    # Re-entry occurs on bar 3, NOT on the stop bar (bar 2).
    assert second.entry_time == candles[3].timestamp


def test_no_look_ahead_last_bar_signal_is_not_executed():
    # A LONG only on the FINAL bar must never trade: the simulator acts on the
    # previous bar's signal, so a last-bar signal has no execution bar.
    class LastBarLong(Strategy):
        name = "last_bar_long"

        def generate_signals(self, candles):
            signals = []
            for idx, c in enumerate(candles):
                if idx == len(candles) - 1:
                    signals.append(
                        Signal(
                            timestamp=c.timestamp,
                            instrument=c.instrument,
                            action=SignalAction.LONG,
                            confidence=1.0,
                            reason="last bar only",
                            stop_loss=c.close * 0.5,
                        )
                    )
                else:
                    signals.append(
                        Signal(
                            timestamp=c.timestamp,
                            instrument=c.instrument,
                            action=SignalAction.FLAT,
                        )
                    )
            return signals

    result = run_signal_backtest(
        make_candles([100.0, 101.0, 102.0]), LastBarLong(), risk_manager=_all_in_risk()
    )
    assert result.metrics.num_trades == 0
    assert result.ending_equity == pytest.approx(10_000.0)
