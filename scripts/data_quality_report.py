"""Data-quality report over the stored candle series (continuity, dupes, alignment, outliers).

Writes ``<lake>/_reports/quality-<UTC date>.md`` and ``.json`` and prints the
Markdown. Intended as the nightly job (cron) on the research host::

    17 2 * * * cd /path/to/repo && .venv/bin/python scripts/data_quality_report.py --strict

``--strict`` exits 1 when any series fails (missing bars, duplicates,
misalignment, incoherent OHLC). Offline: reads Parquet files only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.backfill import DEFAULT_TIMEFRAMES  # noqa: E402
from app.datalake.layout import LakeLayout  # noqa: E402
from app.datalake.parquet_store import read_candles  # noqa: E402
from app.datalake.quality import assess_candles, render_markdown  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Candle data-quality report for the Parquet lake.")
    p.add_argument("--instruments", nargs="+", default=list(ALLOWED_INSTRUMENTS), choices=list(ALLOWED_INSTRUMENTS))
    p.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    p.add_argument("--lake-dir", default=None)
    p.add_argument("--out-dir", default=None, help="Report directory (default <lake>/_reports).")
    p.add_argument("--strict", action="store_true", help="Exit 1 if any stored series is not OK.")
    p.add_argument("--no-write", action="store_true", help="Print only; do not write report files.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    now = datetime.now(tz=timezone.utc)
    reports = []
    for instrument in args.instruments:
        for timeframe in args.timeframes:
            table = read_candles(layout, instrument, timeframe)
            if table.num_rows == 0:
                continue
            reports.append(assess_candles(table, instrument=instrument, timeframe=timeframe))
    if not reports:
        print("No stored candle series found; run scripts/backfill_history.py first.")
        return 1 if args.strict else 0
    markdown = render_markdown(reports, generated_at=now)
    print(markdown)
    if not args.no_write:
        out_dir = Path(args.out_dir) if args.out_dir else layout.reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = out_dir / f"quality-{now:%Y-%m-%d}"
        stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps([r.to_dict() for r in reports], indent=2, default=str), encoding="utf-8"
        )
        print(f"Wrote {stem.with_suffix('.md')} and {stem.with_suffix('.json')}")
    failed = [r for r in reports if not r.ok]
    return 1 if (args.strict and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
