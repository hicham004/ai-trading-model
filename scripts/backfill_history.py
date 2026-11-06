"""Resumable PUBLIC OKX history backfill into the Parquet research lake.

Examples
--------
Everything the plan asks for (BTC/ETH at 1m, 5m, 1H, 4H, 1D back to 2020)::

    python scripts/backfill_history.py

A bounded session (cron slot / smoke test) for one series::

    python scripts/backfill_history.py --instruments BTC-USDT --timeframes 1H --max-pages 50

Re-running is safe: the job resumes from ``data/lake/_state`` and the Parquet
writer de-duplicates. Add ``--quality`` to print the data-quality report for
the series touched. Public endpoints only; no credentials are read or sent.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.datalake.backfill import DEFAULT_START, DEFAULT_TIMEFRAMES, backfill_candles  # noqa: E402
from app.datalake.layout import LakeLayout  # noqa: E402
from app.datalake.parquet_store import read_candles  # noqa: E402
from app.datalake.quality import assess_candles, render_markdown  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS, OKXClientError, OKXPublicClient  # noqa: E402


def _parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Resumable public OKX candle backfill -> Parquet lake.")
    p.add_argument("--instruments", nargs="+", default=list(ALLOWED_INSTRUMENTS), choices=list(ALLOWED_INSTRUMENTS))
    p.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES), help="OKX bars, e.g. 1m 5m 1H 4H 1D")
    p.add_argument("--start", type=_parse_day, default=DEFAULT_START, help="Earliest UTC day wanted (YYYY-MM-DD, default 2020-01-01).")
    p.add_argument("--max-pages", type=int, default=None, help="Stop after N requests per series (resume later).")
    p.add_argument("--sleep", type=float, default=0.15, help="Seconds between requests (OKX: 20 req / 2 s).")
    p.add_argument("--lake-dir", default=None, help="Lake root (default: $DATA_LAKE_DIR or data/lake).")
    p.add_argument("--quality", action="store_true", help="Print a data-quality report afterwards.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    client = OKXPublicClient(settings=settings)

    exit_code = 0
    touched = []
    for instrument in args.instruments:
        for timeframe in args.timeframes:
            try:
                report = backfill_candles(
                    client,
                    layout,
                    instrument,
                    timeframe,
                    start=args.start,
                    max_pages=args.max_pages,
                    sleep_seconds=args.sleep,
                )
            except (OKXClientError, ValueError) as exc:
                print(f"ERROR {instrument} {timeframe}: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(report.summary())
            touched.append((instrument, timeframe))

    if args.quality and touched:
        reports = [
            assess_candles(read_candles(layout, i, t), instrument=i, timeframe=t) for i, t in touched
        ]
        print()
        print(render_markdown(reports))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
