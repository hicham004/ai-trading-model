"""SQLAlchemy ORM models.

Phase 1-3B store PUBLIC market data only (candles + sampled public order books).
Phase 4 adds the local paper-trading ledger/journal (``paper_*`` tables). Those
tables hold VIRTUAL, SIMULATION-ONLY balances, positions, orders, and fills.
There is no account credential, private endpoint, real order, or withdrawal
information anywhere in this module.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
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


# ---------------------------------------------------------------------------
# Phase 4: local paper-trading ledger / journal (SIMULATION ONLY).
#
# These tables are the auditable, restartable record of a forward paper-trading
# run. Every monetary effect of a confirmed candle (orders, fills, trades, and
# an equity snapshot) is written in a single transaction together with the
# ``paper_candles_processed`` marker, so a crash never leaves partial state and
# a candle is never processed twice. Reconstruction on restart replays fills and
# cross-checks the latest equity snapshot.
# ---------------------------------------------------------------------------


class PaperAccount(Base):
    """A named virtual paper-trading account. No real funds, ever."""

    __tablename__ = "paper_accounts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_paper_account_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    starting_cash: Mapped[float] = mapped_column(Float, nullable=False)
    # JSON snapshot of the run configuration (strategy, timeframe, costs, risk
    # limits) for audit. Contains no secrets.
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class PaperRuntimeStatus(Base):
    """Cross-process runtime health for one paper account (single row).

    The runner updates this; the read-only API reads it. ``lock_token`` plus
    ``lock_heartbeat`` provide an advisory lock so two runners do not drive the
    same account at once.
    """

    __tablename__ = "paper_runtime_status"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_paper_runtime_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="starting")
    kill_switch_engaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feed_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feed_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    books_synchronized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciliation_consistent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    last_error: Mapped[str] = mapped_column(String(256), nullable=True)
    lock_token: Mapped[str] = mapped_column(String(64), nullable=True)
    lock_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class PaperProcessedCandle(Base):
    """Processed candle identity plus OHLCV needed for restart reconstruction."""

    __tablename__ = "paper_candles_processed"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "instrument",
            "timeframe",
            "candle_open_time",
            name="uq_paper_processed_candle",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    candle_open_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    candle_close_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class PaperDailyBaseline(Base):
    """Immutable UTC-day starting equity used by the daily-loss lockout."""

    __tablename__ = "paper_daily_baselines"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "market_day", name="uq_paper_daily_baseline"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    market_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_equity: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class PaperSignal(Base):
    """A strategy signal recorded against the candle that produced it."""

    __tablename__ = "paper_signals"
    __table_args__ = (
        UniqueConstraint("account_id", "signal_id", name="uq_paper_signal_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    signal_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_data_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)


class PaperRiskDecision(Base):
    """The risk manager's verdict for one entry decision (audit of vetoes)."""

    __tablename__ = "paper_risk_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    signal_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperOrder(Base):
    """A virtual order. ``client_order_id`` is deterministic (idempotent)."""

    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "client_order_id", name="uq_paper_order_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    client_order_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(String(96), nullable=False)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    reference_price: Mapped[float] = mapped_column(Float, nullable=False)
    quote_bid: Mapped[float] = mapped_column(Float, nullable=True)
    quote_ask: Mapped[float] = mapped_column(Float, nullable=True)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    order_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="filled")


class PaperFill(Base):
    """A simulated fill. ``is_simulated`` is always True."""

    __tablename__ = "paper_fills"
    __table_args__ = (
        UniqueConstraint("account_id", "fill_id", name="uq_paper_fill_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    fill_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    client_order_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PaperTrade(Base):
    """A completed virtual round-trip (entry then exit). SIMULATION ONLY."""

    __tablename__ = "paper_trades"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "exit_signal_id", "instrument", name="uq_paper_trade_exit"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    exit_reason: Mapped[str] = mapped_column(String(24), nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    entry_signal_id: Mapped[str] = mapped_column(String(96), nullable=False)
    exit_signal_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)


class PaperEquitySnapshot(Base):
    """Equity/balance snapshot taken when a candle is processed."""

    __tablename__ = "paper_equity_snapshots"
    __table_args__ = (
        Index("ix_paper_equity_account_time", "account_id", "market_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    day_start_equity: Mapped[float] = mapped_column(Float, nullable=False)
    day_realized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    open_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    kill_switch_engaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PaperEvent(Base):
    """An append-only operational event / failure record for the runtime."""

    __tablename__ = "paper_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id"), nullable=False, index=True
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
