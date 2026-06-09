"""Forward-time paper-trading engine (deterministic, SIMULATION ONLY).

This is the heart of Phase 4. It wires the accepted layers exactly the way a
future automated system would, but strictly forward in time on confirmed public
candles:

    confirmed candle -> validate/dedup -> strategy.generate_signals
        -> PaperRiskManager (final veto) -> virtual order
        -> simulated fill (against fresh bid/ask) -> virtual balances/positions

Design contract: :meth:`process_confirmed_candle` is a PURE function of its
inputs and the engine's current state. It never mutates engine state and never
performs I/O; it returns a :class:`CandleOutcome` describing everything that
should happen. The caller persists that outcome atomically and then calls
:meth:`commit` to adopt the new state. A failed persist therefore leaves the
engine exactly where it was, and the same candle is reprocessed identically on
the next poll (idempotent, no partial state, no look-ahead).

Forward-time guarantees:

* A candle is processed at most once: any candle whose open time is at or below
  the per-instrument watermark is rejected as duplicate/out-of-order.
* Duplicate, missing, stale, future, malformed, wrong-instrument, and
  wrong-timeframe candles are rejected before any evaluation.
* The strategy only ever sees candles up to and including the one being
  processed (no future bars).
* Entries and signal exits fill against a fresh, synchronized live best
  bid/ask captured at decision time - a price available *after* the signal
  became actionable, never a historical or future price.
* Protective stop exits fill at the stop price (or the worse open on an adverse
  gap) of the confirmed candle that breached the stop - the conservative,
  look-ahead-free assumption. A position is only stop-checked against candles
  that close *after* it was opened.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Deque, Dict, List, Optional, Sequence

from app.backtest.validation import validate_candles, validate_signals
from app.broker.base import Broker, OrderSide
from app.broker.paper import PaperBroker
from app.logging_config import get_logger
from app.paper.account import PaperAccount, Position
from app.paper.execution import (
    ExecutionError,
    FeedStatus,
    QuoteSnapshot,
    execute_at_price,
    execute_at_quote,
)
from app.paper.records import (
    EXIT_SIGNAL,
    EXIT_STOP_LOSS,
    INTENT_ENTRY,
    INTENT_SIGNAL_EXIT,
    INTENT_STOP_EXIT,
    CandleOutcome,
    EquitySnapshotRecord,
    EventRecord,
    FillRecord,
    OrderRecord,
    RiskDecisionRecord,
    SignalRecord,
    TradeRecord,
    fill_id_for,
    order_id_for,
    signal_id_for,
)
from app.paper.risk import PaperRiskContext, PaperRiskManager
from app.strategy.base import MarketCandle, SignalAction, Strategy
from app.strategy.timeframes import parse_timeframe

logger = get_logger(__name__)


@dataclass(frozen=True)
class PaperEngineConfig:
    """Static engine configuration. All values are simulation parameters."""

    instruments: Sequence[str]
    timeframe: str
    fee_rate: float = 0.0
    slippage_rate: float = 0.0
    window_size: int = 300
    max_candle_age: timedelta = timedelta(minutes=3)
    future_candle_tolerance: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        if not self.instruments:
            raise ValueError("at least one instrument is required")
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("duplicate instruments are not allowed")
        # Validates the timeframe (fail closed on an unsupported value).
        parse_timeframe(self.timeframe)
        for label, value in (("fee_rate", self.fee_rate), ("slippage_rate", self.slippage_rate)):
            if not isfinite(value) or not 0.0 <= value < 1.0:
                raise ValueError(f"{label} must be in [0.0, 1.0)")
        if isinstance(self.window_size, bool) or not isinstance(self.window_size, int) or self.window_size < 2:
            raise ValueError("window_size must be an integer >= 2")
        if self.max_candle_age <= timedelta(0):
            raise ValueError("max_candle_age must be positive")
        if self.future_candle_tolerance < timedelta(0):
            raise ValueError("future_candle_tolerance must be non-negative")


def _position_dict(position: Position) -> dict:
    return {
        "instrument": position.instrument,
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "stop_loss": position.stop_loss,
        "entry_time": position.entry_time.isoformat(),
        "entry_fee": position.entry_fee,
        "entry_slippage": position.entry_slippage,
        "signal_id": position.signal_id,
    }


class PaperTradingEngine:
    """Deterministic forward-time pipeline over confirmed public candles."""

    def __init__(
        self,
        *,
        config: PaperEngineConfig,
        strategy: Strategy,
        risk_manager: PaperRiskManager,
        account: PaperAccount,
        broker: Optional[Broker] = None,
    ) -> None:
        self._config = config
        self._strategy = strategy
        self._risk = risk_manager
        self._account = account
        # Default to a simulation paper broker carrying the configured cost
        # model. The broker performs only local arithmetic (no network).
        if broker is None:
            from app.broker.base import CostModel

            broker = PaperBroker(
                CostModel(fee_rate=config.fee_rate, slippage_rate=config.slippage_rate)
            )
        self._broker = broker
        if not getattr(self._broker, "is_simulation", False):
            raise ValueError(
                "PaperTradingEngine requires a simulation broker "
                "(broker.is_simulation must be True)."
            )
        self._instruments = tuple(config.instruments)
        self._timeframe = config.timeframe
        self._interval = parse_timeframe(config.timeframe)
        self._windows: Dict[str, Deque[MarketCandle]] = {
            inst: deque(maxlen=config.window_size) for inst in self._instruments
        }
        self._watermark: Dict[str, datetime] = {}
        self._last_close: Dict[str, float] = {}
        self._kill_switch = False

    # -- control / read state ----------------------------------------------

    @property
    def account(self) -> PaperAccount:
        return self._account

    def adopt_account(self, account: PaperAccount) -> None:
        """Replace the in-memory account (used to load reconciled state)."""
        self._account = account

    @property
    def kill_switch_engaged(self) -> bool:
        return self._kill_switch

    def set_kill_switch(self, engaged: bool) -> None:
        self._kill_switch = bool(engaged)

    def watermark(self, instrument: str) -> Optional[datetime]:
        return self._watermark.get(instrument)

    def set_watermark(self, instrument: str, open_time: datetime) -> None:
        """Set the per-instrument 'last processed candle' time (restart resume)."""
        self._watermark[instrument] = open_time

    def last_close(self, instrument: str) -> Optional[float]:
        return self._last_close.get(instrument)

    def set_last_close(self, instrument: str, price: float) -> None:
        self._last_close[instrument] = price

    # -- warmup -------------------------------------------------------------

    def seed_history(self, candles: Sequence[MarketCandle]) -> int:
        """Seed indicator context from persisted history WITHOUT trading.

        Validates the candles, appends them to the rolling window, and advances
        the per-instrument watermark/last-close. No signals, orders, or fills
        are produced - historical bars are context only, never retraded.
        Returns the number of candles seeded.
        """
        seeded = 0
        by_instrument: Dict[str, List[MarketCandle]] = {}
        for candle in candles:
            by_instrument.setdefault(candle.instrument, []).append(candle)
        for instrument, group in by_instrument.items():
            if instrument not in self._windows:
                raise ValueError(f"seed_history: unknown instrument {instrument!r}")
            validate_candles(
                group,
                expected_instrument=instrument,
                expected_timeframe=self._timeframe,
            )
            for candle in group:
                wm = self._watermark.get(instrument)
                if wm is not None and candle.timestamp <= wm:
                    # Already-known context: keep the window populated but do
                    # not move the watermark backwards.
                    self._windows[instrument].append(candle)
                    self._last_close[instrument] = candle.close
                    continue
                self._windows[instrument].append(candle)
                self._watermark[instrument] = candle.timestamp
                self._last_close[instrument] = candle.close
                seeded += 1
        return seeded

    # -- the pipeline (pure) ------------------------------------------------

    def process_confirmed_candle(
        self,
        candle: MarketCandle,
        *,
        quote: Optional[QuoteSnapshot],
        feed_status: FeedStatus,
        now: datetime,
    ) -> CandleOutcome:
        """Run the full pipeline for one confirmed candle. Pure (no mutation)."""
        instrument = candle.instrument
        close_time = candle.timestamp + self._interval

        rejection = self._validate_incoming(candle, close_time, now)
        if rejection is not None:
            return CandleOutcome(
                instrument=instrument,
                timeframe=self._timeframe,
                candle_open_time=candle.timestamp,
                candle_close_time=close_time,
                accepted=False,
                rejection_reason=rejection,
            )

        signal_id = signal_id_for(instrument, self._timeframe, candle.timestamp)
        orders: List[OrderRecord] = []
        fills: List[FillRecord] = []
        trades: List[TradeRecord] = []
        risk_decisions: List[RiskDecisionRecord] = []
        events: List[EventRecord] = []

        # Strategy evaluation over candles up to and including this one.
        window = list(self._windows[instrument])[-(self._config.window_size - 1):]
        window.append(candle)
        signal = None
        signal_record = None
        try:
            signals = self._strategy.generate_signals(window)
            validate_signals(
                signals,
                window,
                expected_instrument=instrument,
                expected_timeframe=self._timeframe,
            )
            signal = signals[-1]
            signal_record = SignalRecord(
                signal_id=signal_id,
                instrument=instrument,
                timeframe=self._timeframe,
                signal_data_time=candle.timestamp,
                candle_close_time=close_time,
                decision_time=now,
                action=signal.action.value,
                confidence=signal.confidence,
                reason=signal.reason,
                stop_loss=signal.stop_loss,
            )
        except (TypeError, ValueError, IndexError) as exc:
            events.append(
                EventRecord(
                    event_time=now,
                    event_type="strategy_output_invalid",
                    severity="error",
                    message="strategy output failed validation; no action taken",
                    payload={
                        "instrument": instrument,
                        "open_time": candle.timestamp.isoformat(),
                        "error_type": type(exc).__name__,
                    },
                )
            )

        working = self._account.copy()
        marks = self._marks(instrument, candle.close)
        working.roll_day_if_needed(close_time.date(), working.equity(marks))

        exited_this_candle = self._maybe_stop_exit(
            working, instrument, candle, signal_id, now, orders, fills, trades
        )

        if signal is not None and not exited_this_candle:
            if signal.action == SignalAction.LONG and not working.has_position(instrument):
                self._maybe_enter(
                    working, instrument, candle, signal, signal_id, quote,
                    feed_status, now, marks, orders, fills, risk_decisions, events,
                )
            elif signal.action == SignalAction.FLAT and working.has_position(instrument):
                self._maybe_signal_exit(
                    working, instrument, candle, signal_id, quote, feed_status,
                    now, orders, fills, trades, events,
                )
            # HOLD: leave any position unchanged.

        # Finalize: snapshot equity at this candle's close mark.
        marks = self._marks(instrument, candle.close)
        equity_snapshot = EquitySnapshotRecord(
            snapshot_time=now,
            market_time=close_time,
            cash=working.cash,
            position_value=working.position_value(marks),
            equity=working.equity(marks),
            realized_pnl=working.realized_pnl,
            unrealized_pnl=working.unrealized_pnl(marks),
            day_start_equity=working.day_start_equity,
            day_realized_pnl=working.day_realized_pnl,
            open_position_count=working.open_position_count,
            positions=[_position_dict(p) for p in working.positions.values()],
            kill_switch_engaged=self._kill_switch,
        )
        self._assert_finite(working, equity_snapshot)

        return CandleOutcome(
            instrument=instrument,
            timeframe=self._timeframe,
            candle_open_time=candle.timestamp,
            candle_close_time=close_time,
            accepted=True,
            candle_open=candle.open,
            candle_high=candle.high,
            candle_low=candle.low,
            candle_close=candle.close,
            candle_volume=candle.volume,
            account=working,
            last_close=candle.close,
            signal=signal_record,
            risk_decisions=risk_decisions,
            orders=orders,
            fills=fills,
            trades=trades,
            events=events,
            equity_snapshot=equity_snapshot,
        )

    def process_recovery_candle(
        self,
        candle: MarketCandle,
        *,
        observed_at: datetime,
    ) -> CandleOutcome:
        """Reconcile one candle observed while the runtime was offline.

        Recovery bars never generate strategy entries or signal exits. They
        only advance market/account state and enforce a protective stop that
        was already active before the outage. This prevents retrospective
        trading while ensuring restart cannot silently ignore a stop breach.
        """
        instrument = candle.instrument
        close_time = candle.timestamp + self._interval
        rejection = self._validate_incoming(
            candle, close_time, observed_at, enforce_freshness=False
        )
        if rejection is not None:
            return CandleOutcome(
                instrument=instrument,
                timeframe=self._timeframe,
                candle_open_time=candle.timestamp,
                candle_close_time=close_time,
                accepted=False,
                rejection_reason=rejection,
            )

        signal_id = signal_id_for(instrument, self._timeframe, candle.timestamp)
        working = self._account.copy()
        marks = self._marks(instrument, candle.close)
        working.roll_day_if_needed(close_time.date(), working.equity(marks))
        orders: List[OrderRecord] = []
        fills: List[FillRecord] = []
        trades: List[TradeRecord] = []
        events = [
            EventRecord(
                event_time=observed_at,
                event_type="recovery_candle",
                severity="info",
                message=(
                    "reconciled candle observed while offline; strategy actions disabled"
                ),
                payload={
                    "instrument": instrument,
                    "open_time": candle.timestamp.isoformat(),
                },
            )
        ]
        self._maybe_stop_exit(
            working,
            instrument,
            candle,
            signal_id,
            close_time,
            orders,
            fills,
            trades,
        )
        marks = self._marks(instrument, candle.close)
        snapshot = EquitySnapshotRecord(
            snapshot_time=observed_at,
            market_time=close_time,
            cash=working.cash,
            position_value=working.position_value(marks),
            equity=working.equity(marks),
            realized_pnl=working.realized_pnl,
            unrealized_pnl=working.unrealized_pnl(marks),
            day_start_equity=working.day_start_equity,
            day_realized_pnl=working.day_realized_pnl,
            open_position_count=working.open_position_count,
            positions=[_position_dict(p) for p in working.positions.values()],
            kill_switch_engaged=self._kill_switch,
        )
        self._assert_finite(working, snapshot)
        return CandleOutcome(
            instrument=instrument,
            timeframe=self._timeframe,
            candle_open_time=candle.timestamp,
            candle_close_time=close_time,
            accepted=True,
            candle_open=candle.open,
            candle_high=candle.high,
            candle_low=candle.low,
            candle_close=candle.close,
            candle_volume=candle.volume,
            account=working,
            last_close=candle.close,
            orders=orders,
            fills=fills,
            trades=trades,
            events=events,
            equity_snapshot=snapshot,
        )

    def commit(self, candle: MarketCandle, outcome: CandleOutcome) -> None:
        """Adopt an accepted outcome (called only after a successful persist)."""
        if not outcome.accepted or outcome.account is None:
            return
        instrument = candle.instrument
        self._windows[instrument].append(candle)
        self._watermark[instrument] = candle.timestamp
        self._last_close[instrument] = candle.close
        self._account = outcome.account

    # -- internals ----------------------------------------------------------

    def _validate_incoming(
        self,
        candle: MarketCandle,
        close_time: datetime,
        now: datetime,
        *,
        enforce_freshness: bool = True,
    ) -> Optional[str]:
        instrument = candle.instrument
        if instrument not in self._windows:
            return "unsupported_instrument"
        if candle.timeframe != self._timeframe:
            return "wrong_timeframe"
        if now.tzinfo is None:
            return "naive_now"
        try:
            validate_candles(
                [candle],
                expected_instrument=instrument,
                expected_timeframe=self._timeframe,
            )
        except ValueError:
            return "malformed_candle"
        if enforce_freshness:
            if close_time - now > self._config.future_candle_tolerance:
                return "future_candle"
            if now - close_time > self._config.max_candle_age:
                return "stale_candle"
        wm = self._watermark.get(instrument)
        if wm is not None:
            if candle.timestamp == wm:
                return "duplicate_candle"
            if candle.timestamp < wm:
                return "out_of_order_candle"
            if candle.timestamp > wm + self._interval:
                return "candle_gap"
        return None

    def _marks(self, instrument: str, close: float) -> Dict[str, float]:
        marks = dict(self._last_close)
        marks[instrument] = close
        return marks

    def _maybe_stop_exit(
        self,
        working: PaperAccount,
        instrument: str,
        candle: MarketCandle,
        signal_id: str,
        now: datetime,
        orders: List[OrderRecord],
        fills: List[FillRecord],
        trades: List[TradeRecord],
    ) -> bool:
        """Exit a PRE-EXISTING position if this candle's low pierces its stop."""
        position = working.positions.get(instrument)
        if position is None or position.stop_loss is None:
            return False
        if candle.low > position.stop_loss:
            return False
        # Conservative gap model: a candle that opens below the stop fills at the
        # worse open; otherwise it fills at the stop price.
        stop_reference = candle.open if candle.open < position.stop_loss else position.stop_loss
        fill = execute_at_price(
            self._broker,
            instrument=instrument,
            side=OrderSide.SELL,
            quantity=position.quantity,
            reference_price=stop_reference,
            when=now,
        )
        entry_signal_id = position.signal_id
        entry_price = position.entry_price
        entry_time = position.entry_time
        entry_fee = position.entry_fee
        entry_slippage = position.entry_slippage
        working.apply_sell(
            instrument=instrument,
            quantity=fill.quantity,
            fill_price=fill.price,
            fee=fill.fee,
            slippage_cost=fill.slippage_cost,
        )
        self._record_exit(
            signal_id, instrument, fill, INTENT_STOP_EXIT, stop_reference, now,
            entry_signal_id, entry_price, entry_time, entry_fee, entry_slippage,
            EXIT_STOP_LOSS, orders, fills, trades,
        )
        return True

    def _maybe_enter(
        self,
        working: PaperAccount,
        instrument: str,
        candle: MarketCandle,
        signal,
        signal_id: str,
        quote: Optional[QuoteSnapshot],
        feed_status: FeedStatus,
        now: datetime,
        marks: Dict[str, float],
        orders: List[OrderRecord],
        fills: List[FillRecord],
        risk_decisions: List[RiskDecisionRecord],
        events: List[EventRecord],
    ) -> None:
        close_time = candle.timestamp + self._interval
        quote_ok = quote is not None and quote.prices_finite_and_coherent()
        reference_price = quote.ask if quote_ok else candle.close
        ctx = PaperRiskContext(
            signal=signal,
            equity=working.equity(marks),
            cash=working.cash,
            reference_price=reference_price,
            current_position_value=working.position_value(marks),
            open_position_count=working.open_position_count,
            has_position_in_instrument=working.has_position(instrument),
            day_start_equity=working.day_start_equity,
            day_realized_pnl=working.day_realized_pnl,
            now=now,
            data_time=close_time,
            quote=quote,
            feed_status=feed_status,
            kill_switch_engaged=self._kill_switch,
        )
        decision = self._risk.evaluate_entry(ctx)
        risk_decisions.append(
            RiskDecisionRecord(signal_id, now, INTENT_ENTRY, decision.allowed, decision.reason)
        )
        if not decision.allowed:
            return

        # Quote is guaranteed usable here (risk allowed the entry).
        assert quote is not None
        ask = quote.touch_price(OrderSide.BUY)
        denom = ask * (1.0 + self._config.slippage_rate) * (1.0 + self._config.fee_rate)
        if denom <= 0:
            return
        qty_by_risk = self._risk.max_entry_quantity(
            ctx,
            fee_rate=self._config.fee_rate,
            slippage_rate=self._config.slippage_rate,
        )
        qty_by_cash = working.cash / denom
        quantity = min(qty_by_risk, qty_by_cash)
        if not (isfinite(quantity) and quantity > 0):
            events.append(
                EventRecord(
                    event_time=now,
                    event_type="entry_not_sized",
                    severity="info",
                    message="entry allowed but sized to zero (insufficient cash/exposure room)",
                    payload={"instrument": instrument, "signal_id": signal_id},
                )
            )
            return
        try:
            fill = execute_at_quote(
                self._broker,
                instrument=instrument,
                side=OrderSide.BUY,
                quantity=quantity,
                quote=quote,
                when=now,
            )
        except ExecutionError as exc:  # pragma: no cover - defensive
            events.append(
                EventRecord(
                    event_time=now,
                    event_type="entry_execution_error",
                    severity="error",
                    message=str(exc),
                    payload={"instrument": instrument, "signal_id": signal_id},
                )
            )
            return
        working.apply_buy(
            instrument=instrument,
            quantity=fill.quantity,
            fill_price=fill.price,
            fee=fill.fee,
            slippage_cost=fill.slippage_cost,
            stop_loss=signal.stop_loss,
            entry_time=now,
            signal_id=signal_id,
        )
        client_order_id = order_id_for(signal_id, INTENT_ENTRY)
        orders.append(
            OrderRecord(
                client_order_id=client_order_id,
                signal_id=signal_id,
                instrument=instrument,
                side=OrderSide.BUY,
                intent=INTENT_ENTRY,
                quantity=fill.quantity,
                reference_price=ask,
                order_time=now,
                quote_bid=quote.bid,
                quote_ask=quote.ask,
                quote_time=quote.timestamp,
            )
        )
        fills.append(
            FillRecord(
                fill_id=fill_id_for(client_order_id),
                client_order_id=client_order_id,
                instrument=instrument,
                side=OrderSide.BUY,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                slippage_cost=fill.slippage_cost,
                fill_time=now,
            )
        )

    def _maybe_signal_exit(
        self,
        working: PaperAccount,
        instrument: str,
        candle: MarketCandle,
        signal_id: str,
        quote: Optional[QuoteSnapshot],
        feed_status: FeedStatus,
        now: datetime,
        orders: List[OrderRecord],
        fills: List[FillRecord],
        trades: List[TradeRecord],
        events: List[EventRecord],
    ) -> None:
        position = working.positions[instrument]
        close_time = candle.timestamp + self._interval
        quote_decision = self._risk.evaluate_execution_quote(
            instrument=instrument,
            quote=quote,
            feed_status=feed_status,
            now=now,
            data_time=close_time,
        )
        if not quote_decision.allowed:
            # Do not invent a fill price. The protective stop still applies on a
            # future candle; this exit is deferred until a usable quote exists.
            events.append(
                EventRecord(
                    event_time=now,
                    event_type="exit_deferred",
                    severity="warning",
                    message="signal exit deferred: quote/feed validation failed",
                    payload={
                        "instrument": instrument,
                        "signal_id": signal_id,
                        "reason": quote_decision.reason,
                    },
                )
            )
            return
        assert quote is not None
        fill = execute_at_quote(
            self._broker,
            instrument=instrument,
            side=OrderSide.SELL,
            quantity=position.quantity,
            quote=quote,
            when=now,
        )
        entry_signal_id = position.signal_id
        entry_price = position.entry_price
        entry_time = position.entry_time
        entry_fee = position.entry_fee
        entry_slippage = position.entry_slippage
        working.apply_sell(
            instrument=instrument,
            quantity=fill.quantity,
            fill_price=fill.price,
            fee=fill.fee,
            slippage_cost=fill.slippage_cost,
        )
        self._record_exit(
            signal_id, instrument, fill, INTENT_SIGNAL_EXIT, quote.bid, now,
            entry_signal_id, entry_price, entry_time, entry_fee, entry_slippage,
            EXIT_SIGNAL, orders, fills, trades, quote=quote,
        )

    def _record_exit(
        self,
        signal_id: str,
        instrument: str,
        fill,
        intent: str,
        reference_price: float,
        now: datetime,
        entry_signal_id: str,
        entry_price: float,
        entry_time: datetime,
        entry_fee: float,
        entry_slippage: float,
        exit_reason: str,
        orders: List[OrderRecord],
        fills: List[FillRecord],
        trades: List[TradeRecord],
        quote: Optional[QuoteSnapshot] = None,
    ) -> None:
        client_order_id = order_id_for(signal_id, intent)
        orders.append(
            OrderRecord(
                client_order_id=client_order_id,
                signal_id=signal_id,
                instrument=instrument,
                side=OrderSide.SELL,
                intent=intent,
                quantity=fill.quantity,
                reference_price=reference_price,
                order_time=now,
                quote_bid=quote.bid if quote is not None else None,
                quote_ask=quote.ask if quote is not None else None,
                quote_time=quote.timestamp if quote is not None else None,
            )
        )
        fills.append(
            FillRecord(
                fill_id=fill_id_for(client_order_id),
                client_order_id=client_order_id,
                instrument=instrument,
                side=OrderSide.SELL,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                slippage_cost=fill.slippage_cost,
                fill_time=now,
            )
        )
        gross = (fill.price - entry_price) * fill.quantity
        realized = gross - entry_fee - fill.fee
        trades.append(
            TradeRecord(
                instrument=instrument,
                entry_time=entry_time,
                exit_time=now,
                entry_price=entry_price,
                exit_price=fill.price,
                quantity=fill.quantity,
                fees=entry_fee + fill.fee,
                slippage_cost=entry_slippage + fill.slippage_cost,
                exit_reason=exit_reason,
                realized_pnl=realized,
                entry_signal_id=entry_signal_id,
                exit_signal_id=signal_id,
            )
        )

    @staticmethod
    def _assert_finite(account: PaperAccount, snapshot: EquitySnapshotRecord) -> None:
        for label, value in (
            ("cash", account.cash),
            ("equity", snapshot.equity),
            ("realized_pnl", snapshot.realized_pnl),
            ("unrealized_pnl", snapshot.unrealized_pnl),
        ):
            if not isfinite(value):
                raise ValueError(f"paper engine produced non-finite {label}")
        for position in account.positions.values():
            if not (isfinite(position.quantity) and isfinite(position.entry_price)):
                raise ValueError("paper engine produced a non-finite position value")
