"""Command-line entry point: local forward PAPER trading (Phase 4).

WARNING: This is a SIMULATION. It consumes only PUBLIC, UNAUTHENTICATED OKX
market data and fills every order VIRTUALLY through the simulation-only paper
broker. It NEVER authenticates, touches an account, uses a private endpoint,
places a real or demo order, borrows, uses leverage, or moves funds. A paper
result authorizes nothing.

It runs strictly forward in time on confirmed public candles, vetoes every entry
through the deterministic risk manager, persists an auditable ledger, and
reconciles that ledger on restart. Phase 4 is authorized and WIP - it is NOT
accepted (that requires independent review and explicit human approval).

Examples
--------
Run the default conservative config until Ctrl-C::

    python scripts/run_paper_trading.py

Run a specific strategy/instrument for 5 minutes::

    python scripts/run_paper_trading.py --strategy ma_crossover \
        --instruments BTC-USDT --timeframe 1m --duration 300

List strategies and exit::

    python scripts/run_paper_trading.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import math
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.database import init_db  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402
from app.paper.config import config_from_settings  # noqa: E402
from app.paper.ledger import PaperLedger  # noqa: E402
from app.paper.runtime import build_paper_runtime  # noqa: E402
from app.strategy.registry import available_strategies  # noqa: E402

logger = get_logger("scripts.run_paper_trading")


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be finite and zero or greater")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def _unit_fraction(value: str) -> float:
    parsed = _positive_float(value)
    if parsed > 1:
        raise argparse.ArgumentTypeError("must be no greater than 1")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local forward PAPER trading loop (SIMULATION ONLY)."
    )
    parser.add_argument("--list", action="store_true", help="List strategies and exit.")
    parser.add_argument("--account", default=None, help="Paper account name.")
    parser.add_argument("--strategy", default=None, help="Strategy name (see --list).")
    parser.add_argument(
        "--instruments",
        nargs="+",
        default=None,
        choices=list(ALLOWED_INSTRUMENTS),
        help="Instruments to trade (BTC-USDT and/or ETH-USDT).",
    )
    parser.add_argument("--timeframe", default=None, help="Candle timeframe (live feed is 1m).")
    parser.add_argument("--starting-cash", type=_positive_float, default=None)
    parser.add_argument("--fee-rate", type=_nonnegative_float, default=None)
    parser.add_argument("--slippage-rate", type=_nonnegative_float, default=None)
    parser.add_argument("--min-confidence", type=_unit_fraction, default=None)
    parser.add_argument("--max-risk-per-trade", type=_unit_fraction, default=None)
    parser.add_argument("--max-position-size", type=_unit_fraction, default=None)
    parser.add_argument("--max-total-exposure", type=_unit_fraction, default=None)
    parser.add_argument("--max-daily-loss", type=_unit_fraction, default=None)
    parser.add_argument("--max-open-positions", type=_positive_int, default=None)
    parser.add_argument("--max-quote-age-seconds", type=_positive_float, default=None)
    parser.add_argument("--max-candle-age-seconds", type=_positive_float, default=None)
    parser.add_argument("--poll-seconds", type=_positive_float, default=None)
    parser.add_argument("--window-size", type=_positive_int, default=None)
    parser.add_argument(
        "--kill-switch",
        action="store_true",
        help="Start with the kill switch ENGAGED (blocks all new entries).",
    )
    control = parser.add_mutually_exclusive_group()
    control.add_argument(
        "--engage-kill-switch",
        action="store_true",
        help="Engage the named paper account's entry kill switch and exit.",
    )
    control.add_argument(
        "--release-kill-switch",
        action="store_true",
        help="Release the named paper account's entry kill switch and exit.",
    )
    control.add_argument(
        "--release-stale-lock",
        action="store_true",
        help=(
            "Explicitly release the named account's expired runtime lock and exit."
        ),
    )
    parser.add_argument(
        "--duration",
        type=_nonnegative_float,
        default=0.0,
        help="Seconds to run before stopping (0 = until Ctrl-C).",
    )
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace):
    settings = get_settings()
    return config_from_settings(
        settings,
        account_name=args.account,
        strategy_name=args.strategy,
        instruments=args.instruments,
        timeframe=args.timeframe,
        starting_cash=args.starting_cash,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        min_confidence=args.min_confidence,
        max_risk_per_trade=args.max_risk_per_trade,
        max_position_size=args.max_position_size,
        max_total_exposure=args.max_total_exposure,
        max_daily_loss=args.max_daily_loss,
        max_open_positions=args.max_open_positions,
        max_quote_age_seconds=args.max_quote_age_seconds,
        max_candle_age_seconds=args.max_candle_age_seconds,
        poll_seconds=args.poll_seconds,
        window_size=args.window_size,
    )


async def _run(args: argparse.Namespace) -> int:
    config = _build_config(args)
    await asyncio.to_thread(init_db)
    if args.release_stale_lock:
        from app.db.database import get_session_factory

        ledger = PaperLedger(get_session_factory(), config.account_name)
        account_id = ledger.find_account_id()
        if account_id is None:
            print(
                f"[PAPER/SIMULATION] account {config.account_name!r} does not exist.",
                file=sys.stderr,
            )
            return 2
        released = ledger.release_stale_lock(
            account_id,
            stale_after_seconds=config.lock_stale_seconds,
            now=datetime.now(tz=timezone.utc),
        )
        print(
            f"[PAPER/SIMULATION] stale lock "
            f"{'released' if released else 'not released (lock is active or absent)'} "
            f"for {config.account_name}."
        )
        return 0 if released else 1
    if args.engage_kill_switch or args.release_kill_switch:
        from app.db.database import get_session_factory

        ledger = PaperLedger(get_session_factory(), config.account_name)
        account_id = ledger.ensure_account(
            config.starting_cash, config.config_snapshot()
        )
        engaged = bool(args.engage_kill_switch)
        ledger.set_kill_switch(
            account_id, engaged, now=datetime.now(tz=timezone.utc)
        )
        print(
            f"[PAPER/SIMULATION] kill switch "
            f"{'ENGAGED' if engaged else 'released'} for {config.account_name}."
        )
        return 0
    runtime = build_paper_runtime(config, kill_switch_on_start=args.kill_switch)

    print("=" * 78)
    print("PHASE 4 LOCAL PAPER TRADING  (SIMULATION ONLY - PUBLIC DATA, NO REAL ORDERS)")
    print("=" * 78)
    print(f"  account            : {config.account_name}")
    print(f"  strategy           : {config.strategy_name}")
    print(f"  instruments / tf   : {', '.join(config.instruments)} / {config.timeframe}")
    print(f"  starting cash      : {config.starting_cash:,.2f} (virtual USDT)")
    print(f"  fee / slippage     : {config.fee_rate} / {config.slippage_rate}")
    print(f"  kill switch        : {'ENGAGED' if args.kill_switch else 'off'}")
    print("-" * 78)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform
            pass

    run_task = asyncio.create_task(runtime.run(stop_event), name="paper-runtime")
    try:
        if args.duration > 0:
            try:
                result = await asyncio.wait_for(asyncio.shield(run_task), timeout=args.duration)
            except asyncio.TimeoutError:
                stop_event.set()
                result = await run_task
        else:
            result = await run_task
    finally:
        stop_event.set()
        if not run_task.done():
            try:
                await asyncio.wait_for(run_task, timeout=20)
            except asyncio.TimeoutError:  # pragma: no cover - defensive
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)

    account = runtime.engine.account
    print("-" * 78)
    print("PAPER (SIMULATION) SUMMARY")
    print(f"  cash               : {account.cash:,.2f}")
    print(f"  open positions     : {account.open_position_count}")
    print(f"  realized PnL       : {account.realized_pnl:,.2f}")
    print(f"  fees / slippage    : {account.total_fees:,.2f} / {account.total_slippage:,.2f}")
    print(
        "Reminder: SIMULATION on public data only. No real/demo orders, accounts, or "
        "funds. This does NOT authorize demo or live trading (PROJECT_RULES.md)."
    )
    print("[PAPER/SIMULATION] stopped.")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        print("Available strategies:")
        for name in available_strategies():
            print(f"  - {name}")
        return 0
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "starting local PAPER trading (SIMULATION ONLY)",
        extra={
            "account": args.account or settings.paper_account_name,
            "strategy": args.strategy or settings.paper_strategy,
        },
    )
    try:
        return asyncio.run(_run(args))
    except ValueError as exc:
        print(f"[PAPER/SIMULATION] configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("[PAPER/SIMULATION] interrupted.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
