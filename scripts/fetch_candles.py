"""Command-line script: fetch public OKX candles and store them locally.

Examples
--------
Fetch the default instruments (BTC-USDT and ETH-USDT) at the 1H timeframe::

    python scripts/fetch_candles.py

Fetch specific instruments and a different timeframe::

    python scripts/fetch_candles.py --instruments BTC-USDT ETH-USDT \
        --timeframe 15m --limit 200

This script uses PUBLIC market data only. It never authenticates and never
touches account, order, or withdrawal endpoints.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly (``python scripts/fetch_candles.py``) by
# making the project root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.database import init_db, session_scope  # noqa: E402
from app.ingest import fetch_and_store  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS, OKXClientError, OKXPublicClient  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and store public OKX candles.")
    parser.add_argument(
        "--instruments",
        nargs="+",
        default=list(ALLOWED_INSTRUMENTS),
        choices=list(ALLOWED_INSTRUMENTS),
        help="Instruments to fetch (default: BTC-USDT ETH-USDT).",
    )
    parser.add_argument(
        "--timeframe",
        default="1H",
        help="OKX bar size, e.g. 1m, 15m, 1H, 1D (default: 1H).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of candles to request per instrument, 1-300 (default: 100).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger("scripts.fetch_candles")

    # Make sure the tables exist before we try to write to them.
    init_db()

    client = OKXPublicClient(settings=settings)

    exit_code = 0
    for instrument in args.instruments:
        try:
            with session_scope() as session:
                result = fetch_and_store(
                    session,
                    client,
                    instrument,
                    timeframe=args.timeframe,
                    limit=args.limit,
                )
            logger.info(
                "Ingest complete",
                extra={
                    "instrument": result.instrument,
                    "timeframe": result.timeframe,
                    "fetched": result.fetched,
                    "inserted": result.inserted,
                    "skipped_duplicates": result.skipped_duplicates,
                },
            )
            print(
                f"{result.instrument} {result.timeframe}: "
                f"fetched {result.fetched}, inserted {result.inserted}, "
                f"skipped {result.skipped_duplicates} duplicate(s)."
            )
        except (OKXClientError, ValueError) as exc:
            # Keep going with the remaining instruments, but report failure.
            logger.error(
                "Ingest failed",
                extra={"instrument": instrument, "error": str(exc)},
            )
            print(f"ERROR fetching {instrument}: {exc}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
