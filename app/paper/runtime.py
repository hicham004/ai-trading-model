"""Async runtime/driver for Phase 4 paper trading (SIMULATION ONLY).

The runtime bridges the live PUBLIC market state (Phase 3) to the deterministic
forward-time engine, and persists every outcome through the ledger. It:

* acquires a single-runner advisory lock so two runners cannot drive one
  account;
* reconciles the ledger on startup and refuses to trade if it is inconsistent
  (fail closed);
* warms strategies up from persisted public candle history without retrading;
* polls the in-memory state for NEW confirmed candles and processes each one
  through ``engine -> ledger -> commit`` exactly once, in order;
* publishes cross-process runtime status (health, kill switch, feed flags,
  reconciliation result) and heartbeats the lock;
* runs the public WebSocket stream and the paper loop as supervised tasks and
  shuts them down gracefully.

The core stepping logic (:meth:`poll_once`) is synchronous and pure with
respect to I/O timing, so it is fully testable offline with fake data, fake
clocks, and a temporary database. The runtime opens no network connection
during import or construction.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.live.market_state import MarketState
from app.logging_config import get_logger
from app.paper.config import PaperRunConfig
from app.paper.engine import PaperTradingEngine
from app.paper.execution import FeedStatus, QuoteSnapshot
from app.paper.ledger import (
    CandleAlreadyPersisted,
    KillSwitchEngaged,
    PaperLedger,
)
from app.paper.records import CandleOutcome, EventRecord
from app.strategy.base import MarketCandle

logger = get_logger(__name__)


class PaperRuntimeError(RuntimeError):
    """Raised when the runtime cannot start or must stop (fail closed)."""


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class PaperTradingRuntime:
    """Drives the forward paper-trading loop against live public market data."""

    def __init__(
        self,
        *,
        config: PaperRunConfig,
        state: MarketState,
        engine: PaperTradingEngine,
        ledger: PaperLedger,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = _utcnow,
        lock_token: Optional[str] = None,
        kill_switch_on_start: bool = False,
    ) -> None:
        self._config = config
        self._state = state
        self._engine = engine
        self._ledger = ledger
        self._session_factory = session_factory
        self._clock = clock
        self._token = lock_token or uuid.uuid4().hex
        self._account_id: Optional[int] = None
        self._consistent = True
        self._kill_switch_on_start = kill_switch_on_start

    @property
    def engine(self) -> PaperTradingEngine:
        return self._engine

    @property
    def account_id(self) -> Optional[int]:
        return self._account_id

    # -- startup: lock + reconcile + warmup --------------------------------

    def prepare(self) -> bool:
        """Acquire the lock, reconcile, and warm up. Returns False if blocked.

        Fails closed: if another runner holds the lock, or the ledger is
        inconsistent, the runtime does not begin trading.
        """
        now = self._clock()
        self._account_id = self._ledger.ensure_account(
            self._config.starting_cash, self._config.config_snapshot()
        )
        if not self._ledger.acquire_lock(
            self._account_id,
            self._token,
            stale_after_seconds=self._config.lock_stale_seconds,
            now=now,
        ):
            logger.error(
                "another paper runner holds the account lock; refusing to start",
                extra={"account": self._config.account_name},
            )
            return False
        self._ledger.update_status(
            self._account_id,
            self._token,
            now=now,
            status="starting",
        )

        try:
            starting_cash = self._ledger.account_starting_cash(self._account_id)
            recon = self._ledger.reconcile(
                self._account_id,
                starting_cash,
                history_limit=self._config.window_size,
            )
            self._ledger.update_status(
                self._account_id,
                self._token,
                now=self._clock(),
                status="starting",
            )
            self._engine.adopt_account(recon.account)
            for instrument, watermark in recon.watermarks.items():
                self._engine.set_watermark(instrument, watermark)
            for instrument, close in recon.last_close.items():
                self._engine.set_last_close(instrument, close)
            self._engine.set_kill_switch(recon.kill_switch_engaged)
            self._consistent = recon.consistent
        except Exception:
            self._ledger.release_lock(
                self._account_id,
                self._token,
                now=self._clock(),
                status="startup_failed",
            )
            raise

        if not recon.consistent:
            self._ledger.record_event(
                self._account_id,
                EventRecord(
                    event_time=now,
                    event_type="reconcile_failed",
                    severity="error",
                    message="ledger reconciliation found inconsistent state; refusing to trade",
                    payload={"issues": recon.issues},
                ),
            )
            self._ledger.update_status(
                self._account_id,
                self._token,
                now=now,
                status="reconcile_failed",
                reconciliation_consistent=False,
                last_error="; ".join(recon.issues)[:256],
            )
            logger.error(
                "paper reconciliation inconsistent; refusing to trade",
                extra={"account": self._config.account_name, "issues": recon.issues},
            )
            self._ledger.release_lock(
                self._account_id,
                self._token,
                now=now,
                status="reconcile_failed",
            )
            return False

        try:
            if self._kill_switch_on_start:
                self._engine.set_kill_switch(True)
            self._warmup(recon.history)
            self._ledger.update_status(
                self._account_id,
                self._token,
                now=now,
                status="running",
                reconciliation_consistent=True,
                kill_switch_engaged=self._engine.kill_switch_engaged,
            )
            self._ledger.record_event(
                self._account_id,
                EventRecord(
                    event_time=now,
                    event_type="startup",
                    severity="info",
                    message="paper trading runtime started (SIMULATION ONLY)",
                    payload=self._config.config_snapshot(),
                ),
            )
        except Exception:
            self._ledger.release_lock(
                self._account_id,
                self._token,
                now=self._clock(),
                status="startup_failed",
            )
            raise
        return True

    def _warmup(
        self, ledger_history: dict[str, List[MarketCandle]]
    ) -> None:
        """Rebuild strategy context and reconcile offline candles."""
        from app.backtest.runner import load_market_candles

        for instrument in self._config.instruments:
            try:
                session = self._session_factory()
                try:
                    candles = load_market_candles(
                        session, instrument, self._config.timeframe
                    )
                finally:
                    session.close()
                watermark = self._engine.watermark(instrument)
                if watermark is None:
                    # Fresh paper account: existing public history is context,
                    # never a retrospective trading opportunity.
                    context = candles
                    recovery: List[MarketCandle] = []
                else:
                    external_context = [
                        candle for candle in candles
                        if candle.timestamp <= watermark
                    ]
                    recovery = [
                        candle for candle in candles
                        if candle.timestamp > watermark
                    ]
                    merged = {
                        candle.timestamp: candle for candle in external_context
                    }
                    for candle in ledger_history.get(instrument, []):
                        existing = merged.get(candle.timestamp)
                        if existing is not None and existing != candle:
                            raise PaperRuntimeError(
                                "stored public candle disagrees with the paper ledger"
                            )
                        merged[candle.timestamp] = candle
                    context = [
                        merged[timestamp] for timestamp in sorted(merged)
                    ]
                context = context[-self._config.window_size:]
                self._engine.seed_history(context)
                recovered = self._recover_offline_candles(recovery)
                logger.info(
                    "paper warmup seeded history",
                    extra={
                        "instrument": instrument,
                        "seeded": len(context),
                        "recovered": recovered,
                    },
                )
            except Exception as exc:
                logger.error(
                    "paper warmup/recovery failed; refusing to start",
                    extra={"instrument": instrument, "error_type": type(exc).__name__},
                )
                if self._account_id is not None:
                    self._ledger.record_event(
                        self._account_id,
                        EventRecord(
                            event_time=self._clock(),
                            event_type="warmup_failed",
                            severity="error",
                            message="warmup/recovery failed; refusing to start",
                            payload={"instrument": instrument, "error_type": type(exc).__name__},
                        ),
                    )
                raise

    def _recover_offline_candles(
        self, candles: Sequence[MarketCandle]
    ) -> int:
        """Persist outage recovery bars; only pre-existing stops may execute."""
        if self._account_id is None:
            raise PaperRuntimeError("offline recovery called before account bootstrap")
        recovered = 0
        observed_at = self._clock()
        for candle in candles:
            outcome = self._engine.process_recovery_candle(
                candle, observed_at=observed_at
            )
            if not outcome.accepted:
                raise PaperRuntimeError(
                    "offline candle recovery failed: "
                    f"{outcome.rejection_reason}"
                )
            self._ledger.persist_outcome(self._account_id, outcome)
            self._engine.commit(candle, outcome)
            self._ledger.update_status(
                self._account_id,
                self._token,
                now=self._clock(),
                status="starting",
            )
            recovered += 1
        return recovered

    # -- the loop step (synchronous, testable) -----------------------------

    def poll_once(self, now: Optional[datetime] = None) -> List[CandleOutcome]:
        """Process every NEW confirmed candle once. Returns accepted outcomes.

        Raises if a persist fails (the engine is NOT advanced for that candle,
        so it is retried on the next call and no partial state is left).
        """
        if self._account_id is None:
            raise PaperRuntimeError("poll_once called before prepare()")
        now = now or self._clock()
        self._refresh_kill_switch()

        health = self._state.health_snapshot()
        feed_status = FeedStatus(connected=health.connected, stale=health.stale)

        candidates = self._new_confirmed_candles()
        results: List[CandleOutcome] = []
        for candle in candidates:
            quote = self._quote_for(candle.instrument)
            outcome = self._engine.process_confirmed_candle(
                candle, quote=quote, feed_status=feed_status, now=now
            )
            if not outcome.accepted:
                if outcome.rejection_reason == "stale_candle":
                    outcome = self._engine.process_recovery_candle(
                        candle, observed_at=now
                    )
                    if not outcome.accepted:
                        raise PaperRuntimeError(
                            "stale-candle recovery failed: "
                            f"{outcome.rejection_reason}"
                        )
                    self._ledger.persist_outcome(self._account_id, outcome)
                    self._engine.commit(candle, outcome)
                    results.append(outcome)
                    continue
                if outcome.rejection_reason not in ("duplicate_candle", "out_of_order_candle"):
                    self._ledger.record_event(
                        self._account_id,
                        EventRecord(
                            event_time=now,
                            event_type="candle_rejected",
                            severity="warning",
                            message=f"rejected confirmed candle: {outcome.rejection_reason}",
                            payload={
                                "instrument": candle.instrument,
                                "open_time": candle.timestamp.isoformat(),
                                "reason": outcome.rejection_reason,
                            },
                        ),
                    )
                if outcome.rejection_reason == "candle_gap":
                    raise PaperRuntimeError(
                        "confirmed candle gap detected; halting paper runtime"
                    )
                continue
            try:
                self._ledger.persist_outcome(self._account_id, outcome)
            except KillSwitchEngaged:
                # The operator engaged the persisted switch after this poll's
                # read. Re-evaluate the same candle with entries blocked, then
                # persist the no-entry outcome atomically.
                self._engine.set_kill_switch(True)
                outcome = self._engine.process_confirmed_candle(
                    candle, quote=quote, feed_status=feed_status, now=now
                )
                self._ledger.persist_outcome(self._account_id, outcome)
            except CandleAlreadyPersisted:
                # Should be unreachable (watermark + lock prevent it). Surface
                # it loudly and stop rather than guess.
                self._ledger.record_event(
                    self._account_id,
                    EventRecord(
                        event_time=now,
                        event_type="duplicate_persist",
                        severity="error",
                        message="candle already persisted; halting to avoid divergence",
                        payload={"instrument": candle.instrument},
                    ),
                )
                raise PaperRuntimeError("candle already persisted; halting")
            self._engine.commit(candle, outcome)
            results.append(outcome)

        self._publish_status(now, feed_status, health.order_books_synchronized)
        return results

    def _refresh_kill_switch(self) -> None:
        """Re-read the persisted kill switch so an operator can engage it live."""
        if self._account_id is None:
            return
        from sqlalchemy import select

        from app.db.models import PaperRuntimeStatus

        session = self._session_factory()
        try:
            engaged = session.scalar(
                select(PaperRuntimeStatus.kill_switch_engaged).where(
                    PaperRuntimeStatus.account_id == self._account_id
                )
            )
        finally:
            session.close()
        if engaged is not None:
            self._engine.set_kill_switch(bool(engaged))

    def _new_confirmed_candles(self) -> List[MarketCandle]:
        instruments = set(self._config.instruments)
        timeframe = self._config.timeframe
        out: List[MarketCandle] = []
        for update in self._state.recent_confirmed_candles():
            if not update.confirmed:
                continue
            if update.instrument not in instruments or update.timeframe != timeframe:
                continue
            watermark = self._engine.watermark(update.instrument)
            if watermark is not None and update.timestamp <= watermark:
                continue
            out.append(
                MarketCandle(
                    instrument=update.instrument,
                    timestamp=update.timestamp,
                    open=update.open,
                    high=update.high,
                    low=update.low,
                    close=update.close,
                    volume=update.volume,
                    timeframe=update.timeframe,
                )
            )
        out.sort(key=lambda c: (c.timestamp, c.instrument))
        return out

    def _quote_for(self, instrument: str) -> Optional[QuoteSnapshot]:
        """Build a quote from the synchronized top of the public order book."""
        for book in self._state.latest_order_books(depth=1):
            if book.instrument != instrument:
                continue
            if not book.bids or not book.asks or book.timestamp is None:
                return None
            return QuoteSnapshot(
                instrument=instrument,
                bid=book.bids[0].price,
                ask=book.asks[0].price,
                timestamp=book.timestamp,
                synchronized=book.synchronized,
                source="order_book",
            )
        return None

    def _publish_status(
        self, now: datetime, feed_status: FeedStatus, books_synchronized: bool
    ) -> None:
        if self._account_id is None:
            return
        self._ledger.update_status(
            self._account_id,
            self._token,
            now=now,
            status="running",
            feed_connected=feed_status.connected,
            feed_stale=feed_status.stale,
            books_synchronized=books_synchronized,
            reconciliation_consistent=self._consistent,
        )

    # -- async orchestration ------------------------------------------------

    async def run(
        self,
        stop_event: asyncio.Event,
        *,
        stream_factory: Optional[Callable[[asyncio.Event], Awaitable[None]]] = None,
    ) -> int:
        """Run the supervised stream + paper loop until ``stop_event`` is set.

        ``stream_factory`` lets tests inject a fake public stream; by default
        the runtime opens the standard PUBLIC OKX WebSocket adapters.
        """
        if not await asyncio.to_thread(self.prepare):
            return 1

        stream_coro = (stream_factory or self._default_stream)(stop_event)
        stream_task = asyncio.create_task(stream_coro, name="paper-public-stream")
        loop_task = asyncio.create_task(
            self._paper_loop(stop_event), name="paper-trading-loop"
        )
        result = 0
        try:
            done, _ = await asyncio.wait(
                {stream_task, loop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if loop_task in done and not stop_event.is_set():
                # The loop exited on its own (e.g. a persist failure).
                result = 1
            if stream_task in done and not stop_event.is_set():
                result = 1
        finally:
            stop_event.set()
            for task in (stream_task, loop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stream_task, loop_task, return_exceptions=True)
            await asyncio.to_thread(self._shutdown)
        return result

    async def _paper_loop(self, stop_event: asyncio.Event) -> None:
        poll = self._config.poll_seconds
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(self.poll_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "paper loop step failed; stopping",
                    extra={"error_type": type(exc).__name__},
                )
                if self._account_id is not None:
                    try:
                        self._ledger.record_event(
                            self._account_id,
                            EventRecord(
                                event_time=self._clock(),
                                event_type="loop_error",
                                severity="error",
                                message="paper loop step failed; stopping",
                                payload={"error_type": type(exc).__name__},
                            ),
                        )
                        self._ledger.update_status(
                            self._account_id,
                            self._token,
                            now=self._clock(),
                            status="degraded",
                            last_error=type(exc).__name__,
                        )
                    except Exception:  # pragma: no cover - best effort
                        pass
                stop_event.set()
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass

    async def _default_stream(self, stop_event: asyncio.Event) -> None:
        from app.config import get_settings
        from app.exchange.okx_public_ws import build_default_adapters
        from app.live.runtime import run_live_runtime

        settings = get_settings()
        adapters = build_default_adapters(
            self._state,
            instruments=tuple(self._config.instruments),
            public_url=settings.okx_public_ws_url,
            business_url=settings.okx_business_ws_url,
        )
        await run_live_runtime(adapters, stop_event)

    def _shutdown(self) -> None:
        if self._account_id is None:
            return
        now = self._clock()
        try:
            self._ledger.record_event(
                self._account_id,
                EventRecord(
                    event_time=now,
                    event_type="shutdown",
                    severity="info",
                    message="paper trading runtime stopped",
                    payload={},
                ),
            )
            self._ledger.release_lock(self._account_id, self._token, now=now)
        except Exception:  # pragma: no cover - best effort on shutdown
            logger.warning("paper shutdown bookkeeping failed")


def build_paper_runtime(
    config: PaperRunConfig,
    *,
    state: Optional[MarketState] = None,
    session_factory: Optional[Callable[[], Session]] = None,
    clock: Callable[[], datetime] = _utcnow,
    kill_switch_on_start: bool = False,
) -> PaperTradingRuntime:
    """Wire a runtime from a validated config (no I/O until ``run``)."""
    from app.db.database import get_session_factory
    from app.live.market_state import MarketState as _MarketState
    from app.live.market_state import MarketStateConfig

    if session_factory is None:
        session_factory = get_session_factory()
    if state is None:
        from app.config import get_settings

        settings = get_settings()
        state = _MarketState(
            MarketStateConfig(stale_after_seconds=settings.live_stale_after_seconds)
        )
    engine = PaperTradingEngine(
        config=config.build_engine_config(),
        strategy=config.build_strategy(),
        risk_manager=config.build_risk_manager(),
        account=config.build_account(),
    )
    ledger = PaperLedger(session_factory, config.account_name)
    return PaperTradingRuntime(
        config=config,
        state=state,
        engine=engine,
        ledger=ledger,
        session_factory=session_factory,
        clock=clock,
        kill_switch_on_start=kill_switch_on_start,
    )
