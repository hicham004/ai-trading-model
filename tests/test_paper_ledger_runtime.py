"""Offline persistence, reconciliation, and runtime-lock tests for Phase 4."""

from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    Candle,
    PaperDailyBaseline,
    PaperEquitySnapshot,
    PaperFill,
    PaperProcessedCandle,
    PaperRuntimeStatus,
    PaperTrade,
)
from app.live.market_state import MarketState
from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    OrderBookAction,
    OrderBookLevel,
    OrderBookUpdate,
)
from app.paper.config import PaperRunConfig
from app.paper.engine import PaperTradingEngine
from app.paper.execution import FeedStatus, QuoteSnapshot
from app.paper.ledger import (
    AccountConfigMismatch,
    CandleAlreadyPersisted,
    KillSwitchEngaged,
    PaperLedger,
)
from app.paper.runtime import build_paper_runtime
from app.paper.risk import PaperRiskContext
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
                stop_loss=c.close * 0.9,
            )
            for c in candles
        ]


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    try:
        yield factory
    finally:
        engine.dispose()


def make_outcome(config: PaperRunConfig):
    target = PaperTradingEngine(
        config=config.build_engine_config(),
        strategy=AlwaysLong(),
        risk_manager=config.build_risk_manager(),
        account=config.build_account(),
    )
    bar = MarketCandle(
        instrument="BTC-USDT",
        timeframe="1m",
        timestamp=START,
        open=100,
        high=105,
        low=95,
        close=100,
        volume=1,
    )
    outcome = target.process_confirmed_candle(
        bar,
        quote=QuoteSnapshot(
            instrument="BTC-USDT",
            bid=99,
            ask=101,
            timestamp=START + timedelta(seconds=61),
            synchronized=True,
        ),
        feed_status=FeedStatus(True, False),
        now=START + timedelta(seconds=62),
    )
    return bar, outcome


def test_atomic_persist_and_reconcile_round_trip(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)

    ledger.persist_outcome(account_id, outcome)
    reconciled = ledger.reconcile(account_id, config.starting_cash)

    assert reconciled.consistent is True
    assert reconciled.account.cash == pytest.approx(outcome.account.cash)
    assert reconciled.account.positions["BTC-USDT"].quantity == pytest.approx(
        outcome.account.positions["BTC-USDT"].quantity
    )


def test_duplicate_candle_rolls_back_without_extra_rows(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.persist_outcome(account_id, outcome)

    with pytest.raises(CandleAlreadyPersisted):
        ledger.persist_outcome(account_id, outcome)

    with session_factory() as session:
        assert session.scalar(
            select(func.count(PaperProcessedCandle.id))
        ) == 1
        assert session.scalar(select(func.count(PaperFill.id))) == 1


def test_constraint_failure_rolls_back_entire_outcome(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.persist_outcome(account_id, outcome)

    conflicting = copy.deepcopy(outcome)
    conflicting.candle_open_time = START + timedelta(minutes=1)
    conflicting.candle_close_time = START + timedelta(minutes=2)
    with pytest.raises(IntegrityError):
        ledger.persist_outcome(account_id, conflicting)

    with session_factory() as session:
        assert session.scalar(select(func.count(PaperProcessedCandle.id))) == 1
        assert session.scalar(select(func.count(PaperFill.id))) == 1


def test_corrupt_snapshot_fails_reconciliation_without_guessing(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.persist_outcome(account_id, outcome)
    with session_factory() as session:
        snapshot = session.scalar(select(PaperEquitySnapshot))
        snapshot.positions_json = "{not-json"
        session.commit()

    reconciled = ledger.reconcile(account_id, config.starting_cash)
    assert reconciled.consistent is False
    assert "invalid positions snapshot JSON" in reconciled.issues


def test_snapshot_cost_basis_tampering_fails_reconciliation(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.persist_outcome(account_id, outcome)
    with session_factory() as session:
        snapshot = session.scalar(select(PaperEquitySnapshot))
        positions = json.loads(snapshot.positions_json)
        positions[0]["entry_price"] = 1.0
        snapshot.positions_json = json.dumps(positions)
        session.commit()

    reconciled = ledger.reconcile(account_id, config.starting_cash)
    assert reconciled.consistent is False
    assert "position cost basis mismatch for BTC-USDT" in reconciled.issues


def test_daily_loss_baseline_cannot_be_overridden_by_snapshot(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.persist_outcome(account_id, outcome)
    with session_factory() as session:
        snapshot = session.scalar(select(PaperEquitySnapshot))
        snapshot.day_start_equity = 1_000_000_000
        session.commit()
        assert session.scalar(select(func.count(PaperDailyBaseline.id))) == 1

    reconciled = ledger.reconcile(account_id, config.starting_cash)
    assert reconciled.consistent is False
    assert reconciled.account.day_start_equity == 10_000
    assert "day-start equity mismatch" in " ".join(reconciled.issues)

    signal = AlwaysLong().generate_signals(
        [
            MarketCandle(
                instrument="BTC-USDT",
                timeframe="1m",
                timestamp=START,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
            )
        ]
    )[0]
    decision = config.build_risk_manager().evaluate_entry(
        PaperRiskContext(
            signal=signal,
            equity=9_400,
            cash=9_400,
            reference_price=101,
            current_position_value=0,
            open_position_count=0,
            has_position_in_instrument=False,
            day_start_equity=reconciled.account.day_start_equity,
            day_realized_pnl=-600,
            now=START + timedelta(seconds=62),
            data_time=START + timedelta(seconds=60),
            quote=QuoteSnapshot(
                instrument="BTC-USDT",
                bid=99,
                ask=101,
                timestamp=START + timedelta(seconds=61),
                synchronized=True,
            ),
            feed_status=FeedStatus(True, False),
            kill_switch_engaged=False,
        )
    )
    assert decision.reason == "max_daily_loss_reached"


def test_non_simulated_persisted_fill_fails_reconciliation(session_factory):
    config = PaperRunConfig()
    ledger = PaperLedger(session_factory, "test")
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.persist_outcome(account_id, outcome)
    with session_factory() as session:
        fill = session.scalar(select(PaperFill))
        fill.is_simulated = False
        session.commit()

    reconciled = ledger.reconcile(account_id, config.starting_cash)
    assert reconciled.consistent is False
    assert any("not marked simulated" in issue for issue in reconciled.issues)


def test_failed_prepare_releases_advisory_lock(session_factory):
    config = PaperRunConfig(account_name="broken")
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    with session_factory() as session:
        session.add(
            PaperFill(
                account_id=account_id,
                fill_id="orphan-fill",
                client_order_id="orphan-order",
                instrument="BTC-USDT",
                side="buy",
                quantity=1,
                price=100,
                fee=0,
                slippage_cost=0,
                fill_time=START,
                is_simulated=True,
            )
        )
        session.commit()

    runtime = build_paper_runtime(
        config,
        state=MarketState(),
        session_factory=session_factory,
        clock=lambda: START + timedelta(minutes=1),
    )
    assert runtime.prepare() is False

    with session_factory() as session:
        status = session.scalar(
            select(PaperRuntimeStatus).where(
                PaperRuntimeStatus.account_id == account_id
            )
        )
        assert status.status == "reconcile_failed"
        assert status.lock_token is None
        assert status.lock_heartbeat is None


def test_local_kill_switch_control_is_persisted_and_audited(session_factory):
    config = PaperRunConfig(account_name="controlled")
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())

    ledger.set_kill_switch(account_id, True, now=START)
    with session_factory() as session:
        status = session.scalar(
            select(PaperRuntimeStatus).where(
                PaperRuntimeStatus.account_id == account_id
            )
        )
        assert status.kill_switch_engaged is True

    reconciled = ledger.reconcile(account_id, config.starting_cash)
    assert reconciled.kill_switch_engaged is True


def test_persisted_kill_switch_blocks_racing_entry_outcome(session_factory):
    config = PaperRunConfig(account_name="kill-race")
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, outcome = make_outcome(config)
    ledger.set_kill_switch(account_id, True, now=START)

    with pytest.raises(KillSwitchEngaged):
        ledger.persist_outcome(account_id, outcome)
    with session_factory() as session:
        assert session.scalar(select(func.count(PaperFill.id))) == 0


def test_status_publish_cannot_overwrite_operator_kill_switch(session_factory):
    config = PaperRunConfig(account_name="kill-status")
    runtime = build_paper_runtime(
        config,
        state=MarketState(),
        session_factory=session_factory,
        clock=lambda: START,
    )
    assert runtime.prepare() is True
    account_id = runtime.account_id
    ledger = PaperLedger(session_factory, config.account_name)
    ledger.set_kill_switch(account_id, True, now=START + timedelta(seconds=1))

    runtime._publish_status(
        START + timedelta(seconds=2),
        FeedStatus(connected=True, stale=False),
        True,
    )
    with session_factory() as session:
        status = session.scalar(
            select(PaperRuntimeStatus).where(
                PaperRuntimeStatus.account_id == account_id
            )
        )
        assert status.kill_switch_engaged is True
    runtime._shutdown()


def test_existing_account_rejects_incompatible_runtime_config(session_factory):
    original = PaperRunConfig(account_name="immutable")
    ledger = PaperLedger(session_factory, original.account_name)
    ledger.ensure_account(original.starting_cash, original.config_snapshot())
    incompatible = PaperRunConfig(
        account_name="immutable",
        instruments=("ETH-USDT",),
    )

    with pytest.raises(AccountConfigMismatch):
        ledger.ensure_account(
            incompatible.starting_cash, incompatible.config_snapshot()
        )


def test_atomic_lock_allows_only_one_concurrent_runner(tmp_path):
    database = tmp_path / "locks.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    config = PaperRunConfig(account_name="locked")
    ledger = PaperLedger(factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    barrier = threading.Barrier(2)

    def acquire(token):
        barrier.wait()
        return PaperLedger(factory, config.account_name).acquire_lock(
            account_id,
            token,
            stale_after_seconds=1,
            now=START,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, ("one", "two")))
    assert sorted(results) == [False, True]
    engine.dispose()


def test_stale_lock_requires_explicit_expired_release(session_factory):
    config = PaperRunConfig(account_name="stale-lock", lock_stale_seconds=10)
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    assert ledger.acquire_lock(
        account_id, "old", stale_after_seconds=10, now=START
    )
    assert not ledger.acquire_lock(
        account_id,
        "new",
        stale_after_seconds=10,
        now=START + timedelta(hours=1),
    )
    assert ledger.release_stale_lock(
        account_id,
        stale_after_seconds=10,
        now=START + timedelta(hours=1),
    )
    assert ledger.acquire_lock(
        account_id,
        "new",
        stale_after_seconds=10,
        now=START + timedelta(hours=1),
    )


def test_restart_recovery_enforces_existing_stop_without_new_entry(session_factory):
    config = PaperRunConfig(account_name="recovery")
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    _, opened = make_outcome(config)
    ledger.persist_outcome(account_id, opened)

    with session_factory() as session:
        session.add_all(
            [
                Candle(
                    instrument="BTC-USDT",
                    timeframe="1m",
                    open_time=START,
                    open=100,
                    high=105,
                    low=95,
                    close=100,
                    volume=1,
                ),
                Candle(
                    instrument="BTC-USDT",
                    timeframe="1m",
                    open_time=START + timedelta(minutes=1),
                    open=80,
                    high=85,
                    low=75,
                    close=82,
                    volume=1,
                ),
            ]
        )
        session.commit()

    runtime = build_paper_runtime(
        config,
        state=MarketState(),
        session_factory=session_factory,
        clock=lambda: START + timedelta(minutes=10),
    )
    assert runtime.prepare() is True
    assert runtime.engine.account.open_position_count == 0

    with session_factory() as session:
        assert session.scalar(select(func.count(PaperTrade.id))) == 1
        assert session.scalar(select(func.count(PaperProcessedCandle.id))) == 2
    runtime._shutdown()


def test_restart_rebuilds_strategy_window_from_paper_ledger(session_factory):
    config = PaperRunConfig(account_name="ledger-history", window_size=40)
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    target = PaperTradingEngine(
        config=config.build_engine_config(),
        strategy=AlwaysLong(),
        risk_manager=config.build_risk_manager(),
        account=config.build_account(),
    )
    for minute in range(35):
        bar = MarketCandle(
            instrument="BTC-USDT",
            timeframe="1m",
            timestamp=START + timedelta(minutes=minute),
            open=100 + minute,
            high=101 + minute,
            low=99 + minute,
            close=100 + minute,
            volume=1,
        )
        outcome = target.process_confirmed_candle(
            bar,
            quote=QuoteSnapshot(
                instrument="BTC-USDT",
                bid=99 + minute,
                ask=101 + minute,
                timestamp=bar.timestamp + timedelta(seconds=61),
                synchronized=True,
            ),
            feed_status=FeedStatus(True, False),
            now=bar.timestamp + timedelta(seconds=62),
        )
        ledger.persist_outcome(account_id, outcome)
        target.commit(bar, outcome)

    runtime = build_paper_runtime(
        config,
        state=MarketState(),
        session_factory=session_factory,
        clock=lambda: START + timedelta(hours=1),
    )
    assert runtime.prepare() is True
    assert len(runtime.engine._windows["BTC-USDT"]) == 35
    assert runtime.engine.last_close("BTC-USDT") == 134
    assert runtime.engine.watermark("BTC-USDT") == START + timedelta(minutes=34)
    runtime._shutdown()


def test_restart_rejects_discontinuous_processed_candle_ledger(session_factory):
    config = PaperRunConfig(account_name="history-gap")
    ledger = PaperLedger(session_factory, config.account_name)
    account_id = ledger.ensure_account(config.starting_cash, config.config_snapshot())
    target = PaperTradingEngine(
        config=config.build_engine_config(),
        strategy=AlwaysLong(),
        risk_manager=config.build_risk_manager(),
        account=config.build_account(),
    )
    for minute in range(3):
        bar = MarketCandle(
            instrument="BTC-USDT",
            timeframe="1m",
            timestamp=START + timedelta(minutes=minute),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
        )
        outcome = target.process_confirmed_candle(
            bar,
            quote=QuoteSnapshot(
                instrument="BTC-USDT",
                bid=99,
                ask=101,
                timestamp=bar.timestamp + timedelta(seconds=61),
                synchronized=True,
            ),
            feed_status=FeedStatus(True, False),
            now=bar.timestamp + timedelta(seconds=62),
        )
        ledger.persist_outcome(account_id, outcome)
        target.commit(bar, outcome)
    with session_factory() as session:
        middle = session.scalar(
            select(PaperProcessedCandle).where(
                PaperProcessedCandle.candle_open_time
                == START + timedelta(minutes=1)
            )
        )
        session.delete(middle)
        session.commit()

    reconciled = ledger.reconcile(
        account_id, config.starting_cash, history_limit=config.window_size
    )
    assert reconciled.consistent is False
    assert any("processed candle gap" in issue for issue in reconciled.issues)
    assert any("one-to-one equity snapshot" in issue for issue in reconciled.issues)

    runtime = build_paper_runtime(
        config,
        state=MarketState(),
        session_factory=session_factory,
        clock=lambda: START + timedelta(minutes=5),
    )
    assert runtime.prepare() is False


def test_stale_candle_is_recovered_without_breaking_history(session_factory):
    now = START + timedelta(minutes=2, seconds=2)
    state = MarketState(clock=lambda: now)
    required = ["books:BTC-USDT", "candle1m:BTC-USDT"]
    state.register_feed("paper-test", required)
    state.set_feed_acked("paper-test", required)
    state.set_feed_status("paper-test", ConnectionStatus.CONNECTED)
    state.apply_order_book(
        OrderBookUpdate(
            instrument="BTC-USDT",
            timestamp=now,
            action=OrderBookAction.SNAPSHOT,
            bids=(OrderBookLevel(Decimal("99"), Decimal("1"), 1),),
            asks=(OrderBookLevel(Decimal("101"), Decimal("1"), 1),),
            previous_sequence_id=-1,
            sequence_id=1,
        ),
        "paper-test",
    )
    for minute in (0, 1):
        state.apply_candle(
            CandleUpdate(
                instrument="BTC-USDT",
                timeframe="1m",
                timestamp=START + timedelta(minutes=minute),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
                confirmed=True,
            ),
            "paper-test",
        )
    config = PaperRunConfig(
        account_name="stale-history",
        max_candle_age_seconds=30,
    )
    runtime = build_paper_runtime(
        config,
        state=state,
        session_factory=session_factory,
        clock=lambda: now,
    )
    assert runtime.prepare() is True
    outcomes = runtime.poll_once(now)

    assert len(outcomes) == 2
    assert runtime.engine.watermark("BTC-USDT") == START + timedelta(minutes=1)
    assert [c.timestamp for c in runtime.engine._windows["BTC-USDT"]] == [
        START,
        START + timedelta(minutes=1),
    ]
    with session_factory() as session:
        assert session.scalar(select(func.count(PaperProcessedCandle.id))) == 2
    runtime._shutdown()
