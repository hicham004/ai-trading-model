"""Pydantic response models for the API."""

from __future__ import annotations

from datetime import datetime
from typing import List

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
