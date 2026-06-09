"""Normalized live market-data types and read-only API response models.

Two layers live here:

* Exchange-neutral *update* dataclasses (``TickerUpdate``, ``TradeUpdate``,
  ``CandleUpdate``) that adapters emit and the market state stores. They carry
  no exchange-specific protocol details.
* Pydantic *output* models used by the read-only FastAPI endpoints.

Everything here is observation only. There are no order, account, or trading
fields anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class UpdateType(str, Enum):
    """Kinds of public market-data update we observe."""

    TICKER = "ticker"
    TRADE = "trade"
    CANDLE = "candle"


class ConnectionStatus(str, Enum):
    """Lifecycle status of a live market-data connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"


# --- exchange-neutral update value objects ---------------------------------


@dataclass(frozen=True)
class TickerUpdate:
    """Latest best-price snapshot for an instrument (timestamp in UTC)."""

    instrument: str
    timestamp: datetime
    last: float
    bid: float
    ask: float


@dataclass(frozen=True)
class TradeUpdate:
    """A single public trade print (timestamp in UTC)."""

    instrument: str
    timestamp: datetime
    price: float
    size: float
    side: str  # "buy" or "sell" as reported by the venue
    trade_id: str


@dataclass(frozen=True)
class CandleUpdate:
    """A public OHLCV candle update (bar open time in UTC)."""

    instrument: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool


# --- read-only API output models -------------------------------------------


class TickerOut(BaseModel):
    instrument: str
    timestamp: datetime
    last: float
    bid: float
    ask: float


class TradeOut(BaseModel):
    instrument: str
    timestamp: datetime
    price: float
    size: float
    side: str
    trade_id: str


class CandleOut(BaseModel):
    instrument: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool


class FeedHealthOut(BaseModel):
    """Per-feed (per-connection) health for one live public feed."""

    feed_id: str
    status: ConnectionStatus
    # ``connected`` is True only when the feed's socket is CONNECTED AND every
    # required subscription has been acknowledged.
    connected: bool
    stale: bool
    last_transport_time: Optional[datetime]  # any frame (incl. heartbeats)
    last_market_data_time: Optional[datetime]  # only accepted ticker/trade/candle
    seconds_since_market_data: Optional[float]
    required_subscriptions: List[str]
    acked_subscriptions: List[str]


class LiveHealthOut(BaseModel):
    """Aggregate connection/freshness health across all required feeds.

    Aggregate health fails closed: ``connected`` is True only when every
    registered feed is connected and fully acknowledged, and ``stale`` is True
    if any feed is stale (or if no feeds are registered yet).
    """

    source: str
    status: ConnectionStatus
    connected: bool
    stale: bool
    # Latest accepted market-data time across feeds (freshness, not transport).
    last_message_time: Optional[datetime]
    seconds_since_last_message: Optional[float]
    # Union of every feed's required subscriptions (all retained, never lost).
    subscriptions: List[str]
    feeds: List[FeedHealthOut]
    # Restated each response so the read-only contract is unmistakable.
    note: str = "Public market-data observation only. No trading or accounts."


class LiveStateOut(BaseModel):
    """Full snapshot of the latest observed public market data."""

    health: LiveHealthOut
    tickers: List[TickerOut]
    candles: List[CandleOut]
    recent_trades: List[TradeOut]
