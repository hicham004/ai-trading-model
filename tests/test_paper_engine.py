"""Offline normal and adversarial tests for the Phase 4 paper engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.broker.base import Broker, Fill, Order
from app.paper.account import AccountError, PaperAccount
from app.paper.engine import PaperEngineConfig, PaperTradingEngine
from app.paper.execution import FeedStatus, QuoteSnapshot
from app.paper.risk import PaperRiskContext, PaperRiskLimits, PaperRiskManager
from app.risk.manager import RiskLimits
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
HEALTHY = FeedStatus(connected=True, stale=False)


class AlwaysLong(Strategy):
    name = "always_long"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp,
                instrument=c.instrument,
                timeframe=c.timeframe,
                action=SignalAction.LONG,
                confidence=1.0,
                reason="test entry",
                stop_loss=c.close * 0.9,
            )
            for c in candles
        ]


class AlwaysLongTightStop(Strategy):
    name = "always_long_tight_stop"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp,
                instrument=c.instrument,
                timeframe=c.timeframe,
                action=SignalAction.LONG,
                confidence=1.0,
                reason="cost-aware risk test",
                stop_loss=90.0,
            )
            for c in candles
        ]


class MisalignedStrategy(Strategy):
    name = "misaligned"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp + timedelta(minutes=1),
                instrument=c.instrument,
                timeframe=c.timeframe,
                action=SignalAction.LONG,
                confidence=1.0,
                stop_loss=c.close * 0.9,
            )
            for c in candles
        ]


class LyingBroker(Broker):
    is_simulation = True

    def submit(self, order: Order) -> Fill:
        return Fill(
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=order.reference_price,
            fee=0.0,
            slippage_cost=0.0,
            timestamp=order.timestamp,
            is_simulated=False,
        )


def candle(
    minute: int = 0,
    *,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 100.0,
) -> MarketCandle:
    return MarketCandle(
        instrument="BTC-USDT",
        timeframe="1m",
        timestamp=START + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=10.0,
    )


def quote(minute: int = 0, *, bid: float = 99.0, ask: float = 101.0) -> QuoteSnapshot:
    return QuoteSnapshot(
        instrument="BTC-USDT",
        bid=bid,
        ask=ask,
        timestamp=START + timedelta(minutes=minute, seconds=61),
        synchronized=True,
    )


def engine(strategy: Strategy | None = None, *, broker: Broker | None = None):
    return PaperTradingEngine(
        config=PaperEngineConfig(
            instruments=("BTC-USDT",),
            timeframe="1m",
            fee_rate=0.001,
            slippage_rate=0.01,
        ),
        strategy=strategy or AlwaysLong(),
        risk_manager=PaperRiskManager(),
        account=PaperAccount(starting_cash=10_000.0),
        broker=broker,
    )


def process(target: PaperTradingEngine, bar: MarketCandle, q: QuoteSnapshot | None):
    return target.process_confirmed_candle(
        bar,
        quote=q,
        feed_status=HEALTHY,
        now=bar.timestamp + timedelta(minutes=1, seconds=2),
    )


def test_entry_crosses_ask_then_applies_adverse_slippage_and_fee():
    target = engine()
    outcome = process(target, candle(), quote())

    assert outcome.accepted is True
    assert len(outcome.orders) == len(outcome.fills) == 1
    assert outcome.orders[0].reference_price == 101.0
    assert outcome.fills[0].price == pytest.approx(102.01)
    assert outcome.fills[0].is_simulated is True
    assert outcome.account is not None
    assert outcome.account.cash >= 0
    assert outcome.account.has_position("BTC-USDT")


def test_engine_does_not_mutate_until_commit_and_rejects_duplicate_after_commit():
    target = engine()
    bar = candle()
    outcome = process(target, bar, quote())

    assert target.account.open_position_count == 0
    target.commit(bar, outcome)
    assert target.account.open_position_count == 1
    assert process(target, bar, quote()).rejection_reason == "duplicate_candle"


def test_gap_stale_future_and_wrong_timeframe_candles_fail_closed():
    target = engine()
    first = candle()
    outcome = process(target, first, quote())
    target.commit(first, outcome)

    gap = candle(2)
    assert process(target, gap, quote(2)).rejection_reason == "candle_gap"

    stale_target = engine()
    stale = stale_target.process_confirmed_candle(
        candle(),
        quote=quote(),
        feed_status=HEALTHY,
        now=START + timedelta(minutes=10),
    )
    assert stale.rejection_reason == "stale_candle"

    future_target = engine()
    future = future_target.process_confirmed_candle(
        candle(),
        quote=quote(),
        feed_status=HEALTHY,
        now=START,
    )
    assert future.rejection_reason == "future_candle"

    wrong = candle()
    wrong = MarketCandle(**{**vars(wrong), "timeframe": "5m"})
    assert process(engine(), wrong, quote()).rejection_reason == "wrong_timeframe"


def test_quote_from_before_candle_close_cannot_price_entry():
    target = engine()
    early_quote = QuoteSnapshot(
        instrument="BTC-USDT",
        bid=99.0,
        ask=101.0,
        timestamp=START + timedelta(seconds=30),
        synchronized=True,
    )
    outcome = process(target, candle(), early_quote)

    assert outcome.fills == []
    assert outcome.risk_decisions[0].reason == "quote_before_signal"


@pytest.mark.parametrize(
    ("feed", "synchronized", "reason"),
    [
        (FeedStatus(False, False), True, "feed_disconnected"),
        (FeedStatus(True, True), True, "feed_stale"),
        (HEALTHY, False, "order_book_unsynchronized"),
    ],
)
def test_feed_and_book_failures_veto_entries(feed, synchronized, reason):
    q = QuoteSnapshot(
        instrument="BTC-USDT",
        bid=99,
        ask=101,
        timestamp=START + timedelta(seconds=61),
        synchronized=synchronized,
    )
    outcome = engine().process_confirmed_candle(
        candle(), quote=q, feed_status=feed, now=START + timedelta(seconds=62)
    )
    assert outcome.fills == []
    assert outcome.risk_decisions[0].reason == reason


def test_invalid_strategy_output_is_journaled_but_never_acted_on():
    outcome = process(engine(MisalignedStrategy()), candle(), quote())

    assert outcome.accepted is True
    assert outcome.signal is None
    assert outcome.orders == []
    assert outcome.events[0].event_type == "strategy_output_invalid"


def test_gap_through_stop_uses_worse_open_and_does_not_reenter_same_candle():
    target = engine()
    first = candle()
    opened = process(target, first, quote())
    target.commit(first, opened)
    position = target.account.positions["BTC-USDT"]

    gap_bar = candle(1, open_=80.0, high=85.0, low=75.0, close=82.0)
    stopped = process(target, gap_bar, quote(1, bid=81.0, ask=83.0))

    assert len(stopped.fills) == 1
    assert stopped.orders[0].intent == "stop_exit"
    assert stopped.orders[0].reference_price == 80.0
    assert stopped.fills[0].price == pytest.approx(79.2)
    assert stopped.trades[0].entry_price == position.entry_price
    assert stopped.account is not None
    assert stopped.account.open_position_count == 0


def test_modeled_stop_loss_including_costs_stays_within_risk_limit():
    risk = PaperRiskManager(
        PaperRiskLimits(
            base=RiskLimits(
                max_risk_per_trade=0.01,
                max_position_size=1.0,
                max_data_staleness=timedelta(minutes=3),
            ),
            max_total_exposure=1.0,
        )
    )
    target = PaperTradingEngine(
        config=PaperEngineConfig(
            instruments=("BTC-USDT",),
            timeframe="1m",
            fee_rate=0.001,
            slippage_rate=0.01,
        ),
        strategy=AlwaysLongTightStop(),
        risk_manager=risk,
        account=PaperAccount(starting_cash=10_000),
    )
    first = candle()
    opened = process(target, first, quote())
    target.commit(first, opened)

    stop_bar = candle(1, open_=100, high=101, low=89, close=95)
    stopped = process(target, stop_bar, quote(1))

    assert len(stopped.trades) == 1
    assert -stopped.trades[0].realized_pnl <= 100 + 1e-6


def test_kill_switch_blocks_entry():
    target = engine()
    target.set_kill_switch(True)
    outcome = process(target, candle(), quote())
    assert outcome.fills == []
    assert outcome.risk_decisions[0].reason == "kill_switch_engaged"


def test_portfolio_exposure_and_open_position_caps_veto_entries():
    signal = AlwaysLong().generate_signals([candle()])[0]
    manager = PaperRiskManager(
        PaperRiskLimits(
            base=RiskLimits(max_data_staleness=timedelta(minutes=3)),
            max_total_exposure=0.5,
            max_open_positions=1,
        )
    )
    base = dict(
        signal=signal,
        equity=1_000,
        cash=500,
        reference_price=101,
        has_position_in_instrument=False,
        day_start_equity=1_000,
        day_realized_pnl=0,
        now=START + timedelta(seconds=62),
        data_time=START + timedelta(seconds=60),
        quote=quote(),
        feed_status=HEALTHY,
        kill_switch_engaged=False,
    )
    open_cap = PaperRiskContext(
        current_position_value=100,
        open_position_count=1,
        **base,
    )
    exposure_cap = PaperRiskContext(
        current_position_value=500,
        open_position_count=0,
        **base,
    )

    assert manager.evaluate_entry(open_cap).reason == "max_open_positions_reached"
    assert manager.evaluate_entry(exposure_cap).reason == "max_exposure_reached"


def test_account_rejects_partial_sell_and_preserves_position():
    account = PaperAccount(starting_cash=1_000)
    account.apply_buy(
        instrument="BTC-USDT",
        quantity=1,
        fill_price=100,
        fee=1,
        slippage_cost=0,
        stop_loss=90,
        entry_time=START,
        signal_id="s1",
    )

    with pytest.raises(AccountError, match="full held quantity"):
        account.apply_sell(
            instrument="BTC-USDT",
            quantity=0.5,
            fill_price=110,
            fee=1,
            slippage_cost=0,
        )
    assert account.positions["BTC-USDT"].quantity == 1


def test_account_rejects_buy_that_would_make_cash_negative():
    account = PaperAccount(starting_cash=100)
    with pytest.raises(AccountError, match="insufficient cash"):
        account.apply_buy(
            instrument="BTC-USDT",
            quantity=2,
            fill_price=100,
            fee=1,
            slippage_cost=0,
            stop_loss=90,
            entry_time=START,
            signal_id="s1",
        )
    assert account.cash == 100
    assert account.positions == {}


def test_non_simulated_fill_is_rejected_before_account_mutation():
    target = engine(broker=LyingBroker())
    with pytest.raises(ValueError, match="non-simulated"):
        process(target, candle(), quote())
    assert target.account.cash == 10_000
    assert target.account.open_position_count == 0
