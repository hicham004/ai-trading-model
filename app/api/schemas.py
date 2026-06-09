"""Pydantic response models for the API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_env: str
    live_trading_enabled: bool


class CandleOut(BaseModel):
    instrument: str
    timeframe: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    # Let Pydantic read attributes off SQLAlchemy ORM objects.
    model_config = {"from_attributes": True}


class CandleListResponse(BaseModel):
    instrument: str
    timeframe: str
    count: int
    candles: List[CandleOut]


class PersistedOrderBookOut(BaseModel):
    instrument: str
    channel: str
    exchange_time: datetime
    sequence_id: int
    depth: int
    best_bid: float
    best_ask: float
    bids: List[List[float | int]]
    asks: List[List[float | int]]


class PersistedOrderBookListResponse(BaseModel):
    instrument: str
    count: int
    snapshots: List[PersistedOrderBookOut]


# --- Phase 4: read-only paper-trading observation models -------------------
# Everything below describes VIRTUAL, SIMULATION-ONLY state read from the
# paper-trading ledger. There are no order-placement / modify / cancel fields.


_PAPER_NOTE = "Local paper trading (SIMULATION ONLY). No real or demo orders, accounts, or funds."


class PaperHealthOut(BaseModel):
    """Cross-process runtime health for a paper account (read-only)."""

    account: str
    exists: bool
    status: str
    running: bool
    kill_switch_engaged: bool
    feed_connected: bool
    feed_stale: bool
    books_synchronized: bool
    reconciliation_consistent: bool
    last_error: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    note: str = _PAPER_NOTE


class PaperPositionOut(BaseModel):
    instrument: str
    quantity: float
    entry_price: float
    stop_loss: Optional[float] = None
    entry_time: Optional[datetime] = None
    signal_id: str = ""


class PaperBalanceOut(BaseModel):
    asset: str
    amount: float


class PaperAccountOut(BaseModel):
    account: str
    exists: bool
    base_currency: str = "USDT"
    starting_cash: float = 0.0
    cash: float = 0.0
    position_value: float = 0.0
    equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    day_start_equity: float = 0.0
    day_realized_pnl: float = 0.0
    open_position_count: int = 0
    kill_switch_engaged: bool = False
    as_of: Optional[datetime] = None
    note: str = _PAPER_NOTE


class PaperBalancesOut(BaseModel):
    account: str
    balances: List[PaperBalanceOut]
    note: str = _PAPER_NOTE


class PaperPositionsOut(BaseModel):
    account: str
    positions: List[PaperPositionOut]
    note: str = _PAPER_NOTE


class PaperSignalOut(BaseModel):
    signal_id: str
    instrument: str
    timeframe: str
    signal_data_time: datetime
    candle_close_time: datetime
    decision_time: datetime
    action: str
    confidence: float
    reason: str
    stop_loss: Optional[float] = None


class PaperRiskDecisionOut(BaseModel):
    signal_id: str
    decision_time: datetime
    intent: str
    allowed: bool
    reason: str


class PaperOrderOut(BaseModel):
    client_order_id: str
    signal_id: str
    instrument: str
    side: str
    intent: str
    quantity: float
    reference_price: float
    quote_bid: Optional[float] = None
    quote_ask: Optional[float] = None
    quote_time: Optional[datetime] = None
    order_time: datetime
    status: str


class PaperFillOut(BaseModel):
    fill_id: str
    client_order_id: str
    instrument: str
    side: str
    quantity: float
    price: float
    fee: float
    slippage_cost: float
    fill_time: datetime
    is_simulated: bool


class PaperTradeOut(BaseModel):
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


class PaperEventOut(BaseModel):
    event_time: datetime
    event_type: str
    severity: str
    message: str


class PaperDailyReportRow(BaseModel):
    day: str
    num_trades: int
    wins: int
    realized_pnl: float
    fees: float
    slippage_cost: float


class PaperDailyReportOut(BaseModel):
    account: str
    equity: float
    realized_pnl: float
    days: List[PaperDailyReportRow]
    note: str = _PAPER_NOTE
