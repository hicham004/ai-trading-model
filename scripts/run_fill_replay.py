"""Fill-cost replay from OKX's PUBLIC tick and order-book archive (plan row R22, SIMULATION ONLY).

Lists the venue's daily archive files for BTC-USDT and ETH-USDT (tick trades, 1-minute candles, the
400-level L2 book) through the data lake's GET-only public client, fetches them with a host-pinned
GET-only downloader into a git-ignored folder, replays the book at every 4H and 6H bar close and at
the next bar's open for market orders of 1 K, 5 K, 10 K and 20 K USDT on both sides, measures how
often a post-only order at the touch fills within one bar, and writes the numbers the report
``docs/research/FILL_COST_REPLAY.md`` rests on (``research/fill_replay.py``). Public data only: no
key, no header, no account, no order of any kind; nothing here trades or changes the running system.

Modes::

    python scripts/run_fill_replay.py --list   [--start D --end D | --days N] [--instruments ...]   # the listing only (network)
    python scripts/run_fill_replay.py --fetch  [...]                                                 # list + resumable download + verify
    python scripts/run_fill_replay.py --replay [--keep] [--out JSON] [--tables MD]                   # files on disk only (no network)
    python scripts/run_fill_replay.py --all    [...] [--keep]                                        # fetch, replay, delete the raw files
    python scripts/run_fill_replay.py --status                                                       # what the archive folder holds

Days are UTC. ``--end`` defaults to three days ago (the book is published T+3) and ``--days`` to 10. The raw
files are deleted after the summaries are written unless ``--keep`` is given; the per-file manifests (name,
size, SHA-256, time) stay as the record.

Exit codes: 0 = done; 1 = the pass had errors (a file failed to download or verify, a day failed to replay;
the next run resumes); 2 = a setup problem (a bad option, nothing on disk to replay).

This process needs no secrets: started as a script, it keeps ``python-dotenv`` from loading the repository
``.env`` into its environment when ``app.config`` is imported through the data-lake client.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # app/config.py then skips load_dotenv(): no .env secrets in this process

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from research.fill_replay import (  # noqa: E402
    CLIP_SIZES_USDT,
    DEFAULT_ARCHIVE_DIR,
    INSTRUMENTS,
    KINDS,
    ArchiveDownloader,
    FillReplayError,
    archive_status,
    build_results,
    delete_raw_files,
    headline,
    list_all_kinds,
    manifests_as_files,
    render_tables,
    replay_archive,
    write_results,
)

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_SETUP = 2
LOG_LEVEL_ENV = "FILL_REPLAY_LOG_LEVEL"
DEFAULT_RESULTS_JSON = Path("docs/research/fill_cost_replay_results.json")
DEFAULT_TABLES_MD = Path("docs/research/fill_cost_replay_tables.md")
PUBLISH_LAG_DAYS = 3  # the order-book files are published T+3
TAIL_DAYS = {"trades": 1, "candles_1m": 1}  # one more trades/candle file than book days (their day is UTC+8, the book's UTC)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fill-cost replay from OKX's public tick and order-book archive (research; nothing trades).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List the archive files for the window (network: the listing only).")
    mode.add_argument("--fetch", action="store_true", help="List, then download and verify the files (resumable).")
    mode.add_argument("--replay", action="store_true", help="Replay the verified files on disk and write the results (no network).")
    mode.add_argument("--all", action="store_true", help="Fetch, replay, then delete the raw files unless --keep.")
    mode.add_argument("--status", action="store_true", help="Show what the archive folder holds (files only).")
    p.add_argument("--start", type=date.fromisoformat, default=None, help="First UTC day (YYYY-MM-DD).")
    p.add_argument("--end", type=date.fromisoformat, default=None, help=f"Last UTC day (default: {PUBLISH_LAG_DAYS} days ago).")
    p.add_argument("--days", type=int, default=10, help="Window length when --start is not given (default 10).")
    p.add_argument("--instruments", nargs="+", default=list(INSTRUMENTS), help=f"Instruments (default {' '.join(INSTRUMENTS)}).")
    p.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR, help=f"Where the raw files go (default {DEFAULT_ARCHIVE_DIR}, git-ignored).")
    p.add_argument("--out", type=Path, default=DEFAULT_RESULTS_JSON, help=f"--replay/--all: the results JSON (default {DEFAULT_RESULTS_JSON}).")
    p.add_argument("--tables", type=Path, default=DEFAULT_TABLES_MD, help=f"--replay/--all: the Markdown tables (default {DEFAULT_TABLES_MD}).")
    p.add_argument("--keep", action="store_true", help="--replay/--all: keep the raw files after the summaries are written.")
    p.add_argument("--clips", nargs="+", type=float, default=list(CLIP_SIZES_USDT), help="Market-order clips in USDT.")
    p.add_argument("--sleep", type=float, default=0.5, help="Seconds between listing requests (default 0.5; the limit is 5 per 2 s).")
    p.add_argument("--json", action="store_true", help="Print summaries as JSON.")
    p.add_argument("--log-level", default=None, help=f"Logging level (default ${LOG_LEVEL_ENV} or WARNING).")
    args = p.parse_args(argv)
    if args.days < 1:
        p.error("--days must be at least 1")
    if args.sleep < 0:
        p.error("--sleep must be zero or positive")
    if any(c <= 0 for c in args.clips):
        p.error("--clips must be positive")
    if args.start and args.end and args.end < args.start:
        p.error("--end is before --start")
    if args.keep and not (args.replay or args.all):
        p.error("--keep only applies to --replay and --all")
    for inst in args.instruments:
        if inst not in INSTRUMENTS:
            p.error(f"instrument {inst} is not one of {INSTRUMENTS}")
    return args


def _window(args: argparse.Namespace, today: date) -> tuple[date, date]:
    end = args.end or (today - timedelta(days=PUBLISH_LAG_DAYS))
    start = args.start or (end - timedelta(days=args.days - 1))
    return start, end


def _say(message: str) -> None:
    print(f"{datetime.now(tz=timezone.utc):%Y-%m-%d %H:%M:%S}Z  {message}", flush=True)


def _print(args: argparse.Namespace, payload: object, text: str) -> None:
    print(json.dumps(payload, sort_keys=True, default=str) if args.json else text, flush=True)


def cmd_list(args: argparse.Namespace, rest: OKXPublicRest, window: tuple[date, date], sleep: Callable[[float], None]) -> tuple[int, list]:
    try:
        # The trades and candle files hold the UTC+8 day, so the file named end + 1 holds the evening of the last UTC book day.
        files = list_all_kinds(rest, instruments=args.instruments, start=window[0], end=window[1], sleep=sleep, sleep_seconds=args.sleep,
                               tail_days=TAIL_DAYS)
    except (PublicRestError, FillReplayError, ValueError) as exc:
        print(f"listing failed: {exc}", file=sys.stderr)
        return EXIT_ERRORS, []
    total = sum(f.size_mb for f in files)
    lines = [f"{len(files)} archive files for {', '.join(args.instruments)}, book days {window[0]} to {window[1]} (trades and candles one file further, "
             f"their files hold the UTC+8 day; {total:,.0f} MB listed):"]
    for kind in KINDS:
        of_kind = [f for f in files if f.kind == kind]
        if of_kind:
            days = sorted({f.day for f in of_kind})
            lines.append(f"  {kind:10s} {len(of_kind):3d} files, {sum(f.size_mb for f in of_kind):8,.1f} MB, days {days[0]} .. {days[-1]}")
    for f in files:
        lines.append(f"    {f.day} {f.instrument:9s} {f.kind:10s} {f.size_mb:8.2f} MB  {f.filename}")
    _print(args, [f.to_json() for f in files], "\n".join(lines))
    return EXIT_OK, files


def cmd_fetch(args: argparse.Namespace, files: list, session: Any) -> int:
    dl = ArchiveDownloader(args.archive_dir, session)
    total = sum(f.size_mb for f in files)
    _say(f"fetching {len(files)} files ({total:,.0f} MB listed) into {args.archive_dir} (files already verified are skipped)")
    summary = dl.fetch_all(files, log=_say)
    _say(f"fetch done: {summary.fetched} fetched ({summary.bytes / 1048576:,.0f} MB), {summary.skipped} already present, {summary.failed} failed")
    for err in summary.errors:
        print(f"  error: {err}", file=sys.stderr)
    return EXIT_ERRORS if summary.failed else EXIT_OK


def cmd_replay(args: argparse.Namespace, now: datetime, window: Optional[tuple[date, date]]) -> int:
    files = manifests_as_files(args.archive_dir, args.instruments)
    if not files:
        print(f"nothing to replay: no verified archive files under {args.archive_dir}", file=sys.stderr)
        return EXIT_SETUP
    _say(f"replaying {len(files)} verified files under {args.archive_dir}")
    replay = replay_archive(args.archive_dir, files, instruments=args.instruments, clips=args.clips, log=_say)
    results = build_results(replay, files=files, archive_root=args.archive_dir, now=now, clips=args.clips, window=window)
    out = write_results(args.out, results)
    tables = render_tables(results)
    args.tables.parent.mkdir(parents=True, exist_ok=True)
    args.tables.write_text(tables, encoding="utf-8")
    for err in replay["errors"]:
        print(f"  error: {err}", file=sys.stderr)
    if args.json:
        _print(args, {"out": str(out), "tables": str(args.tables), "headline": headline(results), "errors": replay["errors"]}, "")
    else:
        print(tables, flush=True)
        for inst, h in headline(results).items():
            _say(f"{inst}: {h['largest_clip']} market order vs the next open, median {h['largest_clip_vs_open_median_bps']:.2f} bps (p90 "
                 f"{h['largest_clip_vs_open_p90_bps']:.2f}); {h['smallest_clip_vs_mid_median_bps']:.2f} bps vs mid for the smallest clip; post-only fill "
                 f"rate {100 * (h['post_only_fill_rate_min'] or 0):.0f}-{100 * (h['post_only_fill_rate_max'] or 0):.0f} %"
                 if h["largest_clip_vs_open_median_bps"] is not None else f"{inst}: no complete boundary")
        _say(f"results written: {out}; tables: {args.tables}")
    if not args.keep and not replay["errors"]:
        removed = delete_raw_files(args.archive_dir, files)
        _say(f"raw files deleted: {removed} (manifests kept; pass --keep to keep the archives)")
    elif not args.keep:
        _say("raw files kept because the replay reported errors")
    return EXIT_ERRORS if replay["errors"] else EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    st = archive_status(args.archive_dir)
    lines = [f"archive {st['root']}: {st['verified']} verified files, {st['raw_present']} raw files present ({st['raw_bytes'] / 1048576:,.0f} MB)"]
    for item in st["files"]:
        lines.append(f"  {item['day']} {item['instrument']:9s} {item['kind']:10s} {(item['size_bytes'] or 0) / 1048576:8.1f} MB  "
                     f"{'present' if item['raw_present'] else 'deleted'}  {item['filename']}")
    _print(args, st, "\n".join(lines))
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, *, rest: Optional[OKXPublicRest] = None, session: Any = None,
         now_fn: Optional[Callable[[], datetime]] = None, sleep: Optional[Callable[[float], None]] = None) -> int:
    import os
    import time

    args = parse_args(argv)
    env = os.environ if env is None else env
    configure_logging(args.log_level or env.get(LOG_LEVEL_ENV) or "WARNING")
    now_fn = now_fn or (lambda: datetime.now(tz=timezone.utc))
    sleep = sleep or time.sleep
    now = now_fn()
    window = _window(args, now.date())
    if args.status:
        return cmd_status(args)
    if args.replay:
        return cmd_replay(args, now, window if (args.start or args.end) else None)
    rest = rest or OKXPublicRest()
    code, files = cmd_list(args, rest, window, sleep)
    if args.list or code != EXIT_OK:
        return code
    if session is None:
        import requests

        session = requests.Session()
    code = cmd_fetch(args, files, session)
    if args.fetch:
        return code
    replay_code = cmd_replay(args, now, window)
    return EXIT_ERRORS if (code != EXIT_OK or replay_code != EXIT_OK) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
