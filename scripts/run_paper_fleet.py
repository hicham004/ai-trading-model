"""Paper fleet (plan row R5a): the Sprint 2c shortlist run forward on live PUBLIC OKX data — SIMULATION ONLY.

Every configuration of ``docs/research/paper_fleet_shortlist_v1c.json``, the
jointly sized BTC+ETH x S1/S2/S4 portfolio, its allocator-v2 twin (plan row
R5b: the same sleeves with a correlation cap, a weekly loss limit and a
cooldown) and the controls (always long with the policy sizing; plain
buy-and-hold) run as separate LOCAL paper accounts
with virtual fills, one append-only journal each, and a weekly ranking report
that compares the forward numbers with the walk-forward and holdout
expectations. Public data only (OKX public REST: candles, funding rate, open
interest). No keys, no demo account, no database, no order of any kind.

Modes::

    python scripts/run_paper_fleet.py --loop        # the service: one cycle a minute until stopped
    python scripts/run_paper_fleet.py --once        # one cycle (creates the fleet on first use)
    python scripts/run_paper_fleet.py --dry-run [--days 3] [--out DIR] [--synthetic]   # offline replay, no network
    python scripts/run_paper_fleet.py --report [YYYY-Www]   # rebuild a weekly report from the journals
    python scripts/run_paper_fleet.py --status      # accounts, positions, health (reads the state file only)

The first live run creates the fleet in ``--fleet-dir`` (default
``$PAPER_FLEET_DIR`` or ``logs/paper_fleet``): it copies the research lake's
public history if there is one (``$DATA_LAKE_DIR`` or ``data/lake``, read
only), tops it up from OKX, and starts every account at the first bar that
closes after that moment. Later runs resume it: an account added to the
shortlist since starts then, an account removed is retired (its journal stays),
and a fleet whose shared rules or an existing account's rules changed refuses
to resume (start a new directory, or give a changed configuration a new id).

Exit codes: 0 = done; 1 = a dry run failed an invariant, or repeated cycle
failures; 2 = a setup error a restart cannot fix (changed rules, a bad option);
3 = not startable right now (another instance holds the fleet, or the public data
is missing, stale or not yet complete for the bar that closed last) — the service is simply started again a minute later.

This process needs no secrets: started as a script, it keeps ``python-dotenv``
from loading the repository ``.env`` (which holds the OKX demo keys) into its
environment when ``app.config`` is imported through the data-lake helpers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # app/config.py then skips load_dotenv(): no .env secrets in this process

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.layout import LAKE_DIR_ENV, LakeLayout  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from research.paper_fleet.config import DEFAULT_RESULTS, DEFAULT_SHORTLIST, INSTRUMENTS, load_manifest  # noqa: E402
from research.paper_fleet.data import POSITIONING_SOURCES, FleetLake, MarketData, OkxPublicFeed  # noqa: E402
from research.paper_fleet.replay import run_dry  # noqa: E402
from research.paper_fleet.report import ReportScheduler, iso_week, write_week  # noqa: E402
from research.paper_fleet.runner import FleetError, FleetNotReady, FleetSettings, PaperFleet, status_from_state  # noqa: E402
from research.paper_fleet.store import FleetPaths, read_state  # noqa: E402

FLEET_DIR_ENV = "PAPER_FLEET_DIR"
DEFAULT_FLEET_DIR = "logs/paper_fleet"
LOG_LEVEL_ENV = "PAPER_FLEET_LOG_LEVEL"
MAX_CONSECUTIVE_FAILURES = 10
EXIT_SETUP = 2  # a restart cannot fix it
EXIT_RETRY_LATER = 3  # systemd restarts the service after RestartSec
DRY_RUN_SETTINGS = FleetSettings()  # the live settings: a dry run exercises exactly what the service runs


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper fleet: the v1c shortlist forward on public OKX data (simulation only, no orders).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--loop", action="store_true", help="Run a cycle every --interval seconds until stopped (the service).")
    mode.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    mode.add_argument("--dry-run", action="store_true", help="Replay recorded public data offline through the whole fleet (no network).")
    mode.add_argument("--report", nargs="?", const="current", metavar="YYYY-Www", help="Rebuild one weekly report from the journals.")
    mode.add_argument("--status", action="store_true", help="Show accounts, positions and health from the state file (no network).")
    p.add_argument("--fleet-dir", type=Path, default=None, help=f"Fleet directory (default ${FLEET_DIR_ENV} or {DEFAULT_FLEET_DIR}).")
    p.add_argument("--lake-dir", type=Path, default=None, help=f"Research lake to seed history from, read only (default ${LAKE_DIR_ENV} or data/lake).")
    p.add_argument("--positioning-source", default="okx", choices=list(POSITIONING_SOURCES), help="Funding / open-interest source for the S5 filter.")
    p.add_argument("--shortlist", type=Path, default=DEFAULT_SHORTLIST, help="Paper-fleet shortlist JSON.")
    p.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="Research results JSON (expectations, portfolio sleeves).")
    p.add_argument("--interval", type=float, default=60.0, help="Seconds between cycle starts (default 60).")
    p.add_argument("--max-cycles", type=int, default=None, help="Stop --loop after this many cycles.")
    p.add_argument("--max-minutes", type=float, default=None, help="Stop --loop after this many minutes.")
    p.add_argument("--days", type=float, default=3.0, help="Dry run: days of history to replay (default 3; a few minutes).")
    p.add_argument("--out", type=Path, default=None, help="Dry run: output directory, new or empty (default: a new temp directory).")
    p.add_argument("--synthetic", action="store_true", help="Dry run: use a deterministic synthetic market instead of the research lake.")
    p.add_argument("--log-level", default=None, help=f"Logging level (default ${LOG_LEVEL_ENV} or WARNING).")
    p.add_argument("--json", action="store_true", help="Print summaries as JSON.")
    args = p.parse_args(argv)
    for flag in ("days", "out", "synthetic"):
        if not args.dry_run and getattr(args, flag) not in (None, False, 3.0):
            p.error(f"--{flag} only applies to --dry-run")
    if args.interval < 10:
        p.error("--interval must be at least 10 seconds")
    if args.max_cycles is not None and args.max_cycles < 1:
        p.error("--max-cycles must be at least 1")
    if args.days <= 0:
        p.error("--days must be positive")
    if args.report not in (None, "current") and not re.fullmatch(r"\d{4}-W\d{2}", args.report):
        p.error("--report takes a week like 2026-W43")
    return args


def _fleet_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    return args.fleet_dir or Path(env.get(FLEET_DIR_ENV) or DEFAULT_FLEET_DIR)


def _lake(args: argparse.Namespace, env: Mapping[str, str]) -> LakeLayout:
    return LakeLayout(args.lake_dir) if args.lake_dir else LakeLayout.from_env(env)


def _print(args: argparse.Namespace, payload: dict, text: str) -> None:
    print(json.dumps(payload, sort_keys=True, default=str) if args.json else text, flush=True)


# -- modes ------------------------------------------------------------------------------


def cmd_dry_run(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    lake = _lake(args, env)
    try:
        manifest = load_manifest(args.shortlist, args.results)
        result = run_dry(args.out, days=args.days, lake=None if args.synthetic else lake, synthetic=args.synthetic, manifest=manifest,
                         settings=DRY_RUN_SETTINGS)
    except (ValueError, OSError) as exc:
        print(f"paper fleet dry run refused: {exc}", file=sys.stderr)
        return 2
    payload = {"out_dir": str(result.out_dir), "source": result.source, "start": result.start, "end": result.end, "cycles": result.cycles,
               "requests_served_offline": result.feed_requests, "checks": [list(c) for c in result.checks], "ok": result.ok,
               "accounts": result.summary, "reports": result.reports}
    lines = [f"dry run: {result.cycles} hourly cycles offline over {result.start} -> {result.end} ({result.source}); "
             f"{result.feed_requests} data requests served from memory, none sent to the network"]
    for aid, s in result.summary.items():
        eq = s["equity"]
        lines.append(f"  {aid:28s} bars {s['bars']:4d}  fills {s['fills']:3d}  equity {eq if eq is None else f'{eq:,.2f}'}"
                     + (f"  portfolio days {s['portfolio_days']}" if s["portfolio_days"] else ""))
    for name, ok, detail in result.checks:
        lines.append(f"  check: {name}: {'ok' if ok else 'FAILED ' + detail}")
    lines.append(f"  journals, state and reports: {result.out_dir}")
    for path in result.reports:
        lines.append(f"  report: {path}")
    _print(args, payload, "\n".join(lines))
    return 0 if result.ok else 1


def cmd_report(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    paths = FleetPaths(_fleet_dir(args, env))
    if read_state(paths.state_file) is None:
        print(f"paper fleet report: no fleet in {paths.root}", file=sys.stderr)
        return 2
    now = datetime.now(tz=timezone.utc)
    if args.report == "current":
        year, week = iso_week(now.date())
    else:
        year, week = int(args.report[:4]), int(args.report[6:])
    out = write_week(paths, now, year=year, week=week)
    print(f"report: {out}")
    return 0


def cmd_status(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    paths = FleetPaths(_fleet_dir(args, env))
    state = read_state(paths.state_file)
    if state is None:
        _print(args, {"fleet_dir": str(paths.root), "state": None}, f"paper fleet status: no fleet in {paths.root} yet")
        return 0
    st = status_from_state(state)
    health = st.get("health") or {}
    lines = [f"paper fleet status ({paths.root})",
             f"  created {st['created_at']}, last cycle {st['last_cycle']} ({st['cycles']} cycles), data {'STALE' if health.get('stale') else 'fresh'}"
             f", newest 1H candle {health.get('newest_candle')}, positioning source {st['positioning_source']}"]
    for key, s in sorted((st.get("series") or {}).items()):
        lines.append(f"  {key}: anchor {s.get('anchor')}, last bar {s.get('last_bar')}, bars {s.get('bars')}, skipped {s.get('gaps')}")
    for aid, a in st["accounts"].items():
        eq = a.get("equity")
        pos = "long" if a.get("in_position") else "flat"
        if "sleeves_in_position" in a:
            pos = "long " + ",".join(n for n, v in a["sleeves_in_position"].items() if v) if any(a["sleeves_in_position"].values()) else "flat"
        lines.append(f"  {aid:28s} equity {'-' if eq is None else f'{eq:,.2f}'}  {pos}  trades {a.get('trades_closed', '-')}  "
                     f"journal records {a.get('journal_records')}")
        alloc = a.get("allocator")
        if alloc:
            cool = alloc.get("cooldown_days_left") or 0
            lines.append(f"  {'':28s} allocator v2: " + (f"IN CASH for {cool} more day(s) after a weekly loss-limit trip" if cool else "armed")
                         + f", {alloc.get('loss_limit_trips') or 0} trip(s) so far, v1 on the same sleeves {alloc.get('reference_v1_equity', 0):,.2f}")
    if health.get("last_errors"):
        lines.append(f"  last errors: {health['last_errors']}")
    _print(args, st, "\n".join(lines))
    return 0


def build_fleet(args: argparse.Namespace, env: Mapping[str, str]) -> PaperFleet:
    manifest = load_manifest(args.shortlist, args.results)
    paths = FleetPaths(_fleet_dir(args, env))
    settings = FleetSettings()
    market = MarketData(FleetLake(paths.lake), OkxPublicFeed(), instruments=INSTRUMENTS, history_days=settings.history_days,
                        positioning=args.positioning_source)
    lake = _lake(args, env)
    return PaperFleet(manifest, paths, market, settings=settings, seed_lake=lake if lake.root.exists() else None,
                      report_writer=ReportScheduler(paths))


def cmd_live(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    try:
        fleet = build_fleet(args, env)
    except (ValueError, OSError) as exc:
        print(f"paper fleet not started: {exc}", file=sys.stderr)
        return 2
    if not fleet.acquire():
        print(f"paper fleet not started: another instance holds {fleet.paths.lock_file}", file=sys.stderr)
        return EXIT_RETRY_LATER
    try:
        try:
            opened = fleet.open(datetime.now(tz=timezone.utc))
        except FleetError as exc:
            print(f"paper fleet not started: {exc}", file=sys.stderr)
            return EXIT_SETUP
        except FleetNotReady as exc:
            print(f"paper fleet not started yet: {exc}", file=sys.stderr)
            return EXIT_RETRY_LATER
        print(f"paper fleet {opened['type']}: {fleet.paths.root} ({len(fleet.manifest.accounts)} accounts, "
              f"fingerprint {fleet.manifest.fingerprint()[:12]})", flush=True)
        if opened.get("added") or opened.get("retired"):
            print(f"  accounts added: {', '.join(opened.get('added') or []) or 'none'}; retired: {', '.join(opened.get('retired') or []) or 'none'}",
                  flush=True)
        return _loop(args, fleet)
    finally:
        fleet.release()


def _loop(args: argparse.Namespace, fleet: PaperFleet) -> int:
    stop = threading.Event()

    def on_signal(signum, _frame) -> None:
        stop.set()

    handled = [signal.SIGINT] + ([signal.SIGTERM] if hasattr(signal, "SIGTERM") else [])
    previous = {sig: signal.signal(sig, on_signal) for sig in handled}
    started = time.monotonic()
    failures = cycles = 0
    code = 0
    try:
        while not stop.is_set():
            began = time.monotonic()
            try:
                summary = fleet.cycle(datetime.now(tz=timezone.utc))
                failures = failures + 1 if summary.get("processing_failed") else 0
                bars = sum(summary["bars"].values())
                if bars or summary["errors"] or summary["portfolio_days"] or args.once or cycles % 60 == 0:
                    print(f"cycle {fleet.state.get('cycles')}: bars {summary['bars']} portfolio days {summary['portfolio_days']} "
                          f"stale={summary.get('stale')} errors={len(summary['errors'])}"
                          + (f" first error: {summary['errors'][0]}" if summary["errors"] else ""), flush=True)
            except Exception as exc:  # a cycle that crashed outright (e.g. the disk is full): count it, keep going
                failures += 1
                print(f"cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                print("paper fleet stopping: repeated cycle failures", file=sys.stderr, flush=True)
                code = 1
                break
            cycles += 1
            if args.once or (args.max_cycles is not None and cycles >= args.max_cycles):
                break
            if args.max_minutes is not None and (time.monotonic() - started) / 60.0 >= args.max_minutes:
                break
            stop.wait(max(1.0, args.interval - (time.monotonic() - began)))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return code


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    args = parse_args(argv)
    env = os.environ if env is None else env
    configure_logging(args.log_level or env.get(LOG_LEVEL_ENV) or "WARNING")
    if args.dry_run:
        return cmd_dry_run(args, env)
    if args.report is not None:
        return cmd_report(args, env)
    if args.status:
        return cmd_status(args, env)
    return cmd_live(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
