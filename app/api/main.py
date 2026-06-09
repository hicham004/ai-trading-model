"""FastAPI application exposing stored public candle data (read-only).

Run locally with::

    uvicorn app.api.main:app --reload

Interactive docs are then available at http://localhost:8000/docs

Safety: this API is strictly read-only over PUBLIC market data. There are no
endpoints for trading, orders, accounts, or withdrawals.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import Iterator, List

from fastapi import Depends, FastAPI, Query
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.api.live import router as live_router
from app.api.schemas import CandleListResponse, CandleOut, HealthResponse
from app.config import get_settings
from app.db.database import get_session_factory, init_db
from app.db.models import Candle
from app.logging_config import configure_logging, get_logger
from app.okx.client import ALLOWED_INSTRUMENTS

logger = get_logger(__name__)


def _report_live_task_result(task: asyncio.Task) -> None:
    """Consume and report unexpected autostart task failures."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "live public market-data autostart task failed",
            extra={"error_type": type(error).__name__},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging and ensure tables exist when the app starts.

    The live PUBLIC market-data stream is only opened in-process when
    ``LIVE_WS_AUTOSTART`` is explicitly enabled. By default it stays off, so
    importing this module or starting the app in tests never opens a WebSocket.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    logger.info("API startup complete", extra={"app_env": settings.app_env})

    live_task = None
    live_stop = None
    if settings.live_ws_autostart:
        # Imported lazily so the WS machinery is only touched when opted in.
        from app.exchange.okx_public_ws import build_default_adapters, run_adapters
        from app.live.market_state import get_market_state

        live_stop = asyncio.Event()
        adapters = build_default_adapters(
            get_market_state(),
            public_url=settings.okx_public_ws_url,
            business_url=settings.okx_business_ws_url,
        )
        live_task = asyncio.create_task(run_adapters(adapters, live_stop))
        live_task.add_done_callback(_report_live_task_result)
        logger.info("live public market-data stream autostarted")

    try:
        yield
    finally:
        if live_stop is not None:
            live_stop.set()
        if live_task is not None:
            live_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await live_task


app = FastAPI(
    title="AI Trading Model - Research and Live Observation API",
    description=(
        "Read-only API over stored and live PUBLIC OKX market data. "
        "No trading, account, or order functionality."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

# Read-only Phase 3A live public market-data endpoints (under /live).
app.include_router(live_router)


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
