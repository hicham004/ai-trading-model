"""Long-running Phase 5 demo-trading driver (disarmed by default, fail closed).

This is the integration layer that connects the accepted Phase 4 market data,
strategy, and risk manager to the Phase 5 demo execution lifecycle. It:

* acquires and continuously heartbeats the exact runtime lock;
* synchronizes server time and validates the demo account before arming;
* runs ONE fail-closed startup gate (resolve open intents -> reconcile ->
  refuse while any ambiguous order remains);
* starts the public market-data stream and the authenticated private-order
  stream;
* rebuilds Phase 4 strategy history safely (context only, never retraded);
* processes confirmed 1m candles forward only, evaluates the approved strategy
  and deterministic risk veto, and submits only through DemoExecutionRuntime /
  OrderLifecycle;
* projects private order updates and REST fills durably;
* periodically reconciles exchange truth;
* fails closed on stale feeds, a lost lock, foreign/unknown activity, or an
  inconsistent ledger, and never auto-arms.

The synchronous core (:meth:`startup_gate`, :meth:`step`,
:meth:`project_private_orders`) is fully testable offline; network access is
confined to the injected REST client, private WS, and public market state.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Deque, Dict, List, Optional

from app.config import Settings, get_settings
from app.exchange.credentials import DemoCredentials
from app.exchange.instruments import InstrumentMeta
from app.execution.account_validation import validate_demo_account
from app.execution.ids import CLIENT_ORDER_PREFIX
from app.execution.identity import demo_identity_config
from app.execution.lifecycle import INTENT_ENTRY, OrderLifecycle
from app.execution.reconcile import DemoReconciler
from app.execution.runtime import DemoExecutionRuntime, EntryContext
from app.execution.store import (
    STATUS_UNKNOWN,
    DemoStore,
    map_okx_state,
)
from app.live.market_state import MarketState
from app.logging_config import get_logger
from app.paper.execution import FeedStatus, QuoteSnapshot
from app.strategy.base import MarketCandle, SignalAction
from app.strategy.registry import build_strategy

logger = get_logger(__name__)


def _dec(value: object) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


@dataclass
class GateOutcome:
    lock_acquired: bool
    account_valid: bool
    consistent: bool
    armable: bool
    issues: List[str] = field(default_factory=list)


class DemoTradingDriver:
    """Supervised demo-trading runtime built from accepted repository pieces."""

    def __init__(
        self,
        *,
        credentials: DemoCredentials,
        rest,
        session_factory: Callable,
        settings: Optional[Settings] = None,
        market_state: Optional[MarketState] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
        private_ws_factory: Optional[Callable] = None,
        public_stream_factory: Optional[Callable] = None,
        account_selection_explicit: bool = True,
    ) -> None:
        self._settings = settings or get_settings()
        self._credentials = credentials
        self._account_selection_explicit = account_selection_explicit
        self._rest = rest
        self._session_factory = session_factory
        self._clock = clock
        self._instruments = tuple(self._settings.demo_instruments)
        self._timeframe = self._settings.demo_timeframe
        self._quote_ccy = self._settings.demo_quote_currency

        self._store = DemoStore(session_factory, self._settings.demo_account_name)
        self._account_id = self._store.ensure_account(
            credentials.key_fingerprint(), demo_identity_config(self._settings)
        )
        self._token = uuid.uuid4().hex
        self._lifecycle = OrderLifecycle(
            self._store,
            rest,
            self._account_id,
            self._settings.demo_account_name,
            lock_token=self._token,
            clock=clock,
        )
        self._reconciler = DemoReconciler(
            self._store, rest, session_factory, self._account_id,
            instruments=self._instruments,
            key_fingerprint=credentials.key_fingerprint(),
            clock=clock,
        )
        self._runtime = DemoExecutionRuntime(
            store=self._store, lifecycle=self._lifecycle, reconciler=self._reconciler,
            account_id=self._account_id, token=self._token, settings=self._settings, clock=clock,
        )
        self._strategy = build_strategy(self._settings.demo_strategy)
        self._windows: Dict[str, Deque[MarketCandle]] = {
            inst: deque(maxlen=self._settings.paper_window_size) for inst in self._instruments
        }
        self._watermark: Dict[str, datetime] = {}
        self._instrument_meta: Dict[str, InstrumentMeta] = {}
        self._balances: Dict[str, Decimal] = {}
        self._market_state = market_state or MarketState()
        self._private_ws_factory = private_ws_factory
        self._public_stream_factory = public_stream_factory
        self._private_authenticated = False
        self._private_last_msg: Optional[datetime] = None
        self._market_continuity = {inst: True for inst in self._instruments}
        self._needs_reconcile = False

    @property
    def runtime(self) -> DemoExecutionRuntime:
        return self._runtime

    @property
    def rest(self):
        return self._rest

    @property
    def lifecycle(self) -> OrderLifecycle:
        return self._lifecycle

    @property
    def store(self) -> DemoStore:
        return self._store

    @property
    def account_id(self) -> int:
        return self._account_id

    def release_lock(self) -> None:
        self._store.release_lock(self._account_id, self._token, now=self._clock())

    @property
    def token(self) -> str:
        return self._token

    # -- warmup (history is context only; never retraded) ------------------

    def warmup(self) -> int:
        from app.backtest.runner import load_market_candles

        seeded = 0
        for inst in self._instruments:
            try:
                session = self._session_factory()
                try:
                    candles = load_market_candles(session, inst, self._timeframe)
                finally:
                    session.close()
            except Exception as exc:  # warmup is best effort
                logger.warning(
                    "demo warmup skipped",
                    extra={"instrument": inst, "error_type": type(exc).__name__},
                )
                continue
            expected = None
            continuous = True
            for candle in candles:
                if expected is not None and candle.timestamp != expected:
                    continuous = False
                    self._store.record_event(
                        self._account_id,
                        "warmup_candle_gap",
                        "error",
                        f"warmup gap for {inst}: expected {expected.isoformat()}, "
                        f"got {candle.timestamp.isoformat()}",
                        now=self._clock(),
                    )
                    break
                expected = candle.timestamp + self._interval()
            self._market_continuity[inst] = continuous
            if not continuous:
                continue
            for candle in candles:
                self._windows[inst].append(candle)
                self._watermark[inst] = candle.timestamp
                seeded += 1
        return seeded

    # -- the ONE fail-closed startup gate ----------------------------------

    def _account_partition_issue(self) -> Optional[str]:
        """Return a fail-closed issue if the account selection is ambiguous."""
        from app.execution.account_guard import (
            AmbiguousDemoAccountError,
            assert_unambiguous_demo_account,
        )

        try:
            assert_unambiguous_demo_account(
                self._session_factory,
                account_name=self._settings.demo_account_name,
                fingerprint=self._credentials.key_fingerprint(),
                explicit=self._account_selection_explicit,
            )
        except AmbiguousDemoAccountError as exc:
            return str(exc)
        return None

    def startup_gate(self) -> GateOutcome:
        now = self._clock()
        # Account-partition guard: never silently run under the default name when
        # several local accounts share this API key (fail closed before locking).
        guard_issue = self._account_partition_issue()
        if guard_issue is not None:
            self._store.record_event(
                self._account_id, "ambiguous_demo_account", "error",
                guard_issue, now=now,
            )
            return GateOutcome(False, False, False, False, [guard_issue])
        if not self._store.acquire_lock(self._account_id, self._token, now=now):
            self._store.record_event(
                self._account_id, "lock_unavailable", "error",
                "another demo runner holds the lock; refusing to start", now=now,
            )
            return GateOutcome(False, False, False, False, ["runtime lock unavailable"])
        self._store.update_status(
            self._account_id, self._token, now=now, status="starting",
            reconciliation_consistent=False, ws_authenticated=False,
            feed_connected=False, feed_stale=True,
        )
        try:
            self._rest.sync_time()
        except Exception as exc:
            self._store.record_event(
                self._account_id, "time_sync_failed", "error",
                f"server time sync failed: {type(exc).__name__}", now=self._clock(),
            )
            return GateOutcome(True, False, False, False, ["time sync failed"])

        account_valid = False
        try:
            validation = validate_demo_account(
                self._rest,
                instruments=self._instruments,
                allowed_acct_levels=tuple(self._settings.demo_allowed_acct_levels),
                quote_ccy=self._quote_ccy,
            )
        except Exception as exc:
            self._runtime.set_reconcile_consistent(False, now=self._clock())
            self._store.record_event(
                self._account_id,
                "account_validation_error",
                "error",
                f"demo account validation errored: {type(exc).__name__}",
                now=self._clock(),
            )
            return GateOutcome(
                True, False, False, False, ["account validation unavailable"]
            )
        if not validation.ok:
            self._store.record_event(
                self._account_id, "account_validation_failed", "error",
                "demo account validation failed; refusing to run",
                payload={"issues": validation.issues, "acct_level": validation.acct_level},
                now=self._clock(),
            )
            self._runtime.set_reconcile_consistent(False, now=self._clock())
            return GateOutcome(True, False, False, False, validation.issues)
        account_valid = True
        self._instrument_meta = validation.instruments

        # Resolve every non-terminal intent, then reconcile (one gate).
        try:
            self._lifecycle.resolve_open_intents()
            result = self._runtime.reconcile_now()
        except Exception as exc:
            self._runtime.set_reconcile_consistent(False, now=self._clock())
            self._store.record_event(
                self._account_id,
                "startup_reconcile_error",
                "error",
                f"startup reconciliation errored: {type(exc).__name__}",
                now=self._clock(),
            )
            return GateOutcome(
                True, account_valid, False, False, ["reconciliation unavailable"]
            )
        self._refresh_balances(result.summary.get("balances", []))

        ambiguous = [
            i for i in self._store.list_open_intents(self._account_id)
            if i.status == STATUS_UNKNOWN
        ]
        armable = result.consistent and not ambiguous
        if not armable:
            self._runtime.set_reconcile_consistent(False, now=self._clock())
            self._store.record_event(
                self._account_id, "startup_gate_blocked", "warning",
                "startup gate blocked: inconsistent or ambiguous orders remain",
                payload={"consistent": result.consistent, "ambiguous": len(ambiguous)},
                now=self._clock(),
            )
        else:
            self._store.record_event(
                self._account_id, "startup_gate_ok", "info",
                "startup gate passed; runtime consistent (still disarmed until armed)",
                now=self._clock(),
            )
        return GateOutcome(True, True, result.consistent, armable, result.issues)

    def _refresh_balances(self, balance_list: list) -> None:
        balances: Dict[str, Decimal] = {}
        for entry in balance_list:
            if not isinstance(entry, dict):
                continue
            ccy = str(entry.get("ccy", ""))
            amount = _dec(entry.get("avail"))
            if ccy and amount is not None:
                balances[ccy] = amount
        if balances:
            self._balances = balances

    # -- durable private-order projection ----------------------------------

    def project_private_orders(self, rows: List[dict]) -> None:
        """Project validated private order/fill updates; fail closed on foreign."""
        if not self._store.owns_lock(self._account_id, self._token):
            return
        now = self._clock()
        self._private_last_msg = now
        for row in rows:
            if not isinstance(row, dict):
                continue
            inst = str(row.get("instId", ""))
            cl = str(row.get("clOrdId", "") or "")
            if inst not in self._instruments:
                self._flag_foreign(f"private update for unapproved instrument {inst}", now)
                continue
            intent = self._store.get_intent(self._account_id, cl) if cl else None
            if (
                not cl
                or not cl.startswith(CLIENT_ORDER_PREFIX)
                or intent is None
                or intent.instrument != inst
            ):
                self._flag_foreign(
                    f"foreign/unknown private update clOrdId={cl or '<none>'} on {inst}", now
                )
                continue
            state = str(row.get("state", ""))
            if not state or map_okx_state(state) is None:
                self._flag_foreign(
                    f"private update with invalid state {state!r} for {cl}", now
                )
                continue
            side = str(row.get("side", "") or "")
            if side and side != intent.side:
                self._flag_foreign(
                    f"private update side {side!r} conflicts with {intent.side!r} for {cl}",
                    now,
                )
                continue
            filled = _dec(row.get("accFillSz"))
            requested = _dec(intent.size)
            if filled is not None and (
                filled < 0 or requested is None or filled > requested
            ):
                self._flag_foreign(
                    f"private update has invalid accumulated fill for {cl}", now
                )
                continue
            ord_id = str(row.get("ordId") or "") or None
            if (
                intent.exchange_order_id
                and ord_id
                and intent.exchange_order_id != ord_id
            ):
                self._flag_foreign(
                    f"private update order id conflicts with local intent {cl}", now
                )
                continue
            self._store.apply_order_update(
                self._account_id,
                client_order_id=cl,
                exchange_order_id=ord_id,
                state=state,
                filled_size=str(row.get("accFillSz")) if row.get("accFillSz") not in (None, "") else None,
                avg_price=str(row.get("avgPx")) if row.get("avgPx") else None,
                fee=str(row.get("fee")) if row.get("fee") not in (None, "") else None,
                fee_ccy=str(row.get("feeCcy")) if row.get("feeCcy") else None,
                update_time=now,
                source="ws",
                now=now,
            )
            self._maybe_record_fill(row, inst, cl, ord_id, now)
            self._needs_reconcile = True

    def _maybe_record_fill(self, row: dict, inst: str, cl: str, ord_id: Optional[str], now: datetime) -> None:
        trade_id = str(row.get("tradeId", "") or "")
        fill_sz = _dec(row.get("fillSz"))
        fill_px = _dec(row.get("fillPx"))
        if not trade_id or fill_sz is None or fill_sz <= 0 or fill_px is None or fill_px <= 0:
            return
        side = str(row.get("side", ""))
        if side not in ("buy", "sell"):
            self._flag_foreign(f"private fill with invalid side {side!r} for {cl}", now)
            return
        self._store.record_fill(
            self._account_id,
            fill_id=trade_id,
            client_order_id=cl,
            exchange_order_id=ord_id,
            instrument=inst,
            side=side,
            fill_size=str(row.get("fillSz")),
            fill_price=str(row.get("fillPx")),
            fee=str(row.get("fillFee", row.get("fee"))) if row.get("fillFee", row.get("fee")) not in (None, "") else None,
            fee_ccy=str(row.get("fillFeeCcy", row.get("feeCcy"))) if row.get("fillFeeCcy", row.get("feeCcy")) else None,
            fill_time=now,
            source="ws",
            now=now,
        )

    def _flag_foreign(self, message: str, now: datetime) -> None:
        self._store.record_event(self._account_id, "private_foreign", "warning", message, now=now)
        # Fail closed: block new entries until a REST reconciliation re-evaluates.
        self._runtime.set_reconcile_consistent(False, now=now)

    # -- forward-only trading step (synchronous, testable) -----------------

    def step(self, now: Optional[datetime] = None) -> List:
        now = now or self._clock()
        # Enforce an engaged kill switch: cancel owned pending ENTRY orders even
        # when it was engaged externally (e.g. by an operator CLI command).
        if self._runtime.kill_switch_engaged():
            self._runtime.cancel_pending_entries()
        feed = self._effective_feed_status(now)
        results = []
        for inst in self._instruments:
            for candle in self._new_confirmed_candles(inst):
                self._windows[inst].append(candle)
                self._watermark[inst] = candle.timestamp
                quote = self._quote_for(inst, now)
                meta = self._instrument_meta.get(inst)
                if meta is None:
                    continue
                position_size, stop_loss = self._store.position_summary(
                    self._account_id, inst
                )
                if (
                    position_size > 0
                    and stop_loss is not None
                    and Decimal(str(candle.low)) <= stop_loss
                ):
                    result = self._runtime.consider_exit(
                        signal_id=f"stop|{inst}|{candle.timestamp.isoformat()}",
                        instrument=inst,
                        meta=meta,
                        quote=quote,
                        feed_status=feed,
                        base_balance=position_size,
                        now=now,
                    )
                    if result is not None:
                        results.append(result)
                    continue
                signals = self._strategy.generate_signals(list(self._windows[inst]))
                if not signals:
                    continue
                signal = signals[-1]
                if signal.action == SignalAction.LONG:
                    available = self._balances.get(self._quote_ccy, Decimal(0))
                    equity, exposure, open_positions = self._equity_exposure(now)
                    if (
                        not equity.is_finite()
                        or equity <= 0
                        or not exposure.is_finite()
                    ):
                        self._store.record_event(
                            self._account_id,
                            "equity_unavailable",
                            "warning",
                            "entry blocked: complete marked equity is unavailable",
                            payload={"instrument": inst},
                            now=now,
                        )
                        continue
                    day_start = self._store.get_or_create_daily_baseline(
                        self._account_id, now.date(), equity, now=now
                    )
                    ctx = EntryContext(
                        signal=signal, instrument=inst, meta=meta, quote=quote,
                        feed_status=feed, available_quote=available, equity=equity,
                        day_start_equity=day_start,
                        day_realized_pnl=equity - day_start,
                        now=now, data_time=candle.timestamp + self._interval(),
                        existing_exposure=exposure,
                        open_positions=open_positions,
                        instrument_position_size=position_size,
                    )
                    r = self._runtime.consider_entry(ctx)
                    if r is not None:
                        results.append(r)
                elif signal.action == SignalAction.FLAT:
                    base, _ = self._store.position_summary(self._account_id, inst)
                    if base > 0:
                        r = self._runtime.consider_exit(
                            signal_id=self._runtime._signal_id(signal, inst),
                            instrument=inst, meta=meta, quote=quote, feed_status=feed,
                            base_balance=base, now=now,
                        )
                        if r is not None:
                            results.append(r)
        return results

    def _equity_exposure(self, now: datetime) -> tuple[Decimal, Decimal, int]:
        equity = self._balances.get(self._quote_ccy, Decimal(0))
        exposure = Decimal(0)
        open_positions = 0
        for inst in self._instruments:
            size, _ = self._store.position_summary(self._account_id, inst)
            if size <= 0:
                continue
            quote = self._quote_for(inst, now)
            if quote is None or not quote.is_usable():
                return Decimal(0), Decimal("Infinity"), len(self._instruments)
            value = size * Decimal(str(quote.bid))
            equity += value
            exposure += value
            open_positions += 1
        return equity, exposure, open_positions

    def _interval(self) -> timedelta:
        from app.strategy.timeframes import parse_timeframe

        return parse_timeframe(self._timeframe)

    def _new_confirmed_candles(self, inst: str) -> List[MarketCandle]:
        out: List[MarketCandle] = []
        watermark = self._watermark.get(inst)
        for update in self._market_state.recent_confirmed_candles():
            if not update.confirmed or update.instrument != inst or update.timeframe != self._timeframe:
                continue
            if watermark is not None and update.timestamp <= watermark:
                continue
            out.append(
                MarketCandle(
                    instrument=update.instrument, timestamp=update.timestamp,
                    open=update.open, high=update.high, low=update.low,
                    close=update.close, volume=update.volume, timeframe=update.timeframe,
                )
            )
        out.sort(key=lambda c: c.timestamp)
        expected = watermark + self._interval() if watermark is not None else None
        for candle in out:
            if expected is not None and candle.timestamp != expected:
                if self._market_continuity.get(inst, True):
                    self._store.record_event(
                        self._account_id,
                        "market_candle_gap",
                        "error",
                        f"candle gap for {inst}: expected {expected.isoformat()}, "
                        f"got {candle.timestamp.isoformat()}",
                        now=self._clock(),
                    )
                self._market_continuity[inst] = False
                return []
            expected = candle.timestamp + self._interval()
        if out:
            self._market_continuity[inst] = True
        return out

    def _quote_for(self, inst: str, now: datetime) -> Optional[QuoteSnapshot]:
        for book in self._market_state.latest_order_books(depth=1):
            if book.instrument != inst:
                continue
            if not book.bids or not book.asks or book.timestamp is None:
                return None
            return QuoteSnapshot(
                instrument=inst,
                bid=Decimal(str(book.bids[0].price)),
                ask=Decimal(str(book.asks[0].price)),
                timestamp=book.timestamp,
                synchronized=book.synchronized,
                source="order_book",
            )
        return None

    def _effective_feed_status(self, now: datetime) -> FeedStatus:
        health = self._market_state.health_snapshot()
        private_stale = self._private_last_msg is None or (
            now - self._private_last_msg
        ) > timedelta(seconds=self._settings.demo_private_stale_seconds)
        connected = health.connected and self._private_authenticated
        stale = health.stale or private_stale or not self._market_continuity_ok
        return FeedStatus(connected=connected, stale=stale)

    @property
    def _market_continuity_ok(self) -> bool:
        return all(self._market_continuity.values())

    def _mark_private_liveness(self) -> None:
        self._private_last_msg = self._clock()

    def _set_private_authenticated(self, authed: bool) -> None:
        self._private_authenticated = authed
        if authed:
            self._private_last_msg = self._clock()
        now = self._clock()
        if self._store.owns_lock(self._account_id, self._token):
            self._store.update_status(
                self._account_id, self._token, now=now,
                ws_authenticated=authed, heartbeat=False,
            )

    # -- async supervision --------------------------------------------------

    async def run(self, stop_event: asyncio.Event) -> int:
        gate = await asyncio.to_thread(self.startup_gate)
        if not gate.lock_acquired or not gate.account_valid:
            if gate.lock_acquired:
                await asyncio.to_thread(self._shutdown)
            return 1
        await asyncio.to_thread(self.warmup)

        tasks = [
            asyncio.create_task(self._public_stream(stop_event), name="demo-public-stream"),
            asyncio.create_task(self._private_stream(stop_event), name="demo-private-stream"),
            asyncio.create_task(self._heartbeat_loop(stop_event), name="demo-heartbeat"),
            asyncio.create_task(self._trading_loop(stop_event), name="demo-trading"),
            asyncio.create_task(self._reconcile_loop(stop_event), name="demo-reconcile"),
        ]
        result = 0
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if not stop_event.is_set():
                result = 1  # a supervised task exited on its own
        finally:
            stop_event.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(self._shutdown)
        return result

    async def _public_stream(self, stop_event: asyncio.Event) -> None:
        if self._public_stream_factory is not None:
            await self._public_stream_factory(stop_event)
            return
        from app.exchange.okx_public_ws import build_default_adapters
        from app.live.runtime import run_live_runtime

        adapters = build_default_adapters(
            self._market_state, instruments=self._instruments,
            public_url=self._settings.okx_public_ws_url,
            business_url=self._settings.okx_business_ws_url,
        )
        await run_live_runtime(adapters, stop_event)

    async def _private_stream(self, stop_event: asyncio.Event) -> None:
        if self._private_ws_factory is not None:
            ws = self._private_ws_factory(
                self.project_private_orders,
                self._set_private_authenticated,
                self._mark_private_liveness,
            )
        else:
            from app.exchange.okx_demo_ws import OKXDemoPrivateWebSocket

            ws = OKXDemoPrivateWebSocket(
                self._credentials, instruments=list(self._instruments),
                url=self._settings.okx_demo_private_ws_url,
                on_orders=self.project_private_orders,
                on_status=self._set_private_authenticated,
                on_liveness=self._mark_private_liveness,
                clock=self._clock,
            )
        await ws.run(stop_event)

    async def _heartbeat_loop(self, stop_event: asyncio.Event) -> None:
        interval = self._settings.demo_heartbeat_seconds
        while not stop_event.is_set():
            now = self._clock()
            if not self._store.owns_lock(self._account_id, self._token):
                self._store.record_event(
                    self._account_id, "lock_lost", "error",
                    "runtime lock lost; stopping", now=now,
                )
                stop_event.set()
                return
            effective = self._effective_feed_status(now)
            self._store.update_status(
                self._account_id, self._token, now=now, status="running",
                feed_connected=effective.connected, feed_stale=not effective.usable,
                ws_authenticated=self._private_authenticated,
            )
            await self._sleep(interval, stop_event)

    async def _trading_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                if self._needs_reconcile:
                    self._runtime.set_reconcile_consistent(False, now=self._clock())
                    result = await asyncio.to_thread(self._runtime.reconcile_now)
                    self._refresh_balances(result.summary.get("balances", []))
                    self._needs_reconcile = False
                await asyncio.to_thread(self.step)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._runtime.set_reconcile_consistent(False, now=self._clock())
                self._store.record_event(
                    self._account_id, "trading_step_error", "error",
                    f"trading step failed: {type(exc).__name__}", now=self._clock(),
                )
            await self._sleep(self._settings.demo_poll_seconds, stop_event)

    async def _reconcile_loop(self, stop_event: asyncio.Event) -> None:
        interval = self._settings.demo_reconcile_interval_seconds
        while not stop_event.is_set():
            await self._sleep(interval, stop_event)
            if stop_event.is_set():
                return
            try:
                await asyncio.to_thread(self._lifecycle.resolve_open_intents)
                result = await asyncio.to_thread(self._runtime.reconcile_now)
                self._refresh_balances(result.summary.get("balances", []))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._runtime.set_reconcile_consistent(False, now=self._clock())
                self._store.record_event(
                    self._account_id, "reconcile_error", "error",
                    f"periodic reconcile failed: {type(exc).__name__}", now=self._clock(),
                )

    async def _sleep(self, seconds: float, stop_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _shutdown(self) -> None:
        now = self._clock()
        try:
            self._store.record_event(
                self._account_id, "shutdown", "info", "demo driver stopped", now=now
            )
            self._store.release_lock(self._account_id, self._token, now=now)
        except Exception:  # pragma: no cover - best effort
            logger.warning("demo driver shutdown bookkeeping failed")
