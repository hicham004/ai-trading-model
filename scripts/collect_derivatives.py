"""Collect PUBLIC OKX SWAP statistics (features only) into the Parquet lake.

Series: funding_rate (8-hourly), open_interest, long_short_ratio, taker_volume
for BTC-USDT-SWAP / ETH-USDT-SWAP. Resumable; re-runs only fetch new data.
This project does not trade swaps: these are research inputs. No credentials.

Example::

    python scripts/collect_derivatives.py --period 1H
    python scripts/collect_derivatives.py --kinds funding_rate --instruments BTC-USDT-SWAP --max-pages 5
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.datalake.derivatives import DEFAULT_START, PERIODS, SWAP_INSTRUMENTS, backfill_series  # noqa: E402
from app.datalake.layout import SERIES_KINDS, LakeLayout  # noqa: E402
from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def _parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Public OKX derivatives statistics -> Parquet lake (features only).")
    p.add_argument("--instruments", nargs="+", default=list(SWAP_INSTRUMENTS), choices=list(SWAP_INSTRUMENTS))
    p.add_argument("--kinds", nargs="+", default=list(SERIES_KINDS), choices=list(SERIES_KINDS))
    p.add_argument("--period", default="1H", choices=list(PERIODS), help="Aggregation period for rubik series.")
    p.add_argument("--start", type=_parse_day, default=DEFAULT_START)
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--sleep", type=float, default=0.25)
    p.add_argument("--lake-dir", default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(get_settings().log_level)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    rest = OKXPublicRest()
    exit_code = 0
    for kind in args.kinds:
        for instrument in args.instruments:
            try:
                report = backfill_series(
                    rest,
                    layout,
                    kind,
                    instrument,
                    period=args.period,
                    start=args.start,
                    max_pages=args.max_pages,
                    sleep_seconds=args.sleep,
                )
            except (PublicRestError, ValueError) as exc:
                print(f"ERROR {kind} {instrument}: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(report.summary())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
