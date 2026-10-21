"""Phase 6b news shadow runner (PHASE6B_DESIGN sections 11 and 14) — LOG-ONLY.

A separate observer next to the Phase 6a shadow run. Every few minutes it reads
a small set of official and public news sources, cleans and de-duplicates the
text, asks Claude Haiku 5.5 / Opus 5.5 to classify it, applies the fixed rules
(two independent sources or a market confirmation, decay, expiry), and records
what the news layer WOULD have done to each new-long decision the Phase 6a run
made (read from its journal files). It writes only news logs, a daily report and
its own state. It places, sizes, approves, modifies and cancels nothing; it has
no OKX keys, never calls an authenticated endpoint, never opens the demo
database, and nothing in the trading runtime reads its output.

Modes::

    python scripts/run_news_shadow.py --dry-run [--fixtures DIR] [--out DIR]   # offline, no key, no network
    python scripts/run_news_shadow.py --loop      # the service (needs ANTHROPIC_API_KEY, or --no-model)
    python scripts/run_news_shadow.py --once      # one cycle
    python scripts/run_news_shadow.py --report [YYYY-MM-DD]   # rebuild a daily report from the logs
    python scripts/run_news_shadow.py --status    # spend, last cycle and live events (reads files only)

Without ``ANTHROPIC_API_KEY`` a live mode refuses to start (exit 2); ``--no-model``
collects and logs news without calling the AI. This script never loads ``.env``:
the service gets only its own environment file (see docs/runbooks/NEWS_SHADOW.md).
The API key is passed to the SDK only and never printed, logged or stored.

Exit codes: 0 = done; 1 = a dry run missed its expectations or a safety check,
or repeated cycle failures; 2 = setup error (missing key, bad option, another
instance running).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.news.budget import (  # noqa: E402
    DAILY_PACE_ENV,
    DEFAULT_DAILY_PACE,
    DEFAULT_MONTHLY_CAP_USD,
    MONTHLY_CAP_ENV,
    BudgetedClient,
    SpendGuard,
    env_float,
)
from app.news.classifier import API_KEY_ENV, NewsClassifier  # noqa: E402
from app.news.dedup import SeenStore  # noqa: E402
from app.news.dryrun import DEFAULT_SHADOW_FIXTURES, run_dry  # noqa: E402
from app.news.evaluation import live_client  # noqa: E402
from app.news.fetch import NewsFetcher  # noqa: E402
from app.news.market import PublicMarketData  # noqa: E402
from app.news.phase6a import Phase6aJournal, journal_dir_from_env  # noqa: E402
from app.news.report import write_daily_report  # noqa: E402
from app.news.shadow import STATE_FILE, NewsShadowRunner, RunnerLock, ShadowSettings  # noqa: E402
from app.news.sources import DEFAULT_SOURCES, get_sources  # noqa: E402
from app.news.store import DEFAULT_SHADOW_LOG_DIR, SHADOW_LOG_DIR_ENV, NewsShadowLog, NewsStore  # noqa: E402

LOG_LEVEL_ENV = "NEWS_SHADOW_LOG_LEVEL"
NO_KEY_MESSAGE = (
    "news shadow not started: ANTHROPIC_API_KEY is not set. "
    "Use --dry-run for an offline run, or --no-model to collect news without classifying it."
)
MAX_CONSECUTIVE_FAILURES = 5

logger = get_logger("news_shadow")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 6b news shadow (log-only; no orders, no OKX keys).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--loop", action="store_true", help="Run cycles every --interval seconds until stopped (the service).")
    mode.add_argument("--once", action="store_true", help="Run one cycle, write the report, exit.")
    mode.add_argument("--dry-run", action="store_true", help="Run the whole shadow offline from fixtures: no network, no key.")
    mode.add_argument("--report", nargs="?", const="today", metavar="YYYY-MM-DD", help="Rebuild one day's report from the logs.")
    mode.add_argument("--status", action="store_true", help="Show spend, the last cycle and live events (reads files only).")
    p.add_argument("--fixtures", type=Path, default=None, help=f"Dry-run fixture directory (default {DEFAULT_SHADOW_FIXTURES}).")
    p.add_argument("--out", type=Path, default=None, help="Dry-run output directory, new or empty (default: a new temp directory).")
    p.add_argument("--interval", type=float, default=300.0, help="Seconds between cycle starts (default 300).")
    p.add_argument("--max-cycles", type=int, default=None, help="Stop --loop after this many cycles.")
    p.add_argument("--sources", nargs="+", default=None, help=f"Source ids (default: all enabled): {[s.source_id for s in DEFAULT_SOURCES]}")
    p.add_argument("--log-dir", type=Path, default=None, help=f"Shadow logs, reports and state (default ${SHADOW_LOG_DIR_ENV} or {DEFAULT_SHADOW_LOG_DIR}).")
    p.add_argument("--news-dir", type=Path, default=None, help="Ingested news store (default $NEWS_DATA_DIR or data/news).")
    p.add_argument("--journal-dir", type=Path, default=None, help="Phase 6a journal directory, read-only (default $PHASE6A_JOURNAL_DIR or logs/shadow).")
    p.add_argument("--monthly-cap-usd", type=float, default=None, help=f"Monthly AI spend cap (default ${MONTHLY_CAP_ENV} or {DEFAULT_MONTHLY_CAP_USD:g}).")
    p.add_argument("--daily-pace", type=float, default=None, help=f"Max share of a day: x times the even daily share left (default ${DAILY_PACE_ENV} or {DEFAULT_DAILY_PACE:g}; 0 = off).")
    p.add_argument("--no-model", action="store_true", help="Collect and log news without calling the AI (no key needed).")
    p.add_argument("--log-level", default=None, help=f"Logging level (default ${LOG_LEVEL_ENV} or INFO).")
    p.add_argument("--json", action="store_true", help="Print summaries as JSON.")
    args = p.parse_args(argv)
    if args.fixtures is not None and not args.dry_run:
        p.error("--fixtures only applies to --dry-run")
    if args.out is not None and not args.dry_run:
        p.error("--out only applies to --dry-run")
    if args.interval < 10:
        p.error("--interval must be at least 10 seconds")
    if args.max_cycles is not None and args.max_cycles < 1:
        p.error("--max-cycles must be at least 1")
    return args


def _log_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    return args.log_dir or Path(env.get(SHADOW_LOG_DIR_ENV) or DEFAULT_SHADOW_LOG_DIR)


def _journal_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    return args.journal_dir or journal_dir_from_env(env)


def _overlaps_journal(log_dir: Path, journal_dir: Path) -> bool:
    """The news logs must never share the Phase 6a journal directory (same report file names)."""
    try:
        return log_dir.resolve() == journal_dir.resolve()
    except OSError:
        return False


def _print(args: argparse.Namespace, payload: dict, text: str) -> None:
    print(json.dumps(payload, sort_keys=True, default=str) if args.json else text)


# -- modes ----------------------------------------------------------------------------------------


def cmd_dry_run(args: argparse.Namespace) -> int:
    fixtures = args.fixtures or DEFAULT_SHADOW_FIXTURES
    result = run_dry(fixtures, args.out)
    h = result.report_data["headline"]
    if args.json:
        print(json.dumps({"out_dir": str(result.out_dir), "cycles": result.cycles, "headline": h,
                          "expectations": [list(e) for e in result.expectations], "ok": result.ok}, default=str))
    else:
        print(f"dry run: {result.cycles} cycles offline (fixture network only, {result.network_requests} requests served)")
        print(
            f"  articles {h['items']} (quarantined {h['quarantined']}), triage calls {h['triage_calls']}, "
            f"stories classified {h['classify_calls']}, events {h['events']} (confirmed {h['corroborated_events']}, "
            f"with effect {h['events_with_effect']}), estimated cost ${h['cost_usd']:.4f}"
        )
        print(f"  Phase 6a decisions {h['decisions']}: would block {h['would_block']}, would reduce {h['would_reduce']}")
        print(f"  safety checks: {'all passed' if h['invariants_ok'] else 'FAILED'}")
        for name, wanted, got, ok in result.expectations:
            print(f"  expect {name} = {wanted}: {'ok' if ok else f'MISMATCH (got {got})'}")
        print(f"  logs and state: {result.out_dir}")
        for path in result.reports:
            print(f"  report: {path}")
    return 0 if result.ok else 1


def cmd_report(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    day = datetime.now(tz=timezone.utc).date() if args.report == "today" else date.fromisoformat(args.report)
    journal = _journal_dir(args, env)
    if _overlaps_journal(_log_dir(args, env), journal):
        print("news shadow report refused: the log directory is the Phase 6a journal directory", file=sys.stderr)
        return 2
    path = write_daily_report(_log_dir(args, env), journal if journal.is_dir() else None, day)
    print(f"report: {path}")
    return 0


def cmd_status(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    log_dir = _log_dir(args, env)
    state_dir = log_dir / "_state"
    now = datetime.now(tz=timezone.utc)
    payload: dict = {"log_dir": str(log_dir), "now": now.isoformat()}
    state_path = state_dir / STATE_FILE
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
            payload["state_error"] = "unreadable state file"
        payload["last_saved"] = state.get("saved_at")
        payload["started_at"] = state.get("started_at")
        payload["cycles"] = state.get("cycle")
        health = state.get("health") or []
        payload["last_cycle_healthy"] = health[-1][1] if health else None
        live = []
        for entry in state.get("book") or []:
            event = (entry.get("versions") or [{}])[-1].get("event") or {}
            if str(event.get("expires_at", "")) > now.isoformat():
                live.append({k: event.get(k) for k in ("event_id", "category", "corroboration_status", "action", "expires_at")})
        payload["live_events"] = live
    else:
        payload["state"] = "no state yet (the shadow has not run here)"
    try:
        guard = SpendGuard(
            state_dir,
            monthly_cap_usd=args.monthly_cap_usd if args.monthly_cap_usd is not None else env_float(env, MONTHLY_CAP_ENV, DEFAULT_MONTHLY_CAP_USD),
            daily_pace=args.daily_pace if args.daily_pace is not None else env_float(env, DAILY_PACE_ENV, DEFAULT_DAILY_PACE),
        )
    except ValueError as exc:
        print(f"news shadow status: {exc}", file=sys.stderr)
        return 2
    payload["spend"] = guard.snapshot(now).to_dict()
    payload["api_key_present"] = bool((env.get(API_KEY_ENV) or "").strip())
    lines = [f"news shadow status ({payload['now']})", f"  logs: {log_dir}"]
    if "last_saved" in payload:
        lines.append(f"  last cycle saved: {payload['last_saved']} (cycles {payload['cycles']}, last healthy: {payload['last_cycle_healthy']})")
        lines.append(f"  live events: {len(payload['live_events'])}")
        for e in payload["live_events"]:
            lines.append(f"    {e['event_id']} {e['category']} {e['corroboration_status']} {e['action']} until {e['expires_at']}")
    else:
        lines.append(f"  {payload.get('state', payload.get('state_error'))}")
    s = payload["spend"]
    lines.append(f"  spend {s['month']}: ${s['spent_usd']:.4f} of ${s['cap_usd']:.2f} (today ${s['today_usd']:.4f})")
    if s.get("state_error"):
        lines.append(f"  spend record problem: {s['state_error']}")
    lines.append(f"  ANTHROPIC_API_KEY in this environment: {'yes' if payload['api_key_present'] else 'no'}")
    _print(args, payload, "\n".join(lines))
    return 0


def cmd_live(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    try:
        cap = args.monthly_cap_usd if args.monthly_cap_usd is not None else env_float(env, MONTHLY_CAP_ENV, DEFAULT_MONTHLY_CAP_USD)
        pace = args.daily_pace if args.daily_pace is not None else env_float(env, DAILY_PACE_ENV, DEFAULT_DAILY_PACE)
        sources = get_sources(args.sources)
    except ValueError as exc:
        print(f"news shadow not started: {exc}", file=sys.stderr)
        return 2
    key = "" if args.no_model else (env.get(API_KEY_ENV) or "").strip()
    if not args.no_model and not key:
        print(NO_KEY_MESSAGE, file=sys.stderr)
        return 2
    log_dir = _log_dir(args, env)
    if _overlaps_journal(log_dir, _journal_dir(args, env)):
        print("news shadow not started: the log directory is the Phase 6a journal directory", file=sys.stderr)
        return 2
    state_dir = log_dir / "_state"
    lock = RunnerLock(state_dir / "runner.lock")
    if not lock.acquire():
        print(f"news shadow not started: another instance holds {lock.path}", file=sys.stderr)
        return 2
    try:
        guard = SpendGuard(state_dir, monthly_cap_usd=cap, daily_pace=pace)
        classifier = None
        if not args.no_model:
            try:
                # The SDK must not retry: BudgetedClient retries, one budget reservation per attempt.
                classifier = NewsClassifier(BudgetedClient(live_client(key, max_retries=0), guard))
            except Exception as exc:  # never echo the exception text: it is about the key's client
                print(f"news shadow not started: the AI client could not be built ({type(exc).__name__})", file=sys.stderr)
                return 2
        key = ""  # drop this reference; only the SDK client keeps the key
        store = NewsStore(args.news_dir) if args.news_dir else NewsStore.from_env(env)
        journal = Phase6aJournal(_journal_dir(args, env))
        runner = NewsShadowRunner(
            sources=sources,
            fetcher=NewsFetcher(),
            store=store,
            seen=SeenStore(store.seen_file),
            market=PublicMarketData(),
            classifier=classifier,
            guard=guard,
            log=NewsShadowLog(log_dir),
            journal=journal,
            state_dir=state_dir,
            settings=ShadowSettings(interval_seconds=args.interval, model_enabled=not args.no_model),
            report_writer=lambda day: write_daily_report(log_dir, journal.journal_dir if journal.exists else None, day),
        )
        return _loop(args, runner)
    finally:
        lock.release()


def _loop(args: argparse.Namespace, runner: NewsShadowRunner) -> int:
    stop = threading.Event()
    reason = {"value": "operator_stop"}

    def on_signal(signum, _frame) -> None:
        reason["value"] = f"signal_{signum}"
        stop.set()

    handled = [signal.SIGINT] + ([signal.SIGTERM] if hasattr(signal, "SIGTERM") else [])
    previous = {sig: signal.signal(sig, on_signal) for sig in handled}
    runner.start()
    failures = cycles = 0
    code = 0
    try:
        while not stop.is_set():
            began = time.monotonic()
            try:
                summary = runner.run_cycle()
                failures = 0
                print(
                    f"cycle {summary['cycle']}: healthy={summary['healthy']} items={summary['items']['new']} "
                    f"triage={summary['triage'].get('calls', 0)} stories={summary['stories'].get('classified', 0)} "
                    f"decisions={summary['overlay'].get('evaluated', 0)} errors={len(summary['errors'])}",
                    flush=True,
                )
            except Exception as exc:  # a cycle that crashed outright; the stages catch their own errors
                failures += 1
                logger.error("news shadow cycle failed", extra={"error_type": type(exc).__name__, "failures": failures})
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    reason["value"] = "repeated_cycle_failures"
                    code = 1
                    break
            cycles += 1
            if args.once or (args.max_cycles is not None and cycles >= args.max_cycles):
                reason["value"] = "once" if args.once else "max_cycles"
                break
            stop.wait(max(1.0, args.interval - (time.monotonic() - began)))
    finally:
        try:
            runner.stop(reason["value"])
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return code


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    args = parse_args(argv)
    env = os.environ if env is None else env
    configure_logging(args.log_level or env.get(LOG_LEVEL_ENV) or ("WARNING" if args.dry_run else "INFO"))
    if args.dry_run:
        return cmd_dry_run(args)
    if args.report is not None:
        return cmd_report(args, env)
    if args.status:
        return cmd_status(args, env)
    return cmd_live(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
