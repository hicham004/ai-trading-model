"""Phase 6a shadow supervisor: unattended, fail-closed demo-driver babysitter.

Owner-authorized scope (June 11, 2026): demo-only (`x-simulated-trading: 1`),
account ``demo-seeded``, SPOT BTC-USDT, long-only 1x, software stop accepted
for demo, ``ma_crossover`` untouched.

What it does:

* runs the REVIEWED Phase 5 driver and restarts it on crash — but every
  restart passes the full fail-closed startup gate, and re-arming happens only
  after a CLEAN gate;
* restart budget: ``max_restarts`` within ``restart_window_seconds``; when
  exhausted -> permanent disarm + ALERT state;
* ANY reconcile inconsistency / wrong-account-scope / foreign detection ->
  kill switch + permanent disarm + ALERT; the supervisor never auto-recovers
  from those (operator only);
* persisted shadow caps (config/shadow_period.json): per-order notional and
  open-position caps tighten the runtime; entries/day and daily-loss caps are
  enforced here by engaging the kill switch (entries blocked, protective
  exits still possible) and auto-release ONLY on a new UTC day and ONLY when
  the supervisor itself engaged it. An operator-engaged kill switch is never
  released by this code;
* decision journal (candles, shadow-evaluated signals with confidence and
  veto reason, stop evaluations, ledger mirror, health) with daily rollover,
  a heartbeat liveness file, and periodic daily reports.

Safety-core boundary: this module COMPOSES the reviewed driver exactly the
way the accepted Session 2/2b validation runners did (same supervised task
set, warmup intentionally skipped so the strategy window builds from live
candles and a stale candle DB cannot wedge the feed-continuity check). It
modifies no reviewed code and only TIGHTENS the operative runtime caps; the
stored account identity is never touched. Note the documented consequence of
live-built windows: after a restart while a position is open, the strategy's
warm-up FLAT signals will close that position via the reviewed exit path —
conservative by design, and visible in the journal.

An AI/LLM never places orders here: entries/exits flow only through the
reviewed strategy -> risk veto -> execution runtime; this supervisor only
arms, disarms, engages the kill switch, journals, and reports.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, List, Optional

from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    DemoBalanceSnapshot,
    DemoEvent,
    DemoOrderIntent,
    DemoReconciliation,
    DemoRuntimeStatus,
)
from app.execution.precision import is_flat
from app.logging_config import get_logger
from app.shadow.config import ShadowConfig
from app.shadow.journal import DecisionJournal, LedgerPoller, write_atomic_json
from app.shadow.policy import CapBreach, GateDecision, ShadowPolicy
from app.shadow.report import write_daily_report
from app.strategy.base import SignalAction
from app.strategy.registry import build_strategy

logger = get_logger(__name__)

ALERT_FILENAME = "ALERT"
STATE_FILENAME = "state.json"
HEARTBEAT_FILENAME = "heartbeat.json"
READINESS_ALERT_EVENTS = {
    "market_candle_gap_too_large",
    "market_candle_backfill_failed",
    "market_candle_recovery_cap_exceeded",
    "market_candle_backfill_divergence",
}


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _dec(value) -> Optional[Decimal]:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return out if out.is_finite() else None


async def _public_stream_for_timeframe(driver, stop_event: asyncio.Event) -> None:
    """Public market-data stream subscribed to the driver's OWN timeframe.

    The reviewed ``driver._public_stream`` subscribes the default candle
    channel (``candle1m``); the shadow run's timeframe is persisted config, so
    the channel is derived from the same ``settings.demo_timeframe`` the
    driver filters on — one timeframe everywhere, validated against the
    public-WS fail-closed candle-channel allowlist.
    """
    from app.exchange.okx_public_ws import build_default_adapters
    from app.live.runtime import run_live_runtime

    adapters = build_default_adapters(
        driver._market_state,
        instruments=driver._instruments,
        public_url=driver._settings.okx_public_ws_url,
        business_url=driver._settings.okx_business_ws_url,
        candle_channel=f"candle{driver._settings.demo_timeframe}",
    )
    await run_live_runtime(adapters, stop_event)


def default_driver_tasks(driver, stop_event: asyncio.Event) -> list:
    """The reviewed driver's supervised task set, minus warmup (see module
    docstring). Identical composition to the accepted Session 2/2b runners,
    except the public stream subscribes the configured shadow timeframe."""
    return [
        asyncio.create_task(
            _public_stream_for_timeframe(driver, stop_event), name="shadow-public"
        ),
        asyncio.create_task(driver._private_stream(stop_event), name="shadow-private"),
        asyncio.create_task(driver._heartbeat_loop(stop_event), name="shadow-heartbeat"),
        asyncio.create_task(driver._trading_loop(stop_event), name="shadow-trading"),
        asyncio.create_task(driver._reconcile_loop(stop_event), name="shadow-reconcile"),
    ]


class ShadowSupervisor:
    """Long-running Phase 6a supervisor (built for unattended multi-day runs)."""

    def __init__(
        self,
        *,
        settings: Settings,
        config: ShadowConfig,
        session_factory,
        driver_factory: Callable,
        journal: DecisionJournal,
        market_state_factory: Callable,
        driver_tasks_factory: Callable = default_driver_tasks,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._settings = settings
        self._cfg = config
        self._session_factory = session_factory
        self._driver_factory = driver_factory
        self._market_state_factory = market_state_factory
        self._driver_tasks_factory = driver_tasks_factory
        self._journal = journal
        self._clock = clock
        self._dir = Path(config.shadow_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._policy = ShadowPolicy(
            max_restarts=config.max_restarts,
            restart_window_seconds=config.restart_window_seconds,
            max_entries_per_day=config.max_entries_per_day,
            max_daily_loss_usdt=Decimal(str(config.max_daily_loss_usdt)),
            restarts=[
                datetime.fromisoformat(t) for t in self._state.get("restarts", [])
            ],
        )
        self._halt_reason: Optional[str] = None
        self._last_report_day: Optional[date] = None
        self._lot_sizes: Dict[str, Decimal] = {}
        self._last_readiness_alert_event_id = 0

    # -- persisted supervisor state (atomic JSON) ----------------------------

    def _load_state(self) -> dict:
        path = self._dir / STATE_FILENAME
        if not path.exists():
            return {"kill_owner": None, "capped_day": None, "alert": None, "restarts": []}
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            # Unreadable state is ambiguous -> fail closed at startup checks.
            return {"kill_owner": None, "capped_day": None,
                    "alert": "state_file_unreadable", "restarts": []}

    def _save_state(self) -> None:
        self._state["restarts"] = [t.isoformat() for t in self._policy.restarts]
        write_atomic_json(self._dir / STATE_FILENAME, self._state)

    def _write_alert(self, reason: str) -> None:
        self._state["alert"] = reason
        self._save_state()
        (self._dir / ALERT_FILENAME).write_text(
            f"{self._clock().isoformat()} SHADOW HALT: {reason}\n"
            "Operator action required. Review the journal and reconcile, then\n"
            "clear with: python scripts/run_shadow_period.py --acknowledge-alert\n"
        )
        self._journal.write("supervisor", event="alert", reason=reason)

    def _write_readiness_alert(self, event: dict) -> None:
        reason = f"readiness:{event['event_type']}:{event['id']}"
        self._last_readiness_alert_event_id = max(
            self._last_readiness_alert_event_id, int(event["id"])
        )
        if self._state.get("alert") == reason:
            return
        self._state["alert"] = reason
        self._save_state()
        (self._dir / ALERT_FILENAME).write_text(
            f"{self._clock().isoformat()} SHADOW READINESS ALERT: {event['event_type']}\n"
            f"{event['message']}\n"
            "Entries remain fail-closed until the operator reviews the journal and\n"
            "clears with: python scripts/run_shadow_period.py --acknowledge-alert\n"
        )
        self._journal.write(
            "supervisor",
            event="readiness_alert",
            reason=reason,
            ledger_event_id=event["id"],
            event_type=event["event_type"],
            message=event["message"],
            payload=event["payload"],
        )

    def _write_heartbeat(self, **fields) -> None:
        write_atomic_json(
            self._dir / HEARTBEAT_FILENAME,
            {"ts": self._clock().isoformat(), "pid": os.getpid(), **fields},
        )

    # -- small read-only ledger helpers --------------------------------------

    def _runtime_status(self, account_id: int) -> Optional[DemoRuntimeStatus]:
        session = self._session_factory()
        try:
            return session.scalar(
                select(DemoRuntimeStatus).where(DemoRuntimeStatus.account_id == account_id)
            )
        finally:
            session.close()

    def _latest_reconciliation(self, account_id: int) -> Optional[DemoReconciliation]:
        session = self._session_factory()
        try:
            return session.scalar(
                select(DemoReconciliation)
                .where(DemoReconciliation.account_id == account_id)
                .order_by(DemoReconciliation.id.desc())
                .limit(1)
            )
        finally:
            session.close()

    def _latest_readiness_alert_event(self, account_id: int) -> Optional[dict]:
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoEvent)
                .where(
                    DemoEvent.account_id == account_id,
                    DemoEvent.event_type.in_(READINESS_ALERT_EVENTS),
                    DemoEvent.id > self._last_readiness_alert_event_id,
                )
                .order_by(DemoEvent.id.desc())
                .limit(1)
            )
            if row is None:
                return None
            return {
                "id": int(row.id),
                "event_type": row.event_type,
                "message": row.message,
                "payload": row.payload_json,
            }
        finally:
            session.close()

    @staticmethod
    def _feed_health_snapshot(market_state) -> List[dict]:
        if not hasattr(market_state, "all_feed_health"):
            return []
        return [
            {
                "feed_id": feed.feed_id,
                "status": str(feed.status.value if hasattr(feed.status, "value") else feed.status),
                "connected": bool(feed.connected),
                "stale": bool(feed.stale),
                "last_transport_time": feed.last_transport_time,
                "last_market_data_time": feed.last_market_data_time,
                "seconds_since_market_data": feed.seconds_since_market_data,
                "required_subscriptions": list(feed.required_subscriptions),
                "acked_subscriptions": list(feed.acked_subscriptions),
            }
            for feed in market_state.all_feed_health()
        ]

    def _entries_today(self, account_id: int, today: date) -> int:
        day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        session = self._session_factory()
        try:
            return int(
                session.scalar(
                    select(func.count(DemoOrderIntent.id)).where(
                        DemoOrderIntent.account_id == account_id,
                        DemoOrderIntent.intent == "entry",
                        DemoOrderIntent.requested_at >= day_start,
                    )
                )
                or 0
            )
        finally:
            session.close()

    def _quote_bid(self, market_state) -> Optional[Decimal]:
        now = self._clock()
        for book in market_state.latest_order_books(depth=1):
            if book.instrument != self._cfg.instrument:
                continue
            if not book.synchronized or not book.bids or book.timestamp is None:
                return None
            age = (now - book.timestamp).total_seconds()
            if age > self._settings.demo_max_quote_age_seconds:
                return None
            return _dec(book.bids[0].price)
        return None

    def _quote_balance(self, account_id: int) -> Optional[Decimal]:
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoBalanceSnapshot)
                .where(DemoBalanceSnapshot.account_id == account_id)
                .order_by(DemoBalanceSnapshot.id.desc())
                .limit(1)
            )
        finally:
            session.close()
        if row is None:
            return None
        try:
            balances = json.loads(row.balances_json)
        except ValueError:
            return None
        for entry in balances:
            if isinstance(entry, dict) and entry.get("ccy") == self._settings.demo_quote_currency:
                return _dec(entry.get("avail"))
        return None

    def _day_pnl(self, store, account_id: int, market_state, today: date) -> Optional[Decimal]:
        """Marked equity vs the immutable day baseline; None when unmarkable."""
        cash = self._quote_balance(account_id)
        if cash is None:
            return None
        position, _ = store.position_summary(account_id, self._cfg.instrument)
        equity = cash
        if position > 0:
            bid = self._quote_bid(market_state)
            if bid is None:
                return None  # cannot mark the open position -> skip this tick
            equity += position * bid
        baseline = store.get_or_create_daily_baseline(
            account_id, today, equity, now=self._clock()
        )
        return equity - baseline

    # -- cap enforcement and kill-switch ownership (sync, unit-tested) -------

    def enforce_caps(
        self, runtime, today: date, breach: CapBreach, already_engaged: bool = False
    ) -> bool:
        """Act on a cap breach. Returns True when the kill switch was engaged.

        If the switch is already engaged but the supervisor holds no ownership
        record, it was engaged by the operator (or a halt path): observe and
        journal, but never claim it — claiming would let the new-day release
        path free an operator-engaged switch.
        """
        if breach == CapBreach.NONE or self._state.get("kill_owner"):
            return False
        if already_engaged:
            self._journal.write(
                "supervisor", event="cap_breach_switch_already_engaged_not_claimed",
                cap=breach.value, day=today.isoformat(),
            )
            return False
        runtime.engage_kill_switch()
        self._state["kill_owner"] = breach.value
        self._state["capped_day"] = today.isoformat()
        self._save_state()
        self._journal.write(
            "supervisor", event="cap_breach", cap=breach.value, day=today.isoformat()
        )
        return True

    def maybe_release_new_day(self, runtime, account_id: int, today: date) -> bool:
        """Release a SUPERVISOR-owned kill switch on a new UTC day (fail closed).

        ``runtime.release_kill_switch`` itself refuses unless reconciliation is
        consistent and no entry orders are unresolved; an operator-engaged
        switch is never touched.
        """
        status = self._runtime_status(account_id)
        engaged = bool(status is not None and status.kill_switch_engaged)
        capped = self._state.get("capped_day")
        capped_day = date.fromisoformat(capped) if capped else None
        owner = self._state.get("kill_owner")
        if not engaged and owner:
            # Operator released it manually; drop our claim.
            self._state["kill_owner"] = None
            self._state["capped_day"] = None
            self._save_state()
            return False
        if not self._policy.may_auto_release(
            engaged=engaged, owner=owner, capped_day=capped_day, today=today
        ):
            return False
        released = bool(runtime.release_kill_switch())
        self._journal.write(
            "supervisor", event="kill_switch_release_attempt", released=released
        )
        if released:
            self._state["kill_owner"] = None
            self._state["capped_day"] = None
            self._save_state()
        return released

    # -- shadow signal evaluation (read-only observability) -------------------

    def _journal_market(self, driver, market_state, window, watermark: dict, strategy) -> None:
        """Journal new confirmed candles, the shadow-evaluated signal for each,
        and a stop evaluation while a position is open. Mirrors the reviewed
        driver's inputs; the runtime stays authoritative for actions."""
        inst = self._cfg.instrument
        timeframe = self._settings.demo_timeframe
        floor = self._settings.demo_min_confidence
        new = [
            u
            for u in market_state.recent_confirmed_candles()
            if u.instrument == inst
            and u.timeframe == timeframe
            and (watermark.get(inst) is None or u.timestamp > watermark[inst])
        ]
        new.sort(key=lambda u: u.timestamp)
        for u in new:
            watermark[inst] = u.timestamp
            self._journal.write(
                "candle", instrument=inst, timeframe=timeframe,
                candle_ts=u.timestamp, open=u.open, high=u.high, low=u.low,
                close=u.close, volume=u.volume,
            )
            from app.strategy.base import MarketCandle

            window.append(
                MarketCandle(
                    instrument=inst, timestamp=u.timestamp, open=u.open,
                    high=u.high, low=u.low, close=u.close, volume=u.volume,
                    timeframe=timeframe,
                )
            )
            signals = strategy.generate_signals(list(window))
            if not signals:
                continue
            signal = signals[-1]
            cleared = (
                signal.action == SignalAction.LONG and signal.confidence >= floor
            )
            veto = (
                "confidence_too_low"
                if signal.action == SignalAction.LONG and not cleared
                else None
            )
            self._journal.write(
                "signal", source="shadow_eval", instrument=inst,
                candle_ts=u.timestamp, action=signal.action.value,
                confidence=signal.confidence, reason=signal.reason,
                stop_loss=signal.stop_loss, cleared=cleared, veto_reason=veto,
            )
            position, stop_level = driver.store.position_summary(driver.account_id, inst)
            if position > 0 and stop_level is not None:
                low = _dec(u.low) or Decimal(0)
                self._journal.write(
                    "stop_eval", instrument=inst, candle_ts=u.timestamp,
                    low=str(low), stop_level=str(stop_level),
                    breached=bool(low <= stop_level),
                )

    # -- reporting -------------------------------------------------------------

    def _refresh_reports(self, account_id: int, force: bool = False) -> None:
        today = self._clock().date()
        try:
            if self._last_report_day is not None and self._last_report_day != today:
                # Finalize yesterday once the UTC day rolls over.
                write_daily_report(
                    journal_dir=self._dir, session_factory=self._session_factory,
                    account_id=account_id, day=self._last_report_day,
                    instrument=self._cfg.instrument,
                    min_confidence=self._settings.demo_min_confidence,
                )
            write_daily_report(
                journal_dir=self._dir, session_factory=self._session_factory,
                account_id=account_id, day=today, instrument=self._cfg.instrument,
                min_confidence=self._settings.demo_min_confidence,
            )
            self._last_report_day = today
        except Exception as exc:  # reporting must never kill the run
            logger.warning(
                "shadow report refresh failed", extra={"error_type": type(exc).__name__}
            )

    # -- main loops --------------------------------------------------------------

    async def run(self, stop_event: asyncio.Event) -> int:
        """Outer attempt loop. Returns 0 on operator stop, 1 on permanent halt,
        2 when startup preconditions refuse to run at all."""
        if self._state.get("alert"):
            print(f"[SHADOW] refusing to start: unacknowledged ALERT "
                  f"({self._state['alert']}). Run --acknowledge-alert after review.")
            return 2
        if tuple(self._settings.demo_instruments) != (self._cfg.instrument,):
            print("[SHADOW] refusing to start: DEMO_INSTRUMENTS must equal the "
                  f"shadow instrument ({self._cfg.instrument!r}) for Phase 6a.")
            return 2
        if self._settings.demo_timeframe != self._cfg.timeframe:
            # The launcher must build settings via shadow_settings(); a
            # mismatch would split the feed subscription from the driver's
            # candle filter (mixed timeframes) — refuse outright.
            print("[SHADOW] refusing to start: settings timeframe "
                  f"({self._settings.demo_timeframe!r}) != shadow config "
                  f"timeframe ({self._cfg.timeframe!r}).")
            return 2
        self._journal.write(
            "supervisor", event="start", phase="6a",
            instrument=self._cfg.instrument,
            timeframe=self._settings.demo_timeframe,
            account=self._settings.demo_account_name,
            caps={
                "max_order_notional_usdt": self._cfg.max_order_notional_usdt,
                "max_open_positions": self._cfg.max_open_positions,
                "max_entries_per_day": self._cfg.max_entries_per_day,
                "max_daily_loss_usdt": str(self._cfg.max_daily_loss_usdt),
            },
        )
        while not stop_event.is_set():
            outcome = await self._run_attempt(stop_event)
            if outcome == "stopped":
                self._journal.write("supervisor", event="operator_stop")
                return 0
            if outcome.startswith("halt:"):
                reason = outcome.split(":", 1)[1]
                self._write_alert(reason)
                self._write_heartbeat(state="halted_alert", reason=reason)
                return 1
            if self._state.get("alert"):
                reason = self._state["alert"]
                self._journal.write(
                    "supervisor", event="restart_blocked_by_alert", reason=reason
                )
                self._write_heartbeat(state="halted_alert", reason=reason)
                return 1
            # crashed / transient gate failure -> bounded, gated restart
            now = self._clock()
            within_budget = self._policy.record_restart(now)
            self._save_state()
            self._journal.write(
                "supervisor", event="restart", outcome=outcome,
                restarts_in_window=self._policy.restarts_in_window(now),
            )
            if not within_budget:
                self._write_alert("restart_budget_exhausted")
                self._write_heartbeat(state="halted_alert", reason="restart_budget_exhausted")
                return 1
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._cfg.restart_backoff_seconds
                )
            except asyncio.TimeoutError:
                pass
        return 0

    async def _run_attempt(self, stop_event: asyncio.Event) -> str:
        market_state = self._market_state_factory()
        driver = self._driver_factory(market_state)
        gate = await asyncio.to_thread(driver.startup_gate)
        decision, reason = self._policy.classify_gate(
            lock_acquired=gate.lock_acquired, account_valid=gate.account_valid,
            consistent=gate.consistent, armable=gate.armable, issues=list(gate.issues),
        )
        self._journal.write(
            "supervisor", event="gate", decision=decision.value, reason=reason,
            lock=gate.lock_acquired, account_valid=gate.account_valid,
            consistent=gate.consistent, armable=gate.armable, issues=list(gate.issues),
        )
        if decision != GateDecision.PROCEED:
            if gate.lock_acquired:
                await asyncio.to_thread(driver._shutdown)
            if decision == GateDecision.HALT:
                return f"halt:{reason}"
            return "gate_retry"

        # Respect an operator-engaged kill switch found at startup: never
        # auto-release it; refuse to run until the operator resolves it.
        status = self._runtime_status(driver.account_id)
        if (
            status is not None
            and status.kill_switch_engaged
            and self._state.get("kill_owner") is None
        ):
            await asyncio.to_thread(driver._shutdown)
            return "halt:kill_switch_engaged_by_operator"

        # Tighten the OPERATIVE caps from the persisted shadow config. The
        # stored account identity is never mutated (same mechanism the
        # accepted Session 2/2b validation runs used).
        driver._runtime._settings = replace(
            driver._runtime._settings,
            demo_max_order_notional=float(self._cfg.max_order_notional_usdt),
            demo_max_open_positions=int(self._cfg.max_open_positions),
        )

        # Journal instrument metadata (lot size) for lot-precision reporting.
        try:
            from app.exchange.instruments import parse_instruments

            metas = parse_instruments(driver.rest.get_instruments())
            meta = metas.get(self._cfg.instrument)
            if meta is not None:
                self._lot_sizes[self._cfg.instrument] = meta.lot_size
                self._journal.write(
                    "meta", instrument=self._cfg.instrument,
                    lot_size=str(meta.lot_size), tick_size=str(meta.tick_size),
                    min_size=str(meta.min_size),
                )
        except Exception as exc:
            self._journal.write(
                "supervisor", event="meta_fetch_failed", error=type(exc).__name__
            )

        armed_until = driver.runtime.arm(ttl_seconds=self._cfg.arm_ttl_seconds)
        if armed_until is None:
            await asyncio.to_thread(driver._shutdown)
            return "arm_refused"
        self._journal.write("supervisor", event="armed", until=armed_until)

        attempt_stop = asyncio.Event()
        tasks = self._driver_tasks_factory(driver, attempt_stop)
        tasks.append(
            asyncio.create_task(
                self._supervise_loop(driver, market_state, stop_event, attempt_stop),
                name="shadow-supervise",
            )
        )
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            attempt_stop.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                driver.runtime.disarm()
            finally:
                await asyncio.to_thread(driver._shutdown)
            self._journal.write("supervisor", event="attempt_cleanup_done")

        if self._halt_reason is not None:
            reason, self._halt_reason = self._halt_reason, None
            return f"halt:{reason}"
        if stop_event.is_set():
            return "stopped"
        return "crashed"

    async def _supervise_loop(
        self, driver, market_state, stop_event: asyncio.Event, attempt_stop: asyncio.Event
    ) -> None:
        account_id = driver.account_id
        poller = LedgerPoller(self._session_factory, account_id, self._journal)
        await asyncio.to_thread(poller.prime)
        strategy = build_strategy(self._settings.demo_strategy)
        from collections import deque

        window = deque(maxlen=self._settings.paper_window_size)
        watermark: dict = {}
        self._journal.write(
            "supervisor", event="eval_window_reset",
            note="shadow evaluation window rebuilt from live candles for this attempt",
        )
        last_report = self._clock()
        while not stop_event.is_set() and not attempt_stop.is_set():
            now = self._clock()
            today = now.date()
            try:
                await asyncio.to_thread(
                    self._journal_market, driver, market_state, window, watermark, strategy
                )
                await asyncio.to_thread(poller.poll)
                readiness_alert = await asyncio.to_thread(
                    self._latest_readiness_alert_event, account_id
                )
                if readiness_alert is not None:
                    await asyncio.to_thread(
                        self._write_readiness_alert, readiness_alert
                    )

                # Fail-closed watch on exchange-truth reconciliations. The
                # wrong_scope count is persisted inside summary_json (the row
                # has no dedicated column); consistent=False already guarantees
                # a halt, the parse only sharpens the alert reason.
                rec = await asyncio.to_thread(self._latest_reconciliation, account_id)
                if rec is not None:
                    try:
                        wrong_scope = int(
                            json.loads(rec.summary_json or "{}").get("wrong_scope", 0)
                        )
                    except (ValueError, TypeError):
                        wrong_scope = 0
                    halt = self._policy.classify_reconcile_row(
                        consistent=bool(rec.consistent),
                        foreign_orders=int(rec.foreign_orders or 0),
                        wrong_scope=wrong_scope,
                        unexplained=int(rec.unexplained_balances or 0),
                    )
                    if halt is not None:
                        self._journal.write("supervisor", event="halt", reason=halt)
                        try:
                            await asyncio.to_thread(driver.runtime.engage_kill_switch)
                            self._state["kill_owner"] = f"halt:{halt}"
                            self._save_state()
                        finally:
                            self._halt_reason = halt
                            attempt_stop.set()
                        return

                # One status snapshot per tick: kill-switch ownership decisions
                # and the health/heartbeat lines all read from it.
                status = await asyncio.to_thread(self._runtime_status, account_id)
                kill_engaged_now = bool(
                    status.kill_switch_engaged if status is not None else False
                )

                # Shadow caps (persisted config). Engage/release can call the
                # exchange (cancel pending entries), so keep them off the loop.
                entries_today = await asyncio.to_thread(
                    self._entries_today, account_id, today
                )
                day_pnl = await asyncio.to_thread(
                    self._day_pnl, driver.store, account_id, market_state, today
                )
                breach = self._policy.check_caps(
                    entries_today=entries_today, day_pnl_usdt=day_pnl
                )
                engaged_now = await asyncio.to_thread(
                    self.enforce_caps, driver.runtime, today, breach, kill_engaged_now
                )
                kill_engaged_now = kill_engaged_now or engaged_now
                await asyncio.to_thread(
                    self.maybe_release_new_day, driver.runtime, account_id, today
                )

                # Keep the expiring arming gate fresh while healthy: stay armed
                # even when cap-kill-switched so protective exits remain possible.
                armed_until = status.armed_until if status is not None else None
                if armed_until is not None and armed_until.tzinfo is None:
                    armed_until = armed_until.replace(tzinfo=timezone.utc)
                if (
                    armed_until is None
                    or (armed_until - now).total_seconds() < self._cfg.rearm_interval_seconds
                ):
                    renewed = driver.runtime.arm(ttl_seconds=self._cfg.arm_ttl_seconds)
                    self._journal.write(
                        "supervisor", event="rearm",
                        renewed=bool(renewed), until=renewed,
                    )

                # Health + heartbeat + journal.
                position, stop_level = driver.store.position_summary(
                    account_id, self._cfg.instrument
                )
                lot = self._lot_sizes.get(self._cfg.instrument)
                flat = is_flat(position, lot) if lot is not None else None
                ws_auth = bool(status.ws_authenticated) if status is not None else False
                feed_connected = bool(status.feed_connected) if status is not None else False
                feed_stale = bool(status.feed_stale) if status is not None else True
                feed_usable = bool(
                    status is not None and feed_connected and not feed_stale
                )
                per_feed_health = await asyncio.to_thread(
                    self._feed_health_snapshot, market_state
                )
                gap_snapshot = getattr(driver, "gap_recovery_snapshot", None)
                gap_recovery = (
                    await asyncio.to_thread(gap_snapshot)
                    if callable(gap_snapshot)
                    else {"market_continuity": {}, "recoveries_per_24h": 0, "instruments": {}}
                )
                market_continuity_ok = bool(
                    getattr(driver, "_market_continuity_ok", True)
                )
                kill = kill_engaged_now
                self._journal.write(
                    "health", ws_auth=ws_auth, feed_usable=feed_usable, kill=kill,
                    feed_connected=feed_connected, feed_stale=feed_stale,
                    market_continuity_ok=market_continuity_ok,
                    per_feed_health=per_feed_health,
                    gap_recovery=gap_recovery,
                    reconcile_consistent=bool(
                        status.reconciliation_consistent if status is not None else False
                    ),
                    position=str(position), flat_at_lot=flat,
                    entries_today=entries_today,
                    day_pnl=(str(day_pnl) if day_pnl is not None else None),
                )
                self._write_heartbeat(
                    state="running", armed_until=armed_until, kill=kill,
                    kill_owner=self._state.get("kill_owner"),
                    restarts_in_window=self._policy.restarts_in_window(now),
                    position=str(position), flat_at_lot=flat,
                    entries_today=entries_today,
                    day_pnl=(str(day_pnl) if day_pnl is not None else None),
                    last_candle=(watermark.get(self._cfg.instrument)),
                    market_continuity_ok=market_continuity_ok,
                    gap_recovery=gap_recovery,
                )

                if (now - last_report).total_seconds() >= self._cfg.report_refresh_seconds:
                    await asyncio.to_thread(self._refresh_reports, account_id)
                    last_report = now
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A supervision tick must not kill the attempt; journal and go on.
                self._journal.write(
                    "supervisor", event="supervise_tick_error", error=type(exc).__name__
                )
            try:
                await asyncio.wait_for(
                    self._race(stop_event, attempt_stop),
                    timeout=self._cfg.heartbeat_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    @staticmethod
    async def _race(*events: asyncio.Event) -> None:
        waits = [asyncio.create_task(e.wait()) for e in events]
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waits:
                if not w.done():
                    w.cancel()
