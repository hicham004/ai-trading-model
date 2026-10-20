"""News-ingestion skeleton runner (Phase 6b 7.1-7.3): fetch -> sanitize -> dedup -> JSONL.

LOG-ONLY. No LLM call, no classification, no trading effect; it reads no
exchange or account state. Items land under ``data/news`` (git-ignored).

Examples::

    python scripts/ingest_news.py --once
    python scripts/ingest_news.py --loop --interval 900 --max-cycles 4
    python scripts/ingest_news.py --once --sources sec_press fed_press_monetary --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.news.dedup import SeenStore  # noqa: E402
from app.news.fetch import NewsFetcher  # noqa: E402
from app.news.pipeline import run_once  # noqa: E402
from app.news.sources import DEFAULT_SOURCES, get_sources  # noqa: E402
from app.news.store import NewsStore  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Log-only news ingestion skeleton (no LLM).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one cycle (default).")
    mode.add_argument("--loop", action="store_true", help="Run repeatedly every --interval seconds.")
    p.add_argument("--interval", type=float, default=900.0, help="Seconds between cycles in --loop mode.")
    p.add_argument("--max-cycles", type=int, default=None, help="Stop after N cycles in --loop mode.")
    p.add_argument("--sources", nargs="+", default=None, help=f"Source ids (default: all enabled): {[s.source_id for s in DEFAULT_SOURCES]}")
    p.add_argument("--list-sources", action="store_true", help="Print the source allowlist and exit.")
    p.add_argument("--news-dir", default=None, help="Store root (default: $NEWS_DATA_DIR or data/news).")
    p.add_argument("--dry-run", action="store_true", help="Fetch and report, write nothing.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(get_settings().log_level)
    if args.list_sources:
        for s in DEFAULT_SOURCES:
            state = "enabled " if s.enabled else "disabled"
            print(f"{state} {s.source_id:20s} {s.kind:10s} {s.tier:8s} {s.publisher}  {('- ' + s.note) if s.note else ''}")
        return 0
    sources = get_sources(args.sources)
    store = NewsStore(Path(args.news_dir)) if args.news_dir else NewsStore.from_env()
    seen = SeenStore(store.seen_file)
    fetcher = NewsFetcher()
    cycles = 0
    while True:
        summary = run_once(sources, fetcher, store, seen, dry_run=args.dry_run)
        cycles += 1
        print(f"cycle {cycles}: {summary.line()}")
        for err in summary.errors:
            print(f"  warning: {err}", file=sys.stderr)
        if not args.loop or (args.max_cycles is not None and cycles >= args.max_cycles):
            break
        time.sleep(max(1.0, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
