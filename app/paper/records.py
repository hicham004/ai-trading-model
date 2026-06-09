"""Immutable outcome records for one processed confirmed candle.

The forward-time engine is a *pure* function of its inputs: given a confirmed
candle (plus a quote, feed status, and clock) it returns a :class:`CandleOutcome`
describing everything that should happen - the signal, risk decisions, virtual
orders, simulated fills, completed trades, operational events, and the resulting
equity snapshot - WITHOUT mutating engine state. The ledger then persists the
whole outcome in a single transaction, and only on success does the engine
adopt the new account state. This separation is what makes the loop atomic,
restartable, and free of partial state.

Every identifier here is deterministic (derived from the candle identity), so
reprocessing a candle would produce identical IDs and be rejected by the
ledger's uniqueness constraints (idempotency).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.broker.base import OrderSide
from app.paper.account import PaperAccount

# Order/decision intents (audit-friendly, stable strings).
INTENT_ENTRY = "entry"
INTENT_SIGNAL_EXIT = "signal_exit"
INTENT_STOP_EXIT = "stop_exit"

# Trade exit reasons.
EXIT_SIGNAL = "signal"
EXIT_STOP_LOSS = "stop_loss"


def signal_id_for(instrument: str, timeframe: str, open_time: datetime) -> str:
    """Deterministic signal identity: one decision per candle."""
    return f"{instrument}|{timeframe}|{open_time.isoformat()}"


def order_id_for(signal_id: str, intent: str) -> str:
    """Deterministic order identity (at most one per intent per candle)."""
    return f"{signal_id}|{intent}"


def fill_id_for(client_order_id: str) -> str:
    """Deterministic fill identity for a (one-shot) virtual order."""
    return f"{client_order_id}|fill"


@dataclass(frozen=True)
class SignalRecord:
    signal_id: str
    instrument: str
    timeframe: str
    signal_data_time: datetime  # source candle OPEN time
    candle_close_time: datetime  # source candle CLOSE time (data complete)
    decision_time: datetime
    action: str
    confidence: float
    reason: str
    stop_loss: Optional[float]


@dataclass(frozen=True)
class RiskDecisionRecord:
    signal_id: str
    decision_time: datetime
    intent: str
    allowed: bool
    reason: str


@dataclass(frozen=True)
class OrderRecord:
    client_order_id: str
    signal_id: str
    instrument: str
    side: OrderSide
    intent: str
    quantity: float
    reference_price: float
    order_time: datetime
    quote_bid: Optional[float] = None
    quote_ask: Optional[float] = None
    quote_time: Optional[datetime] = None
    status: str = "filled"


@dataclass(frozen=True)
class FillRecord:
    fill_id: str
    client_order_id: str
    instrument: str
    side: OrderSide
    quantity: float
    price: float
    fee: float
    slippage_cost: float
    fill_time: datetime
    is_simulated: bool = True


@dataclass(frozen=True)
class TradeRecord:
    instrument: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    fees: float
    slippage_cost: float
    exit_reason: str
    realized_pnl: float
    entry_signal_id: str
    exit_signal_id: str


@dataclass(frozen=True)
class EventRecord:
    event_time: datetime
    event_type: str
    severity: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EquitySnapshotRecord:
    snapshot_time: datetime
    market_time: datetime
    cash: float
    position_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    day_start_equity: float
    day_realized_pnl: float
    open_position_count: int
    positions: List[Dict[str, Any]]
    kill_switch_engaged: bool


@dataclass
class CandleOutcome:
    """The full, atomically-persistable result of processing one candle."""

    instrument: str
    timeframe: str
    candle_open_time: datetime
    candle_close_time: datetime
    accepted: bool
    rejection_reason: Optional[str] = None
    candle_open: Optional[float] = None
    candle_high: Optional[float] = None
    candle_low: Optional[float] = None
    candle_close: Optional[float] = None
    candle_volume: Optional[float] = None
    account: Optional[PaperAccount] = None
    last_close: Optional[float] = None
    signal: Optional[SignalRecord] = None
    risk_decisions: List[RiskDecisionRecord] = field(default_factory=list)
    orders: List[OrderRecord] = field(default_factory=list)
    fills: List[FillRecord] = field(default_factory=list)
    trades: List[TradeRecord] = field(default_factory=list)
    events: List[EventRecord] = field(default_factory=list)
    equity_snapshot: Optional[EquitySnapshotRecord] = None

    @property
    def traded(self) -> bool:
        return bool(self.fills)
