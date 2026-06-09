"""Read-only FastAPI router for live PUBLIC market-data observation (Phase 3A).

These endpoints expose the in-memory :class:`MarketState` only. They are
strictly read-only: there are no endpoints that trade, place orders, touch an
account, or open a connection. Importing this module opens no WebSocket; the
stream is started separately (the standalone runner, or the app's opt-in
autostart).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query

from app.live.market_state import MarketState, get_market_state
from app.live.schemas import (
    FeedHealthOut,
    LiveHealthOut,
    LiveStateOut,
    TickerOut,
    TradeOut,
)
from app.okx.client import ALLOWED_INSTRUMENTS

router = APIRouter(prefix="/live", tags=["live-market-data"])


def get_state() -> MarketState:
    """Dependency returning the process-wide live market state."""
    return get_market_state()


@router.get("/health", response_model=LiveHealthOut)
def live_health(state: MarketState = Depends(get_state)) -> LiveHealthOut:
    """Connection status, freshness, and subscriptions for the live feed."""
    return state.health_snapshot()


@router.get("/feeds", response_model=List[FeedHealthOut])
def live_feeds(state: MarketState = Depends(get_state)) -> List[FeedHealthOut]:
    """Per-connection health for the required public and business feeds."""
    return state.all_feed_health()


@router.get("/state", response_model=LiveStateOut)
def live_state(
    trade_limit: int = Query(50, ge=1, le=500),
    state: MarketState = Depends(get_state),
) -> LiveStateOut:
    """Full snapshot: health, latest tickers/candles, and recent trades."""
    return state.state_snapshot(trade_limit=trade_limit)


@router.get("/tickers", response_model=List[TickerOut])
def live_tickers(state: MarketState = Depends(get_state)) -> List[TickerOut]:
    """Latest ticker per observed instrument."""
    return [TickerOut(**vars(t)) for t in state.latest_tickers()]


@router.get("/trades", response_model=List[TradeOut])
def live_trades(
    limit: int = Query(50, ge=1, le=500),
    state: MarketState = Depends(get_state),
) -> List[TradeOut]:
    """Most recent observed public trades (bounded window)."""
    return [TradeOut(**vars(t)) for t in state.recent_trades(limit=limit)]


@router.get("/instruments", response_model=List[str])
def live_instruments() -> List[str]:
    """Instruments supported by the live public feed (BTC-USDT, ETH-USDT)."""
    return list(ALLOWED_INSTRUMENTS)
