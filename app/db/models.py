"""SQLAlchemy ORM models for public candles and sampled public order books."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


class Candle(Base):
    """A single OHLCV candlestick for one instrument and timeframe.

    The ``(instrument, timeframe, open_time)`` combination is unique so the
    same candle can never be stored twice (see the ingest layer, which also
    skips duplicates before inserting).
    """

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "instrument", "timeframe", "open_time", name="uq_candle_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # e.g. "BTC-USDT"
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # OKX bar size, e.g. "1H"
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    # Candle open time, stored in UTC.
    open_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    # When this row was written locally (UTC).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return (
            f"<Candle {self.instrument} {self.timeframe} "
            f"{self.open_time.isoformat()} close={self.close}>"
        )


class OrderBookSnapshot(Base):
    """A sampled, sequence-validated public order-book snapshot.

    Phase 3B stores only bounded depth from the reconstructed public book. The
    JSON fields contain arrays of ``[price, size, order_count]`` values and no
    account or order information.
    """

    __tablename__ = "order_book_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "instrument",
            "exchange_time",
            "sequence_id",
            name="uq_order_book_snapshot_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="books")
    exchange_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sequence_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    best_bid: Mapped[float] = mapped_column(Float, nullable=False)
    best_ask: Mapped[float] = mapped_column(Float, nullable=False)
    bids_json: Mapped[str] = mapped_column(Text, nullable=False)
    asks_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
