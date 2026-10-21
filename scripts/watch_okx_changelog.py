"""OKX API changelog watcher (plan row R6; master plan sections 5.4 and 9) — observability only.

Once a day it reads OKX's public API changelog (https://www.okx.com/docs-v5/log_en/,
one unauthenticated GET), remembers every entry it has seen, and flags new or edited
entries that mention a host, port, REST path, WebSocket channel or authentication
detail this repository uses — the kind of change that announced the end of
WebSocket port 8443. Flags go to Telegram; nothing changes automatically.

Modes::

    python scripts/watch_okx_changelog.py               # a preview: check now, print what it would send, save nothing
    python scripts/watch_okx_changelog.py --send        # the timer: check, send flags to Telegram, remember what it saw
    python scripts/watch_okx_changelog.py --from-file PAGE.html   # read a saved copy instead of fetching
    python scripts/watch_okx_changelog.py --status      # what it knows (reads its state file only)

The first check records the whole page as a baseline and flags only the upcoming
changes and the entries of the last ``--baseline-days`` days. Telegram credentials come
from the environment only (``TELEGRAM_BOT_TOKEN``, ``TELEGRAM_CHAT_ID``; never
printed); ``TELEGRAM_DRY_RUN=1`` formats but never sends. An alert that was not really
sent (Telegram down, or a dry run) stays pending and goes out with the next checks for
7 days. State folder: ``--state-dir``, else ``$OKX_CHANGELOG_STATE_DIR``, else
``$OPS_DIR/okx_changelog``, else ``logs/ops/okx_changelog`` (where the digest reads it).
This script holds no exchange keys, never loads the repository ``.env`` and never calls
an OKX API.

Exit codes: 0 = checked; 1 = the page could not be fetched or read (counted; one
Telegram alert after 3 failed checks in a row); 2 = setup error (a bad option, or
``--send`` without Telegram credentials).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # nothing this process imports may load the repository .env

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.notify.telegram import TelegramNotifier  # noqa: E402
from app.ops.digest import send_text  # noqa: E402
from app.ops.okx_changelog import (  # noqa: E402
    CHANGELOG_URL,
    DEFAULT_BASELINE_DAYS,
    DEFAULT_STATE_DIR,
    STATE_DIR_ENV,
    STATE_FILE,
    fetch_changelog,
    run_check,
    status_summary,
)

TRUTHY = {"1", "true", "yes", "on"}
MAX_LOCAL_FILE_BYTES = 8_000_000
OPS_DIR_ENV = "OPS_DIR"  # the digest's folder; the watcher's state lives in its okx_changelog/ (scripts/ops_digest.py)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OKX API changelog watcher (public page only; no keys, no orders).")
    p.add_argument("--send", action="store_true", help="Send flags (and a repeated-failure alert) to Telegram.")
    p.add_argument("--status", action="store_true", help="Show what the watcher knows (reads its state only).")
    p.add_argument("--from-file", type=Path, default=None, help="Read this saved copy of the page instead of fetching it.")
    p.add_argument("--state-dir", type=Path, default=None,
                   help=f"State and log folder (default ${STATE_DIR_ENV}, else ${OPS_DIR_ENV}/okx_changelog, else {DEFAULT_STATE_DIR}).")
    p.add_argument("--baseline-days", type=int, default=DEFAULT_BASELINE_DAYS,
                   help=f"First check only: flag entries of the last N days (default {DEFAULT_BASELINE_DAYS}).")
    p.add_argument("--json", action="store_true", help="Print the result as JSON.")
    args = p.parse_args(argv)
    if args.baseline_days < 0 or args.baseline_days > 3650:
        p.error("--baseline-days must be between 0 and 3650")
    if args.status and (args.send or args.from_file):
        p.error("--status reads the state only")
    return args


def telegram_dry_run(env: Mapping[str, str]) -> bool:
    return (env.get("TELEGRAM_DRY_RUN") or "").strip().lower() in TRUTHY


def notifier_from_env(env: Mapping[str, str]) -> TelegramNotifier:
    """The existing notifier; with TELEGRAM_DRY_RUN set it formats and never sends, credentials or not."""
    if telegram_dry_run(env):
        return TelegramNotifier(token="dry-run", chat_id="dry-run", dry_run=True)
    return TelegramNotifier.from_env(env)


def _state_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    """``--state-dir``, else ``$OKX_CHANGELOG_STATE_DIR``, else ``$OPS_DIR/okx_changelog`` (where the digest reads it)."""
    if args.state_dir:
        return args.state_dir
    if env.get(STATE_DIR_ENV):
        return Path(env[STATE_DIR_ENV])
    if env.get(OPS_DIR_ENV):
        return Path(env[OPS_DIR_ENV]) / "okx_changelog"
    return Path(DEFAULT_STATE_DIR)


def cmd_status(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    path = _state_dir(args, env) / STATE_FILE
    if not path.exists():
        print(f"okx changelog watcher: no state in {path.parent} yet (it has not run here)")
        return 0
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"okx changelog watcher: the state file is unreadable ({type(exc).__name__})", file=sys.stderr)
        return 1
    summary = status_summary(state, datetime.now(tz=timezone.utc))
    if args.json:
        print(json.dumps(summary, sort_keys=True, default=str))
        return 0
    print(f"okx changelog watcher ({path.parent})")
    print(f"  last check {summary['last_check_at']}, last good check {summary['last_ok_at']}, "
          f"failures in a row {summary['consecutive_failures']}, last error {summary['last_error'] or 'none'}")
    print(f"  entries known {summary['entries_known']}; flagged in the last {summary['days']} days: {len(summary['flagged_recent'])}")
    for rec in summary["flagged_recent"]:
        print(f"    [{rec.get('date')}, {rec.get('change')}] {rec.get('title')} -> {', '.join(rec.get('matches') or [])}")
    return 0


def cmd_check(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    state_dir = _state_dir(args, env)
    notifier = None
    if args.send:
        notifier = notifier_from_env(env)
        if not notifier.configured:
            print("okx changelog watcher not started: --send needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                  "(or TELEGRAM_DRY_RUN=1)", file=sys.stderr)
            return 2
    if args.from_file is not None:
        path = args.from_file
        if not path.is_file() or path.stat().st_size > MAX_LOCAL_FILE_BYTES:
            print(f"okx changelog watcher: {path} is not a readable page of at most {MAX_LOCAL_FILE_BYTES} bytes", file=sys.stderr)
            return 2

        def fetch() -> str:
            return path.read_text(encoding="utf-8", errors="replace")
    else:
        def fetch() -> str:
            return fetch_changelog(CHANGELOG_URL)

    printed = []

    def notify(text: str) -> bool:
        """True only when Telegram took the message: anything else stays pending and is sent again next time."""
        if notifier is None:
            printed.append(("preview: not sent, nothing saved (use --send)", text))
            return False
        result = send_text(text, notifier)
        if result.status == "sent":
            printed.append((f"sent to Telegram ({result.parts} message(s))", text))
        elif result.status == "dry-run":
            printed.append(("Telegram dry run: formatted, not sent (kept for the next real send)", text))
        else:
            printed.append((f"NOT sent ({result.status}: {result.error or 'no detail'}); kept for the next check", text))
        return result.status == "sent"

    now = datetime.now(tz=timezone.utc)
    # Without --send this is a preview: the state is not saved, so the timer still sends what is new.
    result = run_check(state_dir, now, fetch=fetch, notify=notify, baseline_days=args.baseline_days, persist=args.send)
    payload = {"ok": result.ok, "first_run": result.first_run, "mass_change": result.mass_change, "entries": result.entries,
               "new": result.new, "updated": result.updated, "flagged": len(result.flags), "resent": result.resent,
               "delivered": result.delivered, "error": result.error, "consecutive_failures": result.consecutive_failures,
               "state_dir": str(state_dir)}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif result.ok:
        print(f"okx changelog: ok{' (first check: baseline)' if result.first_run else ''}"
              f"{' (the page changed in bulk: new baseline)' if result.mass_change else ''}, {result.entries} entries "
              f"({result.new} new, {result.updated} edited), {len(result.flags)} flagged"
              + (f", {result.resent} undelivered alert(s) sent again" if result.resent else ""))
    else:
        print(f"okx changelog: FAILED ({result.error}), {result.consecutive_failures} failed check(s) in a row", file=sys.stderr)
    if not args.json:
        for how, text in printed:
            print(f"\n--- {how} ---\n{text}")
    return 0 if result.ok else 1


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    args = parse_args(argv)
    env = os.environ if env is None else env
    if args.status:
        return cmd_status(args, env)
    return cmd_check(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
