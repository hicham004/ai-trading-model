"""Fetch public candles from OKX and store them in the local database.

Duplicate candles are skipped: we look up which ``(instrument, timeframe,
open_time)`` rows already exist and only insert the new ones. The unique
constraint on the table is a second line of defence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Candle as CandleRow
from app.logging_config import get_logger
from app.okx.client import Candle as ApiCandle
from app.okx.client import OKXPublicClient

logger = get_logger(__name__)


def _to_naive_utc(value: datetime) -> datetime:
    """Return a timezone-naive UTC datetime for backend-agnostic comparison.

    We always store candle times in UTC, but databases differ in what they
    return: PostgreSQL gives timezone-aware datetimes while SQLite gives naive
    ones. Normalising both the stored and incoming times to naive-UTC lets us
    compare them reliably when detecting duplicates.
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass(frozen=True)
class IngestResult:
    """Summary of one ingest run for a single instrument/timeframe."""

    instrument: str
    timeframe: str
    fetched: int
    inserted: int
    skipped_duplicates: int


def store_candles(
    session: Session,
    instrument: str,
    timeframe: str,
    api_candles: Sequence[ApiCandle],
) -> IngestResult:
    """Insert ``api_candles`` into the database, skipping ones already present.

    This function does not commit; the caller controls the transaction (see
    ``session_scope`` in ``app.db.database``).
    """
    fetched = len(api_candles)
    if fetched == 0:
        return IngestResult(instrument, timeframe, 0, 0, 0)

    # Find which open_times already exist for this instrument/timeframe so we
    # never insert a duplicate.
    candidate_times = [c.timestamp for c in api_candles]
    existing_times = {
        _to_naive_utc(stored)
        for stored in session.scalars(
            select(CandleRow.open_time).where(
                CandleRow.instrument == instrument,
                CandleRow.timeframe == timeframe,
                CandleRow.open_time.in_(candidate_times),
            )
        ).all()
    }

    seen_times = set(existing_times)
    new_rows: List[CandleRow] = []
    for candle in api_candles:
        if candle.instrument != instrument or candle.timeframe != timeframe:
            raise ValueError(
                "Candle identity does not match the requested instrument/timeframe"
            )

        candle_time = _to_naive_utc(candle.timestamp)
        if candle_time in seen_times:
            continue
        seen_times.add(candle_time)
        new_rows.append(
            CandleRow(
                instrument=candle.instrument,
                timeframe=candle.timeframe,
                open_time=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
        )

    session.add_all(new_rows)
    session.flush()  # surface integrity errors now, while we still have context

    result = IngestResult(
        instrument=instrument,
        timeframe=timeframe,
        fetched=fetched,
        inserted=len(new_rows),
        skipped_duplicates=fetched - len(new_rows),
    )
    logger.info(
        "Stored candles",
        extra={
            "instrument": instrument,
            "timeframe": timeframe,
            "fetched": result.fetched,
            "inserted": result.inserted,
            "skipped_duplicates": result.skipped_duplicates,
        },
    )
    return result


def fetch_and_store(
    session: Session,
    client: OKXPublicClient,
    instrument: str,
    timeframe: str = "1H",
    limit: int = 100,
) -> IngestResult:
    """Fetch candles from OKX and store the new ones. Returns a summary."""
    api_candles = client.get_candles(instrument, timeframe=timeframe, limit=limit)
    return store_candles(session, instrument, timeframe, api_candles)
