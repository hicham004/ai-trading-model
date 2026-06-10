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


# ---------------------------------------------------------------------------
# Phase 5: authenticated OKX DEMO (simulated) execution ledger (demo_* tables).
#
# These tables are the durable, auditable, restartable record of demo order
# intents and their exchange outcomes. No credential or secret is ever stored
# here (only a non-reversible key fingerprint hint). Monetary amounts and sizes
# are stored as exact decimal STRINGS, never floats. Deterministic client order
# ids give cross-restart idempotency; an ambiguous submission is resolved by
# querying the exchange by client order id, never by blind retry.
# ---------------------------------------------------------------------------


class DemoAccount(Base):
    """A named demo (simulated) execution account. No real funds, ever."""

    __tablename__ = "demo_accounts"
    __table_args__ = (UniqueConstraint("name", name="uq_demo_account_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Non-reversible hint (sha256[:8]) so a changed API key is detectable across
    # restarts WITHOUT storing any secret material.
    key_fingerprint: Mapped[str] = mapped_column(String(32), nullable=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class DemoRuntimeStatus(Base):
    """Cross-process runtime health, arming, kill switch, and the lock."""

    __tablename__ = "demo_runtime_status"
    __table_args__ = (UniqueConstraint("account_id", name="uq_demo_runtime_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    # Disarmed by default; arming sets an expiry. Entries are blocked unless
    # armed_until is in the future.
    armed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    kill_switch_engaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Fail closed: a freshly created demo runtime is NOT consistent until a
    # successful reconciliation sets it True.
    reconciliation_consistent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    feed_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feed_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ws_authenticated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_error: Mapped[str] = mapped_column(String(256), nullable=True)
    lock_token: Mapped[str] = mapped_column(String(64), nullable=True)
    lock_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class DemoOrderIntent(Base):
    """The durable order outbox / state projection (one row per logical order).

    ``client_order_id`` is deterministic and unique per account, giving
    idempotency across retries, reconnects, and restarts. ``status`` is the
    crash-safe lifecycle state.
    """

    __tablename__ = "demo_order_intents"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "client_order_id", name="uq_demo_intent_clordid"
        ),
        Index("ix_demo_intent_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    client_order_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(String(96), nullable=False)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    td_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="cash")
    ord_type: Mapped[str] = mapped_column(String(12), nullable=False, default="limit")
    price: Mapped[str] = mapped_column(String(40), nullable=True)
    size: Mapped[str] = mapped_column(String(40), nullable=False)
    stop_loss: Mapped[str] = mapped_column(String(40), nullable=True)
    exchange_order_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_submit")
    filled_size: Mapped[str] = mapped_column(String(40), nullable=False, default="0")
    avg_price: Mapped[str] = mapped_column(String(40), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(String(256), nullable=True)


class DemoSubmission(Base):
    """Append-only record of each place/cancel/amend attempt and its outcome."""

    __tablename__ = "demo_submissions"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "client_order_id",
            "request_kind",
            "attempt",
            name="uq_demo_submission",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    client_order_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange_order_id: Mapped[str] = mapped_column(String(64), nullable=True)
    code: Mapped[str] = mapped_column(String(16), nullable=True)
    message: Mapped[str] = mapped_column(String(256), nullable=True)


class DemoOrderUpdate(Base):
    """Append-only order-state update from a REST query or private WS."""

    __tablename__ = "demo_order_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    client_order_id: Mapped[str] = mapped_column(String(32), nullable=True, index=True)
    exchange_order_id: Mapped[str] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    filled_size: Mapped[str] = mapped_column(String(40), nullable=True)
    avg_price: Mapped[str] = mapped_column(String(40), nullable=True)
    fee: Mapped[str] = mapped_column(String(40), nullable=True)
    fee_ccy: Mapped[str] = mapped_column(String(16), nullable=True)
    update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)


class DemoFill(Base):
    """Append-only exchange fill. ``fill_id`` is the venue tradeId (unique)."""

    __tablename__ = "demo_fills"
    __table_args__ = (
        UniqueConstraint("account_id", "fill_id", name="uq_demo_fill_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    fill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_order_id: Mapped[str] = mapped_column(String(32), nullable=True, index=True)
    exchange_order_id: Mapped[str] = mapped_column(String(64), nullable=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    fill_size: Mapped[str] = mapped_column(String(40), nullable=False)
    fill_price: Mapped[str] = mapped_column(String(40), nullable=False)
    fee: Mapped[str] = mapped_column(String(40), nullable=True)
    fee_ccy: Mapped[str] = mapped_column(String(16), nullable=True)
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="ws")


class DemoBalanceSnapshot(Base):
    """A snapshot of demo account balances (per-currency JSON). No secrets."""

    __tablename__ = "demo_balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    balances_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="rest")


class DemoDailyBaseline(Base):
    """Immutable UTC-day starting equity for the demo daily-loss gate."""

    __tablename__ = "demo_daily_baselines"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "market_day", name="uq_demo_daily_baseline"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    market_day: Mapped[date] = mapped_column(Date, nullable=False)
    starting_equity: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class DemoReconciliation(Base):
    """Result of one exchange-authoritative reconciliation run."""

    __tablename__ = "demo_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consistent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    foreign_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unexplained_balances: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issues_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class DemoEvent(Base):
    """An append-only operational event / failure record (no secrets)."""

    __tablename__ = "demo_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), nullable=False, index=True
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
