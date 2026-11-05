"""Tokenized US stocks on OKX: the LOG-ONLY public data collector (plan row R21, SIMULATION ONLY).

Collects, for the 15 most liquid X-prefixed USDT stock pairs on OKX (``XNVDA-USDT``, ``XQQQ-USDT``, ...),
the instrument parameters, 1H and 1Dutc candles back to each listing and order-book snapshots at the US
regular-session open and close (09:30 and 16:00 New York time, converted at run time), at 03:00 UTC every
day and at 12:00 UTC on Saturdays, into the lake layout under ``data/lake/xstocks/`` (``research/xstocks_data.py``).
Public market data only through the GET-only public client of the data lake: no keys, no headers, no account,
no order of any kind; the app's instrument allowlist is untouched and nothing here trades anything.

Modes::

    python scripts/collect_xstocks.py --select-universe           # once: rank the live X-USDT stock pairs by 24h quote volume, write the universe file
    python scripts/collect_xstocks.py --once [--snapshot-now]      # one pass: today's parameters, candles back to listing, the due snapshots (+ an ad-hoc one)
    python scripts/collect_xstocks.py --loop [--max-minutes N]     # the service: snapshots at their slots, 1H candles topped up every hour, 1Dutc daily
    python scripts/collect_xstocks.py --status                     # what the lake holds (files only, no network)
    python scripts/collect_xstocks.py --report [--out PATH]        # the per-pair feasibility tables (files only, no network) and their JSON

The universe file (default ``docs/research/xstocks_universe.json``) is written once by ``--select-universe`` and
read by every other mode, so the laptop task and any later machine collect the same 15 pairs.

Exit codes: 0 = done; 1 = the pass had errors (they are printed; the next pass retries); 2 = a setup problem a
restart cannot fix (no universe file, a bad option).

This process needs no secrets: started as a script, it keeps ``python-dotenv`` from loading the repository ``.env``
into its environment when ``app.config`` is imported through the data-lake client.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # app/config.py then skips load_dotenv(): no .env secrets in this process

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.layout import LAKE_DIR_ENV, LakeLayout  # noqa: E402
from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from research.xstocks_data import (  # noqa: E402
    DEFAULT_SLEEP_SECONDS,
    DEFAULT_UNIVERSE_PATH,
    XStocksDataError,
    XStocksLayout,
    feasibility_rows,
    lake_status,
    load_universe,
    render_feasibility_tables,
    run_loop,
    run_once,
    select_universe,
    write_feasibility_json,
    write_universe,
)

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_SETUP = 2
LOG_LEVEL_ENV = "XSTOCKS_LOG_LEVEL"
DEFAULT_REPORT_JSON = Path("docs/research/tokenized_stocks_feasibility.json")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tokenized US stocks on OKX: log-only public data collector (research; nothing trades).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--select-universe", action="store_true", help="Rank the live X-USDT stock pairs once and write the universe file.")
    mode.add_argument("--once", action="store_true", help="One pass: parameters, candles, the due snapshots.")
    mode.add_argument("--loop", action="store_true", help="Run until stopped: snapshots at their slots, hourly candle top-ups.")
    mode.add_argument("--status", action="store_true", help="Show what the lake holds (files only).")
    mode.add_argument("--report", action="store_true", help="Print the feasibility tables and write their JSON (files only).")
    p.add_argument("--lake-dir", type=Path, default=None, help=f"Research lake root (default ${LAKE_DIR_ENV} or data/lake); the data goes under <lake>/xstocks/.")
    p.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH, help=f"The universe file (default {DEFAULT_UNIVERSE_PATH}).")
    p.add_argument("--force", action="store_true", help="--select-universe: replace an existing universe file (starts a new record).")
    p.add_argument("--snapshot-now", action="store_true", help="--once: also take an ad-hoc order-book snapshot of every pair now.")
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS, help=f"Seconds between public requests (default {DEFAULT_SLEEP_SECONDS}).")
    p.add_argument("--max-pages", type=int, default=None, help="Bound the candle walk of one pass (tests, smoke runs).")
    p.add_argument("--max-minutes", type=float, default=None, help="--loop: stop after this many minutes.")
    p.add_argument("--poll-seconds", type=float, default=30.0, help="--loop: how often the schedule is checked (default 30).")
    p.add_argument("--out", type=Path, default=DEFAULT_REPORT_JSON, help=f"--report: where the JSON goes (default {DEFAULT_REPORT_JSON}).")
    p.add_argument("--json", action="store_true", help="Print summaries as JSON.")
    p.add_argument("--log-level", default=None, help=f"Logging level (default ${LOG_LEVEL_ENV} or WARNING).")
    args = p.parse_args(argv)
    if args.sleep < 0:
        p.error("--sleep must be zero or positive")
    if args.max_pages is not None and args.max_pages < 1:
        p.error("--max-pages must be at least 1")
    if args.max_minutes is not None and args.max_minutes <= 0:
        p.error("--max-minutes must be positive")
    if args.poll_seconds < 1:
        p.error("--poll-seconds must be at least 1")
    if args.force and not args.select_universe:
        p.error("--force only applies to --select-universe")
    if args.snapshot_now and not args.once:
        p.error("--snapshot-now only applies to --once")
    return args


def _layout(args: argparse.Namespace, env: Mapping[str, str]) -> XStocksLayout:
    lake = LakeLayout(args.lake_dir) if args.lake_dir else LakeLayout.from_env(env)
    return XStocksLayout.from_lake(lake)


def _print(args: argparse.Namespace, payload: object, text: str) -> None:
    print(json.dumps(payload, sort_keys=True, default=str) if args.json else text, flush=True)


def _say(message: str) -> None:
    print(f"{datetime.now(tz=timezone.utc):%Y-%m-%d %H:%M:%S}Z  {message}", flush=True)


def cmd_select_universe(args: argparse.Namespace, rest: OKXPublicRest, now: datetime) -> int:
    try:
        payload = select_universe(rest, now=now)
        path = write_universe(args.universe, payload, force=args.force)
    except (PublicRestError, XStocksDataError, ValueError, OSError) as exc:
        print(f"xstocks universe not written: {exc}", file=sys.stderr)
        return EXIT_SETUP
    s = payload["summary"]
    lines = [f"universe written: {path} ({payload['size']} pairs, selected {payload['selected_at']})",
             f"  {s['stock_pairs_usdt_x_live']} live X-USDT stock pairs ranked; total 24h quote volume {s['total_quote_volume_24h']:,.0f} USDT, "
             f"top 10 share {100 * (s['top10_share'] or 0):.0f} %, {s['pairs_above_1m']} above 1M, {s['pairs_below_10k']} below 10K"]
    for r in payload["ranking"][: payload["size"]]:
        lines.append(f"  {r['rank']:2d}. {r['instId']:14s} {r['quote_volume_24h'] or 0:>14,.0f} USDT  listed {r['list_time'] or '-'}")
    _print(args, payload, "\n".join(lines))
    return EXIT_OK


def cmd_once(args: argparse.Namespace, rest: OKXPublicRest, now: datetime, universe: dict, layout: XStocksLayout) -> int:
    summary = run_once(layout, universe, rest=rest, now=now, max_pages=args.max_pages, sleep_seconds=args.sleep, snapshot_now=args.snapshot_now,
                       log=_say if not args.json else (lambda m: None))
    if args.json:
        _print(args, summary, "")
    else:
        stored = sum(c["stored"] for c in summary["candles"])
        added = sum(c["added"] for c in summary["candles"])
        snaps = sum(s["stored"] for s in summary["snapshots"])
        _say(f"pass done: {len(summary['candles'])} candle series ({added} added, {stored} stored), {snaps} book(s) stored in {len(summary['snapshots'])} slot(s), "
             f"{len(summary['errors'])} error(s)")
    return EXIT_ERRORS if summary["errors"] else EXIT_OK


def cmd_loop(args: argparse.Namespace, rest: OKXPublicRest, universe: dict, layout: XStocksLayout, now_fn: Callable[[], datetime]) -> int:
    stop = threading.Event()

    def on_signal(signum, _frame) -> None:
        stop.set()

    handled = [signal.SIGINT] + ([signal.SIGTERM] if hasattr(signal, "SIGTERM") else [])
    previous = {sig: signal.signal(sig, on_signal) for sig in handled}
    try:
        _say(f"xstocks collector started: {len(universe['pairs'])} pairs, lake {layout.root}, universe selected {universe['selected_at']}")
        stats = run_loop(layout, universe, rest=rest, now_fn=now_fn, wait=stop.wait, max_minutes=args.max_minutes, poll_seconds=args.poll_seconds,
                         max_pages=args.max_pages, sleep_seconds=args.sleep, log=_say)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    _say(f"xstocks collector stopped ({stats.get('stopped', 'done')}): {stats['passes']} pass(es), {stats['snapshots']} book(s) stored, "
         f"{stats['errors']} error(s)")
    return EXIT_ERRORS if stats["errors"] else EXIT_OK


def cmd_status(args: argparse.Namespace, universe: dict, layout: XStocksLayout) -> int:
    st = lake_status(layout, universe)
    lines = [f"xstocks lake status ({st['root']}): universe selected {st['universe_selected_at']}, parameters recorded {st['instruments_recorded_at']}"]
    for pair, e in st["pairs"].items():
        last = e["last_snapshot"]
        lines.append(f"  {pair:14s} 1H {e['1H']['rows']:6,} ({(e['1H']['min'] or '-')[:16]} -> {(e['1H']['max'] or '-')[:16]})  1Dutc {e['1Dutc']['rows']:4,}  "
                     f"snapshots {e['snapshots']:4d}" + (f"  last {last['slot']} {last['fetched_at']} spread {last.get('spread_bps')}" if last else ""))
    lines.append(f"  slots taken: {st['slots_taken_total']} (last: {', '.join(st['slots_taken']) or 'none'})")
    _print(args, st, "\n".join(lines))
    return EXIT_OK


def cmd_report(args: argparse.Namespace, universe: dict, layout: XStocksLayout, now: datetime) -> int:
    rows = feasibility_rows(layout, universe, now=now)
    out = write_feasibility_json(args.out, rows, universe, now=now)
    text = render_feasibility_tables(rows, now=now)
    if args.json:
        _print(args, {"out": str(out), "rows": rows}, "")
    else:
        print(text, end="", flush=True)
        print(f"\nJSON written: {out}", flush=True)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, *, rest: Optional[OKXPublicRest] = None,
         now_fn: Optional[Callable[[], datetime]] = None) -> int:
    import os

    args = parse_args(argv)
    env = os.environ if env is None else env
    configure_logging(args.log_level or env.get(LOG_LEVEL_ENV) or "WARNING")
    now_fn = now_fn or (lambda: datetime.now(tz=timezone.utc))
    if args.select_universe:
        return cmd_select_universe(args, rest or OKXPublicRest(), now_fn())
    try:
        universe = load_universe(args.universe)
    except XStocksDataError as exc:
        print(f"xstocks collector not started: {exc}", file=sys.stderr)
        return EXIT_SETUP
    layout = _layout(args, env)
    if args.status:
        return cmd_status(args, universe, layout)
    if args.report:
        return cmd_report(args, universe, layout, now_fn())
    rest = rest or OKXPublicRest()
    if args.once:
        return cmd_once(args, rest, now_fn(), universe, layout)
    return cmd_loop(args, rest, universe, layout, now_fn)


if __name__ == "__main__":
    raise SystemExit(main())
