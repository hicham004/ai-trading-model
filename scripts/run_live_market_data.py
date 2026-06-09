"""Command-line entry point: stream live PUBLIC OKX market data (Phase 3).

This opens UNAUTHENTICATED public OKX WebSocket connections for BTC-USDT and
ETH-USDT, observes ticker / trades / candle / book channels, and prints a periodic
status snapshot from the in-memory state. It is observation only: it never
authenticates, evaluates strategies, simulates trades, or places orders.

Examples
--------
Stream for 60 seconds and exit::

    python scripts/run_live_market_data.py --duration 60

Stream until Ctrl-C::

    python scripts/run_live_market_data.py

WARNING: This is live public market-data observation only (Phase 3B, WIP). It
does not authorize paper, demo, or live trading.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.database import init_db  # noqa: E402
from app.exchange.okx_public_ws import build_default_adapters  # noqa: E402
from app.live.market_state import MarketState, MarketStateConfig  # noqa: E402
from app.live.persistence import build_persistence_from_settings  # noqa: E402
from app.live.runtime import run_live_runtime  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402

logger = get_logger("scripts.run_live_market_data")


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream live PUBLIC OKX market data (observation only)."
    )
    parser.add_argument(
        "--instruments",
        nargs="+",
        default=list(ALLOWED_INSTRUMENTS),
        choices=list(ALLOWED_INSTRUMENTS),
        help="Instruments to observe (default: BTC-USDT ETH-USDT).",
    )
    parser.add_argument(
        "--duration",
        type=_nonnegative_float,
        default=0.0,
        help="Seconds to stream before stopping (0 = until Ctrl-C).",
    )
    parser.add_argument(
        "--status-interval",
        type=_positive_float,
        default=5.0,
        help="Seconds between printed status snapshots (default: 5).",
    )
    return parser.parse_args(argv)


async def _print_status_periodically(
    state: MarketState, stop_event: asyncio.Event, interval: float
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        health = state.health_snapshot()
        tickers = state.latest_tickers()
        order_books = state.latest_order_books(depth=1)
        print(
            f"[LIVE/PUBLIC] status={health.status.value} ready={health.ready} "
            f"stale={health.stale} books_synced={health.order_books_synchronized} "
            f"since_last={health.seconds_since_last_message} "
            f"tickers={len(tickers)} trades={len(state.recent_trades())} "
            f"books={len(order_books)}"
        )
        for feed in health.feeds:
            print(
                f"    feed={feed.feed_id} status={feed.status.value} "
                f"connected={feed.connected} stale={feed.stale} "
                f"since_market={feed.seconds_since_market_data} "
                f"acked={len(feed.acked_subscriptions)}/"
                f"{len(feed.required_subscriptions)}"
            )
        for ticker in tickers:
            print(
                f"    {ticker.instrument} last={ticker.last} "
                f"bid={ticker.bid} ask={ticker.ask} ts={ticker.timestamp.isoformat()}"
            )
        for book in order_books:
            print(
                f"    book={book.instrument} synced={book.synchronized} "
                f"seq={book.sequence_id} gaps={book.sequence_gaps} "
                f"best_bid={book.bids[0].price if book.bids else None} "
                f"best_ask={book.asks[0].price if book.asks else None}"
            )
        persistence = health.persistence
        if persistence.enabled:
            print(
                f"    persistence={persistence.status.value} "
                f"candles={persistence.stored_candles} "
                f"backfilled={persistence.backfilled_candles} "
                f"books={persistence.stored_order_books} "
                f"errors={persistence.write_errors}"
            )


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    state = MarketState(
        MarketStateConfig(stale_after_seconds=settings.live_stale_after_seconds)
    )
    adapters = build_default_adapters(
        state,
        instruments=args.instruments,
        public_url=settings.okx_public_ws_url,
        business_url=settings.okx_business_ws_url,
    )
    persistence = None
    if settings.live_persistence_enabled:
        await asyncio.to_thread(init_db)
        persistence = build_persistence_from_settings(state, settings)

    stop_event = asyncio.Event()

    # Wire Ctrl-C / SIGTERM to a clean shutdown where supported.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform dependent
            pass

    stream_task = asyncio.create_task(
        run_live_runtime(adapters, stop_event, persistence),
        name="public-market-stream",
    )
    status_task = asyncio.create_task(
        _print_status_periodically(state, stop_event, args.status_interval),
        name="public-market-status",
    )
    stop_task = asyncio.create_task(stop_event.wait(), name="public-market-stop")
    result = 0

    try:
        watched = {stream_task, status_task, stop_task}
        done, _ = await asyncio.wait(
            watched,
            timeout=args.duration if args.duration > 0 else None,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not done:
            # A configured duration elapsed normally.
            stop_event.set()
        elif stop_event.is_set():
            # Ctrl-C / SIGTERM requested a normal shutdown.
            pass
        else:
            failed_task = next(task for task in (stream_task, status_task) if task in done)
            task_name = failed_task.get_name()
            try:
                await failed_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error(
                    "live public market-data task failed",
                    extra={"task": task_name, "error_type": type(exc).__name__},
                )
                print(
                    f"[LIVE/PUBLIC] {task_name} failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[LIVE/PUBLIC] {task_name} stopped unexpectedly.",
                    file=sys.stderr,
                )
            result = 1
            stop_event.set()
    finally:
        stop_event.set()
        status_task.cancel()
        stop_task.cancel()
        if not stream_task.done():
            try:
                await asyncio.wait_for(stream_task, timeout=15)
            except asyncio.TimeoutError:
                stream_task.cancel()
        await asyncio.gather(stream_task, status_task, stop_task, return_exceptions=True)

    print("[LIVE/PUBLIC] stopped.")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "starting live public market-data stream (observation only)",
        extra={"instruments": args.instruments},
    )
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("[LIVE/PUBLIC] interrupted.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
