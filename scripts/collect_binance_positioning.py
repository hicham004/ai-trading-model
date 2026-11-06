"""Collect Binance PUBLIC funding-rate and open-interest history into the lake (features only).

Long-history positioning data for research (OKX keeps only months of public
funding/OI history). This project trades OKX SPOT demo only and never trades
on Binance; nothing here authenticates. Resumable: re-runs fetch only new
days / settlements.

Example::

    python scripts/collect_binance_positioning.py                       # BTCUSDT + ETHUSDT, funding + metrics
    python scripts/collect_binance_positioning.py --kinds funding_rate   # funding only (fast)
    python scripts/collect_binance_positioning.py --symbols BTCUSDT --kinds metrics --max-days 30
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.datalake.binance_public import (  # noqa: E402
    SYMBOLS,
    BinancePublicClient,
    BinancePublicError,
    backfill_funding,
    backfill_metrics,
)
from app.datalake.layout import EXTERNAL_KINDS, LakeLayout  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def _parse_day(value: str) -> date:
    return date.fromisoformat(value)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Binance public funding/open-interest history -> Parquet lake (research features only).")
    p.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    p.add_argument("--kinds", nargs="+", default=list(EXTERNAL_KINDS), choices=list(EXTERNAL_KINDS))
    p.add_argument("--start-day", type=_parse_day, default=None, help="First UTC day (default: the documented series start).")
    p.add_argument("--end-day", type=_parse_day, default=None, help="Last UTC day for metrics (default: yesterday).")
    p.add_argument("--max-pages", type=int, default=None, help="Funding: page budget for this run.")
    p.add_argument("--max-days", type=int, default=None, help="Metrics: day budget for this run.")
    p.add_argument("--sleep", type=float, default=0.1)
    p.add_argument("--no-verify", action="store_true", help="Skip sha256 verification of bulk files (not recommended).")
    p.add_argument("--lake-dir", default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(get_settings().log_level)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    client = BinancePublicClient()
    exit_code = 0
    for kind in args.kinds:
        for symbol in args.symbols:
            try:
                if kind == "funding_rate":
                    start = datetime.combine(args.start_day, datetime.min.time(), tzinfo=timezone.utc) if args.start_day else None
                    report = backfill_funding(client, layout, symbol, start=start, max_pages=args.max_pages, sleep_seconds=args.sleep)
                else:
                    report = backfill_metrics(
                        client, layout, symbol, start_day=args.start_day, end_day=args.end_day, max_days=args.max_days,
                        sleep_seconds=args.sleep, verify=not args.no_verify,
                    )
            except (BinancePublicError, ValueError) as exc:
                print(f"ERROR {kind} {symbol}: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(report.summary())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
