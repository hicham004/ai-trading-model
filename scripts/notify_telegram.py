#!/usr/bin/env python3
"""Send one travel-mode notification to the operator via Telegram.

Boring CLI wrapper around :mod:`app.notify.telegram`, intended for CI steps and
the daily-report hook. It reads credentials from the environment only
(``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``) and never prints them.

Examples::

    python scripts/notify_telegram.py --event ci_pass  --repo owner/repo --url "$PR_URL"
    python scripts/notify_telegram.py --event ci_fail  --repo owner/repo --url "$PR_URL"
    python scripts/notify_telegram.py --event safety_fail --title "PR #12 touches app/risk"
    python scripts/notify_telegram.py --event report_ready --details "2026-06-27 shadow report"

By design this NEVER fails the build for a notification problem: missing
credentials or a transport error exit 0 with a printed note (use ``--strict`` to
exit non-zero on a hard send failure). Order/exchange access is impossible from
here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.notify.telegram import EVENT_LABELS, TelegramNotifier  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send a travel-mode Telegram notification.")
    p.add_argument("--event", required=True, choices=sorted(EVENT_LABELS),
                   help="Notification event type.")
    p.add_argument("--title", default=None, help="Short title line.")
    p.add_argument("--url", default=None, help="PR or report URL.")
    p.add_argument("--details", default=None, help="Extra detail line.")
    p.add_argument("--repo", default=None, help="owner/repo for context.")
    p.add_argument("--dry-run", action="store_true",
                   help="Format and print but never hit the network "
                        "(also honored via TELEGRAM_DRY_RUN=1).")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero on a hard send failure (default: never "
                        "fail CI for a notification).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    notifier = TelegramNotifier.from_env()
    if args.dry_run:
        # Force dry-run regardless of env (still goes through the same path).
        notifier = TelegramNotifier(
            token="dry", chat_id="dry", dry_run=True,
        )
    result = notifier.notify(
        args.event, title=args.title, url=args.url,
        details=args.details, repo=args.repo,
    )

    if result.ok and result.skipped == "dry-run":
        print(f"[notify] dry-run: would send '{args.event}'.")
        return 0
    if result.ok:
        print(f"[notify] sent '{args.event}'.")
        return 0
    if result.skipped == "missing-credentials":
        print("[notify] skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set.")
        return 0
    # Hard failure (transport/HTTP). Error text is already secret-redacted.
    print(f"[notify] WARNING: send failed: {result.error or result.status_code}",
          file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
