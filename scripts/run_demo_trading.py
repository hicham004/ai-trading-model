"""Local operator commands + long-running driver for Phase 5 OKX DEMO execution.

WARNING: This drives OKX's DEMO (simulated) trading environment ONLY. Every
request carries ``x-simulated-trading: 1`` to a strict hostname allowlist; there
is no production path. It is long-only SPOT cash for BTC-USDT/ETH-USDT, reuses
the accepted Phase 4 strategy + deterministic risk veto, and is DISARMED by
default.

Operator commands (local CLI; never exposed over HTTP):

    python scripts/run_demo_trading.py --status               # local DB status
    python scripts/run_demo_trading.py --reconcile            # needs demo creds
    python scripts/run_demo_trading.py --arm [--arm-ttl 900]  # gate + arm
    python scripts/run_demo_trading.py --disarm
    python scripts/run_demo_trading.py --engage-kill-switch   # + venue cancels
    python scripts/run_demo_trading.py --release-kill-switch  # reconcile + release
    python scripts/run_demo_trading.py --release-stale-lock
    python scripts/run_demo_trading.py --run [--duration N]   # long-running driver
    python scripts/run_demo_trading.py --smoke-test           # read-only demo

Network access happens ONLY inside --reconcile/--arm/--run/--smoke-test,
kill-switch release, and the venue-cancellation half of kill-switch engagement,
and ONLY if valid demo credentials are present. Running stays DISARMED unless
the persisted, expiring arming gate is valid. Importing this module opens
nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.database import get_session_factory, init_db  # noqa: E402
from app.exchange.credentials import (  # noqa: E402
    demo_credentials_available,
    install_secret_redaction,
    load_demo_credentials,
)
from app.execution.identity import demo_identity_config  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402

logger = get_logger("scripts.run_demo_trading")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OKX DEMO execution operator commands.")
    p.add_argument("--account", default=None, help="Demo account name.")
    p.add_argument("--status", action="store_true", help="Print local DB status and exit.")
    p.add_argument("--reconcile", action="store_true", help="Run the startup gate (needs creds).")
    p.add_argument("--arm", action="store_true", help="Run the gate then arm (needs creds).")
    p.add_argument("--arm-ttl", type=float, default=None, help="Arming TTL seconds.")
    p.add_argument("--disarm", action="store_true", help="Disarm (local).")
    p.add_argument("--engage-kill-switch", action="store_true", help="Engage kill switch + cancel owned entries.")
    p.add_argument(
        "--release-kill-switch",
        action="store_true",
        help="Reconcile, verify no open entries, then release (needs creds).",
    )
    p.add_argument("--release-stale-lock", action="store_true", help="Release a stale lock (local).")
    p.add_argument("--run", action="store_true", help="Run the long-running demo driver (needs creds).")
    p.add_argument("--duration", type=float, default=0.0, help="Seconds to run (0 = until Ctrl-C).")
    p.add_argument(
        "--smoke-test", action="store_true",
        help="Read-only demo connectivity/gate check (needs creds + opt-in).",
    )
    p.add_argument(
        "--place-test-order", action="store_true",
        help="DANGEROUS: within --smoke-test and armed, place ONE tiny demo order.",
    )
    return p.parse_args(argv)


def _account_name(args, settings) -> str:
    return args.account or settings.demo_account_name


def _selection_source(args) -> str:
    """Return how the account name was chosen: 'flag' | 'env' | 'default'."""
    from app.execution.account_guard import account_selection_source

    return account_selection_source(args.account, os.environ.get("DEMO_ACCOUNT_NAME"))


def _account_selection_explicit(args) -> bool:
    """True when the operator chose the account on purpose (flag or env)."""
    return _selection_source(args) != "default"


def _guard_account(account_name: str, args) -> int:
    """Fail closed (exit 2) when the account selection is ambiguous.

    Only checks when demo credentials are present (the fingerprint is needed).
    Returns 0 when safe to proceed, 2 when ambiguous.
    """
    from app.execution.account_guard import (
        AmbiguousDemoAccountError,
        assert_unambiguous_demo_account,
    )

    if not demo_credentials_available():
        return 0
    fingerprint = load_demo_credentials().key_fingerprint()
    try:
        assert_unambiguous_demo_account(
            get_session_factory(),
            account_name=account_name,
            fingerprint=fingerprint,
            explicit=_account_selection_explicit(args),
        )
    except AmbiguousDemoAccountError as exc:
        print(f"[DEMO] {exc}", file=sys.stderr)
        return 2
    return 0


def _build_store(account_name: str):
    from app.execution.store import DemoStore

    return DemoStore(get_session_factory(), account_name)


def _ensure_account_id(store, settings) -> int:
    aid = store.find_account_id()
    if aid is not None:
        return aid
    return store.ensure_account("", demo_identity_config(settings))


def _settings_for_account(settings, account_name: str):
    """Return immutable settings with the operator-selected local account."""
    return replace(settings, demo_account_name=account_name)


def _build_driver(account_name: str, settings, *, explicit: bool = True):
    """Build the full driver (requires demo credentials in the environment)."""
    from app.exchange.okx_demo_rest import OKXDemoRestClient
    from app.execution.driver import DemoTradingDriver

    settings = _settings_for_account(settings, account_name)
    creds = load_demo_credentials()
    install_secret_redaction(creds)
    rest = OKXDemoRestClient(creds, settings=settings)
    driver = DemoTradingDriver(
        credentials=creds, rest=rest, session_factory=get_session_factory(),
        settings=settings, account_selection_explicit=explicit,
    )
    return driver


def _print_status(account_id) -> None:
    from sqlalchemy import select

    from app.db.models import DemoReconciliation, DemoRuntimeStatus

    session = get_session_factory()()
    try:
        status = session.scalar(
            select(DemoRuntimeStatus).where(DemoRuntimeStatus.account_id == account_id)
        )
        recon = session.scalar(
            select(DemoReconciliation)
            .where(DemoReconciliation.account_id == account_id)
            .order_by(DemoReconciliation.id.desc())
            .limit(1)
        )
    finally:
        session.close()
    now = datetime.now(tz=timezone.utc)
    armed = bool(
        status is not None
        and status.armed_until is not None
        and (
            status.armed_until if status.armed_until.tzinfo else status.armed_until.replace(tzinfo=timezone.utc)
        ) > now
    )
    print("=" * 70)
    print("OKX DEMO EXECUTION STATUS (SIMULATION ONLY)")
    print("=" * 70)
    if status is None:
        print("  no runtime status yet")
    else:
        print(f"  status              : {status.status}")
        print(f"  armed               : {armed} (until {status.armed_until})")
        print(f"  kill_switch_engaged : {status.kill_switch_engaged}")
        print(f"  reconcile_consistent: {status.reconciliation_consistent}")
        print(f"  ws_authenticated    : {status.ws_authenticated}")
        print(f"  lock_held           : {bool(status.lock_token)}")
        print(f"  last_error          : {status.last_error}")
    if recon is not None:
        print(
            f"  last reconcile      : consistent={recon.consistent} "
            f"foreign={recon.foreign_orders} unexplained={recon.unexplained_balances}"
        )


def _run_gate_and(driver, settings, *, arm: bool, arm_ttl, smoke: bool, place_test_order: bool) -> int:
    """Run the unified startup gate, then optionally arm / smoke."""
    from app.execution.store import STATUS_UNKNOWN

    try:
        print("[DEMO] running startup gate (sync time, validate account, resolve, reconcile)...")
        gate = driver.startup_gate()
        if not gate.lock_acquired:
            print("[DEMO] another demo runner holds the lock; aborting.", file=sys.stderr)
            return 2
        if not gate.account_valid:
            print("[DEMO] demo account validation FAILED; refusing. Issues:", file=sys.stderr)
            for issue in gate.issues:
                print(f"        - {issue}", file=sys.stderr)
            return 2
        print(
            f"[DEMO] gate: consistent={gate.consistent} armable={gate.armable}"
        )
        for issue in gate.issues:
            print(f"        - {issue}")
        _print_positions(driver, settings)
        if arm:
            armed_until = driver.runtime.arm(ttl_seconds=arm_ttl)
            if armed_until is None:
                print("[DEMO] arm REFUSED (gate not consistent/armable, or lock lost).")
            else:
                print(f"[DEMO] ARMED until {armed_until.isoformat()} (expires).")
        if smoke and place_test_order:
            if driver.runtime.entry_block_reason(datetime.now(tz=timezone.utc)) is not None:
                print(
                    "[DEMO] --place-test-order requires an armed, consistent runtime. "
                    "No order was sent.", file=sys.stderr,
                )
            else:
                _smoke_place_and_cancel(driver, settings)
        print("[DEMO] done. SIMULATION ONLY; no real funds or production access.")
        return 0
    finally:
        driver.release_lock()


def _print_positions(driver, settings) -> None:
    """Read-only per-instrument position report using lot-precision flatness.

    A fully exited position can keep unsellable sub-lot fee dust (e.g. 1.2E-10
    BTC), so "flat" here means floor(position, lot_size) == 0, never an exact
    zero. Reporting only; it changes no gating or order behavior.
    """
    from app.exchange.instruments import parse_instruments
    from app.execution.precision import is_flat

    try:
        metas = parse_instruments(driver.rest.get_instruments())
    except Exception as exc:
        print(f"[DEMO] position report skipped (instruments unavailable: {type(exc).__name__})")
        return
    for inst in settings.demo_instruments:
        position, stop = driver.store.position_summary(driver.account_id, inst)
        meta = metas.get(inst)
        if meta is None:
            print(f"[DEMO] position {inst}: {position} (raw net; lot size unknown)")
            continue
        if is_flat(position, meta.lot_size):
            dust = f", sub-lot dust {position}" if position > 0 else ""
            print(f"[DEMO] position {inst}: FLAT at lot precision{dust}")
        else:
            print(f"[DEMO] position {inst}: {position} OPEN (stop={stop})")


def _smoke_place_and_cancel(driver, settings) -> None:
    """Gated demo smoke order: place a far-below-market resting limit BUY, then

    cancel it. Priced far below market so it cannot fill (no economic effect);
    exercises place -> query -> cancel. Only reached when armed, consistent,
    creds present, the env opt-in is set, and --place-test-order was passed.
    """
    from decimal import Decimal

    from app.exchange.instruments import parse_instruments
    from app.execution.lifecycle import INTENT_ENTRY
    from app.execution.precision import decimal_to_str, floor_size, quantize_price
    from app.okx.client import OKXPublicClient

    instrument = settings.demo_instruments[0]
    meta = parse_instruments(driver.rest.get_instruments()).get(instrument)
    if meta is None or not meta.is_tradable():
        print(f"[DEMO] smoke: {instrument} not tradable; skipping order.")
        return
    candles = OKXPublicClient().get_candles(instrument, timeframe="1m", limit=2)
    if not candles:
        print("[DEMO] smoke: no reference price; skipping order.")
        return
    ref = Decimal(str(candles[-1].close))
    px = quantize_price(ref * Decimal("0.5"), meta.tick_size)
    size = floor_size(meta.min_size, meta.lot_size)
    if size < meta.min_size:
        size = meta.min_size
    signal_id = f"smoke|{instrument}|{datetime.now(tz=timezone.utc).date().isoformat()}"
    print(f"[DEMO] smoke: placing resting demo BUY {size} @ {px} (far below market)...")
    result = driver.lifecycle.submit(
        signal_id=signal_id, instrument=instrument, intent=INTENT_ENTRY, side="buy",
        ord_type="limit", price=decimal_to_str(px), size=decimal_to_str(size),
    )
    print(f"[DEMO] smoke: submit status={result.status} clOrdId={result.client_order_id}")
    cancel = driver.lifecycle.cancel(result.client_order_id, instrument)
    print(f"[DEMO] smoke: cancel status={cancel.status}")


def _engage_kill_switch(account_name: str, settings) -> int:
    """Persist the kill switch first (immediate block), then cancel owned entries."""
    store = _build_store(account_name)
    aid = _ensure_account_id(store, settings)
    now = datetime.now(tz=timezone.utc)
    store.set_kill_switch(aid, True, now=now)
    print("[DEMO] kill switch ENGAGED and persisted (new entries blocked).")
    if not demo_credentials_available():
        print(
            "[DEMO] no demo credentials: a running --run driver will cancel owned "
            "pending ENTRY orders on its next cycle. Venue cancellation needs creds."
        )
        return 0
    driver = _build_driver(account_name, settings)
    if not store.acquire_lock(aid, driver.token, now=datetime.now(tz=timezone.utc)):
        print(
            "[DEMO] a running driver holds the lock; it will cancel owned pending "
            "ENTRY orders. Kill switch remains engaged (fail closed)."
        )
        return 0
    try:
        results = driver.runtime.cancel_pending_entries()
        unresolved = [r for r in results if r.status in ("unknown", "live", "partially_filled")]
        for r in results:
            print(f"[DEMO] cancel {r.client_order_id}: {r.status}")
        if unresolved:
            print(
                f"[DEMO] {len(unresolved)} cancellation(s) UNCONFIRMED; remaining killed "
                "and fail-closed. Re-run --reconcile to resolve.", file=sys.stderr,
            )
            return 1
        print(f"[DEMO] cancelled {len(results)} owned pending entry order(s).")
        return 0
    finally:
        store.release_lock(aid, driver.token, now=datetime.now(tz=timezone.utc))


def _release_kill_switch(account_name: str, settings) -> int:
    """Release only after an authenticated, consistent startup gate."""
    if not demo_credentials_available():
        print(
            "[DEMO] kill-switch release requires demo credentials and "
            "reconciliation. It remains engaged.",
            file=sys.stderr,
        )
        return 2
    driver = _build_driver(account_name, settings)
    try:
        gate = driver.startup_gate()
        if not gate.lock_acquired or not gate.armable:
            print(
                "[DEMO] kill-switch release REFUSED: startup gate is not "
                "armable. It remains engaged.",
                file=sys.stderr,
            )
            return 1
        if not driver.runtime.release_kill_switch():
            print(
                "[DEMO] kill-switch release REFUSED: owned entry orders remain "
                "unresolved. It remains engaged.",
                file=sys.stderr,
            )
            return 1
        print("[DEMO] kill switch released after successful reconciliation.")
        return 0
    finally:
        driver.release_lock()


async def _run_driver(driver, duration: float) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform
            pass
    task = asyncio.create_task(driver.run(stop), name="demo-driver")
    try:
        if duration > 0:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=duration)
            except asyncio.TimeoutError:
                stop.set()
                return await task
        return await task
    finally:
        stop.set()
        if not task.done():
            try:
                await asyncio.wait_for(task, timeout=20)
            except asyncio.TimeoutError:  # pragma: no cover - defensive
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    account_name = _account_name(args, settings)

    # Audit: record which account was selected and the mechanism that chose it.
    from app.execution.account_guard import log_account_selection

    log_account_selection(logger, account_name, _selection_source(args))

    if args.status:
        store = _build_store(account_name)
        aid = store.find_account_id()
        if aid is None:
            print(f"demo account {account_name!r} does not exist yet")
            return 0
        _print_status(aid)
        return 0

    now = datetime.now(tz=timezone.utc)
    if args.disarm or args.release_stale_lock:
        store = _build_store(account_name)
        aid = _ensure_account_id(store, settings)
        if args.disarm:
            store.disarm(aid, now=now)
            print("[DEMO] disarmed.")
        if args.release_stale_lock:
            released = store.release_stale_lock(
                aid, stale_after_seconds=settings.demo_lock_stale_seconds, now=now
            )
            print(f"[DEMO] stale lock released: {released}")
        return 0

    if args.engage_kill_switch:
        guard = _guard_account(account_name, args)
        if guard:
            return guard
        return _engage_kill_switch(account_name, settings)
    if args.release_kill_switch:
        guard = _guard_account(account_name, args)
        if guard:
            return guard
        return _release_kill_switch(account_name, settings)

    # Network commands require demo credentials and explicit opt-in.
    if args.reconcile or args.arm or args.run or args.smoke_test:
        if not demo_credentials_available():
            print(
                "[DEMO] demo credentials are not set (OKX_DEMO_API_KEY/SECRET/PASSPHRASE).\n"
                "       This command needs them; nothing was sent. Aborting.",
                file=sys.stderr,
            )
            return 2
        guard = _guard_account(account_name, args)
        if guard:
            return guard
        if args.smoke_test and not settings.demo_smoke_test_enabled:
            print(
                "[DEMO] the smoke test also requires OKX_DEMO_SMOKE_TEST=1. Aborting.",
                file=sys.stderr,
            )
            return 2
        driver = _build_driver(account_name, settings, explicit=_account_selection_explicit(args))
        if args.run:
            print("[DEMO] starting long-running demo driver (DISARMED unless armed gate valid)...")
            return asyncio.run(_run_driver(driver, args.duration))
        return _run_gate_and(
            driver, settings, arm=args.arm, arm_ttl=args.arm_ttl,
            smoke=args.smoke_test, place_test_order=args.place_test_order,
        )

    print("No command given. Use --status / --reconcile / --arm / --run / --disarm. See --help.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
