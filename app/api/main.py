"""FastAPI application exposing stored public candle data (read-only).

Run locally with::

    uvicorn app.api.main:app --reload

Interactive docs are then available at http://localhost:8000/docs

Safety: this API is strictly read-only over PUBLIC market data. There are no
endpoints for trading, orders, accounts, or withdrawals.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Iterator, List

from fastapi import Depends, FastAPI, Query
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.api.schemas import CandleListResponse, CandleOut, HealthResponse
from app.config import get_settings
from app.db.database import get_session_factory, init_db
from app.db.models import Candle
from app.logging_config import configure_logging, get_logger
from app.okx.client import ALLOWED_INSTRUMENTS

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging and ensure tables exist when the app starts."""
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    logger.info("API startup complete", extra={"app_env": settings.app_env})
    yield


app = FastAPI(
    title="AI Trading Model - Phase 1 Research API",
    description=(
        "Read-only API over locally stored PUBLIC OKX candle data. "
        "No trading, account, or order functionality (Phase 1)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a database session per request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness check plus a confirmation that live trading stays disabled."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        live_trading_enabled=settings.live_trading_enabled,
    )


@app.get("/instruments", response_model=List[str], tags=["market-data"])
def list_instruments(db: Session = Depends(get_db)) -> List[str]:
    """Return the instruments that currently have stored candles."""
    stored = db.scalars(select(distinct(Candle.instrument))).all()
    # Show allowed instruments first, then anything else already stored.
    return sorted(stored, key=lambda i: (i not in ALLOWED_INSTRUMENTS, i))


@app.get("/candles", response_model=CandleListResponse, tags=["market-data"])
def get_candles(
    instrument: str = Query("BTC-USDT", description="e.g. BTC-USDT"),
    timeframe: str = Query("1H", description="OKX bar size, e.g. 1H"),
    limit: int = Query(100, ge=1, le=1000, description="Max candles to return"),
    db: Session = Depends(get_db),
) -> CandleListResponse:
    """Return the most recent stored candles for an instrument/timeframe.

    Candles are returned oldest-first so they are easy to chart.
    """
    rows = db.scalars(
        select(Candle)
        .where(Candle.instrument == instrument, Candle.timeframe == timeframe)
        .order_by(Candle.open_time.desc())
        .limit(limit)
    ).all()

    # We queried newest-first to honour ``limit``; reverse to oldest-first.
    rows = list(reversed(rows))

    return CandleListResponse(
        instrument=instrument,
        timeframe=timeframe,
        count=len(rows),
        candles=[CandleOut.model_validate(row) for row in rows],
    )
